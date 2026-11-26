"""Keep real HA and Ampio controllers while capturing physical I/O."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import can
import pytest
from aioampio import AmpioBridge

CONFIG = {
    "floors": [
        {
            "id": "ground",
            "name": "Ground",
            "level": 0,
            "areas": [{"id": "room", "name": "Test room"}],
        }
    ],
    "devices": [
        {
            "can_id": 0x123,
            "model": 4,
            "name": "Test module",
            "area": "Test room",
            "lights": [
                {
                    "id": "light1",
                    "name": "Test dimmer",
                    "states": ["aout.1", "binout.1"],
                }
            ],
            "switches": [
                {"id": "switch2", "name": "Test relay", "states": ["binout.2"]}
            ],
            "sensors": [
                {
                    "id": "sensor1",
                    "name": "Test temperature",
                    "states": ["temperature.1"],
                    "device_class": "temperature",
                }
            ],
            "binary_sensors": [
                {"id": "input1", "name": "Test input", "states": ["bin.1"]}
            ],
            "alarm_control_panels": [
                {
                    "id": "alarm1",
                    "name": "Test alarm",
                    "states": [
                        "armed.1",
                        "alarm.1",
                        "arming.1",
                        "arming_10s.1",
                        "breached.1",
                    ],
                }
            ],
            "covers": [
                {
                    "id": "cover1",
                    "name": "Test cover",
                    "states": ["aout.2", "binout.3", "binout.4"],
                }
            ],
            "valves": [{"id": "valve1", "name": "Test valve", "states": ["aout.3"]}],
            "climates": [
                {"id": "climate1", "name": "Test climate", "states": ["heating.1"]}
            ],
            "texts": [{"id": "text1", "name": "Test text", "states": ["response.1"]}],
        }
    ],
}


@pytest.fixture(autouse=True)
def skip_dependency_install() -> Iterator[None]:
    """Use the explicitly installed matrix dependency without invoking pip."""
    with patch(
        "homeassistant.requirements.async_process_requirements", new=AsyncMock()
    ):
        yield


@pytest.fixture
def runtime_connection() -> AsyncMock:
    """Control setup's gateway-connectivity result separately from config flows."""
    return AsyncMock(return_value=True)


@pytest.fixture
def apis(runtime_connection: AsyncMock) -> Iterator[list[AmpioBridge]]:
    """Load actual resources and encoders; replace only connection and CAN writes."""
    instances = []

    def create(
        cfg: dict[str, Any],
        interface: str = "waveshare",
        channel: str = "can0",
        **kwargs: Any,
    ) -> AmpioBridge:
        api = AmpioBridge(cfg, interface=interface, channel=channel, **kwargs)
        api.start = AsyncMock()
        api.wait_connected = runtime_connection
        if hasattr(api, "module_metrics"):

            async def start() -> None:
                api._connection_state = type(api.connection_state).CONNECTED
                api._reset_connect_state()
                for device in api.devices:
                    api._on_rx_received(
                        can.Message(
                            arbitration_id=device.can_id,
                            data=b"\xfe\xff",
                            is_extended_id=True,
                        ),
                        api._connected_since_mono,
                    )
                    api._on_rx_message_processed()

            api.start.side_effect = start
        api.stop = AsyncMock()
        api.send = AsyncMock()
        instances.append(api)
        return api

    with patch("custom_components.ampio.bridge.AmpioCanBridge", new=create):
        yield instances


@pytest.fixture
def config_connection() -> AsyncMock:
    """Control the result of a receive-only gateway connection check."""
    return AsyncMock(return_value=True)


@pytest.fixture(autouse=True)
def config_apis(config_connection: AsyncMock) -> Iterator[list[AmpioBridge]]:
    """Validate actual configuration while replacing flow connection I/O."""
    instances = []

    def create(cfg: dict[str, Any], **kwargs: Any) -> AmpioBridge:
        api = AmpioBridge(cfg, **kwargs)
        api.start = AsyncMock()
        api.wait_connected = config_connection
        api.stop = AsyncMock()
        api.send = AsyncMock()
        instances.append(api)
        return api

    with patch("custom_components.ampio.config_flow.AmpioCanBridge", new=create):
        yield instances
