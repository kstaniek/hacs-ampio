"""Gateway hardware identity and address-change regressions."""

from ipaddress import ip_address
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from aioampio import AmpioBridge
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from .conftest import CONFIG
from .test_config_flow import INPUT, discovery
from .test_integration import make_entry
from .test_remaining_review import MAC


@pytest.mark.parametrize(
    "mac", ["123", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:01"]
)
async def test_invalid_mac_is_recoverable(hass: HomeAssistant, mac: str) -> None:
    """Reject a malformed address before any configuration or gateway I/O."""
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data={**INPUT, "gateway_mac": mac}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"gateway_mac": "invalid_mac"}


@pytest.mark.parametrize("port", [20001, 20002])
async def test_same_mac_endpoint_duplicate(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, port: int
) -> None:
    """Prevent duplicates after an IP change while allowing separate CAN endpoints."""
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "gateway_mac": MAC}, unique_id=f"{MAC}_20001"
    )
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_init(
            "ampio",
            context={"source": SOURCE_USER},
            data={**INPUT, "host": "192.0.2.9", "port": port, "gateway_mac": MAC},
        )
        await hass.async_block_till_done()
    if port == 20001:
        assert result["reason"] == "already_configured"
    else:
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == f"{MAC}_20002"


@pytest.mark.parametrize("supplied_mac", [None, "", "d4:ad:20:8c:64:a1"])
async def test_reconfigure_mac_connections(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    aioclient_mock: AiohttpClientMocker,
    supplied_mac: str | None,
) -> None:
    """Keep an omitted MAC, and replace stale connections when explicitly edited."""
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "gateway_mac": MAC}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    device_id = devices.async_get_device_by_identifier(
        ("ampio", entry.entry_id), entry.entry_id
    ).id
    data = {key: value for key, value in INPUT.items() if key != "gateway_mac"}
    if supplied_mac is not None:
        data["gateway_mac"] = supplied_mac
    data["host"] = "192.0.2.9"
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    expected_mac = MAC if supplied_mac is None else supplied_mac
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["gateway_mac"] == expected_mac
    assert devices.async_get(device_id).connections == (
        {(dr.CONNECTION_NETWORK_MAC, expected_mac)} if expected_mac else set()
    )
    assert (
        devices.async_get_device_by_identifier(
            ("ampio", entry.entry_id), entry.entry_id
        ).id
        == device_id
    )


@pytest.mark.parametrize("title", ["192.0.2.1:20001", "My gateway"])
async def test_zeroconf_mac_address_change(
    hass: HomeAssistant, apis: list[AmpioBridge], title: str
) -> None:
    """Use the advertised hardware identity and preserve custom titles."""
    entry = make_entry(title)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "gateway_mac": MAC}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_init(
        "ampio",
        context={"source": SOURCE_ZEROCONF},
        data=discovery(
            ip_address=ip_address("192.0.2.9"),
            ip_addresses=[ip_address("192.0.2.9")],
            properties={"mac": MAC.upper()},
        ),
    )
    await hass.async_block_till_done()
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.9"
    assert entry.unique_id == f"{MAC}_20001"
    assert entry.title == (
        "My gateway"
        if title == "My gateway"
        else "CAN Bridge (waveshare / can0, 192.0.2.9:20001)"
    )


async def test_mac_removal_preserves_other_gateway_port(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Editing one port cannot remove another entry's hardware connection."""
    first = make_entry()
    first.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        first, data={**first.data, "gateway_mac": MAC}
    )
    assert await hass.config_entries.async_setup(first.entry_id)
    second = MockConfigEntry(
        domain="ampio",
        version=3,
        unique_id=f"{MAC}_20002",
        data={**first.data, "port": 20002, "ampio_config": {}},
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    devices = dr.async_get(hass)
    device_id = devices.async_get_device_by_identifier(
        ("ampio", second.entry_id), second.entry_id
    ).id
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    result = await first.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert first.data["gateway_mac"] == ""
    assert second.data["gateway_mac"] == MAC
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in devices.async_get(device_id).connections
