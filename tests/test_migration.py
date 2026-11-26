"""Preserve legacy cached or bundled configuration during version migration."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from aioampio import AmpioBridge
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components import ampio

from .conftest import CONFIG
from .test_config_flow import INPUT
from .test_integration import make_entry


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
    assert entry.version == 3
    assert entry.entry_id == before
    assert entry.unique_id is None
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
    assert entry.version == 3


@pytest.mark.parametrize("content", ["[", "[]", "null"])
async def test_invalid_bundled_config(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """Missing legacy data can be recovered through reconfiguration."""
    (tmp_path / "config.yaml").write_text(content)
    monkeypatch.setattr(ampio, "__file__", str(tmp_path / "__init__.py"))
    entry = legacy_entry(hass)
    before = dict(entry.data)
    assert await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 3
    assert "ampio_config" not in entry.data
    assert entry.data["host"] == before["host"]
    assert entry.unique_id is None


async def test_missing_bundled_config(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report missing legacy configuration without replacing it with an empty config."""
    monkeypatch.setattr(ampio, "__file__", str(tmp_path / "__init__.py"))
    entry = legacy_entry(hass)
    assert await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 3
    assert "ampio_config" not in entry.data


async def test_future_version_rejected(hass: HomeAssistant) -> None:
    """Do not downgrade an entry created by a newer integration version."""
    entry = MockConfigEntry(domain="ampio", version=4, data={"sentinel": "preserve"})
    entry.add_to_hass(hass)
    assert not await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 4
    assert entry.data == {"sentinel": "preserve"}


async def test_duplicate_endpoint_migration(hass: HomeAssistant) -> None:
    """A legacy entry cannot take another entry's unique ID."""
    current = MockConfigEntry(
        domain="ampio",
        version=2,
        unique_id="192.0.2.1:20001",
        data={"host": "192.0.2.1", "port": 20001},
    )
    current.add_to_hass(hass)
    entry = legacy_entry(hass, ampio_config=CONFIG)
    assert not await ampio.async_migrate_entry(hass, entry)
    assert entry.version == 1


async def test_gateway_registry_migration(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Migrate the gateway identifier in place, retaining counter and device IDs."""
    entry = make_entry()
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    old_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("ampio", entry.unique_id)},
        name="Ampio CAN Bridge",
    )
    registry = er.async_get(hass)
    old_sensor = registry.async_get_or_create(
        Platform.SENSOR,
        "ampio",
        f"{entry.entry_id}_rx_total",
        config_entry=entry,
        device_id=old_device.id,
        suggested_object_id="my_gateway_rx",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        devices.async_get_device_by_identifier(
            ("ampio", entry.entry_id), entry.entry_id
        ).id
        == old_device.id
    )
    assert (
        devices.async_get_device_by_identifier(
            ("ampio", "192.0.2.1:20001"), entry.entry_id
        )
        is None
    )
    new_sensor = registry.async_get(old_sensor.entity_id)
    assert new_sensor.id == old_sensor.id
    assert new_sensor.device_id == old_device.id


@pytest.mark.parametrize("content", [None, "[", "[]"])
async def test_recover_missing_legacy_config(  # noqa: PLR0913
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
) -> None:
    """Recover a migrated entry through its actual reconfigure flow and setup."""
    if content is not None:
        (tmp_path / "config.yaml").write_text(content)
    monkeypatch.setattr(ampio, "__file__", str(tmp_path / "__init__.py"))
    entry = legacy_entry(hass)
    original_id = entry.entry_id
    registry = er.async_get(hass)
    old_sensor = registry.async_get_or_create(
        Platform.SENSOR,
        "ampio",
        "00000123_sensor1",
        config_entry=entry,
        suggested_object_id="preserved_temperature",
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.version == 3
    assert entry.state == ConfigEntryState.SETUP_ERROR
    assert not apis
    issues = ir.async_get(hass)
    issue_id = f"config_required_{entry.entry_id}"
    assert issues.async_get_issue("ampio", issue_id) is not None
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.state == ConfigEntryState.LOADED
    assert entry.entry_id == original_id
    assert registry.async_get(old_sensor.entity_id).id == old_sensor.id
    assert issues.async_get_issue("ampio", issue_id) is None
    apis[0].send.assert_not_awaited()
