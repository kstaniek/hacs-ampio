"""Exercise manual, discovered, and reconfigured endpoints through HA flows."""

from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import yaml
from aioampio import AmpioBridge
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
    assert result["result"].title == "CAN Bridge (waveshare / can0, 192.0.2.1:20001)"


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


@pytest.mark.parametrize(
    ("title", "expected_title"),
    [
        ("192.0.2.1:20001", "CAN Bridge (waveshare / can0, 192.0.2.2:20001)"),
        ("Garage gateway", "Garage gateway"),
    ],
)
async def test_reconfigure_preserves_bridge_device(
    hass: HomeAssistant,
    apis: list,
    aioclient_mock: AiohttpClientMocker,
    title: str,
    expected_title: str,
) -> None:
    """Move an endpoint and reload once while retaining the existing bridge device."""
    entry = await setup_entry(hass, title=title)
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
    assert entry.title == expected_title
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


@pytest.mark.parametrize(
    "config",
    [
        {"devices": "not-a-list"},
        {"devices": [{"can_id": 0x123, "model": "invalid"}]},
        {"devices": [{"can_id": 0x123}, {"can_id": 0x123}]},
    ],
)
async def test_invalid_ampio_config_keeps_form_recoverable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_apis: list[AmpioBridge],
    config: dict[str, Any],
) -> None:
    """Validate configuration using the actual library before opening a connection."""
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(config))
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data=INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"config_url": "invalid_config"}
    assert not hass.config_entries.async_entries("ampio")
    config_apis[0].start.assert_not_awaited()
    config_apis[0].stop.assert_awaited_once()
    aioclient_mock.clear_requests()
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
    config_apis[1].start.assert_awaited_once()
    config_apis[1].stop.assert_awaited_once()
    config_apis[1].send.assert_not_awaited()


@pytest.mark.parametrize(
    ("connection_result", "error"),
    [
        (False, "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (OSError(), "cannot_connect"),
        (RuntimeError("test failure"), "unknown"),
    ],
)
async def test_gateway_validation_error_and_recovery(  # noqa: PLR0913
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_apis: list[AmpioBridge],
    config_connection: AsyncMock,
    *,
    connection_result: bool | Exception,
    error: str,
) -> None:
    """Keep setup recoverable and close the candidate connection on every result."""
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    config_connection.side_effect = [connection_result, True]
    result = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_USER}, data=INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert not hass.config_entries.async_entries("ampio")
    config_apis[0].stop.assert_awaited_once()
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], INPUT
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "192.0.2.1:20001"
    config_apis[1].stop.assert_awaited_once()
    config_apis[1].send.assert_not_awaited()


async def test_invalid_reconfiguration_preserves_running_entry(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Do not replace data, identifiers, devices, or a running API with invalid YAML."""
    entry = await setup_entry(hass)
    previous_data = dict(entry.data)
    registry = dr.async_get(hass)
    gateway = registry.async_get_device_by_identifier(
        ("ampio", entry.unique_id), entry.entry_id
    )
    aioclient_mock.get(INPUT["config_url"], text="devices: not-a-list")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "host": "192.0.2.2"}
    )
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"config_url": "invalid_config"}
    assert dict(entry.data) == previous_data
    assert entry.unique_id == "192.0.2.1:20001"
    assert registry.async_get(gateway.id).identifiers == {("ampio", entry.unique_id)}
    apis[0].stop.assert_not_awaited()
    assert len(apis) == 1


async def test_unreachable_reconfiguration_preserves_running_entry(
    hass: HomeAssistant,
    apis: list[AmpioBridge],
    aioclient_mock: AiohttpClientMocker,
    config_connection: AsyncMock,
) -> None:
    """A valid download cannot replace the running entry with an unreachable host."""
    entry = await setup_entry(hass)
    previous_data = dict(entry.data)
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    config_connection.return_value = False
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "host": "192.0.2.2"}
    )
    await hass.async_block_till_done()
    assert result["errors"] == {"base": "cannot_connect"}
    assert dict(entry.data) == previous_data
    apis[0].stop.assert_not_awaited()
    assert len(apis) == 1


async def test_reconfigure_duplicate_created_during_download(
    hass: HomeAssistant,
) -> None:
    """Recheck endpoint ownership after awaiting the configuration server."""
    entry = make_entry()
    entry.add_to_hass(hass)

    async def download(_url: str) -> tuple[dict, dict]:
        other = MockConfigEntry(
            domain="ampio",
            version=2,
            unique_id="192.0.2.2:20001",
            data={**entry.data, "host": "192.0.2.2"},
        )
        other.add_to_hass(hass)
        return CONFIG, {}

    result = await entry.start_reconfigure_flow(hass)
    with patch(
        "custom_components.ampio.config_flow.AmpioFlowHandler.download_and_update_config",
        side_effect=download,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**INPUT, "host": "192.0.2.2"}
        )
    assert result["reason"] == "already_configured"
    assert entry.unique_id == "192.0.2.1:20001"
    assert entry.data["host"] == "192.0.2.1"
