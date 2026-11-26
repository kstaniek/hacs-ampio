"""Config flow for the Ampio integration."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
import yaml
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .const import (
    CONF_CONFIG,
    CONF_CONFIG_URL,
    CONF_MODULE_TIMEOUT,
    CONF_MODULE_TIMEOUTS,
    CONFIG_VERSION,
    DEFAULT_MODULE_TIMEOUT,
    DEFAULT_PORT,
    DOMAIN,
    MAX_PORT,
)
from .utils import describe_can_connection

if TYPE_CHECKING:
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo


def endpoint_id(host: str, port: int) -> str:
    """Keep endpoint identity consistent across setup, discovery, and migration."""
    return f"{host.strip().lower()}:{port}"


def input_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Validate endpoint and configuration URL input with suggested values."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): vol.All(
                cv.string, vol.Length(min=1)
            ),
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_PORT)),
            vol.Required(
                CONF_CONFIG_URL, default=defaults.get(CONF_CONFIG_URL, "")
            ): cv.string,
        }
    )


class AmpioFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle manual setup, discovery, and reconfiguration."""

    VERSION = CONFIG_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> AmpioOptionsFlow:
        """Configure module silence handling separately from the CAN configuration."""
        return AmpioOptionsFlow()

    def __init__(self) -> None:
        """Initialize discovery form defaults."""
        self._discovered: dict[str, Any] = {}
        self._discovery_name = ""

    async def download_and_update_config(  # noqa: PLR0911 - Distinct download and parse errors.
        self, url_str: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Download a YAML mapping without blocking the event loop during parsing."""
        try:
            url = URL(url_str)
            if url.scheme not in ("http", "https") or not url.host:
                return {}, {CONF_CONFIG_URL: "invalid_url"}
        except ValueError:
            return {}, {CONF_CONFIG_URL: "invalid_url"}

        try:
            async with async_get_clientsession(self.hass).get(
                url, timeout=10
            ) as response:
                if response.status != HTTPStatus.OK:
                    return {}, {CONF_CONFIG_URL: "cannot_connect"}
                text = await response.text()
        except TimeoutError:
            return {}, {CONF_CONFIG_URL: "timeout"}
        except (aiohttp.ClientError, UnicodeError):
            return {}, {CONF_CONFIG_URL: "cannot_connect"}

        try:
            data = await self.hass.async_add_executor_job(yaml.safe_load, text)
        except yaml.YAMLError:
            return {}, {CONF_CONFIG_URL: "invalid_yaml"}
        if not isinstance(data, dict):
            return {}, {CONF_CONFIG_URL: "invalid_yaml"}
        return data, {}

    async def _async_submit(
        self, user_input: dict[str, Any], *, step_id: str
    ) -> ConfigFlowResult:
        """Validate input and create or update an endpoint without duplicates."""
        host = user_input[CONF_HOST].strip()
        if not host:
            return self._show_form(step_id, user_input, {CONF_HOST: "invalid_host"})
        port = int(user_input[CONF_PORT])
        url_str = user_input[CONF_CONFIG_URL].strip()
        unique_id = endpoint_id(host, port)
        entry = self._get_reconfigure_entry() if step_id == "reconfigure" else None
        entry_id = entry.entry_id if entry is not None else None
        if self._endpoint_configured(unique_id, entry_id):
            return self.async_abort(reason="already_configured")

        config, errors = await self.download_and_update_config(url_str)
        if not errors:
            if self._endpoint_configured(unique_id, entry_id):
                return self.async_abort(reason="already_configured")
            data = {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_CONFIG_URL: url_str,
                CONF_CONFIG: config,
            }
            if entry is not None:
                old_host = entry.data[CONF_HOST]
                old_port = int(entry.data[CONF_PORT])
                automatic_titles = {
                    entry.unique_id,
                    f"{old_host}:{old_port}",
                    describe_can_connection(old_host, old_port),
                }
                title = (
                    describe_can_connection(host, port)
                    if entry.title in automatic_titles
                    else entry.title
                )
                registry = dr.async_get(self.hass)
                if entry.unique_id is not None and (
                    device := registry.async_get_device_by_identifier(
                        (DOMAIN, entry.unique_id), entry.entry_id
                    )
                ):
                    registry.async_update_device(
                        device.id,
                        new_identifiers=(
                            device.identifiers - {(DOMAIN, entry.unique_id)}
                        )
                        | {(DOMAIN, unique_id)},
                    )
                update = (
                    self.async_update_and_abort
                    if entry.update_listeners
                    else self.async_update_reload_and_abort
                )
                return update(
                    entry,
                    unique_id=unique_id,
                    title=title,
                    data_updates=data,
                    reason="reconfigure_successful",
                )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=describe_can_connection(host, port), data=data
            )
        return self._show_form(step_id, user_input, errors)

    def _endpoint_configured(self, unique_id: str, entry_id: str | None = None) -> bool:
        """Match both current and legacy endpoint identities."""
        return any(
            existing.entry_id != entry_id
            and (
                existing.unique_id == unique_id
                or endpoint_id(existing.data[CONF_HOST], int(existing.data[CONF_PORT]))
                == unique_id
            )
            for existing in self._async_current_entries()
        )

    def _show_form(
        self,
        step_id: str,
        defaults: dict[str, Any],
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show input while retaining values after a download error."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=input_schema(defaults),
            errors=errors or {},
            description_placeholders={"name": self._discovery_name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup."""
        if user_input is not None:
            return await self._async_submit(user_input, step_id="user")
        return self._show_form("user", {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an existing entry without changing its registry identity."""
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            return self.async_abort(reason="missing_entry")
        if user_input is not None:
            return await self._async_submit(user_input, step_id="reconfigure")
        return self._show_form("reconfigure", dict(entry.data))

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Offer a discovered CAN bridge and require a configuration URL."""
        if (
            discovery_info.type != "_can-server._tcp.local."
            or not discovery_info.name.casefold().startswith("can")
        ):
            return self.async_abort(reason="not_can_bridge")
        host = discovery_info.host
        port = discovery_info.port
        if not host or port is None or not 1 <= port <= MAX_PORT:
            return self.async_abort(reason="invalid_discovery")
        unique_id = endpoint_id(host, port)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        if self._endpoint_configured(unique_id):
            return self.async_abort(reason="already_configured")
        self._discovered = {CONF_HOST: host, CONF_PORT: port}
        self._discovery_name = discovery_info.name.removesuffix(
            "._can-server._tcp.local."
        )
        self.context["title_placeholders"] = {"name": self._discovery_name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery and collect the configuration URL."""
        if user_input is not None:
            return await self._async_submit(user_input, step_id="discovery_confirm")
        return self._show_form("discovery_confirm", self._discovered)


def _monitoring_options(
    entry: ConfigEntry, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate integer timeout values and normalize configured CAN identifiers."""

    def timeout(value: Any) -> int:
        result = vol.All(vol.Coerce(float), vol.Range(min=0, max=86400))(value)
        if not result.is_integer():
            raise ValueError
        return int(result)

    known_ids = {
        device["can_id"] for device in entry.data[CONF_CONFIG].get("devices", [])
    }
    overrides = {}
    for key, value in user_input.get(CONF_MODULE_TIMEOUTS, {}).items():
        can_id = int(key, 16)
        normalized = f"{can_id:08x}"
        if can_id not in known_ids or normalized in overrides:
            raise ValueError
        overrides[normalized] = timeout(value)
    return {
        **entry.options,
        CONF_MODULE_TIMEOUT: timeout(user_input[CONF_MODULE_TIMEOUT]),
        CONF_MODULE_TIMEOUTS: overrides,
    }


class AmpioOptionsFlow(OptionsFlow):
    """Configure passive module monitoring without changing library configuration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the global silence timeout and optional per-module overrides."""
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None and runtime.traffic is None:
            return self.async_abort(reason="traffic_not_supported")
        errors = {}
        if user_input is not None:
            try:
                options = _monitoring_options(self.config_entry, user_input)
            except (ValueError, TypeError, AttributeError, vol.Invalid):
                errors["base"] = "invalid_module_timeout"
            else:
                return self.async_create_entry(title="", data=options)
        defaults = user_input if user_input is not None else self.config_entry.options
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODULE_TIMEOUT,
                        default=defaults.get(
                            CONF_MODULE_TIMEOUT, DEFAULT_MODULE_TIMEOUT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=86400,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Optional(
                        CONF_MODULE_TIMEOUTS,
                        default=defaults.get(CONF_MODULE_TIMEOUTS, {}),
                    ): selector.ObjectSelector(),
                }
            ),
        )
