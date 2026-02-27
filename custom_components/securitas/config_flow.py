"""Config flow for the Securitas Direct platform."""

from __future__ import annotations

from collections import OrderedDict
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_ERROR,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import selector

from . import (
    CONF_CODE_ARM_REQUIRED,
    CONF_CHECK_ALARM_PANEL,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENTRY_ID,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_PERI_ALARM,
    CONF_USE_2FA,
    CONFIG_SCHEMA,
    DEFAULT_CODE_ARM_REQUIRED,
    DEFAULT_CHECK_ALARM_PANEL,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_PERI_ALARM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_CODE,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
    generate_uuid,
)
from .securitas_direct_new_api import (
    Installation,
    Login2FAError,
    OtpPhone,
    PERI_DEFAULTS,
    PERI_OPTIONS,
    STD_DEFAULTS,
    STD_OPTIONS,
    STATE_LABELS,
)

VERSION = 1

_LOGGER = logging.getLogger(__name__)


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.config: OrderedDict = OrderedDict()
        self.securitas: SecuritasHub = None
        self.otp_challenge: tuple[str, list[OtpPhone]] = None

    async def _create_entry(
        self, username: str, data: OrderedDict
    ) -> config_entries.ConfigEntry:
        """Register new entry."""

        await self.async_set_unique_id(username)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=username, data=data)

    def _create_client(
        self,
    ) -> SecuritasHub:
        """Create client (SecuritasHub)."""

        if self.config[CONF_PASSWORD] is None:
            raise ValueError(
                "Invalid internal state. Called without either password or token"
            )

        self.securitas = SecuritasHub(
            self.config, None, async_get_clientsession(self.hass), self.hass
        )

        return self.securitas

    async def async_step_phone_list(self, user_input=None) -> FlowResult:
        """Show the list of phones for the OTP challenge."""
        phone_index: int = -1
        selected_phone_key = user_input["phones"]
        
        try:
            index_str = selected_phone_key.split("_")[0]
            list_index = int(index_str)
            if 0 <= list_index < len(self.otp_challenge[1]):
                phone_index = self.otp_challenge[1][list_index].id
        except (ValueError, IndexError):
            for phone_item in self.otp_challenge[1]:
                if phone_item.phone in selected_phone_key:
                    phone_index = phone_item.id
                    break
        
        await self.securitas.send_opt(self.otp_challenge[0], phone_index)
        return self.async_show_form(
            step_id="otp_challenge",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
        )

    async def async_step_otp_challenge(self, user_input=None):
        """Last step of the OTP challenge."""
        await self.securitas.send_sms_code(self.otp_challenge[0], user_input[CONF_CODE])
        return await self.finish_setup()

    async def finish_setup(self):
        """Login and set up installations."""
        await self.securitas.login()
        self.config[CONF_TOKEN] = self.securitas.get_authentication_token()
        result = await self._create_entry(self.config[CONF_USERNAME], self.config)

        self.hass.data[DOMAIN] = {}
        self.hass.data[DOMAIN][SecuritasHub.__name__] = self.securitas
        installations: list[
            Installation
        ] = await self.securitas.session.list_installations()
        devices: list[SecuritasDirectDevice] = []
        for installation in installations:
            await self.securitas.get_services(installation)
            devices.append(SecuritasDirectDevice(installation))

        return result

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SecuritasOptionsFlowHandler:
        """Get the options flow for this handler."""
        return SecuritasOptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """User initiated config flow."""
        if (user_input is None and self.init_data is None) or (
            self.init_data is not None and self.init_data.get("error", None) == "login"
        ):
            return self.async_show_form(
                step_id="user",
                data_schema=CONFIG_SCHEMA.schema[DOMAIN],
            )

        self.config: OrderedDict = user_input
        if self.config is None:
            self.config = self.init_data.copy()

        if self.securitas is None:
            uuid = generate_uuid()
            self.config[CONF_DELAY_CHECK_OPERATION] = DEFAULT_DELAY_CHECK_OPERATION
            self.config[CONF_DEVICE_ID] = uuid
            self.config[CONF_UNIQUE_ID] = uuid
            self.config[CONF_DEVICE_INDIGITALL] = ""
            self.config[CONF_ENTRY_ID] = ""

            self.securitas = self._create_client()

        # check for option to use 2fa
        if not self.config[CONF_USE_2FA]:
            return await self.finish_setup()

        self.otp_challenge: tuple[
            str, list[OtpPhone]
        ] = await self.securitas.validate_device()
        phones: list[str] = []
        phone_options: list[dict] = []
        for i, phone_item in enumerate(self.otp_challenge[1]):
            phone_key = f"{i}_{phone_item.phone}"
            phones.append(phone_key)
            phone_options.append({
                "value": phone_key,
                "label": phone_item.phone
            })
        data_schema = {}
        data_schema["phones"] = selector({"select": {"options": phone_options}})
        return self.async_show_form(
            step_id="phone_list", data_schema=vol.Schema(data_schema)
        )

    async def async_step_import(self, user_input: dict):
        """Import a config entry."""
        if user_input.get(CONF_ERROR):
            error = user_input[CONF_ERROR]
            if error in {"2FA", "login"}:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_USERNAME): str,
                            vol.Required(CONF_PASSWORD): str,
                        }
                    ),
                )
        self.config[CONF_USERNAME] = user_input[CONF_USERNAME]
        self.config[CONF_PASSWORD] = user_input[CONF_PASSWORD]
        self.config[CONF_COUNTRY] = user_input[CONF_COUNTRY]
        self.config[CONF_CODE] = user_input[CONF_CODE]
        self.config[CONF_CODE_ARM_REQUIRED] = user_input.get(
            CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
        )
        self.config[CONF_CHECK_ALARM_PANEL] = user_input.get(
            CONF_CHECK_ALARM_PANEL, DEFAULT_CHECK_ALARM_PANEL
        )
        self.config[CONF_SCAN_INTERVAL] = user_input.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        self.config[CONF_DELAY_CHECK_OPERATION] = user_input.get(
            CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
        )
        self.config[CONF_DEVICE_ID] = user_input[CONF_DEVICE_ID]
        self.config[CONF_UNIQUE_ID] = user_input[CONF_UNIQUE_ID]
        self.config[CONF_DEVICE_INDIGITALL] = user_input[CONF_DEVICE_INDIGITALL]
        self.config[CONF_ENTRY_ID] = user_input.get(CONF_ENTRY_ID, "")
        result = self._create_client()

        try:
            await result.login()
        except Login2FAError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_USERNAME): str,
                        vol.Required(CONF_PASSWORD): str,
                    }
                ),
            )

        return result


class SecuritasOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Securitas options."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._general_data: dict[str, Any] = {}

    def _get(self, key, default=None):
        """Read current value from options, falling back to entry data."""
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: General settings."""
        if user_input is not None:
            self._general_data = user_input
            return await self.async_step_mappings()
        scan_interval = self._get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        code_arm_required = self._get(CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED)
        delay_check_operation = self._get(
            CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
        )
        check_alarm_panel = self._get(
            CONF_CHECK_ALARM_PANEL, DEFAULT_CHECK_ALARM_PANEL
        )
        peri_alarm = self._get(CONF_PERI_ALARM, DEFAULT_PERI_ALARM)

        schema = vol.Schema(
            {
                vol.Optional(CONF_CODE, default=self._get(CONF_CODE, DEFAULT_CODE)): str,
                vol.Optional(CONF_CODE_ARM_REQUIRED, default=code_arm_required): bool,
                vol.Optional(CONF_PERI_ALARM, default=peri_alarm): bool,
                vol.Optional(
                    CONF_CHECK_ALARM_PANEL, default=check_alarm_panel
                ): bool,
                vol.Optional(CONF_SCAN_INTERVAL, default=scan_interval): int,
                vol.Optional(
                    CONF_DELAY_CHECK_OPERATION, default=delay_check_operation
                ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=15.0)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Alarm state mappings."""
        if user_input is not None:
            data = {**self._general_data, **user_input}
            return self.async_create_entry(title="", data=data)

        peri_alarm = self._general_data.get(CONF_PERI_ALARM, DEFAULT_PERI_ALARM)

        # Determine defaults for mapping dropdowns
        defaults = PERI_DEFAULTS if peri_alarm else STD_DEFAULTS
        options = PERI_OPTIONS if peri_alarm else STD_OPTIONS
        valid_values = {state.value for state in options}

        def _valid_map(key: str) -> str:
            """Return saved mapping if valid for current options, else default."""
            val = self._get(key, defaults[key])
            return val if val in valid_values else defaults[key]

        map_home = _valid_map(CONF_MAP_HOME)
        map_away = _valid_map(CONF_MAP_AWAY)
        map_night = _valid_map(CONF_MAP_NIGHT)
        map_custom = _valid_map(CONF_MAP_CUSTOM)

        # Build dropdown options
        select_options = [
            {"value": state.value, "label": STATE_LABELS[state]}
            for state in options
        ]

        schema = vol.Schema(
            {
                vol.Optional(CONF_MAP_HOME, default=map_home): selector(
                    {"select": {"options": select_options}}
                ),
                vol.Optional(CONF_MAP_AWAY, default=map_away): selector(
                    {"select": {"options": select_options}}
                ),
                vol.Optional(CONF_MAP_NIGHT, default=map_night): selector(
                    {"select": {"options": select_options}}
                ),
                vol.Optional(CONF_MAP_CUSTOM, default=map_custom): selector(
                    {"select": {"options": select_options}}
                ),
            }
        )
        return self.async_show_form(step_id="mappings", data_schema=schema)
