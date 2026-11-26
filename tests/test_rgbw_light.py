"""Translate HA RGBW services into captured Ampio channel commands."""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from aioampio import AmpioBridge
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from .test_integration import entity_id

RGBW = ("red", "green", "blue", "white")


@pytest.fixture
async def rgbw_light(hass: HomeAssistant, apis: list[AmpioBridge]) -> str:
    """Create a real RGBW entity with only physical CAN I/O replaced."""
    entry = MockConfigEntry(
        domain="ampio",
        version=2,
        unique_id="192.0.2.1:20001",
        data={
            "host": "192.0.2.1",
            "port": 20001,
            "config_url": "https://example.invalid/config.yaml",
            "ampio_config": {
                "devices": [
                    {
                        "can_id": 0x123,
                        "name": "RGBW module",
                        "model": 12,
                        "lights": [
                            {
                                "id": "light1",
                                "name": "RGBW light",
                                "states": [
                                    "rgb.1",
                                    "binout.25",
                                    "binout.26",
                                    "binout.27",
                                    "binout.28",
                                ],
                            }
                        ],
                    }
                ]
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    apis[0].send.assert_not_awaited()
    return entity_id(hass, "light", "light1")


async def receive(
    hass: HomeAssistant, api: AmpioBridge, levels: tuple[int, int, int, int]
) -> None:
    """Apply actual decoded RGBW and binary feedback through the library."""
    await api.state_store.set("00000123.rgb.1", dict(zip(RGBW, levels, strict=True)))
    for index, value in enumerate(levels, start=25):
        await api.state_store.set(f"00000123.binout.{index}", {"state": bool(value)})
    await hass.async_block_till_done()


def commands(api: AmpioBridge) -> list[tuple[int, str]]:
    """Capture exact CAN IDs, destination IDs, channel order, and levels."""
    return [
        (call.args[0], call.kwargs["data"].hex()) for call in api.send.await_args_list
    ]


def expected_commands(levels: tuple[int, int, int, int]) -> list[tuple[int, str]]:
    """Match the existing four-channel Ampio wire format."""
    return [
        (0x0F000000, f"0000012315{level:02x}{index:02x}")
        for index, level in enumerate(levels)
    ]


async def test_received_rgbw_has_separate_brightness(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Report normalized color once, with physical intensity in brightness."""
    await receive(hass, apis[0], (64, 32, 16, 8))
    state = hass.states.get(rgbw_light)
    assert state.state == "on"
    assert state.attributes["color_mode"] == "rgbw"
    assert state.attributes["brightness"] == 64
    assert isinstance(state.attributes["brightness"], int)
    assert state.attributes["rgbw_color"] == (255, 128, 64, 32)
    apis[0].send.assert_not_awaited()


async def test_missing_rgbw_feedback_is_unknown(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Do not report off before a complete output-level report is available."""
    assert hass.states.get(rgbw_light).state == "unknown"
    await apis[0].state_store.set("00000123.rgb.1", {"red": 64})
    await hass.async_block_till_done()
    assert hass.states.get(rgbw_light).state == "unknown"
    await receive(hass, apis[0], (64, 0, 0, 0))
    assert hass.states.get(rgbw_light).state == "on"
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(
    ("service_data", "levels"),
    [
        ({"brightness": 128}, (128, 64, 32, 0)),
        ({"brightness": 64}, (64, 32, 16, 0)),
        ({"brightness": 128, "rgbw_color": (255, 128, 64, 32)}, (128, 64, 32, 16)),
        ({"brightness": 128, "rgbw_color": (128, 64, 32, 0)}, (64, 32, 16, 0)),
        ({"brightness": 96, "rgbw_color": (0, 0, 0, 255)}, (0, 0, 0, 96)),
        ({"brightness_pct": 25, "rgb_color": (255, 0, 0)}, (64, 0, 0, 0)),
        ({"rgbw_color": (255, 0, 0, 0)}, (200, 0, 0, 0)),
    ],
)
async def test_rgbw_services_scale_channels(  # noqa: PLR0913
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    rgbw_light: str,
    service_data: dict[str, Any],
    levels: tuple[int, int, int, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve hue when dimming and apply brightness to every selected channel."""
    api = apis[0]
    await receive(hass, api, (200, 100, 50, 0))
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light, **service_data}, blocking=True
    )
    assert commands(api) == expected_commands(levels)
    assert "Brightness control not supported for color lights" not in caplog.text
    # Only gateway feedback establishes the reported channel state.
    assert hass.states.get(rgbw_light).attributes["brightness"] == 200
    await receive(hass, api, levels)
    assert hass.states.get(rgbw_light).attributes["brightness"] == max(levels)


@pytest.mark.parametrize(
    ("brightness", "expected"), [(None, (128, 64, 32, 16)), (64, (64, 32, 16, 8))]
)
async def test_off_on_preserves_color(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    rgbw_light: str,
    brightness: int | None,
    expected: tuple[int, int, int, int],
) -> None:
    """Restore the last nonzero color and use an explicit replacement brightness."""
    api = apis[0]
    await receive(hass, api, (128, 64, 32, 16))
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": rgbw_light}, blocking=True
    )
    assert commands(api) == expected_commands((0, 0, 0, 0))
    await receive(hass, api, (0, 0, 0, 0))
    assert hass.states.get(rgbw_light).state == "off"
    api.send.reset_mock()
    data = {} if brightness is None else {"brightness": brightness}
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light, **data}, blocking=True
    )
    assert commands(api) == expected_commands(expected)


async def test_dimming_after_external_off_preserves_color(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Retain observed color when the gateway reports an external off command."""
    await receive(hass, apis[0], (128, 64, 32, 0))
    await receive(hass, apis[0], (0, 0, 0, 0))
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light, "brightness": 64}, blocking=True
    )
    assert commands(apis[0]) == expected_commands((64, 32, 16, 0))


async def test_initial_off_can_dim(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Use the previous default channel selection when no color is known yet."""
    await receive(hass, apis[0], (0, 0, 0, 0))
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light, "brightness": 64}, blocking=True
    )
    assert commands(apis[0]) == expected_commands((64, 64, 64, 64))


async def test_brightness_zero_turns_off(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """HA maps zero brightness to the existing off command for every channel."""
    await receive(hass, apis[0], (128, 64, 32, 0))
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light, "brightness": 0}, blocking=True
    )
    assert commands(apis[0]) == expected_commands((0, 0, 0, 0))


async def test_rgbw_feedback_without_binary_flags(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Use channel feedback when a binary power report has not arrived yet."""
    await apis[0].state_store.set(
        "00000123.rgb.1", {"red": 64, "green": 32, "blue": 0, "white": 0}
    )
    await hass.async_block_till_done()
    assert hass.states.get(rgbw_light).state == "on"
    await apis[0].state_store.set("00000123.rgb.1", dict.fromkeys(RGBW, 0))
    await hass.async_block_till_done()
    assert hass.states.get(rgbw_light).state == "off"
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize("acknowledge_off", [True, False])
async def test_off_feedback_does_not_replace_saved_color(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    rgbw_light: str,
    *,
    acknowledge_off: bool,
) -> None:
    """Ignore partial channel reports from the four-command off sequence."""
    api = apis[0]
    original = (128, 64, 32, 16)
    await receive(hass, api, original)
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": rgbw_light}, blocking=True
    )
    for levels in ((0, 64, 32, 16), (0, 0, 32, 16), (0, 0, 0, 16)):
        await receive(hass, api, levels)
    if acknowledge_off:
        await receive(hass, api, (0, 0, 0, 0))
    api.send.reset_mock()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light}, blocking=True
    )
    assert commands(api) == expected_commands(original)


async def test_requested_color_survives_off_before_feedback(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Remember a new requested color even when feedback has not arrived."""
    api = apis[0]
    await receive(hass, api, (128, 64, 32, 0))
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": rgbw_light, "rgbw_color": (0, 0, 0, 255), "brightness": 32},
        blocking=True,
    )
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": rgbw_light}, blocking=True
    )
    await receive(hass, api, (0, 0, 0, 0))
    api.send.reset_mock()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light}, blocking=True
    )
    assert commands(api) == expected_commands((0, 0, 0, 32))


async def test_overlapping_rgbw_commands_keep_channel_groups_together(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Complete all four off commands before starting a queued on command."""
    api = apis[0]
    original = (128, 64, 32, 16)
    await receive(hass, api, original)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_send(*args: Any, **kwargs: Any) -> None:
        if not entered.is_set():
            entered.set()
            await release.wait()
        await asyncio.sleep(0)

    api.send.side_effect = delayed_send
    off = asyncio.create_task(
        hass.services.async_call(
            "light", "turn_off", {"entity_id": rgbw_light}, blocking=True
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    on = asyncio.create_task(
        hass.services.async_call(
            "light", "turn_on", {"entity_id": rgbw_light}, blocking=True
        )
    )
    try:
        await asyncio.sleep(0)
    finally:
        release.set()
        await asyncio.gather(off, on)
    assert commands(api) == expected_commands((0, 0, 0, 0)) + expected_commands(
        original
    )


@pytest.mark.parametrize("confirm_target", [True, False])
async def test_external_color_after_confirmation_or_timeout(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    rgbw_light: str,
    *,
    confirm_target: bool,
) -> None:
    """Resume learning external colors after confirmation or missing feedback."""
    api = apis[0]
    external = (0, 128, 64, 0)
    with patch("custom_components.ampio.light.monotonic", return_value=100) as clock:
        await receive(hass, api, (128, 64, 32, 16))
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": rgbw_light, "rgbw_color": (255, 0, 0, 0), "brightness": 64},
            blocking=True,
        )
        if confirm_target:
            await receive(hass, api, (64, 0, 0, 0))
        else:
            clock.return_value = 131
        await receive(hass, api, external)
        await hass.services.async_call(
            "light", "turn_off", {"entity_id": rgbw_light}, blocking=True
        )
        await receive(hass, api, (0, 0, 0, 0))
        api.send.reset_mock()
        await hass.services.async_call(
            "light", "turn_on", {"entity_id": rgbw_light}, blocking=True
        )
        assert commands(api) == expected_commands(external)


async def test_failed_command_does_not_replace_saved_color(
    hass: HomeAssistant, apis: list[AmpioBridge], rgbw_light: str
) -> None:
    """Release the command lock and discard a color that could not be sent."""
    api = apis[0]
    original = (128, 64, 32, 16)
    await receive(hass, api, original)
    api.send.side_effect = ConnectionError("test send failure")
    with pytest.raises(ConnectionError, match="test send failure"):
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": rgbw_light, "rgbw_color": (0, 0, 0, 255), "brightness": 32},
            blocking=True,
        )
    api.send.side_effect = None
    await receive(hass, api, (0, 0, 0, 0))
    api.send.reset_mock()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": rgbw_light}, blocking=True
    )
    assert commands(api) == expected_commands(original)
