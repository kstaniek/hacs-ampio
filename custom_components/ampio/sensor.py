"""Ampio Sensor."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    StateType,
)
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from aioampio.controllers.sensor import SensorsController
    from aioampio.models.sensor import Sensor
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry


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
