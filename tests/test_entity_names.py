"""Generate entity IDs from configured names without changing registry identity."""

from copy import deepcopy

import pytest
from aioampio import AmpioBridge
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.ampio.const import (
    CONF_ENTITY_NAMES_MIGRATED,
    CONF_ENTITY_NAMES_VERSION,
    ENTITY_NAMES_VERSION,
)

from .test_integration import entity_id, make_entry

RESOURCES = [
    ("lights", "light", "light1"),
    ("switches", "switch", "switch2"),
    ("sensors", "sensor", "sensor1"),
    ("binary_sensors", "binary_sensor", "input1"),
    ("alarm_control_panels", "alarm_control_panel", "alarm1"),
    ("covers", "cover", "cover1"),
    ("valves", "valve", "valve1"),
    ("climates", "climate", "climate1"),
    ("texts", "sensor", "text1"),
]


@pytest.mark.parametrize(("collection", "domain", "resource"), RESOURCES)
async def test_module_area_prefixes_entity_id(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    collection: str,
    domain: str,
    resource: str,
) -> None:
    """Fall back to the module's YAML area across all configured platforms."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0][collection][0]["name"] = "Komoda"
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, domain, resource)
    assert target == f"{domain}.test_room_komoda"
    registered = er.async_get(hass).async_get(target)
    assert registered.original_name == "Komoda"
    assert registered.unique_id == f"00000123_{resource}"
    assert hass.states.get(target).attributes["friendly_name"].endswith("Komoda")
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(
    ("name", "area", "module_area", "expected"),
    [
        ("Duża łazienka", None, None, "duza_lazienka"),
        ("", None, None, "00000123_light1"),
        ("!!!", None, None, "unknown"),
        ("Komoda", "Salon", None, "salon_komoda"),
        ("Łóżko", "Pokój Emilii", None, "pokoj_emilii_lozko"),
        ("", "Salon", None, "salon_00000123_light1"),
        ("Salon", "Salon", None, "salon"),
        ("  ŁAZIENKA  ", "Łazienka", None, "lazienka"),
        ("Komoda", "   ", None, "komoda"),
        ("Komoda", None, "Salon", "salon_komoda"),
        ("Komoda", "   ", "Salon", "salon_komoda"),
        ("  ŁAZIENKA  ", None, "Łazienka", "lazienka"),
        ("Komoda", None, "   ", "komoda"),
    ],
)
async def test_light_name_slug_and_fallback(  # noqa: PLR0913
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    name: str,
    area: str | None,
    module_area: str | None,
    expected: str,
) -> None:
    """Transliterate Polish names and keep unnamed entities uniquely addressable."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0]["area"] = module_area
    data["ampio_config"]["devices"][0]["lights"][0].update(name=name, area=area)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id(hass, "light", "light1") == f"light.{expected}"
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(("collection", "domain", "resource"), RESOURCES)
async def test_configured_area_prefixes_entity_id(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    collection: str,
    domain: str,
    resource: str,
) -> None:
    """Use each resource's explicit YAML area rather than its module's area."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    device = data["ampio_config"]["devices"][0]
    device["area"] = "Server room"
    device[collection][0].update(name="Komoda", area="Duża łazienka")
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, domain, resource)
    assert target == f"{domain}.duza_lazienka_komoda"
    registered = er.async_get(hass).async_get(target)
    assert registered.unique_id == f"00000123_{resource}"
    assert registered.original_name == "Komoda"
    apis[0].send.assert_not_awaited()


async def test_duplicate_names_keep_distinct_resource_identities(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Let HA allocate suffixes without changing an existing helper or resource ID."""
    registry = er.async_get(hass)
    helper = registry.async_get_or_create(
        "light", "group", "existing-helper", suggested_object_id="test_room_komoda"
    )
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    lights = data["ampio_config"]["devices"][0]["lights"]
    lights[0]["name"] = "Komoda"
    lights.append({"id": "light2", "name": "Komoda", "states": ["binout.3"]})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    targets = {entity_id(hass, "light", resource) for resource in ("light1", "light2")}
    assert targets == {"light.test_room_komoda_2", "light.test_room_komoda_3"}
    assert registry.async_get(helper.entity_id) == helper
    assert len({registry.async_get(target).device_id for target in targets}) == 1
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(("collection", "domain", "resource"), RESOURCES)
async def test_existing_registry_preferences_survive_configured_name_change(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    collection: str,
    domain: str,
    resource: str,
) -> None:
    """Keep existing IDs, device associations and user names when YAML names change."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    original = registry.async_get(entity_id(hass, domain, resource))
    target = f"{domain}.my_entity"
    registry.async_update_entity(
        original.entity_id, new_entity_id=target, name="My custom name"
    )
    await hass.async_block_till_done()
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0][collection][0]["name"] = "Renamed in YAML"
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    registered = registry.async_get(target)
    assert registered.id == original.id
    assert registered.unique_id == original.unique_id
    assert registered.device_id == original.device_id
    assert registered.name == "My custom name"
    assert registered.original_name == "Renamed in YAML"
    assert entity_id(hass, domain, resource) == target
    assert (
        hass.states.get(target).attributes["friendly_name"].endswith("My custom name")
    )
    assert all(not api.send.await_count for api in apis)


@pytest.mark.parametrize(("collection", "domain", "resource"), RESOURCES)
async def test_existing_entity_ids_are_migrated_once(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    collection: str,
    domain: str,
    resource: str,
) -> None:
    """Rename legacy module-based IDs once while retaining registry preferences."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0][collection][0]["name"] = "Komoda"
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        domain,
        "ampio",
        f"00000123_{resource}",
        config_entry=entry,
        suggested_object_id="oswietlenie_1",
    )
    registry.async_update_entity(old.entity_id, name="My name", icon="mdi:star")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, domain, resource)
    assert target == f"{domain}.test_room_komoda"
    migrated = registry.async_get(target)
    assert migrated.id == old.id
    assert migrated.unique_id == old.unique_id
    assert migrated.name == "My name"
    assert migrated.icon == "mdi:star"
    assert registry.async_get(old.entity_id) is None
    assert entry.data[CONF_ENTITY_NAMES_MIGRATED] is True
    issue = ir.async_get(hass).async_get_issue(
        "ampio", f"entity_names_migrated_v{ENTITY_NAMES_VERSION}_{entry.entry_id}"
    )
    assert issue.translation_placeholders == {
        "renames": f"- `{old.entity_id}` → `{target}`"
    }
    custom_id = f"{domain}.chosen_after_migration"
    registry.async_update_entity(target, new_entity_id=custom_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id(hass, domain, resource) == custom_id
    assert registry.async_get(custom_id).id == old.id
    assert all(not api.send.await_count for api in apis)


async def test_migration_preserves_disabled_entities_and_other_entries(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Rename disabled resources without touching helpers or diagnostic sensors."""
    registry = er.async_get(hass)
    helper = registry.async_get_or_create(
        "light", "group", "helper", suggested_object_id="test_room_test_dimmer"
    )
    entry = make_entry()
    entry.add_to_hass(hass)
    old = registry.async_get_or_create(
        "light",
        "ampio",
        "00000123_light1",
        config_entry=entry,
        suggested_object_id="old_module_name",
        disabled_by=er.RegistryEntryDisabler.USER,
        hidden_by=er.RegistryEntryHider.USER,
    )
    diagnostic = registry.async_get_or_create(
        "sensor",
        "ampio",
        "00000123_rx_total",
        config_entry=entry,
        suggested_object_id="my_diagnostic",
    )
    foreign_entry = make_entry()
    foreign_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        foreign_entry,
        data={**foreign_entry.data, "host": "192.0.2.2"},
        unique_id="192.0.2.2:20001",
    )
    foreign = registry.async_get_or_create(
        "switch",
        "ampio",
        "00000456_switch2",
        config_entry=foreign_entry,
        suggested_object_id="another_entry",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, "light", "light1")
    assert target == "light.test_room_test_dimmer_2"
    migrated = registry.async_get(target)
    assert migrated.id == old.id
    assert migrated.disabled_by == er.RegistryEntryDisabler.USER
    assert migrated.hidden_by == er.RegistryEntryHider.USER
    assert hass.states.get(target) is None
    assert registry.async_get(helper.entity_id) == helper
    assert registry.async_get(diagnostic.entity_id).id == diagnostic.id
    assert registry.async_get(foreign.entity_id).id == foreign.id
    assert (
        registry.async_get(foreign.entity_id).config_entry_id == foreign_entry.entry_id
    )
    apis[0].send.assert_not_awaited()


@pytest.mark.parametrize(("collection", "domain", "resource"), RESOURCES)
async def test_area_migration_upgrades_previous_name_migration(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    collection: str,
    domain: str,
    resource: str,
) -> None:
    """Upgrade 0.8 IDs while keeping preferences and the earlier Repairs map."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data[CONF_ENTITY_NAMES_MIGRATED] = True
    data["ampio_config"]["devices"][0][collection][0].update(
        name="Komoda", area="Salon"
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    registry = er.async_get(hass)
    helper = registry.async_get_or_create(
        domain, "test", "existing-helper", suggested_object_id="salon_komoda"
    )
    module = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("ampio", "00000123")}
    )
    old = registry.async_get_or_create(
        domain,
        "ampio",
        f"00000123_{resource}",
        config_entry=entry,
        suggested_object_id="komoda",
        device_id=module.id,
        hidden_by=er.RegistryEntryHider.USER,
    )
    user_area = ar.async_get(hass).async_create("User-selected area")
    registry.async_update_entity(
        old.entity_id, name="My name", icon="mdi:star", area_id=user_area.id
    )
    old_issue_id = f"entity_names_migrated_{entry.entry_id}"
    ir.async_create_issue(
        hass,
        "ampio",
        old_issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="entity_names_migrated",
        translation_placeholders={"renames": "Earlier migration map"},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, domain, resource)
    assert target == f"{domain}.salon_komoda_2"
    migrated = registry.async_get(target)
    assert migrated.id == old.id
    assert migrated.unique_id == old.unique_id
    assert migrated.device_id == module.id
    assert migrated.name == "My name"
    assert migrated.icon == "mdi:star"
    assert migrated.area_id == user_area.id
    assert migrated.hidden_by == er.RegistryEntryHider.USER
    assert registry.async_get(old.entity_id) is None
    assert registry.async_get(helper.entity_id) == helper
    assert entry.data[CONF_ENTITY_NAMES_VERSION] == ENTITY_NAMES_VERSION
    issues = ir.async_get(hass)
    assert issues.async_get_issue("ampio", old_issue_id).translation_placeholders == {
        "renames": "Earlier migration map"
    }
    assert issues.async_get_issue(
        "ampio", f"entity_names_migrated_v{ENTITY_NAMES_VERSION}_{entry.entry_id}"
    ).translation_placeholders == {"renames": f"- `{old.entity_id}` → `{target}`"}
    custom_id = f"{domain}.my_custom_id"
    registry.async_update_entity(target, new_entity_id=custom_id)
    await hass.async_block_till_done()
    updated = deepcopy(dict(entry.data))
    updated["ampio_config"]["devices"][0][collection][0]["area"] = "Other YAML area"
    hass.config_entries.async_update_entry(entry, data=updated)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = registry.async_get(custom_id)
    assert reloaded.id == old.id
    assert reloaded.device_id == migrated.device_id
    assert entity_id(hass, domain, resource) == custom_id
    assert all(not api.send.await_count for api in apis)


async def test_area_upgrade_leaves_resources_without_any_area_unchanged(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Do not rename a resource with neither an entity area nor a module area."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data[CONF_ENTITY_NAMES_MIGRATED] = True
    data["ampio_config"]["devices"][0]["area"] = None
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "light",
        "ampio",
        "00000123_light1",
        config_entry=entry,
        suggested_object_id="my_custom_id",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id(hass, "light", "light1") == old.entity_id
    assert registry.async_get(old.entity_id).id == old.id
    assert entry.data[CONF_ENTITY_NAMES_VERSION] == ENTITY_NAMES_VERSION
    apis[0].send.assert_not_awaited()


async def test_module_area_migrates_existing_msens_sensors(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Give repeated MSENS sensor names room-specific IDs without replacing them."""
    entry = make_entry()
    data = deepcopy(dict(entry.data))
    data[CONF_ENTITY_NAMES_MIGRATED] = True
    modules = [(0x6F5F, "Salon", "salon"), (0x26C7, "Toaleta", "toaleta")]
    data["ampio_config"]["devices"] = [
        {
            "can_id": can_id,
            "name": area,
            "area": area,
            "model": 44,
            "sensors": [
                {
                    "id": "temperature1",
                    "name": "Temperatura",
                    "states": ["temperature.1"],
                    "device_class": "temperature",
                }
            ],
        }
        for can_id, area, _ in modules
    ]
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data=data)
    registry = er.async_get(hass)
    user_area = ar.async_get(hass).async_create("User-selected area")
    originals = []
    for can_id, _, _ in modules:
        module = dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("ampio", f"{can_id:08x}")},
        )
        old = registry.async_get_or_create(
            "sensor",
            "ampio",
            f"{can_id:08x}_temperature1",
            config_entry=entry,
            device_id=module.id,
            suggested_object_id="temperatura",
            disabled_by=er.RegistryEntryDisabler.USER,
            hidden_by=er.RegistryEntryHider.USER,
        )
        old = registry.async_update_entity(
            old.entity_id, area_id=user_area.id, name="My temperature"
        )
        originals.append(old)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for old, (_, _, slug) in zip(originals, modules, strict=True):
        migrated = registry.async_get(f"sensor.{slug}_temperatura")
        assert migrated.id == old.id
        assert migrated.unique_id == old.unique_id
        assert migrated.device_id == old.device_id
        assert migrated.name == old.name
        assert migrated.area_id == user_area.id
        assert migrated.disabled_by == old.disabled_by
        assert migrated.hidden_by == old.hidden_by
        assert registry.async_get(old.entity_id) is None
    assert entry.data[CONF_ENTITY_NAMES_VERSION] == ENTITY_NAMES_VERSION
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    for old, (_, _, slug) in zip(originals, modules, strict=True):
        assert registry.async_get(f"sensor.{slug}_temperatura").id == old.id
    assert all(not api.send.await_count for api in apis)
