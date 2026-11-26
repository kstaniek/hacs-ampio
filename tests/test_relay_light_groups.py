"""Verify binary masked light groups through HA's real light services."""

from unittest.mock import call

import pytest
from aioampio import AmpioBridge
from aioampio.models import config as library_config
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from .test_integration import entity_id
from .test_light_groups import make_group_entry, payloads, service

pytestmark = pytest.mark.skipif(
    library_config.DeviceType.MREL8S
    not in getattr(library_config, "MASKED_LIGHT_OUTPUT_COUNTS", {}),
    reason="Relay masked light groups require aioampio 2.3.0",
)


@pytest.fixture
async def relay_entry(hass: HomeAssistant, apis: list[AmpioBridge]) -> MockConfigEntry:
    """Retain eight individual relays and add a single on/off group."""
    entry = make_group_entry()
    device = entry.data["ampio_config"]["devices"][0]
    device.update(model=4, name="Relay module")
    device["lights"] = [
        {"id": f"light{i}", "name": f"Relay {i}", "states": [f"binout.{i + 24}"]}
        for i in range(1, 9)
    ]
    device["light_groups"] = [
        {"id": "garaz", "name": "Garaż", "members": ["light3", "light5", "light6"]}
    ]
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    apis[0].send.assert_not_awaited()
    return entry


async def test_relay_group_services(
    hass: HomeAssistant, apis: list[AmpioBridge], relay_entry: MockConfigEntry
) -> None:
    """Advertise on/off only and issue exactly one masked frame for each action."""
    group = entity_id(hass, "light", "light_group_garaz")
    assert group == "light.garaz"
    assert er.async_get(hass).async_get(group).original_name == "Garaż"
    assert hass.states.get(group).attributes["supported_color_modes"] == ["onoff"]
    assert "brightness" not in hass.states.get(group).attributes
    await service(hass, "turn_on", "garaz")
    await service(hass, "turn_off", "garaz")
    assert payloads(apis[0]) == ["0000012314ff3400", "0000012314003400"]
    assert hass.states.get(group).state == "unknown"
    assert len(apis[0].lights) == 9


async def test_relay_feedback_and_failure(
    hass: HomeAssistant, apis: list[AmpioBridge], relay_entry: MockConfigEntry
) -> None:
    """Update the group for individual feedback without generating extra commands."""
    api = apis[0]
    group = entity_id(hass, "light", "light_group_garaz")
    for output in (3, 5, 6):
        await api.state_store.set(f"00000123.binout.{output + 24}", {"state": False})
    await hass.async_block_till_done()
    assert hass.states.get(group).state == "off"
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id(hass, "light", "light5")},
        blocking=True,
    )
    assert payloads(api) == ["0000012315ff0400"]
    await api.state_store.set("00000123.binout.29", {"state": True})
    await hass.async_block_till_done()
    assert hass.states.get(group).state == "on"
    assert "brightness" not in hass.states.get(group).attributes
    await api.state_store.set("00000123.binout.29", {"state": False})
    await hass.async_block_till_done()
    assert hass.states.get(group).state == "off"
    api.send.reset_mock()
    api.send.side_effect = ConnectionError("failed write")
    with pytest.raises(HomeAssistantError, match="command could not be sent"):
        await service(hass, "turn_on", "garaz")
    assert api.send.await_args_list == [
        call(0x0F000000, data=bytes.fromhex("0000012314ff3400"))
    ]
    assert hass.states.get(group).state == "off"
