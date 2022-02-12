"""Config flow for the MELCloud platform."""
from __future__ import annotations
from datetime import timedelta

import voluptuous as vol

from homeassistant.const import (
    CONF_CODE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CONF_CHECK_ALARM_PANEL, CONF_COUNTRY, DOMAIN, SecuritasHub


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def _create_entry(
        self,
        username: str,
        token: str,
        password: str,
        country: str,
        code: str,
        check_alarm: bool,
        scan_interval: timedelta,
    ):
        """Register new entry."""
        await self.async_set_unique_id(username)
        self._abort_if_unique_id_configured(
            {
                CONF_USERNAME: username,
                CONF_TOKEN: token,
                CONF_PASSWORD: password,
                CONF_COUNTRY: country,
                CONF_CODE: code,
                CONF_CHECK_ALARM_PANEL: check_alarm,
            }
        )
        return self.async_create_entry(
            title=username,
            data={
                CONF_USERNAME: username,
                CONF_TOKEN: token,
                CONF_PASSWORD: password,
                CONF_COUNTRY: country,
                CONF_CODE: code,
                CONF_CHECK_ALARM_PANEL: check_alarm,
            },
        )

    async def _create_client(
        self,
        username: str,
        password: str,
        country: str,
        code: str,
        check_alarm: bool,
        scan_interval: timedelta,
    ):
        """Create client."""
        if password is None and password is None:
            raise ValueError(
                "Invalid internal state. Called without either password or token"
            )

        config = dict()
        config[CONF_USERNAME] = username
        config[CONF_PASSWORD] = password
        config[CONF_COUNTRY] = country
        config[CONF_CODE] = code
        config[CONF_CHECK_ALARM_PANEL] = check_alarm
        config[CONF_SCAN_INTERVAL] = scan_interval
        securitas = SecuritasHub(config, async_get_clientsession(self.hass))
        succeed: bool = await securitas.login()
        if not succeed:
            raise Exception("error login")
        return await self._create_entry(
            username,
            securitas.get_authentication_token(),
            password,
            country,
            code,
            check_alarm,
            scan_interval,
        )

    async def async_step_user(self, user_input=None):
        """User initiated config flow."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
                ),
            )
        return await self._create_client(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            user_input[CONF_COUNTRY],
            user_input[CONF_CODE],
            user_input[CONF_CHECK_ALARM_PANEL],
            user_input[CONF_SCAN_INTERVAL],
        )

    async def async_step_import(self, user_input):
        """Import a config entry."""
        return await self._create_client(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            user_input[CONF_COUNTRY],
            user_input[CONF_CODE],
            user_input[CONF_CHECK_ALARM_PANEL],
            user_input[CONF_SCAN_INTERVAL],
        )
