"""Prepare and run an isolated HA environment for this checkout."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
PROBE = """
import json, sys
from importlib.metadata import distribution, version
from pathlib import Path
import aioampio, homeassistant
from packaging.requirements import Requirement
settings = json.loads(sys.argv[1])
def require(condition):
    if not condition:
        raise RuntimeError('Environment does not match the requested source or version')
for requirement in settings['requirements']:
    req = Requirement(requirement)
    if req.name != 'aioampio' or settings['aioampio'] is None:
        require(version(req.name) in req.specifier)
require('.'.join(map(str, sys.version_info[:3])) == settings['python'])
if settings['core']:
    require(Path(homeassistant.__file__).is_relative_to(settings['core']))
else:
    require(version('homeassistant') == settings['ha_version'])
direct = json.loads(distribution('aioampio').read_text('direct_url.json') or '{}')
if settings['aioampio']:
    require(Path(aioampio.__file__).is_relative_to(settings['aioampio']))
else:
    require(not direct.get('dir_info', {}).get('editable', False))
print(json.dumps({'homeassistant': version('homeassistant'),
    'core_path': homeassistant.__file__, 'aioampio': version('aioampio'),
    'library_path': aioampio.__file__, 'python': sys.executable}))
"""


class Selection(TypedDict):
    """Sources and versions used to detect a stale development environment."""

    core: str | None
    aioampio: str | None
    python: str
    ha_version: str
    requirements: list[str]


def clean_environment() -> dict[str, str]:
    """Keep ambient Python overrides out of dependency checks and HA startup."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
    }


def run(*args: str) -> None:
    """Run a command with explicit paths and no shell interpolation."""
    subprocess.run(args, cwd=ROOT, env=clean_environment(), check=True)  # noqa: S603


