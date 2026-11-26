"""Exercise unknown states and platform actions through Home Assistant."""

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aioampio import AmpioBridge
from homeassistant.const import STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant.common import MockConfigEntry

from .test_integration import entity_id, make_entry, setup_entry


@pytest.mark.parametrize(
    ("platform", "resource", "topic", "payload", "expected"),
    [
        (Platform.SWITCH, "switch2", "binout.2", {"state": False}, "off"),
        (Platform.SWITCH, "switch2", "binout.2", {"state": True}, "on"),
        (Platform.LIGHT, "light1", "binout.1", {"state": False}, "off"),
        (Platform.LIGHT, "light1", "binout.1", {"state": True}, "on"),
        (Platform.LIGHT, "light1", "aout.1", {"value": 0}, "off"),
        (Platform.LIGHT, "light1", "aout.1", {"value": 128}, "on"),
    ],
)
async def test_unknown_power_until_feedback(  # noqa: PLR0913
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    platform: Platform,
    resource: str,
    topic: str,
    payload: dict[str, Any],
    expected: str,
) -> None:
    """A reachable module does not establish any individual output's state."""
    await setup_entry(hass)
    target = entity_id(hass, platform, resource)
    assert hass.states.get(target).state == STATE_UNKNOWN
    await apis[0].state_store.set(f"00000123.{topic}", payload)
    await hass.async_block_till_done()
    assert hass.states.get(target).state == expected
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(
    ("reports", "expected"),
    [
        ({"alarm": False}, STATE_UNKNOWN),
        ({"arming": False}, STATE_UNKNOWN),
        ({"breached": False}, STATE_UNKNOWN),
        ({"armed": False}, "disarmed"),
        ({"armed": True}, "armed_away"),
        ({"arming": True}, "arming"),
        ({"arming_10s": True}, "arming"),
        ({"breached": True}, "pending"),
        ({"alarm": True}, "triggered"),
        ({"armed": False, "arming": True, "breached": True}, "pending"),
        ({"armed": True, "breached": True, "alarm": True}, "triggered"),
    ],
)
async def test_partial_alarm_feedback(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    reports: dict[str, bool],
    expected: str,
) -> None:
    """Require armed feedback for disarmed, while honoring positive alarm flags."""
    await setup_entry(hass)
    target = entity_id(hass, Platform.ALARM_CONTROL_PANEL, "alarm1")
    assert hass.states.get(target).state == STATE_UNKNOWN
    for name, value in reports.items():
        await apis[0].state_store.set(f"00000123.{name}.1", {"state": value})
    await hass.async_block_till_done()
    assert hass.states.get(target).state == expected
    apis[0].send.assert_not_awaited()


