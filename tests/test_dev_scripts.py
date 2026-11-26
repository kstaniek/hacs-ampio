"""Guard existing configuration and running instances during dev setup."""

import platform
import socket
import sys
from pathlib import Path

import pytest

from scripts import dev


def test_link_preserves_config_and_is_idempotent(tmp_path: Path) -> None:
    """Repeated setup keeps custom YAML and the integration link unchanged."""
    config = tmp_path / "dev config"
    config.mkdir()
    yaml = config / "configuration.yaml"
    yaml.write_text("homeassistant:\n  name: My existing configuration\n")
    dev.prepare_link(config)
    link = config / "custom_components/ampio"
    original = link.lstat().st_ino
    dev.prepare_link(config)
    assert link.resolve() == dev.ROOT / "custom_components/ampio"
    assert link.lstat().st_ino == original
    assert yaml.read_text() == "homeassistant:\n  name: My existing configuration\n"


def test_absolute_link_becomes_portable(tmp_path: Path) -> None:
    """An existing correct host link can also resolve under the container mount."""
    target = tmp_path / "custom_components/ampio"
    target.parent.mkdir()
    target.symlink_to(dev.ROOT / "custom_components/ampio", target_is_directory=True)
    dev.prepare_link(tmp_path)
    assert not target.readlink().is_absolute()
    assert target.resolve() == dev.ROOT / "custom_components/ampio"


def test_other_integration_copy_is_preserved(tmp_path: Path) -> None:
    """A separate installed copy cannot be replaced silently."""
    target = tmp_path / "custom_components/ampio"
    target.mkdir(parents=True)
    marker = target / "__init__.py"
    marker.write_text("# Existing user copy\n")
    with pytest.raises(ValueError, match="Refusing to replace"):
        dev.prepare_link(tmp_path)
    assert marker.read_text() == "# Existing user copy\n"
    assert not target.is_symlink()


def test_broken_other_link_is_preserved(tmp_path: Path) -> None:
    """A broken link to another checkout remains available for user recovery."""
    target = tmp_path / "custom_components/ampio"
    target.parent.mkdir()
    target.symlink_to(tmp_path / "missing checkout")
    with pytest.raises(ValueError, match="Refusing to replace"):
        dev.prepare_link(tmp_path)
    assert target.is_symlink()
    assert target.readlink() == tmp_path / "missing checkout"


def test_wrong_dependency_detected_with_python_optimization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optimized Python must still reject an incorrect installed library version."""
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    selected: dev.Selection = {
        "core": None,
        "aioampio": None,
        "python": platform.python_version(),
        "ha_version": "2026.11.0",
        "requirements": ["aioampio==0.0.0"],
    }
    assert dev.probe(Path(sys.executable), selected) is None


@pytest.mark.enable_socket
def test_running_instance_port_is_not_reused(tmp_path: Path) -> None:
    """Check the configured port before starting another HA process."""
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        (tmp_path / "configuration.yaml").write_text(f"http:\n  server_port: {port}\n")
        with pytest.raises(ValueError, match=f"Port {port} is in use"):
            dev.check_port(Path(sys.executable), tmp_path)


@pytest.mark.enable_socket
def test_recently_stopped_instance_port_can_be_reused(tmp_path: Path) -> None:
    """Allow restart after server-side close leaves connections in TIME_WAIT."""
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client:
            connection, _address = server.accept()
            connection.close()
            assert client.recv(1) == b""
    (tmp_path / "configuration.yaml").write_text(f"http:\n  server_port: {port}\n")
    assert dev.check_port(Path(sys.executable), tmp_path) == port
