"""Preserve legacy cached or bundled configuration during version migration."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components import ampio

from .conftest import CONFIG


def legacy_entry(hass: HomeAssistant, **overrides: object) -> MockConfigEntry:
    """Register a version 1 endpoint with optional cached configuration."""
    entry = MockConfigEntry(
        domain="ampio",
        version=1,
        data={"host": "192.0.2.1", "port": 20001, **overrides},
    )
    entry.add_to_hass(hass)
    return entry


async def test_bundled_config_migration(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migrate through HA setup while preserving the entry and its bundled config."""
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(CONFIG))
    monkeypatch.setattr(ampio, "__file__", str(tmp_path / "__init__.py"))
    entry = legacy_entry(hass)
    before = entry.entry_id
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.version == 2
    assert entry.entry_id == before
    assert entry.unique_id == "192.0.2.1:20001"
    assert entry.data["ampio_config"] == CONFIG
    assert entry.data["config_url"] == ""


async def test_cached_config_migration(hass: HomeAssistant) -> None:
    """Retain a previously customized cached config and URL."""
    entry = legacy_entry(
        hass, ampio_config=CONFIG, config_url="https://example.invalid/custom.yaml"
    )
    assert await ampio.async_migrate_entry(hass, entry)
    assert entry.data["ampio_config"] == CONFIG
    assert entry.data["config_url"] == "https://example.invalid/custom.yaml"
    assert entry.version == 2


@pytest.mark.parametrize("content", ["[", "[]", "null"])
async def test_invalid_bundled_config(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """A failed migration must leave all entry data and its version untouched."""
    (tmp_path / "config.yaml").write_text(content)
    monkeypatch.setattr(ampio, "__file__", str(tmp_path / "__init__.py"))
    entry = legacy_entry(hass)
    before = dict(entry.data)
    assert not await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 1
    assert dict(entry.data) == before
    assert entry.unique_id is None


async def test_missing_bundled_config(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report missing legacy configuration without replacing it with an empty config."""
    monkeypatch.setattr(ampio, "__file__", str(tmp_path / "__init__.py"))
    entry = legacy_entry(hass)
    assert not await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 1


async def test_future_version_rejected(hass: HomeAssistant) -> None:
    """Do not downgrade an entry created by a newer integration version."""
    entry = MockConfigEntry(domain="ampio", version=3, data={"sentinel": "preserve"})
    entry.add_to_hass(hass)
    assert not await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 3
    assert entry.data == {"sentinel": "preserve"}


async def test_duplicate_endpoint_migration(hass: HomeAssistant) -> None:
    """A legacy entry cannot take another entry's unique ID."""
    current = MockConfigEntry(domain="ampio", version=2, unique_id="192.0.2.1:20001")
    current.add_to_hass(hass)
    entry = legacy_entry(hass, ampio_config=CONFIG)
    assert not await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 1
