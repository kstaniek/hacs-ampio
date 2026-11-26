"""Ampio Cover."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from aioampio.controllers.events import EventType
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverEntity,
    CoverEntityDescription,
    CoverEntityFeature,
)
from homeassistant.const import STATE_CLOSED, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.covers import CoversController
    from aioampio.models.cover import Cover
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .bridge import AmpioBridge, AmpioConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: AmpioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up cover entities."""
    bridge = config_entry.runtime_data
    api = bridge.api
    controller: CoversController = api.covers
    make_cover_entity = partial(AmpioCover, bridge, controller)

    @callback
    def async_add_cover(event_type: EventType, resource: Cover) -> None:
        """Add Ampio Cover."""
        async_add_entities([make_cover_entity(resource)])

    async_add_entities(make_cover_entity(cover) for cover in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_cover, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioCover(AmpioBaseEntity, CoverEntity):
    """Representation of an Ampio Cover."""

    entity_description = CoverEntityDescription(
        key="cover",
        has_entity_name=False,
    )

    def __init__(
        self, bridge: AmpioBridge, controller: CoversController, resource: Cover
    ) -> None:
        """Initialize the Ampio Cover."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name
        self._attr_device_class = resource.device_class
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.STOP
            | CoverEntityFeature.OPEN_TILT
            | CoverEntityFeature.CLOSE_TILT
            | CoverEntityFeature.STOP_TILT
            | CoverEntityFeature.SET_TILT_POSITION
        )

    @property
    def current_cover_position(self) -> int | None:
        """Return the reported cover position."""
        return (
            self.resource.cover.position
            if self.resource.state not in (None, STATE_UNKNOWN)
            else None
        )

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the reported tilt position."""
        return (
            self.resource.tilt.position
            if self.resource.state not in (None, STATE_UNKNOWN)
            else None
        )

    @property
    def is_closed(self) -> bool | None:
        """Return whether the reported cover state is closed."""
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

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.controller.open_cover(self.resource.id)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.controller.close_cover(self.resource.id)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self.controller.stop_cover(self.resource.id)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        await self.controller.set_position(
            self.resource.id,
            position=kwargs.get(ATTR_POSITION),
        )

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the cover tilt."""
        await self.controller.open_tilt(self.resource.id)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the cover tilt."""
        await self.controller.close_tilt(self.resource.id)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the cover tilt."""
        await self.controller.stop_tilt(self.resource.id)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set the cover tilt position."""
        await self.controller.set_position(
            self.resource.id,
            tilt_position=kwargs.get(ATTR_TILT_POSITION),
        )
