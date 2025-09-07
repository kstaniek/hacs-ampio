"""Ampio Climate."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.climates import ClimatesController
    from aioampio.models.climate import Climate
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
    controller: ClimatesController = api.climates
    make_climate_entity = partial(AmpioClimate, bridge, controller)

    @callback
    def async_add_climate(event_type: EventType, resource: Climate) -> None:
        """Add Climate."""
        async_add_entities([make_climate_entity(resource)])

    async_add_entities(make_climate_entity(climate) for climate in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_climate, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioClimate(AmpioBaseEntity, ClimateEntity):
    """Representation of an Ampio Climate."""

    entity_description = ClimateEntityDescription(
        key="ampio_climate",
        has_entity_name=False,
    )
    _attr_temperature_unit = "°C"
    _attr_hvac_modes = (HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT)
    _attr_hvac_mode = HVACMode.HEAT

    def __init__(
        self, bridge: AmpioBridge, controller: ClimatesController, resource: Climate
    ) -> None:
        """Initialize Ampio Climate."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def state(self) -> str | None:
        """Return the current state."""
        if self.resource.heating is None:
            return None
        if self.resource.heating:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.resource.current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.resource.target_temperature
