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
from homeassistant.components.climate.const import HVACAction, HVACMode
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
    _attr_native_temperature_unit = "°C"
    _attr_supported_features = ClimateEntityFeature(0)

    def __init__(
        self, bridge: AmpioBridge, controller: ClimatesController, resource: Climate
    ) -> None:
        """Initialize Ampio Climate."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name
        self._attr_hvac_modes = []

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Report an enabled zone independently of its current heating activity."""
        if self.resource.state is None:
            return None
        return HVACMode.HEAT if self.resource.state else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return heating activity without inferring that an idle zone is off."""
        if self.resource.state is False:
            return HVACAction.OFF
        if self.resource.heating is None:
            return None
        return HVACAction.HEATING if self.resource.heating else HVACAction.IDLE

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.resource.current_temperature

    @property
    def native_target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.resource.target_temperature
