"""Ampio Binary Sensor."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.binary_sensor import BinarySensorsController
    from aioampio.models.binary_sensor import BinarySensor
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
    controller: BinarySensorsController = api.binary_sensors
    make_binary_sensor_entity = partial(AmpioBinarySensor, bridge, controller)

    @callback
    def async_add_binary_sensor(event_type: EventType, resource: BinarySensor) -> None:
        """Add Ampio Binary Sensor."""
        async_add_entities([make_binary_sensor_entity(resource)])

    async_add_entities(make_binary_sensor_entity(sensor) for sensor in controller)
    config_entry.async_on_unload(
        controller.subscribe(
            async_add_binary_sensor, event_filter=EventType.RESOURCE_ADDED
        )
    )


class AmpioBinarySensor(AmpioBaseEntity, BinarySensorEntity):
    """Representation of an Ampio Binary Sensor."""

    entity_description = BinarySensorEntityDescription(
        key="ampio_binary_sensor",
        has_entity_name=False,
    )

    def __init__(
        self,
        bridge: AmpioBridge,
        controller: BinarySensorsController,
        resource: BinarySensor,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(bridge, controller, resource)

        self._attr_device_class = resource.device_class
        self.name = resource.name

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self.resource.state
