"""Exercise diagnostic entities and passive availability through real HA setup."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest
from aioampio import AmpioBridge
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

from .test_integration import entity_id, make_entry

pytestmark = [
    pytest.mark.usefixtures("apis"),
    pytest.mark.skipif(
        not hasattr(AmpioBridge, "module_metrics"),
        reason="Requires the per-module metrics API in the local aioampio checkout",
    ),
]


async def setup_modules(hass: HomeAssistant) -> tuple:
    """Set up two independent owners, including one without configured sensors."""
    entry = make_entry()
    entry.add_to_hass(hass)
    config = deepcopy(entry.data["ampio_config"])
    config["devices"].append(
        {
            "can_id": 0x124,
            "model": 4,
            "name": "Second module",
            "lights": [
                {"id": "light1", "name": "Second light", "states": ["binout.1"]}
            ],
        }
    )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "ampio_config": config}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, entry.runtime_data.traffic


def snapshot(
    age: float | None,
    rx: int = 1,
    tx: int = 0,
    timestamp: datetime | None = None,
    reconnects: int = 0,
) -> SimpleNamespace:
    """Represent the public immutable metrics contract without physical I/O."""
    return SimpleNamespace(
        rx_total=rx,
        tx_total=tx,
        last_rx_age_s=age,
        last_rx_at=timestamp,
        reconnects=reconnects,
    )


async def test_all_modules_have_diagnostics(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Attach counters to existing module devices and retain readable offline data."""
    entry, monitor = await setup_modules(hass)
    registry = er.async_get(hass)
    diagnostics = [
        entity
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.entity_category == er.EntityCategory.DIAGNOSTIC
    ]
    assert len(diagnostics) == 10
    assert len({entity.device_id for entity in diagnostics}) == 3
    timestamps = [
        entity for entity in diagnostics if entity.unique_id.endswith("last_rx_at")
    ]
    assert len(timestamps) == 3
    for entity in timestamps:
        assert entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity.entity_id) is None
    counters = [
        entity
        for entity in diagnostics
        if entity.unique_id.endswith(("rx_total", "tx_total"))
    ]
    for entity in counters:
        state = hass.states.get(entity.entity_id)
        expected_rx = "2" if entity.unique_id.startswith(entry.entry_id) else "1"
        assert state.state == (
            expected_rx if entity.unique_id.endswith("rx_total") else "0"
        )
        assert state.attributes["state_class"] == "total_increasing"
        assert state.attributes["unit_of_measurement"] == "frames"
    with patch.object(
        type(apis[0]), "module_metrics", new_callable=PropertyMock
    ) as data:
        data.return_value = {0x123: snapshot(61), 0x124: snapshot(0)}
        monitor.async_refresh()
        assert (
            hass.states.get(entity_id(hass, "light", "light1")).state == "unavailable"
        )
        assert all(
            hass.states.get(entity.entity_id).state != "unavailable"
            for entity in counters
        )
    apis[0].send.assert_not_awaited()


async def test_silence_and_unchanged_rx_restore_all_owner_entities(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """A shared timer changes availability without resource value changes or TX."""
    entry, monitor = await setup_modules(hass)
    api = apis[0]
    await api.state_store.set("00000123.binout.2", {"state": True})
    await hass.async_block_till_done()
    functional = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.unique_id.startswith("00000123_") and entity.entity_category is None
    ]
    with patch.object(type(api), "module_metrics", new_callable=PropertyMock) as data:
        data.return_value = {0x123: snapshot(60, tx=99), 0x124: snapshot(0)}
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
        await hass.async_block_till_done()
        assert all(
            hass.states.get(entity).state == "unavailable" for entity in functional
        )
        assert monitor.available(0x124)
        second_light = er.async_get(hass).async_get_entity_id(
            "light", "ampio", "00000124_light1"
        )
        assert hass.states.get(second_light).state != "unavailable"
        # No value/controller event: receipt alone recovers cached entity states.
        data.return_value = {0x123: snapshot(0, rx=2, tx=99), 0x124: snapshot(0)}
        monitor.async_refresh()
        assert all(
            hass.states.get(entity).state != "unavailable" for entity in functional
        )
        assert hass.states.get(entity_id(hass, "switch", "switch2")).state == "on"
    api.send.assert_not_awaited()
    assert not api._reconnect_now.is_set()


