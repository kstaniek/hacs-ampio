"""Code to handle Ampio Bridge."""

from __future__ import annotations

import asyncio
import logging
from inspect import signature
from typing import Any

from aioampio import AmpioBridge as AmpioCanBridge
from can import CanError
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr

from .const import (
    CONF_CONFIG,
    CONF_CONFIG_URL,
    DEFAULT_CAN_CHANNEL,
    DEFAULT_CAN_INTERFACE,
    DOMAIN,
)
from .device import async_setup_devices
from .migration import async_migrate_entity_names, async_migrate_text_entities
from .traffic import ModuleTrafficMonitor
from .utils import describe_can_connection, entity_area, entity_object_id

PLATFORMS = [
    Platform.LIGHT,
    Platform.ALARM_CONTROL_PANEL,
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
        self._stop_task: asyncio.Task[None] | None = None

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

    async def async_initialize_bridge(self) -> None:
        """Initialize the Ampio bridge."""
        setup_ok = False
        try:
            try:
                await self.api.initialize()
            except (ValueError, TypeError, KeyError) as err:
                raise ConfigEntryError(
                    translation_domain=DOMAIN, translation_key="invalid_config"
                ) from err
            try:
                async with asyncio.timeout(10):
                    await self.api.start()
                    connected = await self.api.wait_connected()
            except (TimeoutError, OSError, CanError) as err:
                raise ConfigEntryNotReady(
                    translation_domain=DOMAIN, translation_key="cannot_connect"
                ) from err
            if not connected:
                raise ConfigEntryNotReady(
                    translation_domain=DOMAIN, translation_key="cannot_connect"
                )
            self.config_entry.async_on_unload(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STOP, self._async_shutdown
                )
            )
            await self._async_setup_resources()
            setup_ok = True
        finally:
            if not setup_ok:
                await self.async_reset()

    async def _async_setup_resources(self) -> None:
        """Register resources only after a gateway connection is established."""
        fr_reg = fr.async_get(self.hass)
        for floor in self.api.floors:
            f = fr_reg.async_get_floor_by_name(floor.name)
            if not f:
                f = fr_reg.async_create(floor.name, level=floor.level)

        ar_reg = ar.async_get(self.hass)
        for area in self.api.areas:
            a = ar_reg.async_get_area_by_name(area.name)
            if area.floor_name is not None:
                f = fr_reg.async_get_floor_by_name(area.floor_name)
                fid = f.floor_id if f is not None else None
            else:
                fid = None

            if not a:
                a = ar_reg.async_create(area.name, floor_id=fid, icon=area.icon)

        # Older stable aioampio releases do not expose module traffic yet.
        self._start_traffic_monitor()
        await async_setup_devices(self)
        async_migrate_entity_names(self)
        async_migrate_text_entities(
            self.hass,
            self.config_entry,
            resource_object_ids={
                resource.id: entity_object_id(
                    resource.name,
                    resource.id,
                    entity_area(
                        resource.area,
                        device.area
                        if (device := self.api.texts.get_device(resource.id))
                        else None,
                    ),
                )
                for resource in self.api.texts
            },
        )
        await self.hass.config_entries.async_forward_entry_setups(
            self.config_entry, PLATFORMS
        )
        self.config_entry.async_on_unload(
            self.config_entry.add_update_listener(_update_listener)
        )

    def _start_traffic_monitor(self) -> None:
        """Use module traffic only when the installed library provides it."""
        if hasattr(self.api, "module_metrics"):
            self.traffic = ModuleTrafficMonitor(self)
            self.traffic.start()

    async def async_reset(self) -> bool:
        """Reset the bridge connection."""
        if self._stop_task is None:
            self._stop_task = self.hass.async_create_task(self.api.stop())
        await asyncio.shield(self._stop_task)
        return True

    async def _async_shutdown(self, event: core.Event) -> None:
        """Finish transport cleanup before HA stops its event loop."""
        await self.async_reset()


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
