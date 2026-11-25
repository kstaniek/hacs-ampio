"""Handling devices for the Ampio integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aioampio.controllers.events import EventType
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

if TYPE_CHECKING:
    from aioampio import AmpioBridge
    from aioampio.models.device import Device
    from homeassistant.helpers.device_registry import DeviceEntry

    from custom_components.ampio.entity import AmpioResource

    AmpioDevice = "AmpioDevice"


async def async_setup_devices(bridge: AmpioBridge) -> None:
    """Manage setup of devices from Ampio Bridge."""
    entry = bridge.config_entry
    hass = bridge.hass
    dev_reg = dr.async_get(hass)
    ar_reg = ar.async_get(hass)
    dev_controller = bridge.api.devices

    @callback
    def add_device(ampio_resource: AmpioResource) -> DeviceEntry:
        """Register Ampio Device in device registry."""
        params = {
            "identifiers": {(DOMAIN, ampio_resource.id)},
            "name": f"{ampio_resource.name}",
            "manufacturer": "Ampio",
            "model": ampio_resource.model.name,
            "model_id": str(ampio_resource.model.value),
            "sw_version": str(ampio_resource.sw_version),
            "hw_version": str(ampio_resource.pcb),
            "serial_number": f"{ampio_resource.can_id:08X}",
        }

        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            **params,
        )

        area = (
            ar_reg.async_get_area_by_name(ampio_resource.area)
            if ampio_resource.area
            else None
        )
        if area:
            device = dev_reg.async_update_device(device.id, area_id=area.id)

        return device

    @callback
    def remove_device(ampio_resource_id: str) -> None:
        """Remove Ampio Device from device registry."""
        if device := dev_reg.async_get_device(
            identifiers={(DOMAIN, ampio_resource_id)}
        ):
            dev_reg.async_remove_device(device.id)

    @callback
    def handle_device_event(evt_type: EventType, ampio_resource: Device) -> None:
        """Handle events from Ampio devices."""
        if evt_type == EventType.RESOURCE_DELETED:
            remove_device(ampio_resource.id)

        else:
            add_device(ampio_resource)

    ampio_devices = list(dev_controller)
    known_device_ids = {add_device(ampio_device).id for ampio_device in ampio_devices}
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if (
            device.id not in known_device_ids
            and (DOMAIN, entry.unique_id) not in device.identifiers
        ):
            dev_reg.async_remove_device(device.id)

    entry.async_on_unload(dev_controller.subscribe(handle_device_event))
