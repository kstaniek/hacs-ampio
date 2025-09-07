"""Config flow for Ampio integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


class AmpioFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ampio."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("host"): str,
                        vol.Required("port", default=20001): int,
                    }
                ),
            )

        # Here you would typically validate the input and create a config entry
        LOGGER.info("User input received: %s", user_input)
        return self.async_create_entry(title="Ampio Bridge", data=user_input)
