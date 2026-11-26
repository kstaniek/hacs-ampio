"""Support for Ampio Alarm Control Panels connected to Satel."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityDescription,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant, callback

from .entity import AmpioBaseEntity

if TYPE_CHECKING:
    from aioampio.controllers.alarm_control_panels import AlarmControlPanelsController
    from aioampio.models.alarm_control_panel import AlarmControlPanel
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
    controller: AlarmControlPanelsController = api.alarm_control_panels
    make_alarm_entity = partial(AmpioAlarm, bridge, controller)

    @callback
    def async_add_alarm(event_type: EventType, resource: AlarmControlPanel) -> None:
        """Add Ampio Alarm Control Panel."""
        async_add_entities([make_alarm_entity(resource)])

    async_add_entities(make_alarm_entity(alarm) for alarm in controller)
    config_entry.async_on_unload(
        controller.subscribe(async_add_alarm, event_filter=EventType.RESOURCE_ADDED)
    )


class AmpioAlarm(AmpioBaseEntity, AlarmControlPanelEntity):
    """Representation of an Ampio alarm control panel."""

    _attr_code_format = CodeFormat.NUMBER
    entity_description = AlarmControlPanelEntityDescription(
        key="ampio_alarm",
        has_entity_name=False,
    )
    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY

    def __init__(
        self,
        bridge: AmpioBridge,
        controller: AlarmControlPanelsController,
        resource: AlarmControlPanel,
    ) -> None:
        """Initialize the Ampio entity."""
        super().__init__(bridge, controller, resource)
        self.name = resource.name

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the current alarm control panel entity state."""
        resource_state = (
            self.resource.get_state()
            if hasattr(self.resource, "get_state")
            else self.resource.state
        )
        if not resource_state:
            return None
        if resource_state.get("alarm") is True:
            return AlarmControlPanelState.TRIGGERED
        if resource_state.get("breached") is True:
            return AlarmControlPanelState.PENDING
        if (
            resource_state.get("arming") is True
            or resource_state.get("arming_10s") is True
        ):
            return AlarmControlPanelState.ARMING
        if (armed := resource_state.get("armed")) is None:
            return None
        return (
            AlarmControlPanelState.ARMED_AWAY
            if armed
            else AlarmControlPanelState.DISARMED
        )

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        await self.async_command(self.controller.disarm(self.resource.id, code))

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        await self.async_command(self.controller.arm_in_mode0(self.resource.id, code))
