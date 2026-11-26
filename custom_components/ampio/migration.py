"""Preserve registry preferences while moving read-only text to sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


@callback
def async_migrate_text_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Copy preferences to status sensors before removing obsolete text entities."""
    registry = er.async_get(hass)
    for old in er.async_entries_for_config_entry(registry, entry.entry_id):
        if old.domain != Platform.TEXT:
            continue
        target_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, old.unique_id)
        if target_id is None:
            target = registry.async_get_or_create(
                Platform.SENSOR,
                DOMAIN,
                old.unique_id,
                config_entry=entry,
                suggested_object_id=old.entity_id.partition(".")[2],
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
