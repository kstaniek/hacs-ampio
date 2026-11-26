"""Regressions for lifecycle, registry ownership, and transport errors."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import aioampio
import pytest
import yaml
from aioampio import AmpioBridge
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from .conftest import CONFIG
from .test_config_flow import INPUT
from .test_integration import entity_id, make_entry, setup_entry

MAC = "d4:ad:20:8c:64:a0"


async def test_status_is_a_read_only_sensor(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Expose status feedback without registering an editable text platform."""
    await setup_entry(hass)
    await apis[0].state_store.set("00000123.response.1", {"response": "ready"})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, Platform.SENSOR, "text1")).state == "ready"
    assert (
        er.async_get(hass).async_get_entity_id(Platform.TEXT, "ampio", "00000123_text1")
        is None
    )
    assert not hass.services.has_service(Platform.TEXT, "set_value")
    apis[0].send.assert_not_awaited()


async def test_status_registry_migration_preserves_preferences(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Preserve customization while explaining the unavoidable domain change."""
    entry = make_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    area = ar.async_get(hass).async_create("User area")
    old = registry.async_get_or_create(
        Platform.TEXT,
        "ampio",
        "00000123_text1",
        config_entry=entry,
        suggested_object_id="custom_alarm_status",
        disabled_by=er.RegistryEntryDisabler.USER,
        hidden_by=er.RegistryEntryHider.USER,
    )
    registry.async_update_entity(
        old.entity_id, name="My status", icon="mdi:message", area_id=area.id
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    new_id = registry.async_get_entity_id(Platform.SENSOR, "ampio", old.unique_id)
    new = registry.async_get(new_id)
    assert new.entity_id == "sensor.custom_alarm_status"
    assert new.name == "My status"
    assert new.icon == "mdi:message"
    assert new.area_id == area.id
    assert new.disabled_by == er.RegistryEntryDisabler.USER
    assert new.hidden_by == er.RegistryEntryHider.USER
    assert registry.async_get(old.entity_id) is None
    issue = ir.async_get(hass).async_get_issue("ampio", f"text_migrated_{old.id}")
    assert issue.translation_placeholders == {
        "old_entity_id": old.entity_id,
        "new_entity_id": new_id,
    }
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(new_id).id == new.id


async def test_status_migration_retains_existing_sensor(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Retain an existing target's customization when both registry entries exist."""
    entry = make_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        Platform.TEXT, "ampio", "00000123_text1", config_entry=entry
    )
    target = registry.async_get_or_create(
        Platform.SENSOR,
        "ampio",
        old.unique_id,
        config_entry=entry,
        suggested_object_id="existing_status",
    )
    registry.async_update_entity(target.entity_id, name="Keep my name")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None
    assert registry.async_get(target.entity_id).id == target.id
    assert registry.async_get(target.entity_id).name == "Keep my name"


@pytest.mark.parametrize("result", [False, TimeoutError(), OSError("unreachable")])
async def test_temporary_setup_failure_retries(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    runtime_connection: AsyncMock,
    *,
    result: bool | Exception,
) -> None:
    """Let HA retry transient connectivity failures after closing the candidate API."""
    entry = make_entry()
    entry.add_to_hass(hass)
    runtime_connection.side_effect = [result]
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state == ConfigEntryState.SETUP_RETRY
    apis[0].stop.assert_awaited_once()


