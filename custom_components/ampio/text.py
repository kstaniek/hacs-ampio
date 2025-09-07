"""Text representation of the Ampio alarm control panel."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.text import (
    TextEntity,
    TextEntityDescription,
)
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.text import TextsController
    from aioampio.models.text import Text
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: TextsController = api.texts
    make_text_entity = partial(AmpioText, bridge, controller)

    @callback
    def async_add_text(event_type: EventType, resource: Text) -> None:
        """Add Ampio Text."""
        async_add_entities([make_text_entity(resource)])

    async_add_entities(make_text_entity(text) for text in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_text, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioText(AmpioBaseEntity, TextEntity):
    """Representation of an Ampio text entity."""

    entity_description = TextEntityDescription(
        key="ampio_alarm",
        has_entity_name=False,
    )
    _attr_native_value = ""

    def __init__(
        self,
        bridge: AmpioBridge,
        controller: TextsController,
        resource: Text,
    ) -> None:
        """Initialize the Ampio entity."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name

    @property
    def state(self) -> str | None:
        """Return the current state of the text entity."""
        if self.resource.state is None:
            return None
        return self.resource.state
