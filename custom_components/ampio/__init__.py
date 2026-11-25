"""Example Load Platform integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .bridge import PLATFORMS, AmpioBridge, AmpioConfigEntry
from .config_flow import endpoint_id
from .const import (
    CONF_CONFIG,
    CONF_CONFIG_URL,
    CONFIG_VERSION,
    DEFAULT_PORT,
    DOMAIN,
    MAX_PORT,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

LOGGER = logging.getLogger(__name__)


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType


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
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    if entry.runtime_data is None:
        return True
    return await entry.runtime_data.async_reset()


async def async_migrate_entry(  # noqa: PLR0911 - Preserve the entry on each failure.
    hass: HomeAssistant,
    entry: AmpioConfigEntry,
) -> bool:
    """Preserve version 1 bundled configuration when upgrading to cached config."""
    if entry.version > CONFIG_VERSION:
        LOGGER.error("Cannot migrate Ampio configuration from a newer version")
        return False
    if entry.version == CONFIG_VERSION:
        return True
    if entry.version != 1:
        return False
    data = dict(entry.data)
    host = data.get(CONF_HOST)
    try:
        port = int(data.get(CONF_PORT, DEFAULT_PORT))
    except (TypeError, ValueError):
        return False
    if not isinstance(host, str) or not host.strip() or not 1 <= port <= MAX_PORT:
        return False
    unique_id = endpoint_id(host, port)
    existing = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, unique_id)
    if existing is not None and existing.entry_id != entry.entry_id:
        LOGGER.error("Cannot migrate duplicate Ampio endpoint")
        return False
    if CONF_CONFIG not in data:

        def load_bundled_config() -> dict:
            with (
                Path(__file__).with_name("config.yaml").open(encoding="utf-8") as stream
            ):
                return yaml.safe_load(stream)

        try:
            data[CONF_CONFIG] = await hass.async_add_executor_job(load_bundled_config)
        except (OSError, yaml.YAMLError):
            LOGGER.exception("Cannot read the legacy Ampio configuration")
            return False
    if not isinstance(data[CONF_CONFIG], dict):
        return False
    data[CONF_HOST] = host.strip()
    data[CONF_PORT] = port
    data.setdefault(CONF_CONFIG_URL, "")
    hass.config_entries.async_update_entry(
        entry, data=data, unique_id=unique_id, version=CONFIG_VERSION, minor_version=1
    )
    return True
