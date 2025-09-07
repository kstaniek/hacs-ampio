"""Ampio Switch."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from aioampio.controllers.events import EventType
from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.switch import SwitchesController
    from aioampio.models.switch import Switch
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: SwitchesController = api.switches
    make_switch_entity = partial(AmpioSwitch, bridge, controller)

    @callback
    def async_add_switch(event_type: EventType, resource: Switch) -> None:
        """Add Ampio Switch."""
        async_add_entities([make_switch_entity(resource)])

    async_add_entities(make_switch_entity(switch) for switch in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_switch, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioSwitch(AmpioBaseEntity, SwitchEntity):
    """Representation of an Ampio Binary Switch."""

    entity_description = SwitchEntityDescription(
        key="binary_switch",
        has_entity_name=False,
    )

    def __init__(
        self, bridge: AmpioBridge, controller: SwitchesController, resource: Switch
    ) -> None:
        """Initialize the Ampio switch."""
        super().__init__(bridge, controller, resource)

        self.name = resource.name

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        return bool(self.resource.state)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.controller.set_state(id=self.resource.id, on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.controller.set_state(id=self.resource.id, on=False)
