"""Ampio Sensor."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from aioampio.controllers.sensor import SensorsController
    from aioampio.controllers.texts import TextsController
    from aioampio.models.device import Device
    from aioampio.models.sensor import Sensor
    from aioampio.models.text import Text
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from .bridge import AmpioBridge, AmpioConfigEntry
    from .traffic import ModuleTrafficMonitor


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up light entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: SensorsController = api.sensors
    make_sensor_entity = partial(AmpioSensor, bridge, controller)

    @callback
    def async_add_sensor(event_type: EventType, resource: Sensor) -> None:
        """Add Ampio Sensor."""
        async_add_entities([make_sensor_entity(resource)])

    async_add_entities(make_sensor_entity(sensor) for sensor in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_sensor, event_filter=EventType.RESOURCE_ADDED)
    )

    @callback
    def async_add_text(event_type: EventType, resource: Text) -> None:
        """Expose status messages without editable text controls."""
        async_add_entities([AmpioTextSensor(bridge, api.texts, resource)])

    async_add_entities(AmpioTextSensor(bridge, api.texts, text) for text in api.texts)
    config_entry.async_on_unload(
        api.texts.subscribe(async_add_text, event_filter=EventType.RESOURCE_ADDED)
    )
    if bridge.traffic is not None:
        async_add_entities(
            AmpioTrafficSensor(bridge.traffic, None, counter)
            for counter in ("rx_total", "tx_total", "last_rx_at")
        )

        @callback
        def async_add_diagnostics(event_type: EventType, resource: Device) -> None:
            """Add traffic counters to modules even without configured sensors."""
            async_add_entities(
                AmpioTrafficSensor(bridge.traffic, resource, counter)
                for counter in ("rx_total", "tx_total", "last_rx_at")
            )

        for device in api.devices:
            async_add_diagnostics(EventType.RESOURCE_ADDED, device)
        config_entry.async_on_unload(
            api.devices.subscribe(
                async_add_diagnostics, event_filter=EventType.RESOURCE_ADDED
            )
        )


class AmpioTrafficSensor(SensorEntity):
    """Diagnostic traffic counter which remains readable during module silence."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "frames"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, traffic: ModuleTrafficMonitor, device: Device | None, counter: str
    ) -> None:
        """Attach a stable counter identity to the existing module device."""
        self._traffic = traffic
        self._can_id = device.can_id if device is not None else None
        self._counter = counter
        owner_id = (
            device.id if device is not None else traffic.bridge.config_entry.entry_id
        )
        identifier = (
            device.id if device is not None else traffic.bridge.config_entry.entry_id
        )
        self._attr_unique_id = f"{owner_id}_{counter}"
        self._attr_translation_key = counter
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, identifier)})
        if counter == "last_rx_at":
            self._attr_entity_registry_enabled_default = False
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_native_unit_of_measurement = None
            self._attr_state_class = None

    @property
    def native_value(self) -> int | datetime | None:
        """Return the most recently published counter snapshot."""
        snapshot = (
            self._traffic.gateway_metrics
            if self._can_id is None
            else self._traffic.metrics.get(self._can_id)
        )
        if snapshot is not None:
            return getattr(snapshot, self._counter, None)
        return None

    async def async_added_to_hass(self) -> None:
        """Keep diagnostic updates separate from functional availability."""
        self.async_on_remove(
            self._traffic.subscribe_diagnostics(self.async_write_ha_state)
        )


class AmpioSensor(AmpioBaseEntity, SensorEntity):
    """Representation of an Ampio Sensor."""

    entity_description = SensorEntityDescription(
        key="sensor",
        has_entity_name=False,
    )

    def __init__(
        self, bridge: AmpioBridge, controller: SensorsController, resource: Sensor
    ) -> None:
        """Initialize the Ampio sensor."""
        super().__init__(bridge, controller, resource)
        self._attr_device_class = resource.device_class
        self._attr_native_unit_of_measurement = resource.unit_of_measurement
        self.name = resource.name

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the value reported by the sensor."""
        return self.resource.state


class AmpioTextSensor(AmpioBaseEntity, SensorEntity):
    """Represent a read-only Ampio status message."""

    entity_description = SensorEntityDescription(
        key="ampio_status", has_entity_name=False
    )

    def __init__(
        self, bridge: AmpioBridge, controller: TextsController, resource: Text
    ) -> None:
        """Initialize the status sensor."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name

    @property
    def native_value(self) -> str | None:
        """Return the latest reported message."""
        return self.resource.state
