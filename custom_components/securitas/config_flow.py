"""Config flow for the Securitas Direct platform."""

from __future__ import annotations

import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    CountrySelector,
    CountrySelectorConfig,
    selector,
)

from . import (
    CONF_ADVANCED,
    CONF_CODE_ARM_REQUIRED,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENTRY_ID,
    CONF_HAS_PERI,
    CONF_INSTALLATION,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    COUNTRY_CODES,
    DEFAULT_CODE,
    DEFAULT_CODE_ARM_REQUIRED,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasHub,
    generate_uuid,
)
from .securitas_direct_new_api import (
    Attribute,
    Attributes,
    Installation,
    Login2FAError,
    LoginError,
    OtpPhone,
    PERI_DEFAULTS,
    PERI_OPTIONS,
    SecuritasDirectError,
    Service,
    STD_DEFAULTS,
    STD_OPTIONS,
    STATE_LABELS,
)

VERSION = 3

_LOGGER = logging.getLogger(__name__)

_NOTIFY_EXCLUDE = {"notify", "send_message", "persistent_notification"}


def _get_notify_options(hass: HomeAssistant) -> list[dict[str, str]]:
    """Build notify service dropdown options."""
    notify_services = sorted(
        svc
        for svc in hass.services.async_services().get("notify", {}).keys()
        if svc not in _NOTIFY_EXCLUDE
    )
    return [{"value": "", "label": "(disabled)"}] + [
        {"value": svc, "label": svc} for svc in notify_services
    ]


