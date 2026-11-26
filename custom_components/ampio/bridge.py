"""Code to handle Ampio Bridge."""

from __future__ import annotations

import asyncio
import logging
from inspect import signature
from typing import Any

from aioampio import AmpioBridge as AmpioCanBridge
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr

from .const import (
    CONF_CONFIG,
    CONF_CONFIG_URL,
    DEFAULT_CAN_CHANNEL,
    DEFAULT_CAN_INTERFACE,
)
from .device import async_setup_devices
from .traffic import ModuleTrafficMonitor
from .utils import describe_can_connection

PLATFORMS = [
    Platform.LIGHT,
    Platform.ALARM_CONTROL_PANEL,
    Platform.TEXT,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.COVER,
    Platform.VALVE,
    Platform.CLIMATE,
    # Platform.BUTTON,
    # Platform.EVENT,
]

type AmpioConfigEntry = ConfigEntry[AmpioBridge]


class AmpioBridge:
    """Manages single Ampio Bridge."""

    def __init__(
        self, hass: core.HomeAssistant, config_entry: AmpioConfigEntry
    ) -> None:
        """Initialize the Ampio bridge."""
        self.hass = hass
        self.config_entry = config_entry
        self.logger = logging.getLogger(__name__)

        api_kwargs: dict[str, Any] = {CONF_HOST: self.host, CONF_PORT: self.port}
        # aioampio 0.2.3 predates the python-can interface/channel parameters.
        if "interface" in signature(AmpioCanBridge).parameters:
            api_kwargs.update(interface=self.interface, channel=self.channel)
        self.api = AmpioCanBridge(self.ampio_config, **api_kwargs)
        self.traffic: ModuleTrafficMonitor | None = None

        self.config_entry.runtime_data = self

    @property
    def interface(self) -> str:
        """Return the CAN backend currently used by this integration."""
        return DEFAULT_CAN_INTERFACE

    @property
    def channel(self) -> str:
        """Return the CAN channel currently used by this integration."""
        return DEFAULT_CAN_CHANNEL

    @property
    def manufacturer(self) -> str | None:
        """Return the known manufacturer of the current CAN gateway hardware."""
        return "Waveshare" if self.interface == "waveshare" else None

    @property
    def connection_description(self) -> str:
        """Describe the gateway transport for the device information model line."""
        return describe_can_connection(
            self.host, self.port, interface=self.interface, channel=self.channel
        )

    @property
    def url(self) -> str:
        """Return the config URL of the bridge."""
        return self.config_entry.data[CONF_CONFIG_URL]

    @property
    def host(self) -> str:
        """Return the host of the bridge."""
        return self.config_entry.data[CONF_HOST]

    @property
    def ampio_config(self) -> dict[str, Any]:
        """Return the config of the bridge."""
        return self.config_entry.data[CONF_CONFIG]

    @property
    def port(self) -> int:
        """Return the port of the bridge."""
        return self.config_entry.data[CONF_PORT]

    async def async_initialize_bridge(self) -> bool:
        """Initialize the Ampio bridge."""
        setup_ok = False
        try:
            async with asyncio.timeout(10):
                await self.api.initialize()
                await self.api.start()
            setup_ok = True
        except TimeoutError:
            return False
        except Exception:
            self.logger.exception("Unknown error connecting to Ampio CAN Bridge")
            return False
        finally:
            if not setup_ok and self.api is not None:
                await self.api.stop()

        fr_reg = fr.async_get(self.hass)
        for floor in self.api.floors:
            f = fr_reg.async_get_floor_by_name(floor.name)
            if not f:
                f = fr_reg.async_create(floor.name, level=floor.level)
            else:
                fr_reg.async_update(f.floor_id, name=floor.name, level=floor.level)

        ar_reg = ar.async_get(self.hass)
        for area in self.api.areas:
            a = ar_reg.async_get_area_by_name(area.name)
            if area.floor_name is not None:
                f = fr_reg.async_get_floor_by_name(area.floor_name)
                fid = f.floor_id
            else:
                fid = None

            if not a:
                a = ar_reg.async_create(area.name, floor_id=fid, icon=area.icon)
            else:
                ar_reg.async_update(a.id, name=area.name, floor_id=fid, icon=area.icon)

        # Older stable aioampio releases do not expose module traffic yet.
        self._start_traffic_monitor()
        await async_setup_devices(self)
        await self.hass.config_entries.async_forward_entry_setups(
            self.config_entry, PLATFORMS
        )
        self.config_entry.async_on_unload(
            self.config_entry.add_update_listener(_update_listener)
        )
        return True

    def _start_traffic_monitor(self) -> None:
        """Use module traffic only when the installed library provides it."""
        if hasattr(self.api, "module_metrics"):
            self.traffic = ModuleTrafficMonitor(self)
            self.traffic.start()

    async def async_reset(self) -> bool:
        """Reset the bridge connection."""
        if self.api is None:
            return True

        await self.api.stop()
        return True


async def _update_listener(hass: core.HomeAssistant, entry: AmpioConfigEntry) -> None:
    """Handle ConfigEntry options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def create_config_flow(hass: core.HomeAssistant, host: str, port: int) -> None:
    """Start a config flow."""
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            core.DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={"host": host, "port": port},
        )
    )