def prepare_link(config: Path) -> None:
    """Link the integration without replacing another checkout or installed copy."""
    target = config / "custom_components" / "ampio"
    source = ROOT / "custom_components" / "ampio"
    relative = os.path.relpath(source, target.parent)
    if target.exists() or target.is_symlink():
        if target.resolve() != source:
            msg = f"Refusing to replace {target}; it does not point to {source}."
            raise ValueError(msg)
        if target.is_symlink() and target.readlink().is_absolute():
            with tempfile.TemporaryDirectory(dir=target.parent) as directory:
                link = Path(directory) / "ampio"
                link.symlink_to(relative, target_is_directory=True)
                link.replace(target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(relative, target_is_directory=True)


def settings(args: argparse.Namespace) -> Selection:
    """Read dependency versions from Core, HACS, and the integration manifest."""
    core = args.core
    if (
        core is None
        and not args.stable
        and (ROOT.parent / "core/pyproject.toml").is_file()
    ):
        core = ROOT.parent / "core"
    if core is not None:
        core = core.resolve()
        if not (core / "homeassistant/__init__.py").is_file():
            msg = f"Not a Home Assistant Core checkout: {core}"
            raise ValueError(msg)
    library = args.aioampio.resolve() if args.aioampio else None
    if library is not None and not (library / "aioampio/__init__.py").is_file():
        msg = f"Not an aioampio checkout: {library}"
        raise ValueError(msg)
    pin = (core if core is not None else ROOT) / ".python-version"
    return {
        "core": str(core) if core else None,
        "aioampio": str(library) if library else None,
        "python": pin.read_text().strip(),
        "ha_version": json.loads((ROOT / "hacs.json").read_text())["homeassistant"],
        "requirements": json.loads(
            (ROOT / "custom_components/ampio/manifest.json").read_text()
        )["requirements"],
    }


def probe(python: Path, selected: Selection) -> dict[str, str] | None:
    """Detect dependency drift, editable overrides, and stale framework imports."""
    if not python.is_file():
        return None
    result = subprocess.run(  # noqa: S603
        [str(python), "-c", PROBE, json.dumps(selected)],
        cwd=ROOT,
        env=clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(result.stdout) if result.returncode == 0 else None


def setup(venv: Path, config: Path, selected: Selection) -> dict[str, str]:
    """Install development dependencies without altering the sibling Core venv."""
    uv = shutil.which("uv")
    if uv is None:
        msg = "Install uv before running scripts/setup."
        raise ValueError(msg)
    python = venv / "bin/python"
    if not python.is_file():
        if venv.exists() and any(venv.iterdir()):
            msg = f"{venv} is not a usable venv. Choose a fresh path with --venv."
            raise ValueError(msg)
        run(uv, "venv", "--seed", "--python", selected["python"], str(venv))
    else:
        installed = subprocess.check_output(  # noqa: S603
            [str(python), "-c", "import platform; print(platform.python_version())"],
            env=clean_environment(),
            text=True,
        ).strip()
        if installed != selected["python"]:
            msg = (
                f"{venv} uses Python {installed}; "
                f"choose a fresh --venv for {selected['python']}."
            )
            raise ValueError(msg)
    packages = ["--requirements", str(ROOT / "requirements.txt")]
    if core := selected["core"]:
        packages += [
            "--editable",
            core,
            "--editable",
            f"{core}/packages/pytest-homeassistant",
        ]
    else:
        packages += [
            f"homeassistant=={selected['ha_version']}",
            f"pytest-homeassistant=={selected['ha_version']}",
        ]
    packages += [
        requirement
        for requirement in selected["requirements"]
        if not (selected["aioampio"] and requirement.startswith("aioampio=="))
    ]
    if library := selected["aioampio"]:
        packages += ["--editable", library]
    # An equal-version editable install must be replaced in published-library mode.
    run(
        uv,
        "pip",
        "install",
        "--python",
        str(python),
        "--reinstall-package",
        "aioampio",
        "--reinstall-package",
        "homeassistant",
        "--reinstall-package",
        "pytest-homeassistant",
        *packages,
    )
    report = probe(python, selected)
    if report is None:
        msg = "Installed packages do not match the requested source and versions."
        raise ValueError(msg)
    (venv / "ampio-dev.json").write_text(json.dumps(selected, indent=2) + "\n")
    if not (config / "configuration.yaml").is_file():
        run(
            str(python),
            "-m",
            "homeassistant",
            "--script",
            "ensure_config",
            "--config",
            str(config),
        )
    return report


def check_port(python: Path, config: Path) -> int:
    """Refuse to hide a new instance behind a server already using its HTTP port."""
    code = (
        "from homeassistant.util.yaml import load_yaml; import sys; "
        "print(((load_yaml(sys.argv[1]) or {}).get('http') or {})"
        ".get('server_port', 8123))"
    )
    port = int(
        subprocess.check_output(  # noqa: S603
            [str(python), "-c", code, str(config / "configuration.yaml")],
            env=clean_environment(),
            text=True,
        ).strip()
    )
    with socket.socket() as sock:
        # Match HA's listener so a recently stopped server's TIME_WAIT sockets
        # do not prevent a restart; an active listener still rejects this bind.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as err:
            msg = f"Port {port} is in use. Stop the existing dev HA first."
            raise ValueError(msg) from err
    return port


def main() -> None:
    """Prepare the selected framework/library pair and optionally start HA."""
    if not sys.argv[1:] or sys.argv[1] not in {"setup", "develop"}:
        sys.exit("Use scripts/setup or scripts/develop.")
    action = sys.argv[1]
    parser = argparse.ArgumentParser(prog=f"scripts/{action}", description=__doc__)
    framework = parser.add_mutually_exclusive_group()
    framework.add_argument(
        "--core", type=Path, help="Core checkout (default: ../core when present)"
    )
    framework.add_argument(
        "--stable",
        action="store_true",
        help="Use the minimum HA version from hacs.json",
    )
    parser.add_argument(
        "--aioampio",
        type=Path,
        help="Use this editable library instead of the manifest pin",
    )
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    parser.add_argument("--config", type=Path, default=ROOT / ".dev-config")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--setup", action="store_true", help="Refresh dependencies before starting"
    )
    mode.add_argument(
        "--setup-only", action="store_true", help="Prepare without starting HA"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable HA and asyncio debug mode"
    )
    args = parser.parse_args(sys.argv[2:])
    try:
        selected = settings(args)
        venv, config = args.venv.resolve(), args.config.resolve()
        prepare_link(config)
        python = venv / "bin/python"
        state = venv / "ampio-dev.json"
        stored = json.loads(state.read_text()) if state.is_file() else None
        report = probe(python, selected) if stored == selected else None
        if (
            action == "setup"
            or args.setup
            or args.setup_only
            or report is None
            or not (config / "configuration.yaml").is_file()
        ):
            report = setup(venv, config, selected)
        for key, value in report.items():
            print(f"{key}: {value}", flush=True)
        if action == "setup" or args.setup_only:
            print(
                "Environment ready. Run scripts/develop with the same source options."
            )
            return
        port = check_port(python, config)
        command = [str(python), "-m", "homeassistant", "--config", str(config)]
        if args.aioampio:
            command += ["--skip-pip-packages", "aioampio"]
        if args.debug:
            command.append("--debug")
        print(
            f"Starting development HA at http://localhost:{port} using {config}",
            flush=True,
        )
        env = clean_environment()
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        os.chdir(ROOT)
        os.execve(python, command, env)  # noqa: S606 - Explicit managed venv interpreter.
    except (ValueError, OSError, subprocess.CalledProcessError) as err:
        parser.exit(1, f"{err}\n")


if __name__ == "__main__":
    main()
