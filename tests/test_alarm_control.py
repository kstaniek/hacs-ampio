"""Exercise alarm controls alongside the migrated command-status sensor."""

from copy import deepcopy

import pytest
from aioampio import AmpioBridge
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .test_integration import entity_id, make_entry


@pytest.mark.parametrize(
    ("service", "command"), [("alarm_arm_away", 0x80), ("alarm_disarm", 0x84)]
)
async def test_zone_three_command_with_status_sensor(
    hass: HomeAssistant, apis: list[AmpioBridge], service: str, command: int
) -> None:
    """Keep a zone-3 command and its response separate from read-only status naming."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0]["alarm_control_panels"] = [
        {
            "id": "zone3",
            "name": "Outside",
            "states": ["armed.3", "arming.3", "arming_10s.3", "breached.3", "alarm.3"],
        }
    ]
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    target = entity_id(hass, "alarm_control_panel", "zone3")
    status = entity_id(hass, "sensor", "text1")
    assert registry.async_get_entity_id("text", "ampio", "00000123_text1") is None
    initial_armed = service == "alarm_disarm"
    initial_state = "armed_away" if initial_armed else "disarmed"
    await apis[0].state_store.set("00000123.armed.3", {"state": initial_armed})
    await hass.async_block_till_done()
    assert hass.states.get(target).state == initial_state
    await hass.services.async_call(
        "alarm_control_panel",
        service,
        {"entity_id": target, "code": "1234"},
        blocking=True,
    )
    frames = apis[0].send.await_args_list
    assert len(frames) == 9
    assert all(call.args == (0x0F000000,) for call in frames)
    assert all(call.kwargs["data"][:4] == bytes.fromhex("00000123") for call in frames)
    assert [call.kwargs["data"][5] for call in frames] == list(range(9))
    payload = b"".join(call.kwargs["data"][6:] for call in frames[1:])
    assert payload == bytes((0x14, 0x0D, command)) + bytes.fromhex(
        "1234ffffffffffff04000000"
    )
    assert frames[0].kwargs["data"][6:] == bytes((8, sum(payload) & 0xFF))
    assert hass.states.get(target).state == initial_state
    await apis[0].state_store.set("00000123.response.1", {"response": "accepted"})
    await apis[0].state_store.set("00000123.armed.3", {"state": not initial_armed})
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "accepted"
    assert hass.states.get(target).state == (
        "disarmed" if initial_armed else "armed_away"
    )
