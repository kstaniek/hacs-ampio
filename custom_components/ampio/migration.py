"""Migrate entity IDs while preserving registry identity and preferences."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_ENTITY_NAMES_MIGRATED,
    CONF_ENTITY_NAMES_VERSION,
    DOMAIN,
    ENTITY_NAMES_VERSION,
)
from .utils import entity_area, entity_object_id

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .bridge import AmpioBridge


@callback
def async_migrate_entity_names(bridge: AmpioBridge) -> None:
    """Rename configured resources once, leaving later user ID choices intact."""
    entry = bridge.config_entry
    previous_version = entry.data.get(
        CONF_ENTITY_NAMES_VERSION,
        1 if entry.data.get(CONF_ENTITY_NAMES_MIGRATED) else 0,
    )
    if previous_version >= ENTITY_NAMES_VERSION:
        return
    hass = bridge.hass
    registry = er.async_get(hass)
    renames = []
    controllers = (
        (Platform.LIGHT, bridge.api.lights),
        (Platform.ALARM_CONTROL_PANEL, bridge.api.alarm_control_panels),
        (Platform.BINARY_SENSOR, bridge.api.binary_sensors),
        (Platform.SENSOR, bridge.api.sensors),
        (Platform.SENSOR, bridge.api.texts),
        (Platform.SWITCH, bridge.api.switches),
        (Platform.COVER, bridge.api.covers),
        (Platform.VALVE, bridge.api.valves),
        (Platform.CLIMATE, bridge.api.climates),
    )
    for domain, controller in controllers:
        for resource in controller:
            device = controller.get_device(resource.id)
            area = entity_area(resource.area, device.area if device else None)
            if previous_version >= 1 and not area:
                continue
            old_id = registry.async_get_entity_id(domain, DOMAIN, resource.id)
            if old_id is None:
                continue
            old = registry.async_get(old_id)
            if old.config_entry_id != entry.entry_id:
                continue
            new_id = registry.async_get_available_entity_id(
                domain,
                entity_object_id(resource.name, resource.id, area),
                current_entity_id=old_id,
            )
            if new_id == old_id:
                continue
            registry.async_update_entity(old_id, new_entity_id=new_id)
            renames.append(f"- `{old_id}` → `{new_id}`")
    if renames:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"entity_names_migrated_v{ENTITY_NAMES_VERSION}_{entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="entity_names_migrated",
            translation_placeholders={"renames": "\n".join(renames)},
        )
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_ENTITY_NAMES_MIGRATED: True,
            CONF_ENTITY_NAMES_VERSION: ENTITY_NAMES_VERSION,
        },
    )


@callback
def async_migrate_text_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    resource_object_ids: Mapping[str, str] | None = None,
) -> None:
    """Copy preferences to status sensors before removing obsolete text entities."""
    registry = er.async_get(hass)
    for old in er.async_entries_for_config_entry(registry, entry.entry_id):
        if old.domain != Platform.TEXT:
            continue
        target_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, old.unique_id)
        if target_id is None:
            object_id = old.entity_id.partition(".")[2]
            if resource_object_ids is not None and old.unique_id in resource_object_ids:
                object_id = resource_object_ids[old.unique_id]
            target = registry.async_get_or_create(
                Platform.SENSOR,
                DOMAIN,
                old.unique_id,
                config_entry=entry,
                suggested_object_id=object_id,
                device_id=old.device_id,
                disabled_by=old.disabled_by,
                hidden_by=old.hidden_by,
                original_name=old.original_name,
                original_icon=old.original_icon,
            )
            target_id = target.entity_id
            registry.async_update_entity(
                target_id,
                name=old.name,
                icon=old.icon,
                area_id=old.area_id,
                aliases=old.aliases,
                labels=old.labels,
            )
        registry.async_remove(old.entity_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"text_migrated_{old.id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="text_migrated",
            translation_placeholders={
                "old_entity_id": old.entity_id,
                "new_entity_id": target_id,
            },
        )