@pytest.fixture
async def positioned_entry(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> MockConfigEntry:
    """Configure cover tilt and valve motion feedback in the real controllers."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    device = data["ampio_config"]["devices"][0]
    device["covers"][0]["states"].append("aout.7")
    device["valves"][0]["states"].extend(("binout.5", "binout.6"))
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    apis[0].send.assert_not_awaited()
    return entry


@pytest.mark.usefixtures("positioned_entry")
@pytest.mark.parametrize("platform", [Platform.COVER, Platform.VALVE])
@pytest.mark.parametrize(
    ("position", "expected"), [(0, "closed"), (50, "open"), (100, "open")]
)
async def test_position_state_contract(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    platform: Platform,
    position: int,
    expected: str,
) -> None:
    """HA builds states and the closed attribute from standard position properties."""
    target = entity_id(hass, platform, f"{platform}1")
    assert hass.states.get(target).state == STATE_UNKNOWN
    assert hass.states.get(target).attributes.get("current_position") is None
    channel = 2 if platform == Platform.COVER else 3
    await apis[0].state_store.set(f"00000123.aout.{channel}", {"value": position})
    await hass.async_block_till_done()
    state = hass.states.get(target)
    assert state.state == expected
    assert state.attributes["current_position"] == position
    assert state.attributes["is_closed"] is (position == 0)


@pytest.mark.usefixtures("positioned_entry")
@pytest.mark.parametrize(
    ("position", "action"), [(0, "open_cover"), (100, "close_cover")]
)
async def test_cover_toggle(
    hass: HomeAssistant, apis: list[AmpioBridge], position: int, action: str
) -> None:
    """Select a toggle direction from reported position without attribute errors."""
    api = apis[0]
    await api.state_store.set("00000123.aout.2", {"value": position})
    await hass.async_block_till_done()
    with patch.object(api.covers, action, new=AsyncMock()) as command:
        await hass.services.async_call(
            Platform.COVER,
            "toggle",
            {"entity_id": entity_id(hass, Platform.COVER, "cover1")},
            blocking=True,
        )
        command.assert_awaited_once_with("00000123_cover1")


@pytest.mark.usefixtures("positioned_entry")
@pytest.mark.parametrize(("position", "target"), [(0, 100), (100, 0)])
async def test_valve_toggle(
    hass: HomeAssistant, apis: list[AmpioBridge], position: int, target: int
) -> None:
    """Use the reported closed state when selecting the next valve position."""
    api = apis[0]
    await api.state_store.set("00000123.aout.3", {"value": position})
    await hass.async_block_till_done()
    with patch.object(api.valves, "set_position", new=AsyncMock()) as command:
        await hass.services.async_call(
            Platform.VALVE,
            "toggle",
            {"entity_id": entity_id(hass, Platform.VALVE, "valve1")},
            blocking=True,
        )
        command.assert_awaited_once_with("00000123_valve1", position=target)


@pytest.mark.usefixtures("positioned_entry")
@pytest.mark.parametrize("platform", [Platform.COVER, Platform.VALVE])
@pytest.mark.parametrize(("offset", "motion"), [(0, "closing"), (1, "opening")])
async def test_toggle_stops_motion(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    platform: Platform,
    offset: int,
    motion: str,
) -> None:
    """The shared HA toggle action stops a moving actuator."""
    api = apis[0]
    channel = 3 if platform == Platform.COVER else 5
    controller = api.covers if platform == Platform.COVER else api.valves
    await api.state_store.set(f"00000123.binout.{channel + offset}", {"state": True})
    await hass.async_block_till_done()
    target = entity_id(hass, platform, f"{platform}1")
    assert hass.states.get(target).state == motion
    with patch.object(controller, f"stop_{platform}", new=AsyncMock()) as command:
        await hass.services.async_call(
            platform, "toggle", {"entity_id": target}, blocking=True
        )
        command.assert_awaited_once_with(f"00000123_{platform}1")


@pytest.mark.usefixtures("positioned_entry")
async def test_cover_tilt_toggle_and_stop(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Tilt position drives HA's toggle and the implemented stop action is exposed."""
    api = apis[0]
    target = entity_id(hass, Platform.COVER, "cover1")
    await api.state_store.set("00000123.aout.7", {"value": 0})
    await hass.async_block_till_done()
    assert hass.states.get(target).attributes["current_tilt_position"] == 0
    with patch.object(api.covers, "open_tilt", new=AsyncMock()) as open_tilt:
        await hass.services.async_call(
            Platform.COVER, "toggle_cover_tilt", {"entity_id": target}, blocking=True
        )
        open_tilt.assert_awaited_once_with("00000123_cover1")
    with patch.object(api.covers, "stop_tilt", new=AsyncMock()) as stop_tilt:
        await hass.services.async_call(
            Platform.COVER, "stop_cover_tilt", {"entity_id": target}, blocking=True
        )
        stop_tilt.assert_awaited_once_with("00000123_cover1")


@pytest.mark.parametrize(
    ("report", "mode", "action"),
    [
        ({"heating": False}, STATE_UNKNOWN, "idle"),
        ({"state": True, "heating": False}, "heat", "idle"),
        ({"state": True, "heating": True}, "heat", "heating"),
        ({"state": False, "heating": False}, "off", "off"),
    ],
)
async def test_climate_feedback_is_read_only(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    report: dict[str, Any],
    mode: str,
    action: str,
) -> None:
    """An idle heating zone keeps its mode, while unknown mode remains unknown."""
    await setup_entry(hass)
    await apis[0].state_store.set(
        "00000123.heating.1",
        {"current_temperature": 20, "target_temperature": 22, **report},
    )
    await hass.async_block_till_done()
    state = hass.states.get(entity_id(hass, Platform.CLIMATE, "climate1"))
    assert state.state == mode
    assert state.attributes["hvac_action"] == action
    assert state.attributes["current_temperature"] == 20
    assert state.attributes["hvac_modes"] == []
    assert state.attributes["supported_features"] == 0
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("turn_on", {}),
        ("turn_off", {}),
        ("set_temperature", {"temperature": 22}),
        ("set_hvac_mode", {"hvac_mode": "auto"}),
    ],
)
async def test_climate_rejects_unsupported_actions(
    hass: HomeAssistant, apis: list[AmpioBridge], service: str, data: dict[str, Any]
) -> None:
    """HA rejects unavailable controls before reaching unimplemented library code."""
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            Platform.CLIMATE,
            service,
            {"entity_id": entity_id(hass, Platform.CLIMATE, "climate1"), **data},
            blocking=True,
        )
    apis[0].send.assert_not_awaited()
