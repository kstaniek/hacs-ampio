"""Generic Ampio Entity Model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aioampio.controllers.events import EventType
from can import CanError
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from aioampio.controllers.base import AmpioResourceController
    from aioampio.models.alarm_control_panel import AlarmControlPanel
    from aioampio.models.light import Light
    from aioampio.models.text import Text

    from .bridge import AmpioBridge

    type AmpioResource = Light | AlarmControlPanel | Text


class AmpioBaseEntity(Entity):
    """Base class for all Ampio entities."""

    _attr_should_poll = False

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
        self._attr_name = resource.name
        domain = (
            Platform.SENSOR if resource.type.value == "text" else resource.type.value
        )
        # Suggest a complete ID so HA does not prefix the owning module's name.
        self.entity_id = f"{domain}.{slugify(resource.name) or slugify(resource.id)}"
        if self.device is None:
            # attach all device-less entities to the bridge itself
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, bridge.config_entry.entry_id)},
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.device.id)},
            )
        self._last_state = None

    @property
    def available(self) -> bool:
        """Expose module silence without changing registry identity or state data."""
        if self.bridge.traffic is None:
            return True
        return self.bridge.traffic.available(
            self.device.can_id if self.device is not None else None
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity which was added to hass."""
        if self.bridge.traffic is not None:
            self.async_on_remove(
                self.bridge.traffic.subscribe(
                    self.device.can_id if self.device is not None else None,
                    self.async_write_ha_state,
                )
            )
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

    async def async_command(self, command: Awaitable[Any]) -> None:
        """Translate transport failures into actionable HA service errors."""
        try:
            await command
        except (OSError, CanError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from err

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
