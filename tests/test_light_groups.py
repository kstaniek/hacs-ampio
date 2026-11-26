"""Exercise native masked groups through real HA services and library resources."""

import asyncio
from copy import deepcopy
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from aioampio import AmpioBridge
from aioampio.models.light import Light
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from .test_integration import entity_id
from .test_module_traffic import snapshot

pytestmark = pytest.mark.skipif(
    "members" not in Light.__dataclass_fields__,
    reason="Native masked light groups require aioampio 2.2.0",
)


@pytest.fixture
async def group_entry(hass: HomeAssistant, apis: list[AmpioBridge]) -> MockConfigEntry:
    """Set up 16 real members and three groups with all physical I/O mocked."""
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
                        "name": "MLED module",
                        "model": 17,
                        "lights": [
                            {
                                "id": f"light{i}",
                                "name": f"MLED {i}",
                                "states": [f"aout.{i}", f"binout.{i + 24}"],
                            }
                            for i in range(1, 17)
                        ],
                        "light_groups": [
                            {
                                "id": "kitchen",
                                "name": "MLED Kitchen",
                                "members": [f"light{i}" for i in range(1, 11)],
                            },
                            {
                                "id": "sofa",
                                "name": "MLED Sofa",
                                "area": "Living room",
                                "members": [f"light{i}" for i in range(11, 17)],
                            },
                            {
                                "id": "sparse",
                                "name": "MLED sparse",
                                "members": ["light1", "light16"],
                            },
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
    return entry


async def service(
    hass: HomeAssistant, action: str, group: str = "sofa", **data: Any
) -> None:
    """Call the actual HA light service by the group's registered entity ID."""
    await hass.services.async_call(
        "light",
        action,
        {"entity_id": entity_id(hass, "light", "light_group_" + group), **data},
        blocking=True,
    )


def payloads(api: AmpioBridge) -> list[str]:
    """Capture physical frame payloads rather than member service invocations."""
    assert all(call.args == (0x0F000000,) for call in api.send.await_args_list)
    return [call.kwargs["data"].hex() for call in api.send.await_args_list]


async def test_setup_retains_members(
    hass: HomeAssistant, group_entry: MockConfigEntry
) -> None:
    """Create separate dimmable groups with the same owning module as their members."""
    registry = er.async_get(hass)
    lights = [
        entry
        for entry in er.async_entries_for_config_entry(registry, group_entry.entry_id)
        if entry.domain == "light"
    ]
    assert len(lights) == 19
    member = registry.async_get(entity_id(hass, "light", "light11"))
    group = registry.async_get(entity_id(hass, "light", "light_group_sofa"))
    assert group.device_id == member.device_id
    assert ar.async_get(hass).async_get_area(group.area_id).name == "Living room"
    state = hass.states.get(group.entity_id)
    assert state.state == "unknown"
    assert state.attributes["supported_color_modes"] == ["brightness"]
    assert "entity_id" not in state.attributes


@pytest.mark.parametrize(
    ("group", "action", "data", "expected"),
    [
        ("kitchen", "turn_on", {}, "0000012314ffff03"),
        ("kitchen", "turn_off", {}, "000001231400ff03"),
        ("kitchen", "turn_on", {"brightness": 128}, "000001231480ff03"),
        ("sofa", "turn_on", {}, "0000012314ff00fc"),
        ("sofa", "turn_off", {}, "00000123140000fc"),
        ("sofa", "turn_on", {"brightness": 128}, "00000123148000fc"),
        ("sofa", "turn_on", {"brightness": 0}, "00000123140000fc"),
    ],
)
async def test_group_service_sends_one_frame(  # noqa: PLR0913
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    group_entry: MockConfigEntry,
    group: str,
    action: str,
    data: dict[str, Any],
    expected: str,
) -> None:
    """Map on, off, and brightness to one frame without optimistic member states."""
    await service(hass, action, group, **data)
    assert payloads(apis[0]) == [expected]
    assert (
        hass.states.get(entity_id(hass, "light", "light_group_" + group)).state
        == "unknown"
    )
    assert hass.states.get(entity_id(hass, "light", "light11")).state == "unknown"


async def test_individual_service_keeps_indexed_command(
    hass: HomeAssistant, apis: list[AmpioBridge], group_entry: MockConfigEntry
) -> None:
    """An individual action keeps indexed TX and updates its group on feedback."""
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id(hass, "light", "light11"), "brightness": 64},
        blocking=True,
    )
    assert payloads(apis[0]) == ["0000012315400a00"]
    sofa = entity_id(hass, "light", "light_group_sofa")
    assert hass.states.get(sofa).state == "unknown"
    await apis[0].state_store.set("00000123.aout.11", {"value": 64})
    await hass.async_block_till_done()
    assert hass.states.get(sofa).state == "on"
    assert hass.states.get(sofa).attributes["brightness"] == 64


async def test_member_feedback_updates_overlapping_groups(
    hass: HomeAssistant, apis: list[AmpioBridge], group_entry: MockConfigEntry
) -> None:
    """Show mixed levels and retain independent member routing with external changes."""
    api = apis[0]
    sofa = entity_id(hass, "light", "light_group_sofa")
    sparse = entity_id(hass, "light", "light_group_sparse")
    await api.state_store.set("00000123.aout.11", {"value": 0})
    await hass.async_block_till_done()
    assert hass.states.get(sofa).state == "unknown"
    for i in range(12, 17):
        await api.state_store.set(f"00000123.aout.{i}", {"value": 0})
    await hass.async_block_till_done()
    assert hass.states.get(sofa).state == "off"
    await api.state_store.set("00000123.aout.11", {"value": 64})
    await api.state_store.set("00000123.aout.16", {"value": 128})
    await hass.async_block_till_done()
    assert hass.states.get(sofa).state == "on"
    assert hass.states.get(sofa).attributes["brightness"] == 96
    assert hass.states.get(sparse).attributes["brightness"] == 128
    assert (
        hass.states.get(entity_id(hass, "light", "light11")).attributes["brightness"]
        == 64
    )
    await api.state_store.set("00000123.binout.35", {"state": False})
    await api.state_store.set("00000123.binout.40", {"state": False})
    await hass.async_block_till_done()
    assert hass.states.get(sofa).state == "off"
    assert hass.states.get(sparse).state == "unknown"
    api.send.assert_not_awaited()


