"""Config flow for the Verisure OWA platform."""

from __future__ import annotations

import asyncio
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
    CONF_OPERATION_POLL_TIMEOUT,
    CONF_DEVICE_INDIGITALL,
    CONF_ENTRY_ID,
    CONF_INSTALLATION,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
    COUNTRY_CODES,
    DEFAULT_CODE,
    DEFAULT_CODE_ARM_REQUIRED,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_OPERATION_POLL_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    VerisureHub,
    _publish_flow_capabilities,
    _resolve_flow_capabilities,
    generate_uuid,
)
from .const import (
    CIRCUIT_ANNEX,
    CIRCUIT_INTERIOR,
    CIRCUIT_PERIMETER,
    CONF_ENABLE_ACTIVITY_POLLING,
    CONF_ENABLE_ANNEX_PANEL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_PERIMETER_PANEL,
    CONF_LOCK_AUTOMATIONS,
    DEFAULT_ENABLE_ACTIVITY_POLLING,
    CONF_REFRESH_TOKEN,
    LOCK_CIRCUITS,
)
from .api_queue import ApiQueue
from .verisure_owa_api import (
    PERI_DEFAULTS,
    STATE_LABELS,
    STD_DEFAULTS,
    AccountBlockedError,
    AuthenticationError,
    Installation,
    OtpPhone,
    VerisureOwaError,
    TwoFactorRequiredError,
    dropdown_options,
)
from .verisure_owa_api.capabilities import detect_annex, detect_peri

VERSION = 4

_LOGGER = logging.getLogger(__name__)

# Max seconds the Lock Automation options step waits for background lock
# discovery to finish before falling through. Sized to cover the worst case
# we've observed in production logs (~12s for an SDVFAST panel that needs
# the Danalock GraphQL fallback), with a small safety margin. Module-level
# so tests can monkeypatch it down.
LOCK_DISCOVERY_WAIT_TIMEOUT: float = 15.0

# Services that should not appear in the Notify-service dropdown.
# - `notify` / `send_message`: aliases of the legacy generic notify service;
#   not useful as a routing target.
# - `persistent_notification`: the integration already creates its own
#   persistent notification directly via the `persistent_notification` domain.
#   Routing via `notify.persistent_notification` would produce a duplicate
#   card with no actions and no useful body and never reach a real device.
_NOTIFY_EXCLUDE = {"notify", "send_message", "persistent_notification"}

PANEL_OPTION_KEYS = (
    CONF_ENABLE_PERIMETER_PANEL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_ANNEX_PANEL,
)

# Section keys for the grouped settings schema. Persisted-data shape stays
# flat — the handlers flatten these section payloads back to top-level keys.
SECTION_PIN = "pin"
SECTION_NOTIFICATIONS = "notifications"
SECTION_SUBPANELS = "subpanels"
SECTION_ACTIVITY = "activity"
_ALL_SECTIONS = (
    SECTION_PIN,
    SECTION_NOTIFICATIONS,
    SECTION_SUBPANELS,
    SECTION_ACTIVITY,
    CONF_ADVANCED,
)


