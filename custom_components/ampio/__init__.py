"""Example Load Platform integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .bridge import PLATFORMS, AmpioBridge, AmpioConfigEntry
from .config_flow import endpoint_id, gateway_id
from .const import (
    CONF_CONFIG,
    CONF_CONFIG_URL,
    CONF_GATEWAY_MAC,
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
    if not isinstance(entry.data.get(CONF_CONFIG), dict):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"config_required_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="config_required",
            translation_placeholders={"name": entry.title},
        )
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="configuration_required"
        )
    bridge = AmpioBridge(hass, entry)
    if entry.title in {entry.unique_id, f"{bridge.host}:{bridge.port}"}:
        hass.config_entries.async_update_entry(
            entry, title=bridge.connection_description
        )
    try:
        await bridge.async_initialize_bridge()
        device_registry = dr.async_get(hass)
        connections = (
            {(dr.CONNECTION_NETWORK_MAC, entry.data[CONF_GATEWAY_MAC])}
            if entry.data.get(CONF_GATEWAY_MAC)
            else set()
        )
        gateway = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            connections=connections,
            manufacturer=bridge.manufacturer,
            model=bridge.connection_description,
            name="Ampio CAN Bridge",
        )
        # Older HA versions can share one device across gateway-port entries.
        connections |= {
            (dr.CONNECTION_NETWORK_MAC, other.data[CONF_GATEWAY_MAC])
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
            and (DOMAIN, other.entry_id) in gateway.identifiers
            and other.data.get(CONF_GATEWAY_MAC)
        }
        device_registry.async_update_device(
            gateway.id,
            new_connections={
                connection
                for connection in gateway.connections
                if connection[0] != dr.CONNECTION_NETWORK_MAC
            }
            | connections,
        )
    except BaseException:
        await bridge.async_reset()
        raise
    ir.async_delete_issue(hass, DOMAIN, f"config_required_{entry.entry_id}")
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
    """Retain legacy configuration and migrate address-based registry identifiers."""
    if entry.version > CONFIG_VERSION:
        LOGGER.error("Cannot migrate Ampio configuration from a newer version")
        return False
    if entry.version == CONFIG_VERSION:
        return True
    if entry.version not in (1, 2):
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
    if any(
        other.entry_id != entry.entry_id
        and other.data.get(CONF_HOST) is not None
        and endpoint_id(other.data[CONF_HOST], int(other.data[CONF_PORT])) == unique_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        LOGGER.error("Cannot migrate duplicate Ampio endpoint")
        return False
    if entry.version == 1 and CONF_CONFIG not in data:

        def load_bundled_config() -> dict:
            with (
                Path(__file__).with_name("config.yaml").open(encoding="utf-8") as stream
            ):
                return yaml.safe_load(stream)

        try:
            config = await hass.async_add_executor_job(load_bundled_config)
        except (OSError, yaml.YAMLError):
            config = None
        if isinstance(config, dict):
            data[CONF_CONFIG] = config

    # Registry identity is local to this entry, independently of network address.
    registry = dr.async_get(hass)
    if entry.unique_id is not None and (
        gateway := registry.async_get_device_by_identifier(
            (DOMAIN, entry.unique_id), entry.entry_id
        )
    ):
        registry.async_update_device(
            gateway.id,
            new_identifiers=(gateway.identifiers - {(DOMAIN, entry.unique_id)})
            | {(DOMAIN, entry.entry_id)},
        )
    data[CONF_HOST] = host.strip()
    data[CONF_PORT] = port
    data.setdefault(CONF_CONFIG_URL, "")
    data.setdefault(CONF_GATEWAY_MAC, "")
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        unique_id=gateway_id(data[CONF_GATEWAY_MAC], port),
        version=CONFIG_VERSION,
        minor_version=1,
    )
    return True
