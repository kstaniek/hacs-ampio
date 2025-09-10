"""Config flow for Ampio integration."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
import yaml
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .const import CONF_CONFIG, CONF_CONFIG_URL, DEFAULT_PORT, DOMAIN

LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_CONFIG_URL): cv.string,  # keep as string here …
    }
)


class AmpioFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ampio."""

    VERSION = 2

    async def download_and_update_config(
        self, url_str: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Download and update the configuration from a URL."""
        errors: dict[str, str] = {}

        # 1) Basic URL sanity (scheme http/https)
        try:
            url = URL(url_str)
            if url.scheme not in ("http", "https"):
                errors[CONF_CONFIG_URL] = "invalid_url"
        except Exception:  # noqa: BLE001
            errors[CONF_CONFIG_URL] = "invalid_url"

        content_text: str | None = None

        if not errors:
            # 2) Try downloading the YAML (HTTP 200 required)
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(url_str, timeout=10) as resp:
                    if resp.status != HTTPStatus.OK:
                        errors[CONF_CONFIG_URL] = "cannot_connect"
                    else:
                        content_text = await resp.text()
                        LOGGER.info("Configuration file downloaded from %s", url_str)
            except TimeoutError:
                errors[CONF_CONFIG_URL] = "timeout"
            except Exception:  # noqa: BLE001
                errors[CONF_CONFIG_URL] = "cannot_connect"

        data: dict[str, Any] = {}
        if not errors:  # and downloaded_hash != local_hash:
            try:
                data = yaml.safe_load(content_text)
            except yaml.YAMLError:
                errors[CONF_CONFIG_URL] = "invalid_yaml"
        return data, errors

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration step."""
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            return self.async_abort(reason="missing_entry")

        errors: dict[str, str] = {}

        # Prefill the form with current values
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST, default=entry.data.get(CONF_HOST, "")
                ): cv.string,
                vol.Required(
                    CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(
                    CONF_CONFIG_URL, default=entry.data.get(CONF_CONFIG_URL, "")
                ): cv.string,
            }
        )

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            url_str = user_input[CONF_CONFIG_URL].strip()

            # Reuse your validator
            config, errors = await self.download_and_update_config(url_str)

            if not errors:
                # Update entry data (don't touch unique_id here)
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_CONFIG_URL: url_str,
                        CONF_CONFIG: config,
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            url_str: str = user_input[CONF_CONFIG_URL]

            # 1) Download and update config file if needed
            config, errors = await self.download_and_update_config(url_str)
            if not errors:
                # Stable unique_id prevents duplicate entries for same endpoint
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{host}:{port}",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_CONFIG_URL: url_str,
                        CONF_CONFIG: config,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