async def test_invalid_cached_config_is_permanent(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Invalid data is actionable and is not retried as a transport failure."""
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "ampio_config": {"devices": "invalid"}}
    )
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state == ConfigEntryState.SETUP_ERROR
    apis[0].start.assert_not_awaited()
    apis[0].stop.assert_awaited_once()


async def test_setup_failure_after_start_stops_transport(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Release the running transport if later resource registration fails."""
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.ampio.bridge.async_setup_devices",
        new=AsyncMock(side_effect=RuntimeError("registry failed")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    apis[0].start.assert_awaited_once()
    apis[0].stop.assert_awaited_once()


async def test_shutdown_and_unload_stop_once(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Shutting down and then unloading does not stop the same API twice."""
    entry = await setup_entry(hass)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    apis[0].stop.assert_awaited_once()
    assert await hass.config_entries.async_unload(entry.entry_id)
    apis[0].stop.assert_awaited_once()


async def test_cancelled_setup_stops_transport(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    runtime_connection: AsyncMock,
) -> None:
    """Cancelling HA setup while waiting for connectivity closes the candidate API."""
    waiting = asyncio.Event()

    async def wait() -> bool:
        waiting.set()
        await asyncio.Event().wait()
        return True

    runtime_connection.side_effect = wait
    entry = make_entry()
    entry.add_to_hass(hass)
    task = hass.async_create_task(hass.config_entries.async_setup(entry.entry_id))
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    apis[0].stop.assert_awaited_once()


@pytest.mark.parametrize(
    ("platform", "resource", "action", "data"),
    [
        (Platform.SWITCH, "switch2", "turn_on", {}),
        (Platform.LIGHT, "light1", "turn_on", {}),
        (Platform.COVER, "cover1", "open_cover", {}),
        (Platform.VALVE, "valve1", "open_valve", {}),
        (Platform.ALARM_CONTROL_PANEL, "alarm1", "alarm_arm_away", {"code": "1234"}),
    ],
)
@pytest.mark.skipif(
    not hasattr(aioampio, "AmpioTransmissionError"),
    reason="Public transmission errors require aioampio 2.0.2 or newer",
)
async def test_rejected_transport_raises_ha_error(  # noqa: PLR0913
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    platform: Platform,
    resource: str,
    action: str,
    data: dict[str, Any],
) -> None:
    """Exercise library sending with only the physical transport mocked."""
    await setup_entry(hass)
    api = apis[0]
    api.send = type(api).send.__get__(api)
    api._tx_handler.send = AsyncMock(return_value=False)
    with pytest.raises(HomeAssistantError, match="command could not be sent"):
        await hass.services.async_call(
            platform,
            action,
            {"entity_id": entity_id(hass, platform, resource), **data},
            blocking=True,
        )
    api._tx_handler.send.assert_awaited_once()


@pytest.mark.parametrize("selected_area", ["User room", None])
async def test_reload_preserves_user_areas_and_floor_metadata(
    hass: HomeAssistant, apis: list[AmpioBridge], selected_area: str | None
) -> None:
    """Suggestions never override edited or deliberately cleared registry settings."""
    entry = await setup_entry(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier(
        ("ampio", "00000123"), entry.entry_id
    )
    areas = ar.async_get(hass)
    user_area = areas.async_create("User room")
    area_id = user_area.id if selected_area else None
    devices.async_update_device(device.id, area_id=area_id)
    registry = er.async_get(hass)
    target = entity_id(hass, Platform.LIGHT, "light1")
    registry.async_update_entity(target, area_id=user_area.id)
    floor = fr.async_get(hass).async_get_floor_by_name("Ground")
    fr.async_get(hass).async_update(floor.floor_id, level=7)
    room = areas.async_get_area_by_name("Test room")
    areas.async_update(room.id, icon="mdi:sofa")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert devices.async_get(device.id).area_id == area_id
    assert registry.async_get(target).area_id == user_area.id
    assert fr.async_get(hass).async_get_floor(floor.floor_id).level == 7
    assert areas.async_get_area(room.id).icon == "mdi:sofa"


@pytest.mark.parametrize("supplied_mac", ["D4-AD-20-8C-64-A0", "D4AD208C64A0", MAC])
async def test_manual_gateway_mac_identity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, supplied_mac: str
) -> None:
    """Normalize a MAC supplied from the gateway's label or configuration."""
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_init(
            "ampio",
            context={"source": SOURCE_USER},
            data={**INPUT, "gateway_mac": supplied_mac},
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == f"{MAC}_20001"
    assert result["data"]["gateway_mac"] == MAC


async def test_dhcp_updates_address_and_preserves_registry(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """An address change retains bridge, module and entity registry identities."""
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "gateway_mac": MAC}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    gateway = registry.async_get_device_by_identifier(
        ("ampio", entry.entry_id), entry.entry_id
    )
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in gateway.connections
    old_entities = {
        e.id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    result = await hass.config_entries.flow.async_init(
        "ampio",
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(
            ip="192.0.2.9", hostname="can-gateway", macaddress=MAC.replace(":", "")
        ),
    )
    await hass.async_block_till_done()
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.9"
    assert entry.unique_id == f"{MAC}_20001"
    assert (
        registry.async_get_device_by_identifier(
            ("ampio", entry.entry_id), entry.entry_id
        ).id
        == gateway.id
    )
    assert {
        e.id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    } == old_entities
    assert len(apis) == 2