def _build_settings_schema(
    defaults: dict[str, Any],
    notify_options: list[dict[str, str]],
    *,
    use_suggested: bool = False,
) -> vol.Schema:
    """Build the shared settings schema for config and options flows."""
    code_val = defaults.get(CONF_CODE, DEFAULT_CODE)
    code_field = (
        vol.Optional(CONF_CODE, description={"suggested_value": code_val})
        if use_suggested
        else vol.Optional(CONF_CODE, default=code_val)
    )

    return vol.Schema(
        {
            code_field: str,
            vol.Optional(
                CONF_CODE_ARM_REQUIRED,
                default=defaults.get(CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED),
            ): bool,
            vol.Optional(
                CONF_NOTIFY_GROUP,
                default=defaults.get(CONF_NOTIFY_GROUP, ""),
            ): selector(
                {
                    "select": {
                        "options": notify_options,
                        "custom_value": True,
                        "mode": "dropdown",
                    }
                }
            ),
            vol.Optional(CONF_ADVANCED): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_SCAN_INTERVAL,
                            default=defaults.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            ),
                        ): int,
                        vol.Optional(
                            CONF_DELAY_CHECK_OPERATION,
                            default=defaults.get(
                                CONF_DELAY_CHECK_OPERATION,
                                DEFAULT_DELAY_CHECK_OPERATION,
                            ),
                        ): vol.All(vol.Coerce(float), vol.Range(min=2.0, max=15.0)),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.config: dict[str, Any] = {}
        self.securitas: SecuritasHub | None = None
        self.otp_challenge: tuple[str | None, list[OtpPhone] | None] | None = None
        self._available_installations: list[Installation] = []
        self._selected_installation: Installation | None = None
        self._options_data: dict[str, Any] = {}
        self._has_peri: bool = False

    async def _create_entry_for_installation(
        self, installation: Installation
    ) -> config_entries.ConfigFlowResult:
        """Register new entry for a specific installation."""
        username = self.config[CONF_USERNAME]
        unique_id = f"{username}_{installation.number}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        self.config[CONF_INSTALLATION] = installation.number
        return self.async_create_entry(title=installation.alias, data=dict(self.config))

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

    async def async_step_phone_list(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the list of phones for the OTP challenge."""
        phone_index: int = -1
        assert user_input is not None
        selected_phone_key = user_input.get("phones", "")

        assert self.otp_challenge is not None
        assert self.securitas is not None
        otp_phones = self.otp_challenge[1] or []
        try:
            index_str = selected_phone_key.split("_")[0]
            list_index = int(index_str)
            if 0 <= list_index < len(otp_phones):
                phone_index = otp_phones[list_index].id
        except (ValueError, IndexError):
            for phone_item in otp_phones:
                if phone_item.phone in selected_phone_key:
                    phone_index = phone_item.id
                    break

        if phone_index < 0:
            return await self._start_2fa_flow()

        try:
            await self.securitas.send_opt(self.otp_challenge[0] or "", phone_index)
        except SecuritasDirectError:
            return await self._show_2fa_error("otp_send_failed")

        return self.async_show_form(
            step_id="otp_challenge",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
        )

    async def async_step_otp_challenge(self, user_input: dict[str, Any] | None = None):
        """Last step of the OTP challenge."""
        assert self.securitas is not None
        assert self.otp_challenge is not None
        assert user_input is not None
        try:
            result = await self.securitas.send_sms_code(
                self.otp_challenge[0] or "", user_input[CONF_CODE]
            )
        except SecuritasDirectError as err:
            # Check if OTP expired (auth-code 10002) — restart 2FA to get new code
            if self._is_otp_expired(err):
                return await self._show_2fa_error("otp_expired")
            return self.async_show_form(
                step_id="otp_challenge",
                data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
                errors={"base": "invalid_otp"},
            )
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "send_sms_code raised unexpected %s: %s", type(err).__name__, err
            )
            return self.async_show_form(
                step_id="otp_challenge",
                data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
                errors={"base": "invalid_otp"},
            )
        # If validate_device returns a challenge hash, the code was wrong —
        # the API re-issued a challenge instead of completing authentication.
        otp_hash, _phones = result
        if otp_hash is not None:
            return self.async_show_form(
                step_id="otp_challenge",
                data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
                errors={"base": "invalid_otp"},
            )
        # MFA may succeed without returning a token (hash: null).
        # finish_setup() will call login() to obtain it.
        return await self.finish_setup()

    def _user_schema(self, defaults: dict[str, Any] | None = None) -> vol.Schema:
        """Build the credentials form schema with optional defaults."""
        d = defaults or {}
        ha_country = self.hass.config.country
        default_country = d.get(
            CONF_COUNTRY, ha_country if ha_country in COUNTRY_CODES else "ES"
        )
        return vol.Schema(
            {
                vol.Required(CONF_COUNTRY, default=default_country): CountrySelector(
                    CountrySelectorConfig(countries=COUNTRY_CODES)
                ),
                vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Country, username, password, 2FA toggle."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=self._user_schema())

        self.config = dict(user_input)

        self.config[CONF_DELAY_CHECK_OPERATION] = DEFAULT_DELAY_CHECK_OPERATION
        self.config[CONF_DEVICE_INDIGITALL] = ""
        self.config[CONF_ENTRY_ID] = ""
        # Reuse existing session for this username if one is already running,
        # to avoid a new login that would invalidate the active session.
        # Password must match to prevent unauthorized addition of installations.
        username = self.config[CONF_USERNAME]
        password = self.config[CONF_PASSWORD]
        sessions = self.hass.data.get(DOMAIN, {}).get("sessions", {})
        if username in sessions:
            existing_hub = sessions[username]["hub"]
            if existing_hub.config[CONF_PASSWORD] == password:
                self.securitas = existing_hub
                self.config[CONF_DEVICE_ID] = existing_hub.config[CONF_DEVICE_ID]
                self.config[CONF_UNIQUE_ID] = existing_hub.config[CONF_UNIQUE_ID]
                self.config[CONF_DEVICE_INDIGITALL] = existing_hub.config.get(
                    CONF_DEVICE_INDIGITALL, ""
                )
                return await self.finish_setup()

        uuid = generate_uuid()
        self.config[CONF_DEVICE_ID] = uuid
        self.config[CONF_UNIQUE_ID] = uuid

        self.securitas = self._create_client()

        # Login — catches credential errors and network failures
        try:
            await self.securitas.login()
        except Login2FAError:
            # 2FA required — proceed to device validation for phone list
            return await self._start_2fa_flow()
        except LoginError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(user_input),
                errors={"base": "invalid_auth"},
            )
        except SecuritasDirectError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(user_input),
                errors={"base": "cannot_connect"},
            )

        # Login succeeded without 2FA — proceed directly
        return await self.finish_setup()

    async def _start_2fa_flow(
        self, errors: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Call validate_device and show phone selection form."""
        assert self.securitas is not None
        try:
            otp_result = await self.securitas.validate_device()
        except SecuritasDirectError as err:
            _LOGGER.error("2FA device validation failed: %s", err)
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "cannot_connect"},
            )
        self.otp_challenge = otp_result
        otp_phones = otp_result[1] or []
        phone_options = [
            {"value": f"{i}_{phone.phone}", "label": phone.phone}
            for i, phone in enumerate(otp_phones)
        ]
        return self.async_show_form(
            step_id="phone_list",
            data_schema=vol.Schema(
                {"phones": selector({"select": {"options": phone_options}})}
            ),
            errors=errors,
        )

    @staticmethod
    def _is_otp_expired(err: SecuritasDirectError) -> bool:
        """Check if a SecuritasDirectError indicates an expired OTP (auth-code 10002)."""
        try:
            return err.args[1]["errors"][0]["data"].get("auth-code") == "10002"
        except (IndexError, KeyError, TypeError):
            return False

    async def _show_2fa_error(self, error_key: str) -> config_entries.ConfigFlowResult:
        """Re-show phone list form with an error."""
        return await self._start_2fa_flow(errors={"base": error_key})

    async def finish_setup(self):
        """Login, discover installations, detect peri, advance to options."""
        assert self.securitas is not None
        try:
            if self.securitas.get_authentication_token() is None:
                await self.securitas.login()
        except Login2FAError:
            return await self._start_2fa_flow()
        except LoginError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "invalid_auth"},
            )
        except SecuritasDirectError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "cannot_connect"},
            )
        self.config[CONF_TOKEN] = self.securitas.get_authentication_token()

        self.hass.data.setdefault(DOMAIN, {})
        self.hass.data[DOMAIN][SecuritasHub.__name__] = self.securitas

        username = self.config[CONF_USERNAME]
        sessions = self.hass.data[DOMAIN].setdefault("sessions", {})
        if username not in sessions:
            sessions[username] = {"hub": self.securitas, "ref_count": 0}

        try:
            installations = await self.securitas.session.list_installations()
        except SecuritasDirectError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "cannot_connect"},
            )
        self.hass.data[DOMAIN]["installations_cache"] = {
            "data": installations,
            "time": time.monotonic(),
        }

        configured_ids = {
            entry.data.get(CONF_INSTALLATION) for entry in self._async_current_entries()
        }
        available = [
            inst for inst in installations if inst.number not in configured_ids
        ]

        if not available:
            return self.async_abort(reason="already_configured")

        if len(available) == 1:
            return await self._select_installation(available[0])

        self._available_installations = available
        return await self.async_step_select_installation()

    async def _select_installation(self, installation: Installation):
        """Set installation, call get_services, detect peri, advance to options."""
        self.config[CONF_INSTALLATION] = installation.number
        self._selected_installation = installation

        assert self.securitas is not None
        try:
            services = await self.securitas.get_services(installation)
        except SecuritasDirectError as err:
            _LOGGER.error(
                "Failed to fetch services for %s: %s", installation.number, err
            )
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "cannot_connect"},
            )
        self.hass.data.setdefault(DOMAIN, {})
        self.hass.data[DOMAIN]["cached_services"] = {
            "data": {installation.number: services},
            "time": time.monotonic(),
        }

        self._has_peri = self._detect_peri(services, installation)
        self.config[CONF_HAS_PERI] = self._has_peri
        _LOGGER.debug(
            "Perimeter detected for %s: %s", installation.number, self._has_peri
        )

        return await self.async_step_options()

    @staticmethod
    def _detect_peri(services: list[Service], installation: Installation) -> bool:
        """Detect perimeter support from service attributes or alarm partitions."""
        # Check service attributes (e.g. SCH with PERI attribute — Spanish panels)
        for svc in services:
            attrs = svc.attributes
            if isinstance(attrs, Attributes):
                attrs = attrs.attributes
            if isinstance(attrs, list):
                for attr in attrs:
                    if isinstance(attr, Attribute) and attr.name == "PERI":
                        return True
        # Check alarm partitions (e.g. SDVECU Italian panels)
        # Partition "02" with non-empty enterStates indicates perimeter support
        for partition in installation.alarm_partitions:
            if partition.get("id") == "02" and partition.get("enterStates"):
                return True
        return False

    async def async_step_select_installation(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Let user pick which installation to configure."""
        if user_input is not None:
            selected_number = user_input[CONF_INSTALLATION]
            for inst in self._available_installations:
                if inst.number == selected_number:
                    return await self._select_installation(inst)
            return self.async_abort(reason="unknown_installation")

        install_options = [
            {"value": inst.number, "label": inst.alias}
            for inst in self._available_installations
        ]
        return self.async_show_form(
            step_id="select_installation",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INSTALLATION): selector(
                        {"select": {"options": install_options}}
                    ),
                }
            ),
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: PIN, scan interval, notification settings."""
        if user_input is not None:
            user_input.setdefault(CONF_CODE, DEFAULT_CODE)
            # Flatten the advanced section back to top-level keys
            advanced = user_input.pop(CONF_ADVANCED, {})
            user_input.update(advanced)
            self._options_data = user_input
            return await self.async_step_mappings()

        notify_options = _get_notify_options(self.hass)
        schema = _build_settings_schema(
            {
                CONF_CODE: DEFAULT_CODE,
                CONF_CODE_ARM_REQUIRED: DEFAULT_CODE_ARM_REQUIRED,
            },
            notify_options,
        )
        return self.async_show_form(step_id="options", data_schema=schema)

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4: Alarm state mappings, then create entry."""
        if user_input is not None:
            self.config.update(self._options_data)
            self.config.update(user_input)
            assert self._selected_installation is not None
            return await self._create_entry_for_installation(
                self._selected_installation
            )

        defaults = PERI_DEFAULTS if self._has_peri else STD_DEFAULTS
        options = PERI_OPTIONS if self._has_peri else STD_OPTIONS
        select_options = [
            {"value": state.value, "label": STATE_LABELS[state]} for state in options
        ]
        select_cfg = {"select": {"options": select_options, "mode": "dropdown"}}

        schema = vol.Schema(
            {
                vol.Optional(CONF_MAP_HOME, default=defaults[CONF_MAP_HOME]): selector(
                    select_cfg
                ),
                vol.Optional(CONF_MAP_AWAY, default=defaults[CONF_MAP_AWAY]): selector(
                    select_cfg
                ),
                vol.Optional(
                    CONF_MAP_NIGHT, default=defaults[CONF_MAP_NIGHT]
                ): selector(select_cfg),
                vol.Optional(
                    CONF_MAP_VACATION, default=defaults[CONF_MAP_VACATION]
                ): selector(select_cfg),
                vol.Optional(
                    CONF_MAP_CUSTOM, default=defaults[CONF_MAP_CUSTOM]
                ): selector(select_cfg),
            }
        )
        return self.async_show_form(step_id="mappings", data_schema=schema)

    async def async_step_abort(
        self, reason: str | None = None
    ) -> config_entries.ConfigFlowResult:
        """Clean up session when flow is aborted."""
        self._cleanup_flow_session()
        return super().async_abort(reason=reason or "unknown")

    def _cleanup_flow_session(self) -> None:
        """Remove session stored by this flow if it has no active references."""
        if not self.config.get(CONF_USERNAME):
            return
        username = self.config[CONF_USERNAME]
        sessions = self.hass.data.get(DOMAIN, {}).get("sessions", {})
        if username in sessions and sessions[username]["ref_count"] <= 0:
            sessions.pop(username)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SecuritasOptionsFlowHandler:
        """Get the options flow for this handler."""
        return SecuritasOptionsFlowHandler()


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
    ) -> config_entries.ConfigFlowResult:
        """Step 1: General settings."""
        if user_input is not None:
            user_input.setdefault(CONF_CODE, DEFAULT_CODE)
            # Flatten the advanced section back to top-level keys
            advanced = user_input.pop(CONF_ADVANCED, {})
            user_input.update(advanced)
            self._general_data = user_input
            return await self.async_step_mappings()

        notify_options = _get_notify_options(self.hass)
        schema = _build_settings_schema(
            {
                CONF_CODE: self._get(CONF_CODE, DEFAULT_CODE),
                CONF_CODE_ARM_REQUIRED: self._get(
                    CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
                ),
                CONF_NOTIFY_GROUP: self._get(CONF_NOTIFY_GROUP, ""),
                CONF_SCAN_INTERVAL: self._get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
                CONF_DELAY_CHECK_OPERATION: self._get(
                    CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
                ),
            },
            notify_options,
            use_suggested=True,
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Alarm state mappings."""
        if user_input is not None:
            data = {**self._general_data, **user_input}
            return self.async_create_entry(title="", data=data)

        has_peri = self.config_entry.data.get(CONF_HAS_PERI, False)

        # Determine defaults for mapping dropdowns
        defaults = PERI_DEFAULTS if has_peri else STD_DEFAULTS
        options = PERI_OPTIONS if has_peri else STD_OPTIONS
        valid_values = {state.value for state in options}

        def _valid_map(key: str) -> str:
            """Return saved mapping if valid for current options, else default."""
            val = self._get(key, defaults[key])
            return val if val in valid_values else defaults[key]

        map_home = _valid_map(CONF_MAP_HOME)
        map_away = _valid_map(CONF_MAP_AWAY)
        map_night = _valid_map(CONF_MAP_NIGHT)
        map_vacation = _valid_map(CONF_MAP_VACATION)
        map_custom = _valid_map(CONF_MAP_CUSTOM)

        # Build dropdown options
        select_options = [
            {"value": state.value, "label": STATE_LABELS[state]} for state in options
        ]
        select_cfg = {"select": {"options": select_options, "mode": "dropdown"}}

        schema = vol.Schema(
            {
                vol.Optional(CONF_MAP_HOME, default=map_home): selector(select_cfg),
                vol.Optional(CONF_MAP_AWAY, default=map_away): selector(select_cfg),
                vol.Optional(CONF_MAP_NIGHT, default=map_night): selector(select_cfg),
                vol.Optional(CONF_MAP_VACATION, default=map_vacation): selector(
                    select_cfg
                ),
                vol.Optional(CONF_MAP_CUSTOM, default=map_custom): selector(select_cfg),
            }
        )
        return self.async_show_form(step_id="mappings", data_schema=schema)