async def test_gateway_reconnect_counter(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Publish only changed counts, independently of traffic throttling."""
    entry, monitor = await setup_modules(hass)
    api = apis[0]
    registry = er.async_get(hass)
    counters = [
        entity
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.unique_id.endswith("_reconnects")
    ]
    assert len(counters) == 1
    counter = counters[0]
    assert counter.unique_id == f"{entry.entry_id}_reconnects"
    assert counter.entity_category == er.EntityCategory.DIAGNOSTIC
    assert counter.disabled_by is None
    gateway = dr.async_get(hass).async_get_device_by_identifier(
        ("ampio", entry.entry_id), entry.entry_id
    )
    assert counter.device_id == gateway.id
    state = hass.states.get(counter.entity_id)
    assert state.state == "0"
    assert state.attributes["state_class"] == "total_increasing"
    assert "unit_of_measurement" not in state.attributes
    with (
        patch("custom_components.ampio.traffic.monotonic", return_value=100) as clock,
        patch.object(type(api), "connected", new_callable=PropertyMock) as connected,
    ):
        monitor._last_publish = 100
        connected.return_value = False
        api._reconnects = 3
        clock.return_value = 129
        # Older published APIs have no push notification; use the 1s monitor.
        if hasattr(api, "subscribe_reconnects"):
            api._reconnects = 2
            api._record_reconnect()
        else:
            assert hass.states.get(counter.entity_id).state == "0"
            monitor.async_refresh()
        assert hass.states.get(counter.entity_id).state == "3"
        assert monitor._last_publish == 100
        # Neither unchanged values nor periodic traffic updates notify this sensor.
        with patch.object(monitor, "_reconnect_listeners", [changed := Mock()]):
            monitor.async_refresh()
            clock.return_value = 130
            monitor.async_refresh()
            changed.assert_not_called()
        connected.return_value = True
        clock.return_value = 160
        monitor.async_refresh()
        assert hass.states.get(counter.entity_id).state == "3"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(counter.entity_id).id == counter.id
    assert hass.states.get(counter.entity_id).state == "0"
    assert not monitor._diagnostic_listeners
    assert not monitor._reconnect_listeners
    for instance in apis:
        instance.send.assert_not_awaited()
        assert not instance._reconnect_now.is_set()
    if hasattr(api, "subscribe_reconnects"):
        assert not api._reconnect_listeners


async def test_fresh_rx_required_after_connection_and_diagnostics_throttled(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Require fresh RX on reconnect and publish counters at a bounded frequency."""
    _, monitor = await setup_modules(hass)
    api = apis[0]
    counter = er.async_get(hass).async_get_entity_id(
        "sensor", "ampio", "00000123_rx_total"
    )
    light = entity_id(hass, "light", "light1")
    with (
        patch.object(type(api), "module_metrics", new_callable=PropertyMock) as data,
        patch.object(type(api), "connected", new_callable=PropertyMock) as connected,
        patch("custom_components.ampio.traffic.monotonic", return_value=100) as clock,
    ):
        monitor._last_publish = 100
        connected.return_value = False
        data.return_value = {0x123: snapshot(0, rx=5), 0x124: snapshot(0)}
        monitor.async_refresh()
        assert hass.states.get(light).state == "unavailable"
        connected.return_value = True
        data.return_value = {0x123: snapshot(None, rx=5), 0x124: snapshot(None)}
        monitor.async_refresh()
        assert hass.states.get(light).state == "unavailable"
        data.return_value = {0x123: snapshot(0, rx=6), 0x124: snapshot(0)}
        monitor.async_refresh()
        assert hass.states.get(light).state != "unavailable"
        assert hass.states.get(counter).state == "1"
        clock.return_value = 130
        monitor.async_refresh()
        assert hass.states.get(counter).state == "6"


async def test_options_normalize_overrides_and_reload_once(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Persist a global timeout and a disabled module without altering CAN YAML."""
    entry, _ = await setup_modules(hass)
    original_config = deepcopy(dict(entry.data))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"module_timeout": 120, "module_timeouts": {"0x123": 0}}
    )
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {"module_timeout": 120, "module_timeouts": {"00000123": 0}}
    assert entry.data == original_config
    assert len(apis) == 2
    monitor = entry.runtime_data.traffic
    with patch.object(
        type(apis[1]), "module_metrics", new_callable=PropertyMock
    ) as data:
        data.return_value = {0x123: snapshot(None), 0x124: snapshot(119)}
        monitor.async_refresh()
        assert monitor.available(0x123)
        assert monitor.available(0x124)
        data.return_value = {0x123: snapshot(999), 0x124: snapshot(120)}
        monitor.async_refresh()
        assert monitor.available(0x123)
        assert not monitor.available(0x124)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not monitor._diagnostic_listeners
    assert not any(monitor._listeners.values())


async def test_global_disable_still_respects_transport_disconnect(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Disabling silence checks does not conceal a reported gateway failure."""
    entry, _ = await setup_modules(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"module_timeout": 0, "module_timeouts": {}}
    )
    await hass.async_block_till_done()
    api = apis[-1]
    monitor = entry.runtime_data.traffic
    with (
        patch.object(type(api), "module_metrics", new_callable=PropertyMock) as data,
        patch.object(type(api), "connected", new_callable=PropertyMock) as connected,
    ):
        data.return_value = {0x123: snapshot(None), 0x124: snapshot(999)}
        connected.return_value = True
        monitor.async_refresh()
        assert monitor.available(0x123)
        assert monitor.available(0x124)
        connected.return_value = False
        monitor.async_refresh()
        assert not monitor.available(0x123)
        assert not monitor.available(0x124)


@pytest.mark.parametrize(
    "options",
    [
        {"module_timeout": -1},
        {"module_timeout": 86401},
        {"module_timeout": 0.5},
        {"module_timeout": 60, "module_timeouts": {"00009999": 0}},
        {"module_timeout": 60, "module_timeouts": {"123": -1}},
        {"module_timeout": 60, "module_timeouts": {"123": 1, "00000123": 2}},
    ],
)
async def test_invalid_monitoring_options(hass: HomeAssistant, options: dict) -> None:
    """Reject typoed module IDs and invalid durations without changing options."""
    entry, _ = await setup_modules(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    if options["module_timeout"] < 0 or options["module_timeout"] > 86400:
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                result["flow_id"], options
            )
        assert not entry.options
        return
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_module_timeout"}
    assert not entry.options


async def test_gateway_totals_and_last_frame_timestamps(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Use gateway-wide totals and retain actual reception timestamps while offline."""
    entry, monitor = await setup_modules(hass)
    api = apis[0]
    registry = er.async_get(hass)
    gateway = {
        key: registry.async_get_entity_id("sensor", "ampio", f"{entry.entry_id}_{key}")
        for key in ("rx_total", "tx_total", "last_rx_at")
    }
    module_timestamp = registry.async_get_entity_id(
        "sensor", "ampio", "00000123_last_rx_at"
    )
    for entity in (gateway["last_rx_at"], module_timestamp):
        registry.async_update_entity(entity, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    api = apis[-1]
    monitor = entry.runtime_data.traffic
    gateway_device = dr.async_get(hass).async_get_device_by_identifier(
        ("ampio", entry.entry_id), entry.entry_id
    )
    assert registry.async_get(gateway["rx_total"]).device_id == gateway_device.id
    stamp = datetime(2026, 11, 26, 10, 20, 30, tzinfo=UTC)
    with (
        patch.object(type(api), "module_metrics", new_callable=PropertyMock) as modules,
        patch.object(type(api), "metrics", new_callable=PropertyMock) as totals,
        patch.object(type(api), "connected", new_callable=PropertyMock) as connected,
        patch("custom_components.ampio.traffic.monotonic", return_value=100) as clock,
    ):
        modules.return_value = {
            0x123: snapshot(0, rx=4, timestamp=stamp),
            0x124: snapshot(0),
        }
        totals.return_value = snapshot(0, rx=100, tx=25, timestamp=stamp)
        connected.return_value = True
        monitor._last_publish = 70
        monitor.async_refresh()
        assert hass.states.get(gateway["rx_total"]).state == "100"
        assert hass.states.get(gateway["tx_total"]).state == "25"
        assert hass.states.get(gateway["last_rx_at"]).state == stamp.isoformat()
        state = hass.states.get(module_timestamp)
        assert state.state == stamp.isoformat()
        assert state.attributes["device_class"] == "timestamp"
        assert "unit_of_measurement" not in state.attributes
        assert "state_class" not in state.attributes
        connected.return_value = False
        clock.return_value = 130
        monitor.async_refresh()
        assert hass.states.get(module_timestamp).state == stamp.isoformat()
        assert hass.states.get(gateway["last_rx_at"]).state == stamp.isoformat()
        assert hass.states.get(gateway["rx_total"]).state == "100"
    assert (
        registry.async_get(gateway["rx_total"]).device_id
        != registry.async_get(module_timestamp).device_id
    )
    api.send.assert_not_awaited()
