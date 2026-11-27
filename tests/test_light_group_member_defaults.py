"""Keep group members registered with independent enabled and visible defaults."""

from copy import deepcopy

import pytest
from aioampio import AmpioBridge
from aioampio.models.light import Light
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from .test_integration import entity_id
from .test_light_groups import make_group_entry, payloads, service

pytestmark = pytest.mark.skipif(
    "members_visible" not in Light.__dataclass_fields__,
    reason="Member visibility defaults require an updated aioampio build",
)


@pytest.mark.parametrize("model", [4, 17])
@pytest.mark.parametrize("enabled", [None, True, False])
@pytest.mark.parametrize("visible", [None, True, False])
async def test_member_registry_defaults(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    model: int,
    *,
    enabled: bool | None,
    visible: bool | None,
) -> None:
    """Register disabled members on both families and retain native group control."""
    entry = make_group_entry()
    device = entry.data["ampio_config"]["devices"][0]
    device["model"] = model
    if model == 4:
        device["lights"] = [
            {"id": f"light{i}", "name": f"Relay {i}", "states": [f"binout.{i + 24}"]}
            for i in range(1, 9)
        ]
        device["light_groups"] = [
            {"id": "sofa", "name": "Sofa", "members": ["light3", "light5", "light6"]}
        ]
    group_config = next(g for g in device["light_groups"] if g["id"] == "sofa")
    if enabled is not None:
        group_config["members_enabled"] = enabled
    if visible is not None:
        group_config["members_visible"] = visible
    members = group_config["members"]
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    expected_disabler = (
        er.RegistryEntryDisabler.INTEGRATION if enabled is False else None
    )
    for resource in device["lights"]:
        target = entity_id(hass, "light", resource["id"])
        registered = registry.async_get(target)
        assert registered.disabled_by == (
            expected_disabler if resource["id"] in members else None
        )
        assert registered.hidden_by == (
            er.RegistryEntryHider.INTEGRATION
            if resource["id"] in members and visible is False
            else None
        )
        assert (hass.states.get(target) is None) is (registered.disabled_by is not None)
        assert apis[0].lights.get(registered.unique_id) is not None
    for group in device["light_groups"]:
        target = entity_id(hass, "light", "light_group_" + group["id"])
        assert registry.async_get(target).disabled_by is None
        assert registry.async_get(target).hidden_by is None
        assert hass.states.get(target) is not None
    group_id = entity_id(hass, "light", "light_group_sofa")
    for member in members:
        index = int(member.removeprefix("light"))
        topic = f"binout.{index + 24}" if model == 4 else f"aout.{index}"
        report = {"state": False} if model == 4 else {"value": 0}
        await apis[0].state_store.set(f"00000123.{topic}", report)
    await hass.async_block_till_done()
    assert hass.states.get(group_id).state == "off"
    index = int(members[0].removeprefix("light"))
    topic = f"binout.{index + 24}" if model == 4 else f"aout.{index}"
    await apis[0].state_store.set(
        f"00000123.{topic}", {"state": True} if model == 4 else {"value": 128}
    )
    await hass.async_block_till_done()
    assert hass.states.get(group_id).state == "on"
    apis[0].send.assert_not_awaited()
    await service(hass, "turn_off")
    assert payloads(apis[0]) == [
        "0000012314003400" if model == 4 else "00000123140000fc"
    ]
    assert hass.states.get(group_id).state == "on"
    if visible is False and enabled is not False:
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": entity_id(hass, "light", members[0])},
            blocking=True,
        )
        assert payloads(apis[0])[-1] == f"0000012315ff{index - 1:02x}00"


