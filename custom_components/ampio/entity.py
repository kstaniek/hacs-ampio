"""Generic Ampio Entity Model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

if TYPE_CHECKING:
    from aioampio.controllers.base import AmpioResourceController
    from aioampio.models.alarm_control_panel import AlarmControlPanel
    from aioampio.models.light import Light
    from aioampio.models.text import Text

    from .bridge import AmpioBridge

    type AmpioResource = Light | AlarmControlPanel | Text


class AmpioBaseEntity(Entity):
    """Base class for all Ampio entities."""

    _attr_should_pool = False

    def __init__(
        self,
        bridge: AmpioBridge,
        controller: AmpioResourceController,
        resource: AmpioResource,
    ) -> None:
        """Initialize the Ampio entity."""
        self.bridge = bridge
        self.controller = controller
        self.resource = resource
        self.device = controller.get_device(resource.id)
        self.logger = bridge.logger.getChild(resource.type.value)

        # Entity class attributes
        self._attr_unique_id = resource.id
        if self.device is None:
            # attach all device-less entities to the bridge itself
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, bridge.api.config.device.id)},
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.device.id)},
            )
        self._last_state = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which was added to hass."""
        if self.resource.area:
            area = ar.async_get(self.hass).async_get_area_by_name(self.resource.area)
            if area:
                er_reg = er.async_get(self.hass)
                er_reg.async_update_entity(self.entity_id, area_id=area.id)

        self.async_on_remove(
            self.controller.subscribe(
                self._handler_event,
                self.resource.id,
                (EventType.RESOURCE_UPDATED, EventType.RESOURCE_DELETED),
            )
        )

    @callback
    def on_update(self) -> None:
        """Call on update event."""
        # used in subclasses

    @callback
    def _handler_event(self, event_type: EventType, resource: AmpioResource) -> None:
        """Handle events from the controller."""
        if event_type == EventType.RESOURCE_DELETED:
            if self.device is not None and resource.id == self.resource.id:
                ent_reg = er.async_get(self.hass)
                ent_reg.async_remove(self.entity_id)
            return

        self.on_update()
        self.async_write_ha_state()
