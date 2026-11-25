"""Exercise manual, discovered, and reconfigured endpoints through HA flows."""

from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import yaml
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from .conftest import CONFIG
from .test_integration import make_entry, setup_entry

INPUT = {
    "host": "192.0.2.1",
    "port": 20001,
    "config_url": "https://example.invalid/config.yaml",
}


def discovery(**overrides: Any) -> ZeroconfServiceInfo:
    """Build discovery data without contacting mDNS."""
    return ZeroconfServiceInfo(
        **{
            "ip_address": ip_address("192.0.2.1"),
            "ip_addresses": [ip_address("192.0.2.1")],
            "port": 20001,
            "hostname": "can-test.local.",
            "type": "_can-server._tcp.local.",
            "name": "can-test._can-server._tcp.local.",
            "properties": {},
            **overrides,
        }
    )


async def test_manual_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Download and cache YAML, normalize whitespace, and retain endpoint identity."""
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **INPUT,
                "host": " 192.0.2.1 ",
                "config_url": " " + INPUT["config_url"] + " ",
            },
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {**INPUT, "ampio_config": CONFIG}
    assert result["result"].unique_id == "192.0.2.1:20001"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("[", "invalid_yaml"),
        ("[]", "invalid_yaml"),
        ("", "invalid_yaml"),
        ("42", "invalid_yaml"),
    ],
)
async def test_invalid_yaml(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, body: str, expected: str
) -> None:
    """A syntactically valid non-mapping must not create an unusable config entry."""
    aioclient_mock.get(INPUT["config_url"], text=body)
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data=INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"config_url": expected}
    assert result["data_schema"]({}) == INPUT


@pytest.mark.parametrize("url", ["file:///tmp/config.yaml", "http://", "not a URL"])
async def test_invalid_url(hass: HomeAssistant, url: str) -> None:
    """Reject unsupported or hostless URLs before accessing the network."""
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data={**INPUT, "config_url": url}
    )
    assert result["errors"] == {"config_url": "invalid_url"}


@pytest.mark.parametrize(
    ("exception", "error"),
    [(TimeoutError(), "timeout"), (aiohttp.ClientConnectionError(), "cannot_connect")],
)
async def test_download_failure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    exception: Exception,
    error: str,
) -> None:
    """Keep the form recoverable when the configuration server fails."""
    aioclient_mock.get(INPUT["config_url"], exc=exception)
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data=INPUT
    )
    assert result["errors"] == {"config_url": error}


async def test_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reject unsuccessful HTTP responses."""
    aioclient_mock.get(INPUT["config_url"], status=404)
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data=INPUT
    )
    assert result["errors"] == {"config_url": "cannot_connect"}


async def test_discovery_confirmation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Discovery pre-fills the endpoint but creates nothing without confirmation."""
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {"name": "can-test"}
    assert result["data_schema"]({"config_url": INPUT["config_url"]}) == INPUT
    assert not hass.config_entries.async_entries("ampio")
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], INPUT
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "192.0.2.1:20001"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"name": "other._can-server._tcp.local."}, "not_can_bridge"),
        ({"type": "_other._tcp.local."}, "not_can_bridge"),
        ({"port": None}, "invalid_discovery"),
        ({"port": 0}, "invalid_discovery"),
        ({"port": 65536}, "invalid_discovery"),
    ],
)
async def test_invalid_discovery(
    hass: HomeAssistant, overrides: dict[str, Any], reason: str
) -> None:
    """Ignore unrelated services and invalid advertised ports."""
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_ZEROCONF}, data=discovery(**overrides)
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.parametrize("source", [SOURCE_USER, SOURCE_ZEROCONF])
@pytest.mark.parametrize("unique_id", [None, "192.0.2.1:20001"])
async def test_existing_endpoint(
    hass: HomeAssistant, source: str, unique_id: str | None
) -> None:
    """Prevent duplicates even for an existing entry without a unique ID."""
    entry = MockConfigEntry(
        domain="ampio", version=2, unique_id=unique_id, data=make_entry().data
    )
    entry.add_to_hass(hass)
    data = INPUT if source == SOURCE_USER else discovery()
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": source}, data=data
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_discovery_in_progress(hass: HomeAssistant) -> None:
    """Do not offer the same bridge twice during concurrent discovery."""
    first = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    second = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    assert first["type"] == FlowResultType.FORM
    assert second["type"] == FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"


async def test_reconfigure_preserves_bridge_device(
    hass: HomeAssistant, apis: list, aioclient_mock: AiohttpClientMocker
) -> None:
    """Move an endpoint and reload once while retaining the existing bridge device."""
    entry = await setup_entry(hass)
    registry = dr.async_get(hass)
    before = registry.async_get_device_by_identifier(
        ("ampio", entry.unique_id), entry.entry_id
    )
    assert before is not None
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "host": "192.0.2.2"}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "192.0.2.2:20001"
    assert entry.data["host"] == "192.0.2.2"
    after = registry.async_get_device_by_identifier(
        ("ampio", entry.unique_id), entry.entry_id
    )
    assert after.id == before.id
    assert len(apis) == 2


async def test_reconfigure_duplicate(hass: HomeAssistant) -> None:
    """Reject moving an entry onto an endpoint that already exists."""
    entry = make_entry()
    entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain="ampio",
        version=2,
        unique_id="192.0.2.2:20001",
        data={**entry.data, "host": "192.0.2.2"},
    )
    other.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "host": "192.0.2.2"}
    )
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.1"
