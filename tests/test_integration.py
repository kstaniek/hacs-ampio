"""Test real HA setup, registries, services, and lifecycle behavior."""

from unittest.mock import AsyncMock, patch

import pytest
from aioampio import AmpioBridge
from aioampio.controllers.events import EventType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from .conftest import CONFIG


def make_entry(title: str = "192.0.2.1:20001") -> MockConfigEntry:
    """Provide a cached config without fetching a URL."""
    return MockConfigEntry(
        domain="ampio",
        title=title,
        version=2,
        unique_id="192.0.2.1:20001",
        data={
            "host": "192.0.2.1",
            "port": 20001,
            "config_url": "http://example.invalid/config.yaml",
            "ampio_config": CONFIG,
        },
    )


async def setup_entry(
    hass: HomeAssistant, *, title: str = "192.0.2.1:20001"
) -> MockConfigEntry:
    """Set up the entry through the real HA loader."""
    entry = make_entry(title)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    return entry


def entity_id(hass: HomeAssistant, domain: str, resource: str) -> str:
    """Resolve stable unique IDs independently of HA's generated display names."""
    result = er.async_get(hass).async_get_entity_id(
        domain, "ampio", "00000123_" + resource
    )
    assert result is not None
    return result


@pytest.mark.parametrize(
    ("title", "expected_title"),
    [
        ("192.0.2.1:20001", "CAN Bridge (waveshare / can0, 192.0.2.1:20001)"),
        ("Garage gateway", "Garage gateway"),
    ],
)
async def test_setup(
    hass: HomeAssistant, apis: list[AmpioBridge], title: str, expected_title: str
) -> None:
    """Retain device areas, the bridge device, and all configured entities."""
    entry = await setup_entry(hass, title=title)
    apis[0].start.assert_awaited_once_with()
    apis[0].send.assert_not_awaited()
    device = dr.async_get(hass).async_get_device_by_identifier(
        ("ampio", "00000123"), entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Ampio"
    assert (
        dr.async_get(hass).async_get_device_by_identifier(
            ("ampio", entry.entry_id), entry.entry_id
        )
        is not None
    )
    assert ar.async_get(hass).async_get_area(device.area_id).name == "Test room"
    assert len(
        er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ) == (16 if hasattr(apis[0], "module_metrics") else 9)
    gateway = dr.async_get(hass).async_get_device_by_identifier(
        ("ampio", entry.entry_id), entry.entry_id
    )
    assert gateway.model == "CAN Bridge (waveshare / can0, 192.0.2.1:20001)"
    assert gateway.manufacturer == "Waveshare"
    assert entry.title == expected_title
    assert hass.states.get(entity_id(hass, "light", "light1")) is not None


async def test_states(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Map actual library callbacks into HA states and attributes."""
    await setup_entry(hass)
    updates = {
        "binout.1": {"state": True},
        "aout.1": {"value": 128},
        "binout.2": {"state": True},
        "temperature.1": {"value": 21.5},
        "bin.1": {"state": True},
        "armed.1": {"state": True},
        "aout.2": {"value": 50},
        "aout.3": {"value": 75},
        "heating.1": {
            "current_temperature": 20,
            "target_temperature": 22,
            "heating": True,
        },
        "response.1": {"response": "ready"},
    }
    for topic, payload in updates.items():
        await apis[0].state_store.set("00000123." + topic, payload)
    await hass.async_block_till_done()
    expected = {
        entity_id(hass, "light", "light1"): "on",
        entity_id(hass, "switch", "switch2"): "on",
        entity_id(hass, "sensor", "sensor1"): "21.5",
        entity_id(hass, "binary_sensor", "input1"): "on",
        entity_id(hass, "alarm_control_panel", "alarm1"): "armed_away",
        entity_id(hass, "sensor", "text1"): "ready",
    }
    for entity, state in expected.items():
        assert hass.states.get(entity).state == state
    assert (
        hass.states.get(entity_id(hass, "light", "light1")).attributes["brightness"]
        == 128
    )
    assert (
        hass.states.get(entity_id(hass, "cover", "cover1")).attributes[
            "current_position"
        ]
        == 50
    )
    assert (
        hass.states.get(entity_id(hass, "valve", "valve1")).attributes[
            "current_position"
        ]
        == 75
    )
    assert (
        hass.states.get(entity_id(hass, "climate", "climate1")).attributes[
            "current_temperature"
        ]
        == 20
    )
    apis[0].send.assert_not_awaited()


async def test_brightness_restore(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Capture the commands produced by real HA light services."""
    await setup_entry(hass)
    api = apis[0]
    await api.state_store.set("00000123.aout.1", {"value": 128})
    await hass.async_block_till_done()
    await hass.services.async_call(
        "light",
        "turn_off",
        {"entity_id": entity_id(hass, "light", "light1")},
        blocking=True,
    )
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id(hass, "light", "light1")},
        blocking=True,
    )
    assert [c.kwargs["data"].hex() for c in api.send.await_args_list] == [
        "0000012315000000",
        "0000012315800000",
    ]


async def test_reload(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Reload without duplicate listeners, lost devices, or changing entity IDs."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    before = {e.id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert len(entry.update_listeners) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    apis[0].stop.assert_awaited_once_with()
    assert len(apis) == 2
    assert {
        e.id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    } == before
    assert len(entry.update_listeners) == 1
    assert (
        dr.async_get(hass).async_get_device_by_identifier(
            ("ampio", entry.entry_id), entry.entry_id
        )
        is not None
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    apis[1].stop.assert_awaited_once_with()
    assert not entry.update_listeners


async def test_delete_device(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Delete the resource ID while retaining the bridge."""
    entry = await setup_entry(hass)
    await apis[0].devices._handle_event(EventType.RESOURCE_DELETED, {"id": "00000123"})
    await hass.async_block_till_done()
    assert (
        dr.async_get(hass).async_get_device_by_identifier(
            ("ampio", "00000123"), entry.entry_id
        )
        is None
    )
    assert (
        dr.async_get(hass).async_get_device_by_identifier(
            ("ampio", entry.entry_id), entry.entry_id
        )
        is not None
    )


async def test_setup_timeout(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Do not forward platforms or report loaded after initialization times out."""
    entry = make_entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "aioampio.AmpioBridge.initialize", new=AsyncMock(side_effect=TimeoutError)
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    forward.assert_not_awaited()
    apis[0].stop.assert_awaited_once_with()


async def test_failed_unload(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Keep the connection when platform unload fails."""
    entry = await setup_entry(hass)
    with patch.object(
        hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=False)
    ):
        assert not await hass.config_entries.async_unload(entry.entry_id)
    apis[0].stop.assert_not_awaited()