# Localized notes appended to the mappings step's description when
# perimeter and/or annex sub-panels are available. Hassfest doesn't allow
# arbitrary nested keys in strings.json (the form-step schema is strict),
# so we keep these in Python and look them up by hass.config.language.
# Falls back to English when the locale isn't covered.
# pylint: disable=line-too-long
_SUBPANELS_NOTES: dict[str, dict[str, str]] = {
    "en": {
        "peri": "The optional Interior-only and Perimeter-only panels do not use these mappings.",
        "annex": "The optional Interior-only and Annex-only panels do not use these mappings.",
        "both": "The optional Interior-only, Perimeter-only and Annex-only panels do not use these mappings.",
    },
    "es": {
        "peri": "Los paneles opcionales solo Interior y solo Perimetral no usan estas asignaciones.",
        "annex": "Los paneles opcionales solo Interior y solo Anexo no usan estas asignaciones.",
        "both": "Los paneles opcionales solo Interior, solo Perimetral y solo Anexo no usan estas asignaciones.",
    },
    "fr": {
        "peri": "Les panneaux optionnels Intérieur uniquement et Périmètre uniquement n'utilisent pas ces associations.",
        "annex": "Les panneaux optionnels Intérieur uniquement et Annexe uniquement n'utilisent pas ces associations.",
        "both": "Les panneaux optionnels Intérieur uniquement, Périmètre uniquement et Annexe uniquement n'utilisent pas ces associations.",
    },
    "it": {
        "peri": "I pannelli opzionali solo Interno e solo Perimetrale non usano queste associazioni.",
        "annex": "I pannelli opzionali solo Interno e solo Annesso non usano queste associazioni.",
        "both": "I pannelli opzionali solo Interno, solo Perimetrale e solo Annesso non usano queste associazioni.",
    },
    "pt": {
        "peri": "Os painéis opcionais apenas Interior e apenas Perímetro não usam estas associações.",
        "annex": "Os painéis opcionais apenas Interior e apenas Anexo não usam estas associações.",
        "both": "Os painéis opcionais apenas Interior, apenas Perímetro e apenas Anexo não usam estas associações.",
    },
    "pt-BR": {
        "peri": "Os painéis opcionais apenas Interior e apenas Perímetro não usam estas associações.",
        "annex": "Os painéis opcionais apenas Interior e apenas Anexo não usam estas associações.",
        "both": "Os painéis opcionais apenas Interior, apenas Perímetro e apenas Anexo não usam estas associações.",
    },
    "ca": {
        "peri": "Els panells opcionals només Interior i només Perímetre no fan servir aquestes assignacions.",
        "annex": "Els panells opcionals només Interior i només Annex no fan servir aquestes assignacions.",
        "both": "Els panells opcionals només Interior, només Perímetre i només Annex no fan servir aquestes assignacions.",
    },
}
# pylint: enable=line-too-long


def _subpanels_note(hass: HomeAssistant, *, has_peri: bool, has_annex: bool) -> str:
    """Return the localized sub-panels note for the mappings step.

    Empty string when neither perimeter nor annex is supported. Otherwise
    picks one of three sentences (peri-only, annex-only, both) based on
    capability.
    """
    if not (has_peri or has_annex):
        return ""
    key = "both" if has_peri and has_annex else "peri" if has_peri else "annex"
    locale = _SUBPANELS_NOTES.get(hass.config.language, _SUBPANELS_NOTES["en"])
    return f" {locale.get(key, _SUBPANELS_NOTES['en'][key])}"


def _mapping_field(key: str, suggestion: str | None) -> vol.Optional:
    """Build a vol.Optional marker for a state-mapping field.

    Uses ``description={"suggested_value": ...}`` rather than ``default=`` so
    that clearing the field in the UI persists as a missing key (= "not used")
    instead of being silently re-filled with the default on submit. When the
    suggestion is None the field renders blank.
    """
    if suggestion is None:
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": suggestion})


def _mapping_select_options(*, has_peri: bool, has_annex: bool) -> list[dict[str, str]]:
    """Build the dropdown options for a state-mapping field.

    Clearing happens via the form's X (clear) button — HA's frontend then
    omits the key from user_input. ``_normalize_mapping_input`` surfaces
    that absence as an explicit ``""`` in entry.options so the update
    listener sees a diff against the stale entry.data value and syncs.
    """
    return [
        {"value": s.value, "label": STATE_LABELS[s]}
        for s in dropdown_options(has_peri=has_peri, has_annex=has_annex)
    ]


_MAPPING_FIELDS: tuple[str, ...] = (
    CONF_MAP_HOME,
    CONF_MAP_AWAY,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_MAP_CUSTOM,
)


