"""Example Load Platform integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IGNORE
from homeassistant.helpers import device_registry as dr

from .bridge import AmpioBridge, AmpioConfigEntry
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            vol.Schema(
                {
                    vol.Required("host"): vol.All(vol.Coerce(str)),
                    vol.Required("port"): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                },
                extra=vol.ALLOW_EXTRA,
            )
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Stub to allow setting up this component.

    Configuration through YAML is not supported at this time.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AmpioConfigEntry) -> bool:
    """Set up a bridge from config entry."""
    bridge = AmpioBridge(hass, entry)
    if not await bridge.async_initialize_bridge():
        return False

    unique_id = f"{bridge.host}_{bridge.port}_ethcan"
    if entry.unique_id is None:
        # Set unique ID for the config entry
        hass.config_entries.async_update_entry(entry, unique_id=unique_id)
    elif entry.unique_id != unique_id:
        other_entry = next(
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.unique_id == unique_id
        )
        if other_entry is None:
            # If no other entry, update unique ID of this entry ID
            hass.config_entries.async_update_entry(entry, unique_id=unique_id)
        elif other_entry.source == SOURCE_IGNORE:
            # If the other entry is ignored, update its unique ID
            hass.async_create_task(
                hass.config_entries.async_remove(other_entry, unique_id=unique_id)
            )
            hass.config_entries.async_update_entry(other_entry, unique_id=unique_id)
        else:
            # If the other entry is not ignored, we cannot change its unique ID
            hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
            return False
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id)},
        manufacturer="Ampio",
        model="Ampio",
        name="Ampio CAN Bridge",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AmpioConfigEntry) -> bool:
    """Unload a config entry."""
    return await entry.runtime_data.async_reset()
