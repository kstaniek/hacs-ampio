"""Ampio Valve."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from aioampio.controllers.events import EventType
from homeassistant.components.valve import (
    ATTR_CURRENT_POSITION,
    ValveEntity,
    ValveEntityDescription,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.valves import ValvesController
    from aioampio.models.valve import Valve
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
    controller: ValvesController = api.valves
    make_valve_entity = partial(AmpioValve, bridge, controller)

    @callback
    def async_add_valve(event_type: EventType, resource: Valve) -> None:
        """Add Ampio Valve."""
        async_add_entities([make_valve_entity(resource)])

    async_add_entities(make_valve_entity(valve) for valve in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_valve, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioValve(AmpioBaseEntity, ValveEntity):
    """Representation of an Ampio Valve."""

    entity_description = ValveEntityDescription(
        key="ampio_valve",
        has_entity_name=False,
    )
    _attr_reports_position = True

    def __init__(
        self, bridge: AmpioBridge, controller: ValvesController, resource: Valve
    ) -> None:
        """Initialize the Ampio valve."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name
        self._attr_supported_features = (
            ValveEntityFeature.OPEN
            | ValveEntityFeature.CLOSE
            | ValveEntityFeature.SET_POSITION
            | ValveEntityFeature.STOP
        )

    @property
    def state(self) -> str:
        """Return the state of the valve."""
        return self.resource.state

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        data = {}

        if (current := self.resource.valve.position) is not None:
            data[ATTR_CURRENT_POSITION] = current

        return data

    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""
        await self.controller.set_position(
            self.resource.id,
            position=position,
        )

    async def async_stop_valve(self) -> None:
        """Stop the valve."""
        await self.controller.stop_valve(self.resource.id)

    async def async_open_valve(self) -> None:
        """Open the valve."""
        await self.controller.open_valve(self.resource.id)

    async def async_close_valve(self) -> None:
        """Close valve."""
        await self.controller.close_valve(self.resource.id)
