"""Config flow for the MELCloud platform."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components.securitas.securitas_direct_new_api.dataTypes import (
    Installation,
)

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN, SecuritasHub, HUB


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def _create_entry(self, instalation: Installation):
        """Register new entry."""
        await self.async_set_unique_id(instalation.alias)
        self._abort_if_unique_id_configured(instalation)
        return self.async_create_entry(title=instalation.alias, data=instalation)

    async def _create_client(self, config):
        """Create client."""
        if config is None:
            raise ValueError(
                "Invalid internal state. Called without either password or token"
            )

        securitas = SecuritasHub(config, async_get_clientsession(self.hass))
        succeed: bool = await securitas.login()
        if not succeed:
            raise Exception("error login")

        HUB = securitas

    async def async_step_user(self, user_input=None):
        """User initiated config flow."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
                ),
            )
        return await self._create_client(user_input[DOMAIN])

    async def async_step_import(self, user_input):
        """Import a config entry."""
        return await self._create_client(user_input[DOMAIN])
