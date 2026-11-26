"""Ampio Valve."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.valve import (
    ValveEntity,
    ValveEntityDescription,
    ValveEntityFeature,
)
from homeassistant.const import STATE_CLOSED, STATE_UNKNOWN
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
    def current_valve_position(self) -> int | None:
        """Return the reported valve position."""
        return (
            self.resource.valve.position
            if self.resource.state not in (None, STATE_UNKNOWN)
            else None
        )

    @property
    def is_closed(self) -> bool | None:
        """Return whether the reported valve state is closed."""
        if self.resource.state in (None, STATE_UNKNOWN):
            return None
        return self.resource.state == STATE_CLOSED

    @property
    def is_opening(self) -> bool:
        """Return whether the module reports opening motion."""
        return self.resource.opening

    @property
    def is_closing(self) -> bool:
        """Return whether the module reports closing motion."""
        return self.resource.closing

    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""
        await self.async_command(
            self.controller.set_position(
                self.resource.id,
                position=position,
            )
        )

    async def async_stop_valve(self) -> None:
        """Stop the valve."""
        await self.async_command(self.controller.stop_valve(self.resource.id))

    async def async_open_valve(self) -> None:
        """Open the valve."""
        await self.async_command(self.controller.open_valve(self.resource.id))

    async def async_close_valve(self) -> None:
        """Close the valve."""
        await self.async_command(self.controller.close_valve(self.resource.id))