@pytest.mark.parametrize("reverse_groups", [False, True])
@pytest.mark.parametrize("option", ["members_enabled", "members_visible"])
async def test_overlapping_group_disabled_default_wins(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    option: str,
    *,
    reverse_groups: bool,
) -> None:
    """A default-enabled group cannot re-enable members of a default-disabled group."""
    entry = make_group_entry()
    groups = entry.data["ampio_config"]["devices"][0]["light_groups"]
    groups[2][option] = False
    if reverse_groups:
        groups.reverse()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for i in range(1, 17):
        registered = registry.async_get(entity_id(hass, "light", f"light{i}"))
        assert registered.disabled_by == (
            er.RegistryEntryDisabler.INTEGRATION
            if i in (1, 16) and option == "members_enabled"
            else None
        )
        assert registered.hidden_by == (
            er.RegistryEntryHider.INTEGRATION
            if i in (1, 16) and option == "members_visible"
            else None
        )
    apis[0].send.assert_not_awaited()


async def test_manual_member_choices_survive_reload(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Retain a manually enabled group member and a manually disabled ordinary light."""
    entry = make_group_entry()
    groups = entry.data["ampio_config"]["devices"][0]["light_groups"]
    groups[1]["members_enabled"] = False
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    enabled_id = entity_id(hass, "light", "light11")
    disabled_id = entity_id(hass, "light", "light1")
    original = registry.async_get(enabled_id)
    registry.async_update_entity(enabled_id, disabled_by=None)
    registry.async_update_entity(disabled_id, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(enabled_id).id == original.id
    assert registry.async_get(enabled_id).disabled_by is None
    assert hass.states.get(enabled_id) is not None
    assert registry.async_get(disabled_id).disabled_by == er.RegistryEntryDisabler.USER
    assert hass.states.get(disabled_id) is None
    assert all(not api.send.await_count for api in apis)


@pytest.mark.parametrize("option", ["members_enabled", "members_visible"])
async def test_reconfiguring_default_keeps_existing_member_choices(
    hass: HomeAssistant, apis: list[AmpioBridge], option: str
) -> None:
    """Keep saved choices when the initial registration default changes."""
    entry = make_group_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, "light", "light11")
    original = er.async_get(hass).async_get(target)
    data = deepcopy(dict(entry.data))
    data["ampio_config"]["devices"][0]["light_groups"][1][option] = False
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = er.async_get(hass).async_get(target)
    assert reloaded.id == original.id
    assert reloaded.disabled_by is None
    assert reloaded.hidden_by is None
    assert hass.states.get(target) is not None
    assert all(not api.send.await_count for api in apis)


async def test_manual_visibility_choices_survive_reload(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """Retain manually shown members and manually hidden ordinary lights."""
    entry = make_group_entry()
    entry.data["ampio_config"]["devices"][0]["light_groups"][1]["members_visible"] = (
        False
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    shown_id = entity_id(hass, "light", "light11")
    hidden_id = entity_id(hass, "light", "light1")
    original = registry.async_get(shown_id)
    assert original.hidden_by == er.RegistryEntryHider.INTEGRATION
    registry.async_update_entity(shown_id, hidden_by=None)
    registry.async_update_entity(hidden_id, hidden_by=er.RegistryEntryHider.USER)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(shown_id).id == original.id
    assert registry.async_get(shown_id).hidden_by is None
    assert registry.async_get(hidden_id).hidden_by == er.RegistryEntryHider.USER
    assert hass.states.get(shown_id) is not None
    assert hass.states.get(hidden_id) is not None
    assert all(not api.send.await_count for api in apis)


async def test_area_command_skips_hidden_members(
    hass: HomeAssistant, apis: list[AmpioBridge]
) -> None:
    """An area action targets the native group without extra indexed member writes."""
    entry = make_group_entry()
    entry.data["ampio_config"]["devices"][0]["light_groups"][1]["members_visible"] = (
        False
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    area = ar.async_get(hass).async_get_area_by_name("Living room")
    registry = er.async_get(hass)
    for i in range(11, 17):
        registry.async_update_entity(
            entity_id(hass, "light", f"light{i}"), area_id=area.id
        )
    await hass.async_block_till_done()
    await hass.services.async_call(
        "light", "turn_off", {"area_id": area.id}, blocking=True
    )
    assert payloads(apis[0]) == ["00000123140000fc"]