async def test_group_remembers_command_level_without_learning_partial_reports(
    hass: HomeAssistant, apis: list[AmpioBridge], group_entry: MockConfigEntry
) -> None:
    """Restore a common setpoint instead of adopting an intermediate feedback mean."""
    api = apis[0]
    await service(hass, "turn_on", brightness=128)
    await api.state_store.set("00000123.aout.11", {"value": 64})
    await hass.async_block_till_done()
    await service(hass, "turn_off")
    await service(hass, "turn_on")
    assert payloads(api) == [
        "00000123148000fc",
        "00000123140000fc",
        "00000123148000fc",
    ]
    api.send.reset_mock()
    api.send.side_effect = ConnectionError("test send failure")
    with pytest.raises(HomeAssistantError, match="command could not be sent"):
        await service(hass, "turn_on", brightness=32)
    assert len(payloads(api)) == 1
    api.send.side_effect = None
    api.send.reset_mock()
    await service(hass, "turn_on")
    assert payloads(api) == ["00000123148000fc"]


async def test_group_availability_tracks_module_and_recovers_feedback(
    hass: HomeAssistant, apis: list[AmpioBridge], group_entry: MockConfigEntry
) -> None:
    """Recover group and individual states together after module silence."""
    api = apis[0]
    sofa = entity_id(hass, "light", "light_group_sofa")
    member = entity_id(hass, "light", "light11")
    await api.state_store.set("00000123.aout.11", {"value": 64})
    await hass.async_block_till_done()
    monitor = group_entry.runtime_data.traffic
    with patch.object(type(api), "module_metrics", new_callable=PropertyMock) as data:
        data.return_value = {0x123: snapshot(61)}
        monitor.async_refresh()
        assert hass.states.get(sofa).state == "unavailable"
        assert hass.states.get(member).state == "unavailable"
        data.return_value = {0x123: snapshot(0, rx=2)}
        monitor.async_refresh()
        assert hass.states.get(sofa).state == "on"
        assert hass.states.get(member).state == "on"
    api.send.assert_not_awaited()


async def test_concurrent_group_commands_are_serialized(
    hass: HomeAssistant, apis: list[AmpioBridge], group_entry: MockConfigEntry
) -> None:
    """Remember one complete on command before resolving the queued default level."""
    api = apis[0]
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_send(*args: Any, **kwargs: Any) -> None:
        if not entered.is_set():
            entered.set()
            await release.wait()

    api.send.side_effect = delayed_send
    first = asyncio.create_task(service(hass, "turn_on", brightness=64))
    await asyncio.wait_for(entered.wait(), timeout=2)
    second = asyncio.create_task(service(hass, "turn_on"))
    try:
        await asyncio.sleep(0)
    finally:
        release.set()
        await asyncio.gather(first, second)
    assert payloads(api) == ["00000123144000fc", "00000123144000fc"]


async def test_invalid_group_reconfiguration_retains_running_entry(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    group_entry: MockConfigEntry,
    config_apis: list[AmpioBridge],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Reject a missing group member before connecting or replacing cached YAML."""
    previous = deepcopy(dict(group_entry.data))
    cfg = deepcopy(previous["ampio_config"])
    cfg["devices"][0]["light_groups"][1]["members"].append("light99")
    aioclient_mock.get(previous["config_url"], text=yaml.safe_dump(cfg))
    result = await group_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": previous["host"],
            "port": previous["port"],
            "config_url": previous["config_url"],
            "gateway_mac": "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"config_url": "invalid_config"}
    assert dict(group_entry.data) == previous
    assert len(apis) == 1
    apis[0].stop.assert_not_awaited()
    config_apis[0].start.assert_not_awaited()
    config_apis[0].send.assert_not_awaited()


@pytest.mark.parametrize("area_choice", [None, "Other room"])
async def test_reload_preserves_group_registry_and_area_preferences(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    group_entry: MockConfigEntry,
    area_choice: str | None,
) -> None:
    """Retain identity and the user's area choice after name/member changes."""
    registry = er.async_get(hass)
    sofa = entity_id(hass, "light", "light_group_sofa")
    original = registry.async_get(sofa)
    area = ar.async_get(hass).async_create(area_choice) if area_choice else None
    registry.async_update_entity(sofa, area_id=area.id if area else None)
    cfg = group_entry.data["ampio_config"]
    cfg["devices"][0]["light_groups"][1].update(
        name="Renamed sofa", members=["light11", "light16"]
    )
    assert await hass.config_entries.async_reload(group_entry.entry_id)
    await hass.async_block_till_done()
    reloaded = registry.async_get(sofa)
    assert reloaded.id == original.id
    assert reloaded.area_id == (area.id if area else None)
    assert entity_id(hass, "light", "light_group_sofa") == sofa
    await service(hass, "turn_on")
    assert payloads(apis[1]) == ["0000012314ff0084"]
