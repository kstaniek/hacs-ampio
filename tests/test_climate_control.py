"""Run supported climate commands through HA with real protocol controllers."""

from copy import deepcopy
from typing import Any
from unittest.mock import patch

import can
import pytest
from aioampio import AmpioBridge
from aioampio.controllers.climates import ClimatesController
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant.common import MockConfigEntry

from .test_integration import entity_id, make_entry

pytestmark = pytest.mark.skipif(
    not hasattr(ClimatesController, "supports_control"),
    reason="Climate writes require the new aioampio climate controller",
)


@pytest.mark.usefixtures("writable_climate")
async def test_raw_zone_report(hass: HomeAssistant, apis: list[AmpioBridge]) -> None:
    """Decode the captured wire frame before deriving HA mode and preset."""
    await apis[0]._on_frame(
        can.Message(
            arbitration_id=0x123,
            data=bytes.fromhex("fe cb c6 04 c9 04 62 21"),
            is_extended_id=True,
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get(entity_id(hass, Platform.CLIMATE, "climate1"))
    assert state.state == "heat"
    assert state.attributes["preset_mode"] == "temporary"
    assert state.attributes["temperature"] == 22.5
    assert state.attributes["current_temperature"] == 22.2
    apis[0].send.assert_not_awaited()


@pytest.fixture
async def writable_climate(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> MockConfigEntry:
    """Address zone 3 through climate1 to catch entity-ID-based addressing."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    device = data["ampio_config"]["devices"][0]
    device["model"] = 22
    device["climates"][0].update(
        states=["heating.3", "zone.3"], min_temperature=18, max_temperature=26
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    apis[0].send.assert_not_awaited()
    return entry


@pytest.mark.usefixtures("writable_climate")
@pytest.mark.parametrize(
    ("mode", "state", "preset"),
    [
        (0, "auto", "schedule"),
        (1, "heat", "manual"),
        (2, "heat", "temporary"),
        (3, "heat", "holiday"),
        (4, STATE_UNKNOWN, None),
    ],
)
async def test_reported_operating_mode(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    mode: int,
    state: str,
    preset: str | None,
) -> None:
    """Idle demand and a false zone summary do not turn the thermostat off."""
    target = entity_id(hass, Platform.CLIMATE, "climate1")
    initial = hass.states.get(target)
    assert initial.state == STATE_UNKNOWN
    assert initial.attributes["temperature"] is None
    assert initial.attributes["hvac_modes"] == ["auto", "heat"]
    assert initial.attributes["min_temp"] == 18
    assert initial.attributes["max_temp"] == 26
    assert initial.attributes["supported_features"] == int(
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    await apis[0].state_store.set(
        "00000123.heating.3",
        {
            "operating_mode": mode,
            "heating": False,
            "current_temperature": 22.2,
            "target_temperature": 22.0,
        },
    )
    await apis[0].state_store.set("00000123.zone.3", {"state": False})
    await hass.async_block_till_done()
    reported = hass.states.get(target)
    assert reported.state == state
    assert reported.attributes["preset_mode"] == preset
    assert reported.attributes["hvac_action"] == "idle"
    assert reported.attributes["temperature"] == 22.0
    assert reported.attributes["target_temperature"] == 22.0


@pytest.mark.usefixtures("writable_climate")
@pytest.mark.parametrize(
    ("service", "data", "expected"),
    [
        ("set_temperature", {"temperature": 22.5}, ["000001231302e100"]),
        ("set_temperature", {"temperature": 22.25}, ["000001231302df00"]),
        (
            "set_temperature",
            {"temperature": 22.5, "hvac_mode": "auto"},
            [
                "000001231302e100",
                "000001231600020c",
                "0000012316010802",
                "0000012316020200",
            ],
        ),
        (
            "set_hvac_mode",
            {"hvac_mode": "auto"},
            ["000001231600020c", "0000012316010802", "0000012316020200"],
        ),
        (
            "set_hvac_mode",
            {"hvac_mode": "heat"},
            ["000001231600020d", "0000012316010802", "0000012316020201"],
        ),
        (
            "set_preset_mode",
            {"preset_mode": "temporary"},
            ["000001231600020e", "0000012316010802", "0000012316020202"],
        ),
        (
            "set_preset_mode",
            {"preset_mode": "holiday"},
            ["000001231600020f", "0000012316010802", "0000012316020203"],
        ),
    ],
)
async def test_services_encode_captured_frames(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    service: str,
    data: dict[str, Any],
    expected: list[str],
) -> None:
    """Service completion sends frames but does not invent a successful readback."""
    target = entity_id(hass, Platform.CLIMATE, "climate1")
    await hass.services.async_call(
        Platform.CLIMATE, service, {"entity_id": target, **data}, blocking=True
    )
    assert [c.kwargs["data"].hex() for c in apis[0].send.await_args_list] == expected
    assert all(c.args[0] == 0x0F000000 for c in apis[0].send.await_args_list)
    assert hass.states.get(target).state == STATE_UNKNOWN
    assert hass.states.get(target).attributes["temperature"] is None


@pytest.mark.usefixtures("writable_climate")
@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("turn_on", {}),
        ("turn_off", {}),
        ("set_hvac_mode", {"hvac_mode": "off"}),
        ("set_temperature", {"temperature": 22, "hvac_mode": "off"}),
        ("set_temperature", {"temperature": 17.9}),
        ("set_temperature", {"temperature": 26.1}),
        ("set_temperature", {"temperature": float("nan")}),
        ("set_preset_mode", {"preset_mode": "block"}),
    ],
)
async def test_rejected_services_send_nothing(
    hass: HomeAssistant, apis: list[AmpioBridge], service: str, data: dict[str, Any]
) -> None:
    """Do not permit unvalidated off/block commands or bypass application limits."""
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            Platform.CLIMATE,
            service,
            {"entity_id": entity_id(hass, Platform.CLIMATE, "climate1"), **data},
            blocking=True,
        )
    apis[0].send.assert_not_awaited()


async def test_fahrenheit_service_and_feedback(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """HA converts service inputs once; both target attributes use display units."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    # Request the writable fixture after the unit-system change.
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0]["model"] = 22
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, Platform.CLIMATE, "climate1")
    await hass.services.async_call(
        Platform.CLIMATE,
        "set_temperature",
        {"entity_id": target, "temperature": 72.5},
        blocking=True,
    )
    apis[0].send.assert_awaited_once_with(
        0x0F000000, data=bytes.fromhex("000001231300e100")
    )
    await apis[0].state_store.set(
        "00000123.heating.1", {"target_temperature": 22.5, "operating_mode": 2}
    )
    await hass.async_block_till_done()
    state = hass.states.get(target)
    assert (
        state.attributes["temperature"] == state.attributes["target_temperature"] == 72
    )
    assert state.attributes["temperature_unit"] == "°F"


@pytest.mark.usefixtures("writable_climate")
@pytest.mark.parametrize("failed_frame", [0, 1, 2])
async def test_mode_transport_failure(
    hass: HomeAssistant, apis: list[AmpioBridge], failed_frame: int
) -> None:
    """Stop multiframe service writes immediately and return HA's actionable error."""
    from aioampio import AmpioTransmissionError  # noqa: PLC0415

    apis[0].send.side_effect = [None] * failed_frame + [
        AmpioTransmissionError("offline")
    ]
    with pytest.raises(HomeAssistantError, match="could not be sent"):
        await hass.services.async_call(
            Platform.CLIMATE,
            "set_preset_mode",
            {
                "entity_id": entity_id(hass, Platform.CLIMATE, "climate1"),
                "preset_mode": "manual",
            },
            blocking=True,
        )
    assert apis[0].send.await_count == failed_frame + 1


async def test_older_controller_stays_read_only(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Installing the adapter with the manifest-pinned older wheel is safe."""
    with patch.object(ClimatesController, "supports_control", None):
        entry = make_entry()
        data = deepcopy(dict(entry.data))
        data["ampio_config"]["devices"][0]["model"] = 22
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(entry, data=data)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    state = hass.states.get(entity_id(hass, Platform.CLIMATE, "climate1"))
    assert state.attributes["supported_features"] == 0
    assert state.attributes["hvac_modes"] == []
    apis[0].send.assert_not_awaited()