def _normalize_mapping_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Ensure every mapping field is present in ``user_input``.

    HA's frontend omits cleared select fields from the submitted user_input
    entirely (rather than sending an empty string). With the prior options
    dict also missing the same key from an earlier broken save, the new
    options dict would match the old one and no update listener would fire
    — the cleared state never reaches entry.data, and the form keeps
    pre-filling with the stale value on the next open.

    Surface the cleared state as an explicit ``""`` so the diff vs. the
    prior options is non-empty and downstream sync runs.
    """
    return {key: user_input.get(key, "") for key in _MAPPING_FIELDS} | {
        k: v for k, v in user_input.items() if k not in _MAPPING_FIELDS
    }


def _flatten_sections(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten all known section payloads back to top-level keys."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in _ALL_SECTIONS and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _build_panel_extra_fields(
    *,
    has_peri: bool,
    has_annex: bool,
    peri_default: bool = False,
    annex_default: bool = False,
    interior_default: bool = False,
) -> dict[Any, Any]:
    """Build the capability-gated panel-toggle entries for the sub-panels section.

    The interior toggle appears whenever any sibling axis is supported; this
    matches the post-setup options behaviour so users on any peri- or annex-
    capable installation can carve a separate interior sub-panel even after
    flipping the sibling off.

    The returned dict is the *contents* of the SECTION_SUBPANELS section; the
    caller wraps it in a `section()` only when non-empty.
    """
    fields: dict[Any, Any] = {}
    if has_peri:
        fields[vol.Optional(CONF_ENABLE_PERIMETER_PANEL, default=peri_default)] = bool
    if has_annex:
        fields[vol.Optional(CONF_ENABLE_ANNEX_PANEL, default=annex_default)] = bool
    if has_peri or has_annex:
        fields[vol.Optional(CONF_ENABLE_INTERIOR_PANEL, default=interior_default)] = (
            bool
        )
    return fields


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
    extra_fields: dict[Any, Any] | None = None,
) -> vol.Schema:
    """Build the shared sectioned settings schema for config and options flows.

    Layout: a PIN section, a Force-arm-notifications section, an optional
    Sub-panels section (only present when ``extra_fields`` is non-empty),
    and a collapsed Advanced section. Section payloads are flattened back
    to top-level keys by ``_flatten_sections`` before persistence — the
    saved data shape is unchanged.
    """
    code_val = defaults.get(CONF_CODE, DEFAULT_CODE)
    code_field = (
        vol.Optional(CONF_CODE, description={"suggested_value": code_val})
        if use_suggested
        else vol.Optional(CONF_CODE, default=code_val)
    )

    pin_section = section(
        vol.Schema(
            {
                code_field: str,
                vol.Optional(
                    CONF_CODE_ARM_REQUIRED,
                    default=defaults.get(
                        CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
                    ),
                ): bool,
            }
        ),
        {"collapsed": False},
    )

    notifications_section = section(
        vol.Schema(
            {
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
                vol.Optional(
                    CONF_FORCE_ARM_NOTIFICATIONS,
                    default=defaults.get(
                        CONF_FORCE_ARM_NOTIFICATIONS, DEFAULT_FORCE_ARM_NOTIFICATIONS
                    ),
                ): bool,
            }
        ),
        {"collapsed": False},
    )

    activity_section = section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_ACTIVITY_POLLING,
                    default=defaults.get(
                        CONF_ENABLE_ACTIVITY_POLLING, DEFAULT_ENABLE_ACTIVITY_POLLING
                    ),
                ): bool,
            }
        ),
        {"collapsed": False},
    )

    advanced_section = section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): int,
                vol.Optional(
                    CONF_DELAY_CHECK_OPERATION,
                    default=defaults.get(
                        CONF_DELAY_CHECK_OPERATION,
                        DEFAULT_DELAY_CHECK_OPERATION,
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=2.0, max=15.0)),
                vol.Optional(
                    CONF_OPERATION_POLL_TIMEOUT,
                    default=defaults.get(
                        CONF_OPERATION_POLL_TIMEOUT,
                        DEFAULT_OPERATION_POLL_TIMEOUT,
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=60.0, max=300.0)),
            }
        ),
        {"collapsed": True},
    )

    schema_dict: dict[Any, Any] = {
        vol.Required(SECTION_PIN): pin_section,
        vol.Required(SECTION_NOTIFICATIONS): notifications_section,
    }
    if extra_fields:
        schema_dict[vol.Required(SECTION_SUBPANELS)] = section(
            vol.Schema(extra_fields),
            {"collapsed": False},
        )
    schema_dict[vol.Optional(SECTION_ACTIVITY)] = activity_section
    schema_dict[vol.Optional(CONF_ADVANCED)] = advanced_section
    return vol.Schema(schema_dict)


class FlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 4
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the flow handler."""
        self.config: dict[str, Any] = {}
        self.hub: VerisureHub | None = None
        self.otp_challenge: tuple[str | None, list[OtpPhone] | None] | None = None
        self._available_installations: list[Installation] = []
        self._selected_installation: Installation | None = None
        self._options_data: dict[str, Any] = {}
        # Kept separate from _options_data so toggles end up on entry.options,
        # not entry.data — matches where the post-setup OptionsFlow writes them.
        self._panel_options: dict[str, Any] = {}
        self._has_peri: bool = False
        self._has_annex: bool = False
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def _create_entry_for_installation(
        self, installation: Installation
    ) -> config_entries.ConfigFlowResult:
        """Register a new entry, persisting the refresh token (not the password)."""
        username = self.config[CONF_USERNAME]
        unique_id = f"{username}_{installation.number}"
        await self.async_set_unique_id(unique_id)
        # HA 2026.6: opt out of implicit reload to avoid deprecated double-reload
        # with the entry-update listener registered in __init__.async_setup_entry.
        self._abort_if_unique_id_configured(reload_on_update=False)
        self.config[CONF_INSTALLATION] = installation.number
        assert self.hub is not None
        refresh_token = self.hub.get_refresh_token()
        # Refusing here is the only safe move: dropping the password while
        # writing an empty refresh token would leave the entry unable to
        # authenticate on the next restart.
        if not refresh_token:
            _LOGGER.error(
                "Login succeeded but no refresh token was returned; "
                "refusing to create an entry that cannot reauthenticate"
            )
            return self.async_abort(reason="no_refresh_token")
        entry_data = dict(self.config)
        entry_data.pop(CONF_PASSWORD, None)
        entry_data[CONF_REFRESH_TOKEN] = refresh_token
        return self.async_create_entry(
            title=installation.alias,
            data=entry_data,
            options=dict(self._panel_options) if self._panel_options else None,
        )

    def _create_client(
        self,
    ) -> VerisureHub:
        """Create client (VerisureHub)."""

        if self.config[CONF_PASSWORD] is None:
            raise ValueError(
                "Invalid internal state. Called without either password or token"
            )

        self.hub = VerisureHub(
            self.config, None, async_get_clientsession(self.hass), self.hass
        )

        return self.hub

    async def async_step_phone_list(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the list of phones for the OTP challenge."""
        phone_index: int = -1
        assert user_input is not None
        selected_phone_key = user_input.get("phones", "")

        assert self.otp_challenge is not None
        assert self.hub is not None
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
            await self.hub.send_opt(self.otp_challenge[0] or "", phone_index)
        except VerisureOwaError:
            return await self._show_2fa_error("otp_send_failed")

        return self.async_show_form(
            step_id="otp_challenge",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
        )

    async def async_step_otp_challenge(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Last step of the OTP challenge."""
        assert self.hub is not None
        assert self.otp_challenge is not None
        assert user_input is not None
        try:
            result = await self.hub.send_sms_code(
                self.otp_challenge[0] or "", user_input[CONF_CODE]
            )
        except VerisureOwaError as err:
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
        if self._reauth_entry is not None:
            return await self._finish_reauth()
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
        username = self.config[CONF_USERNAME]
        sessions = self.hass.data.get(DOMAIN, {}).get("sessions", {})
        if username in sessions:
            existing_hub = sessions[username]["hub"]
            self.hub = existing_hub
            self.config[CONF_DEVICE_ID] = existing_hub.config[CONF_DEVICE_ID]
            self.config[CONF_UNIQUE_ID] = existing_hub.config[CONF_UNIQUE_ID]
            self.config[CONF_DEVICE_INDIGITALL] = existing_hub.config.get(
                CONF_DEVICE_INDIGITALL, ""
            )
            return await self.finish_setup()

        uuid = generate_uuid()
        self.config[CONF_DEVICE_ID] = uuid
        self.config[CONF_UNIQUE_ID] = uuid

        self.hub = self._create_client()

        # Login — catches credential errors and network failures
        try:
            await self.hub.login()
        except TwoFactorRequiredError:
            # 2FA required — proceed to device validation for phone list
            return await self._start_2fa_flow()
        except AccountBlockedError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(user_input),
                errors={"base": "account_blocked"},
            )
        except AuthenticationError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(user_input),
                errors={"base": "invalid_auth"},
            )
        except VerisureOwaError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(user_input),
                errors={"base": "cannot_connect"},
            )

        # Login succeeded without 2FA — proceed directly
        return await self.finish_setup()

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth when ConfigEntryAuthFailed is raised."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]  # type: ignore[typeddict-item]
        )
        assert self._reauth_entry is not None
        self.config = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show reauth form and handle credential re-entry."""
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            self.config[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            self.config[CONF_USERNAME] = user_input.get(
                CONF_USERNAME, self._reauth_entry.data.get(CONF_USERNAME, "")
            )

            # Preserve existing device IDs from the entry being reauthenticated
            self.config[CONF_DEVICE_ID] = self._reauth_entry.data.get(
                CONF_DEVICE_ID, generate_uuid()
            )
            self.config[CONF_UNIQUE_ID] = self._reauth_entry.data.get(
                CONF_UNIQUE_ID, self.config[CONF_DEVICE_ID]
            )
            self.config.setdefault(
                CONF_DEVICE_INDIGITALL,
                self._reauth_entry.data.get(CONF_DEVICE_INDIGITALL, ""),
            )
            self.config.setdefault(
                CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
            )
            self.config.setdefault(CONF_ENTRY_ID, "")

            self.hub = self._create_client()

            try:
                await self.hub.login()
            except TwoFactorRequiredError:
                return await self._start_2fa_flow()
            except AccountBlockedError:
                errors["base"] = "account_blocked"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except VerisureOwaError:
                errors["base"] = "cannot_connect"
            else:
                return await self._finish_reauth()

        username = self._reauth_entry.data.get(CONF_USERNAME, "")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=username): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _finish_reauth(self) -> config_entries.ConfigFlowResult:
        """Capture a fresh refresh token and reload; the supplied password is never persisted."""
        assert self._reauth_entry is not None
        assert self.hub is not None
        await self.async_set_unique_id(self._reauth_entry.unique_id)
        refresh_token = self.hub.get_refresh_token()
        # Without a refresh token the entry would be left unauthenticatable.
        # Leave the existing entry data untouched so the user can retry reauth.
        if not refresh_token:
            _LOGGER.error(
                "Reauth login succeeded but no refresh token was returned; "
                "leaving existing entry unchanged"
            )
            return self.async_abort(reason="no_refresh_token")
        new_data = {**self._reauth_entry.data}
        new_data[CONF_USERNAME] = self.config[CONF_USERNAME]
        new_data.pop(CONF_PASSWORD, None)
        new_data[CONF_REFRESH_TOKEN] = refresh_token
        self.hass.config_entries.async_update_entry(self._reauth_entry, data=new_data)
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    async def _start_2fa_flow(
        self, errors: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Call validate_device and show phone selection form."""
        assert self.hub is not None
        try:
            otp_result = await self.hub.validate_device()
        except VerisureOwaError as err:
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
    def _is_otp_expired(err: VerisureOwaError) -> bool:
        """Check if a VerisureOwaError indicates an expired OTP (auth-code 10002)."""
        body = err.response_body
        if body is None:
            return False
        try:
            return body["errors"][0]["data"].get("auth-code") == "10002"
        except (IndexError, KeyError, TypeError):
            return False

    async def _show_2fa_error(self, error_key: str) -> config_entries.ConfigFlowResult:
        """Re-show phone list form with an error."""
        return await self._start_2fa_flow(errors={"base": error_key})

    async def finish_setup(self) -> config_entries.ConfigFlowResult:
        """Login, discover installations, detect peri, advance to options."""
        assert self.hub is not None
        try:
            if self.hub.get_authentication_token() is None:
                await self.hub.login()
        except TwoFactorRequiredError:
            return await self._start_2fa_flow()
        except AccountBlockedError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "account_blocked"},
            )
        except AuthenticationError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "invalid_auth"},
            )
        except VerisureOwaError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "cannot_connect"},
            )

        self.hass.data.setdefault(DOMAIN, {})

        username = self.config[CONF_USERNAME]
        sessions = self.hass.data[DOMAIN].setdefault("sessions", {})
        if username not in sessions:
            sessions[username] = {"hub": self.hub, "ref_count": 0}

        try:
            installations = await self.hub.client.list_installations()
        except VerisureOwaError:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(self.config),
                errors={"base": "cannot_connect"},
            )
        self.hass.data[DOMAIN][f"installations_cache_{username}"] = {
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

    async def _select_installation(
        self, installation: Installation
    ) -> config_entries.ConfigFlowResult:
        """Set installation, call get_services, detect peri, advance to options."""
        self.config[CONF_INSTALLATION] = installation.number
        self._selected_installation = installation

        assert self.hub is not None
        try:
            services = await self.hub.get_services(
                installation, priority=ApiQueue.FOREGROUND
            )
        except VerisureOwaError as err:
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

        capabilities = self.hub.client.get_supported_commands(installation.number)
        self._has_peri = detect_peri(installation, services, capabilities)
        self._has_annex = detect_annex(capabilities)
        _LOGGER.debug(
            "Perimeter detected for %s: %s", installation.number, self._has_peri
        )
        # Publish the detection result so the options flow can render the
        # right toggles even if the user opens it before async_setup_entry
        # has finished storing the alarm coordinator under entry.entry_id.
        _publish_flow_capabilities(
            self.hass, installation.number, self._has_peri, self._has_annex
        )

        return await self.async_step_options()

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
        """Step 3: PIN, scan interval, notifications, sub-panel toggles."""
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            user_input.setdefault(CONF_CODE, DEFAULT_CODE)
            # Toggles belong on entry.options, not entry.data.
            for key in PANEL_OPTION_KEYS:
                if key in user_input:
                    self._panel_options[key] = user_input.pop(key)
            self._options_data = user_input
            return await self.async_step_mappings()

        notify_options = _get_notify_options(self.hass)
        extra_fields = _build_panel_extra_fields(
            has_peri=self._has_peri, has_annex=self._has_annex
        )

        schema = _build_settings_schema(
            {
                CONF_CODE: DEFAULT_CODE,
                CONF_CODE_ARM_REQUIRED: DEFAULT_CODE_ARM_REQUIRED,
            },
            notify_options,
            extra_fields=extra_fields,
        )
        install_name = (
            self._selected_installation.alias if self._selected_installation else ""
        )
        return self.async_show_form(
            step_id="options",
            data_schema=schema,
            description_placeholders={"installation_name": install_name},
        )

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4: Alarm state mappings, then create entry."""
        if user_input is not None:
            self.config.update(self._options_data)
            self.config.update(_normalize_mapping_input(user_input))
            assert self._selected_installation is not None
            return await self._create_entry_for_installation(
                self._selected_installation
            )

        defaults = PERI_DEFAULTS if self._has_peri else STD_DEFAULTS
        select_options = _mapping_select_options(
            has_peri=self._has_peri, has_annex=self._has_annex
        )
        select_cfg = {"select": {"options": select_options, "mode": "dropdown"}}

        schema = vol.Schema(
            {
                _mapping_field(CONF_MAP_HOME, defaults.get(CONF_MAP_HOME)): selector(
                    select_cfg
                ),
                _mapping_field(CONF_MAP_AWAY, defaults.get(CONF_MAP_AWAY)): selector(
                    select_cfg
                ),
                _mapping_field(CONF_MAP_NIGHT, defaults.get(CONF_MAP_NIGHT)): selector(
                    select_cfg
                ),
                _mapping_field(
                    CONF_MAP_VACATION, defaults.get(CONF_MAP_VACATION)
                ): selector(select_cfg),
                _mapping_field(
                    CONF_MAP_CUSTOM, defaults.get(CONF_MAP_CUSTOM)
                ): selector(select_cfg),
            }
        )
        return self.async_show_form(
            step_id="mappings",
            data_schema=schema,
            description_placeholders={
                "subpanels_note": _subpanels_note(
                    self.hass, has_peri=self._has_peri, has_annex=self._has_annex
                )
            },
        )

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
    ) -> VerisureOptionsFlowHandler:
        """Get the options flow for this handler."""
        return VerisureOptionsFlowHandler()


class VerisureOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Verisure OWA options."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._general_data: dict[str, Any] = {}

    def _get(self, key: str, default: Any = None) -> Any:
        """Read current value from options, falling back to entry data."""
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: General settings."""
        if user_input is not None:
            user_input = _flatten_sections(user_input)
            user_input.setdefault(CONF_CODE, DEFAULT_CODE)
            self._general_data = user_input
            return await self.async_step_mappings()

        notify_options = _get_notify_options(self.hass)

        # Capability-gated sub-panel toggles — resolve via the helper so the
        # options dialog opened during async_setup_entry's get_services await
        # (when the coordinator dict isn't yet under entry.entry_id) still
        # picks up the published capabilities from the config flow.
        has_peri, has_annex = _resolve_flow_capabilities(self.hass, self.config_entry)
        opts = self.config_entry.options
        extra_fields = _build_panel_extra_fields(
            has_peri=has_peri,
            has_annex=has_annex,
            peri_default=opts.get(CONF_ENABLE_PERIMETER_PANEL, False),
            annex_default=opts.get(CONF_ENABLE_ANNEX_PANEL, False),
            interior_default=opts.get(CONF_ENABLE_INTERIOR_PANEL, False),
        )

        schema = _build_settings_schema(
            {
                CONF_CODE: self._get(CONF_CODE, DEFAULT_CODE),
                CONF_CODE_ARM_REQUIRED: self._get(
                    CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
                ),
                CONF_NOTIFY_GROUP: self._get(CONF_NOTIFY_GROUP, ""),
                CONF_FORCE_ARM_NOTIFICATIONS: self._get(
                    CONF_FORCE_ARM_NOTIFICATIONS, DEFAULT_FORCE_ARM_NOTIFICATIONS
                ),
                CONF_SCAN_INTERVAL: self._get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
                CONF_DELAY_CHECK_OPERATION: self._get(
                    CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
                ),
                CONF_OPERATION_POLL_TIMEOUT: self._get(
                    CONF_OPERATION_POLL_TIMEOUT, DEFAULT_OPERATION_POLL_TIMEOUT
                ),
                CONF_ENABLE_ACTIVITY_POLLING: self._get(
                    CONF_ENABLE_ACTIVITY_POLLING, DEFAULT_ENABLE_ACTIVITY_POLLING
                ),
            },
            notify_options,
            use_suggested=True,
            extra_fields=extra_fields,
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Alarm state mappings."""
        if user_input is not None:
            self._general_data = {
                **self._general_data,
                **_normalize_mapping_input(user_input),
            }
            return await self.async_step_lock_automations()

        # Resolve via the helper so we read coordinator → published cache →
        # False, matching the init step. Avoids the race where the user
        # opens the dialog before async_setup_entry has stored the coord.
        has_peri, has_annex = _resolve_flow_capabilities(self.hass, self.config_entry)

        # Determine defaults for mapping dropdowns
        defaults = PERI_DEFAULTS if has_peri else STD_DEFAULTS
        options = dropdown_options(has_peri=has_peri, has_annex=has_annex)
        valid_values = {state.value for state in options}

        def _suggested_map(key: str) -> str | None:
            """Return the value to pre-fill in the form, or None for blank.

            Saved value wins when it's still in the current option set;
            otherwise falls back to the default. Pre-v5 saved values of
            ``"not_used"`` (or anything else outside the dropdown) collapse
            to blank, so the user sees a cleared field instead of a stale
            unselectable choice.
            """
            val = self._get(key)
            if val and val in valid_values:
                return val
            return defaults.get(key)

        # Build dropdown options — only real values appear; clearing happens
        # via the form's X (clear) button (HA omits the key from user_input,
        # which ``_normalize_mapping_input`` surfaces as an explicit "" in
        # entry.options so the update listener sees the diff).
        select_options = _mapping_select_options(has_peri=has_peri, has_annex=has_annex)
        select_cfg = {"select": {"options": select_options, "mode": "dropdown"}}

        schema = vol.Schema(
            {
                _mapping_field(CONF_MAP_HOME, _suggested_map(CONF_MAP_HOME)): selector(
                    select_cfg
                ),
                _mapping_field(CONF_MAP_AWAY, _suggested_map(CONF_MAP_AWAY)): selector(
                    select_cfg
                ),
                _mapping_field(
                    CONF_MAP_NIGHT, _suggested_map(CONF_MAP_NIGHT)
                ): selector(select_cfg),
                _mapping_field(
                    CONF_MAP_VACATION, _suggested_map(CONF_MAP_VACATION)
                ): selector(select_cfg),
                _mapping_field(
                    CONF_MAP_CUSTOM, _suggested_map(CONF_MAP_CUSTOM)
                ): selector(select_cfg),
            }
        )
        return self.async_show_form(
            step_id="mappings",
            data_schema=schema,
            description_placeholders={
                "subpanels_note": _subpanels_note(
                    self.hass, has_peri=has_peri, has_annex=has_annex
                )
            },
        )

    async def async_step_lock_automations(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Per-lock automation settings (lock-on-arm / disarm-on-unlock).

        Renders one collapsible section per registered lock, each containing
        per-circuit boolean checkboxes for the two automations. The persisted
        shape (CONF_LOCK_AUTOMATIONS = {device_id: {lock_on_arm: [...],
        unlock_disarms: [...]}}) is unchanged — the handler converts between
        per-circuit booleans (UI) and circuit-name lists (storage).
        """
        registered_locks = await self._get_registered_locks()
        if not registered_locks:
            return self.async_create_entry(title="", data=self._general_data)

        enabled_circuits = self._get_enabled_circuits()
        # Preserve LOCK_CIRCUITS ordering so the UI is consistent.
        enabled_circuit_list = [c for c in LOCK_CIRCUITS if c in enabled_circuits]

        if user_input is not None:
            new_map: dict[str, dict[str, list[str]]] = {}
            for lk in registered_locks:
                did = lk["device_id"]
                section_data = user_input.get(f"lock__{did}", {}) or {}
                new_map[did] = {
                    "lock_on_arm": [
                        c
                        for c in enabled_circuit_list
                        if section_data.get(f"lock_on_arm__{c}", False)
                    ],
                    "unlock_disarms": [
                        c
                        for c in enabled_circuit_list
                        if section_data.get(f"unlock_disarms__{c}", False)
                    ],
                }
            return self.async_create_entry(
                title="",
                data={**self._general_data, CONF_LOCK_AUTOMATIONS: new_map},
            )

        existing = self.config_entry.options.get(CONF_LOCK_AUTOMATIONS, {})

        schema_dict: dict[Any, Any] = {}
        placeholders: dict[str, str] = {}
        for lk in registered_locks:
            did = lk["device_id"]
            saved = existing.get(did, {})
            saved_arm = set(saved.get("lock_on_arm", []))
            saved_unlock = set(saved.get("unlock_disarms", []))

            section_fields: dict[Any, Any] = {}
            for c in enabled_circuit_list:
                section_fields[
                    vol.Optional(f"lock_on_arm__{c}", default=c in saved_arm)
                ] = bool
            for c in enabled_circuit_list:
                section_fields[
                    vol.Optional(f"unlock_disarms__{c}", default=c in saved_unlock)
                ] = bool

            schema_dict[vol.Required(f"lock__{did}")] = section(
                vol.Schema(section_fields),
                {"collapsed": False},
            )
            placeholders[f"lock_alias_{did}"] = lk.get("alias") or did

        return self.async_show_form(
            step_id="lock_automations",
            data_schema=vol.Schema(schema_dict),
            description_placeholders=placeholders,
        )

    async def _get_registered_locks(self) -> list[dict[str, str]]:
        """Return [{device_id, alias}] for each lock registered for this entry.

        If the in-memory list is empty but the entry has a pending
        ``lock_discovery_complete`` event (i.e. the installation has a lock
        service and background discovery is still running), wait up to
        ``LOCK_DISCOVERY_WAIT_TIMEOUT`` seconds for discovery to finish, then
        re-read the list. Without this wait, opening options immediately
        after adding an installation silently skips the Lock Automation step
        even though a lock exists.
        """
        domain_entry = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        )
        registered = list(domain_entry.get("registered_locks", []))
        if registered:
            return registered

        event = domain_entry.get("lock_discovery_complete")
        if event is None or event.is_set():
            return registered

        try:
            async with asyncio.timeout(LOCK_DISCOVERY_WAIT_TIMEOUT):
                await event.wait()
        except TimeoutError:
            _LOGGER.warning(
                "Lock discovery did not complete within %.1fs for entry %s; "
                "skipping Lock Automation step",
                LOCK_DISCOVERY_WAIT_TIMEOUT,
                self.config_entry.entry_id,
            )
            return list(domain_entry.get("registered_locks", []))

        return list(domain_entry.get("registered_locks", []))

    def _get_enabled_circuits(self) -> set[str]:
        """Return the set of circuit labels enabled on this installation.

        Interior is always available — every installation has interior alarm.
        The CONF_ENABLE_INTERIOR_PANEL flag controls whether a separate
        sub-panel entity is exposed, not whether the circuit exists.
        Perimeter and annex are gated on their explicit toggles.
        """
        opts = self.config_entry.options
        enabled: set[str] = {CIRCUIT_INTERIOR}
        if opts.get(CONF_ENABLE_PERIMETER_PANEL, False):
            enabled.add(CIRCUIT_PERIMETER)
        if opts.get(CONF_ENABLE_ANNEX_PANEL, False):
            enabled.add(CIRCUIT_ANNEX)
        return enabled
