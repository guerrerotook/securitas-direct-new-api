"""Config flow for the MELCloud platform."""
from __future__ import annotations
from collections import OrderedDict
from datetime import timedelta
import logging
from sqlalchemy import true

import voluptuous as vol
from homeassistant.components.http.view import HomeAssistantView
from homeassistant.components.securitas.securitas_direct_new_api.dataTypes import (
    OtpPhone,
)

from homeassistant.helpers.selector import selector

from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE,
    CONF_ERROR,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResult

CONF_OTPSECRET = "otp_secret"
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
from . import CONF_CHECK_ALARM_PANEL, CONF_COUNTRY, DOMAIN, SecuritasHub


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        self.config = OrderedDict()
        self.securitas: SecuritasHub = None
        self.opt_challange: tuple[str, list[OtpPhone]] = None

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

        self.config[CONF_USERNAME] = username
        self.config[CONF_PASSWORD] = password
        self.config[CONF_COUNTRY] = country
        self.config[CONF_CODE] = code
        self.config[CONF_CHECK_ALARM_PANEL] = check_alarm
        self.config[CONF_SCAN_INTERVAL] = scan_interval
        self.securitas = SecuritasHub(
            self.config, async_get_clientsession(self.hass), self.hass
        )
        succeed: bool = await self.securitas.login()
        if succeed == "2FA":
            return None
        else:
            return self.securitas

    async def async_step_phone_list(self, user_input=None):
        phone_index: int = -1
        for phone_item in self.opt_challange[1]:
            if phone_item.phone == user_input["phones"]:
                phone_index = phone_item.id
        await self.securitas.sent_opt(self.opt_challange[0], phone_index)
        return self.async_show_form(
            step_id="otp_challange",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
        )

    async def async_step_otp_challange(self, user_input=None):
        await self.securitas.send_sms_code(self.opt_challange[0], user_input[CONF_CODE])
        return await self._create_entry(
            self.config[CONF_USERNAME],
            self.securitas.get_authentication_token(),
            self.config[CONF_PASSWORD],
            self.config[CONF_COUNTRY],
            self.config[CONF_CODE],
            self.config[CONF_CHECK_ALARM_PANEL],
            self.config[CONF_SCAN_INTERVAL],
        )

    async def async_step_user(self, user_input=None):
        """User initiated config flow."""
        if user_input is None and self.init_data is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
                ),
            )

        initial_data: dict = self.init_data
        if initial_data.get(CONF_ERROR) and initial_data[CONF_ERROR] == "2FA":
            await self._create_client(
                initial_data[CONF_USERNAME],
                initial_data[CONF_PASSWORD],
                initial_data[CONF_COUNTRY],
                initial_data[CONF_CODE],
                initial_data[CONF_CHECK_ALARM_PANEL],
                initial_data[CONF_SCAN_INTERVAL],
            )
            self.opt_challange: tuple[
                str, list[OtpPhone]
            ] = await self.securitas.validate_device()
            phones: list[str] = []
            for phone_item in self.opt_challange[1]:
                phones.append(phone_item.phone)
            data_schema = {}
            data_schema["phones"] = selector({"select": {"options": phones}})
            return self.async_show_form(
                step_id="phone_list", data_schema=vol.Schema(data_schema)
            )

        succeed = await self._create_client(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            user_input[CONF_COUNTRY],
            user_input[CONF_CODE],
            user_input[CONF_CHECK_ALARM_PANEL],
            user_input[CONF_SCAN_INTERVAL],
        )

        return await self._create_entry(
            self.config[CONF_USERNAME],
            self.securitas.get_authentication_token(),
            self.config[CONF_PASSWORD],
            self.config[CONF_COUNTRY],
            self.config[CONF_CODE],
            self.config[CONF_CHECK_ALARM_PANEL],
            self.config[CONF_SCAN_INTERVAL],
        )

    async def async_step_import(self, user_input: dict):
        """Import a config entry."""
        if user_input.get(CONF_ERROR):
            error = user_input[CONF_ERROR]
            if error == "2FA":
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_USERNAME): str,
                            vol.Required(CONF_PASSWORD): str,
                        }
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
