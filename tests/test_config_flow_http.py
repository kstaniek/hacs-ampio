"""Exercise config forms through the same HTTP serialization used by the UI."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from aiohttp.test_utils import TestClient
from homeassistant.components.config import config_entries
from homeassistant.config_entries import SOURCE_ZEROCONF
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import ClientSessionGenerator

from .conftest import CONFIG
from .test_config_flow import INPUT, discovery
from .test_integration import make_entry

FLOW_URL = "/api/config/config_entries/flow"


@pytest.fixture
async def config_client(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> TestClient:
    """Register HA's actual authenticated config-flow HTTP endpoints."""
    assert await async_setup_component(hass, "http", {})
    config_entries.async_setup(hass)
    return await hass_client()


async def test_manual_form_http(config_client: TestClient) -> None:
    """Opening manual setup must return serializable fields instead of HTTP 500."""
    response = await config_client.post(FLOW_URL, json={"handler": "ampio"})
    assert response.status == HTTPStatus.OK
    result = await response.json()
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    fields = {field["name"]: field for field in result["data_schema"]}
    assert set(fields) == {"host", "port", "config_url"}
    assert fields["host"]["type"] == "string"
    assert fields["port"]["default"] == 20001


async def test_reconfigure_form_http(
    hass: HomeAssistant, config_client: TestClient
) -> None:
    """Render the pre-filled reconfiguration form through the frontend endpoint."""
    entry = make_entry()
    entry.add_to_hass(hass)
    response = await config_client.post(
        FLOW_URL, json={"handler": "ampio", "entry_id": entry.entry_id}
    )
    assert response.status == HTTPStatus.OK
    result = await response.json()
    assert result["step_id"] == "reconfigure"
    assert result["type"] == "form"
    fields = {field["name"]: field for field in result["data_schema"]}
    assert {key: fields[key]["default"] for key in ("host", "port", "config_url")} == {
        key: entry.data[key] for key in ("host", "port", "config_url")
    }


async def test_discovery_form_http(
    hass: HomeAssistant, config_client: TestClient
) -> None:
    """Discovery confirmation shares the same UI serialization requirements."""
    flow = await hass.config_entries.flow.async_init(
        "ampio", context={"source": SOURCE_ZEROCONF}, data=discovery()
    )
    response = await config_client.get(f"{FLOW_URL}/{flow['flow_id']}")
    assert response.status == HTTPStatus.OK
    result = await response.json()
    assert result["step_id"] == "discovery_confirm"
    fields = {field["name"]: field for field in result["data_schema"]}
    assert fields["host"]["default"] == "192.0.2.1"


async def test_error_form_http(config_client: TestClient) -> None:
    """A validation error must also render correctly on the browser retry path."""
    response = await config_client.post(FLOW_URL, json={"handler": "ampio"})
    assert response.status == HTTPStatus.OK
    flow = await response.json()
    response = await config_client.post(
        f"{FLOW_URL}/{flow['flow_id']}",
        json={**INPUT, "config_url": "file:///tmp/config.yaml"},
    )
    assert response.status == HTTPStatus.OK
    result = await response.json()
    assert result["errors"] == {"config_url": "invalid_url"}


@pytest.mark.parametrize("host", [" ", "\t  "])
async def test_blank_host_http(config_client: TestClient, host: str) -> None:
    """Reject an empty normalized host without a YAML download or unusable entry."""
    response = await config_client.post(FLOW_URL, json={"handler": "ampio"})
    assert response.status == HTTPStatus.OK
    flow = await response.json()
    response = await config_client.post(
        f"{FLOW_URL}/{flow['flow_id']}", json={**INPUT, "host": host}
    )
    assert response.status == HTTPStatus.OK
    result = await response.json()
    assert result["type"] == "form"
    assert result["errors"] == {"host": "invalid_host"}


async def test_reconfigure_refreshes_cached_yaml_http(
    hass: HomeAssistant, config_client: TestClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Submit the rendered form and replace the old cached codecs configuration."""
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "ampio_config": {**CONFIG, "codecs": [{"module": "aioampio.codec.ampio"}]},
        },
    )
    aioclient_mock.get(INPUT["config_url"], text=yaml.safe_dump(CONFIG))
    response = await config_client.post(
        FLOW_URL, json={"handler": "ampio", "entry_id": entry.entry_id}
    )
    assert response.status == HTTPStatus.OK
    flow = await response.json()
    with patch(
        "custom_components.ampio.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        response = await config_client.post(
            f"{FLOW_URL}/{flow['flow_id']}", json={**INPUT, "host": " 192.0.2.1 "}
        )
        await hass.async_block_till_done()
    assert response.status == HTTPStatus.OK
    result = await response.json()
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["ampio_config"] == CONFIG
    assert entry.data["host"] == "192.0.2.1"
    assert entry.unique_id == "192.0.2.1:20001"
