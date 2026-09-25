"""Support for Verisure OWA alarms."""

from __future__ import annotations

import asyncio
import inspect
import logging
import socket
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import (
    frontend,  # noqa: F401 — re-exported so tests can patch
)

try:
    # Public location since HA 2026.8.
    from homeassistant.components.http.server import (  # type: ignore[reportMissingImports]
        StaticPathConfig,
    )
except ImportError:
    # Compatibility with our minimum supported HA (2025.2).
    from homeassistant.components.http import (
        StaticPathConfig,  # type: ignore[reportPrivateImportUsage]
    )
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.service import (
    async_extract_entity_ids,
    async_set_service_schema,
)

from .api_queue import ApiQueue
from .card_resources import (
    _register_card_resource,
    _unregister_card_resource,
)
from .const import (  # noqa: F401 — re-exported for backwards compatibility
    ACTIVITY_LOG_CARD_BASE_URL,
    ACTIVITY_LOG_CARD_URL,
    API_CACHE_TTL,
    CAMERA_CARD_BASE_URL,
    CAMERA_CARD_URL,
    CARD_BASE_URL,
    CARD_URL,
    CHIP_CARD_BASE_URL,
    CHIP_CARD_URL,
    CONF_ADVANCED,
    CONF_AUTO_FORCE_ARM,
    CONF_CODE_ARM_REQUIRED,
    CONF_CODE_HASH,
    CONF_CODE_IS_NUMERIC,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENABLE_ACTIVITY_POLLING,
    CONF_ENABLE_ANNEX_PANEL,
    CONF_ENABLE_INTERIOR_PANEL,
    CONF_ENABLE_PERIMETER_PANEL,
    CONF_ENTRY_ID,
    CONF_FORCE_ARM_NOTIFICATIONS,
    CONF_INSTALLATION,
    CONF_LOCK_AUTOMATIONS,
    CONF_LOCK_CODE_REQUIRED,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    CONF_OPERATION_POLL_TIMEOUT,
    CONF_REFRESH_TOKEN,
    CONF_UNSUPPORTED_COMMANDS,
    COUNTRY_CODES,
    DEFAULT_AUTO_FORCE_ARM,
    DEFAULT_CODE,
    DEFAULT_CODE_ARM_REQUIRED,
    DEFAULT_COUNTRY,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_ENABLE_ACTIVITY_POLLING,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_LOCK_CODE_REQUIRED,
    DEFAULT_OPERATION_POLL_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MORE_INFO_BASE_URL,
    MORE_INFO_MODULE_URL,
    PANEL_OPTION_KEYS,
    PLATFORMS,
    SENTINEL_SERVICE_NAMES,
    SIGNAL_CAMERA_STATE,
)

# CameraCoordinator re-exported for backwards compatibility
from .coordinators import (  # noqa: F401
    _DEFAULT_ACTIVITY_INTERVAL,
    ActivityCoordinator,
    AlarmCoordinator,
    CameraCoordinator,
    LockCoordinator,
    SentinelCoordinator,
)
from .discovery import (  # noqa: F401 — re-exported for backwards compatibility
    _async_discover_devices,
    _discover_cameras,
    _discover_locks,
    _schedule_lock_config_retry,
)
from .events import attach_activity_listener
from .hub import (  # noqa: F401 — re-exported for backwards compatibility
    VerisureDevice,
    VerisureHub,
    _async_notify,
    _notify,
)
from .log_filter import SensitiveDataFilter, TransientCoordinatorErrorFilter
from .migrate_unique_ids import migrate_unique_ids
from .pin_crypto import encode_pin
from .verisure_owa_api import (
    APIConnectionError,
    ApiDomains,
    AuthenticationError,
    Installation,
    TwoFactorRequiredError,
    VerisureOwaError,
    generate_uuid,
)
from .verisure_owa_api.exceptions import is_refresh_login_crash

_LOGGER = logging.getLogger(__name__)

# HA 2026.10 removes the old leading ``hass`` argument. Keep the integration's
# HA 2025.2 minimum working while calling only the modern form on current Core.
_EXTRACT_ENTITY_IDS_REQUIRES_HASS = (
    next(iter(inspect.signature(async_extract_entity_ids).parameters)) == "hass"
)


async def _async_extract_service_entity_ids(call: ServiceCall) -> set[str]:
    """Extract service targets across the supported Home Assistant versions."""
    args = (call.hass, call) if _EXTRACT_ENTITY_IDS_REQUIRES_HASS else (call,)
    return await cast(Any, async_extract_entity_ids)(*args)


# Inert: this integration is config-entry only and ``async_setup`` ignores the
# YAML config entirely. The schema exists so a legacy ``securitas:`` block from
# the YAML era doesn't fail config validation at startup — hence ALLOW_EXTRA on
# the domain schema, which lets keys we no longer declare pass through ignored.
# Notably there is no PIN field: the PIN is only ever set through the config
# flow, and is stored hashed (see pin_crypto), so YAML must not invite one.
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_COUNTRY, default=DEFAULT_COUNTRY): str,
                vol.Optional(
                    CONF_CODE_ARM_REQUIRED, default=DEFAULT_CODE_ARM_REQUIRED
                ): bool,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            },
            extra=vol.ALLOW_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def _publish_flow_capabilities(
    hass: HomeAssistant,
    installation_number: str,
    has_peri: bool,
    has_annex: bool,
) -> None:
    """Cache detected capability flags so the options flow can read them
    while async_setup_entry is still running.

    Both the config flow's _select_installation step and async_setup_entry's
    populate_capabilities_from_data call this so the options dialog opened
    immediately after CREATE_ENTRY (or during a slow restart) doesn't see
    has_peri=False just because the alarm coordinator dict isn't yet under
    entry.entry_id in hass.data.
    """
    hass.data.setdefault(DOMAIN, {}).setdefault("flow_capabilities", {})[
        installation_number
    ] = {"has_peri": has_peri, "has_annex": has_annex}


def _resolve_flow_capabilities(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> tuple[bool, bool]:
    """Return (has_peri, has_annex) for *entry* using the most authoritative
    available source.

    Order:
      1. The alarm coordinator if it has populated capabilities.
      2. The published capability cache (set by the config flow and by
         async_setup_entry as soon as detection runs) — covers the race
         window where the entry isn't yet stored in hass.data.
      3. (False, False) if neither source has data — current default.
    """
    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.get(entry.entry_id, {})
    coord = entry_data.get("alarm_coordinator")
    if coord is not None and getattr(coord, "capabilities_populated", False):
        return coord.has_peri, coord.has_annex

    installation_number = entry.data.get(CONF_INSTALLATION)
    if installation_number:
        cached = domain_data.get("flow_capabilities", {}).get(installation_number)
        if cached:
            return cached["has_peri"], cached["has_annex"]

    return False, False


def add_device_information[T: dict](config: T) -> T:
    """Add device information to the configuration."""
    if CONF_DEVICE_ID not in config:
        config[CONF_DEVICE_ID] = generate_uuid()

    if CONF_UNIQUE_ID not in config:
        config[CONF_UNIQUE_ID] = generate_uuid()

    if CONF_DEVICE_INDIGITALL not in config:
        config[CONF_DEVICE_INDIGITALL] = str(uuid4())

    return config


# Fields owned by the options flow. When syncing options into entry.data
# we *replace* these rather than merge, so a key cleared in options (e.g.
# CONF_MAP_VACATION) doesn't leave a stale value lingering in entry.data.
_OPTIONS_MANAGED_FIELDS: tuple[str, ...] = (
    CONF_CODE_HASH,
    CONF_CODE_IS_NUMERIC,
    CONF_CODE_ARM_REQUIRED,
    CONF_LOCK_CODE_REQUIRED,
    CONF_SCAN_INTERVAL,
    CONF_MAP_HOME,
    CONF_MAP_AWAY,
    CONF_MAP_NIGHT,
    CONF_MAP_CUSTOM,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    CONF_FORCE_ARM_NOTIFICATIONS,
    CONF_AUTO_FORCE_ARM,
    *PANEL_OPTION_KEYS,
    CONF_ENABLE_ACTIVITY_POLLING,
    CONF_LOCK_AUTOMATIONS,
    CONF_OPERATION_POLL_TIMEOUT,
)


def _options_are_authoritative(entry: ConfigEntry) -> bool:
    """Return True once entry.options is the source of truth for its fields.

    Until the options flow runs, it isn't. ``_create_entry_for_installation``
    seeds entry.options with ``PANEL_OPTION_KEYS`` (the sub-panel toggles)
    alone, leaving the PIN, mappings, scan interval and everything else in
    entry.data — so "has the options flow run?" is not the same question as
    "is entry.options non-empty?", and answering it with the latter is what
    let ``_synced_entry_data`` delete nine managed keys from a fresh install.

    Seed and test share one constant, and the seed is driven by it
    (``async_step_options`` moves exactly ``PANEL_OPTION_KEYS`` into options),
    so the two can't drift apart.
    """
    return not set(entry.options).issubset(PANEL_OPTION_KEYS)


def _synced_entry_data(entry: ConfigEntry) -> dict[str, Any] | None:
    """Return entry.data with options-managed fields aligned to entry.options.

    Returns ``None`` when no change is needed, or while entry.options is not
    yet authoritative (see ``_options_are_authoritative``) — on a fresh
    install the config-flow values live in entry.data and are the source of
    truth until the options flow runs at least once.

    Otherwise drops options-managed keys from entry.data and re-applies them
    from entry.options, so a key the user cleared in options doesn't keep its
    previous value in data — which `_opt()` (and the options form's
    `_suggested_map` fallback) would otherwise resurrect. That replace step
    relies on clearing being recorded *explicitly*: see
    ``_normalize_mapping_input``, which turns a cleared mapping into ``""``
    precisely so its absence can't be mistaken for "never written".
    """
    if not _options_are_authoritative(entry):
        return None
    new_data = {k: v for k, v in entry.data.items() if k not in _OPTIONS_MANAGED_FIELDS}
    new_data.update(entry.options)
    if dict(entry.data) == new_data:
        return None
    return new_data


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    new_data = _synced_entry_data(entry)
    if new_data is None:
        return
    hass.config_entries.async_update_entry(entry, data=new_data)
    await hass.config_entries.async_reload(entry.entry_id)


def _hash_legacy_plaintext_code(
    mapping: dict[str, Any], seen: dict[str, tuple[str | None, bool]]
) -> None:
    """Replace a legacy plain-text CONF_CODE in *mapping* with its hash.

    Mutates *mapping* in place: drops the raw PIN and writes CONF_CODE_HASH +
    CONF_CODE_IS_NUMERIC (isdigit()-ness is captured before the value is
    discarded — it can't be recovered from the hash later).

    Presence is preserved, not just the value: an *empty* CONF_CODE means the
    user removed the PIN, and in entry.options that emptiness has to keep
    shadowing a stale entry.data PIN (``_opt`` reads options first, then
    data). So an empty PIN writes CONF_CODE_HASH=None rather than leaving the
    key unset, which would stop shadowing and resurrect the old PIN. A
    mapping with no CONF_CODE at all is left untouched.

    *seen* memoises encodings across the data and options mappings, which
    usually hold the *same* PIN. Hashing is salted, so encoding each one
    separately would leave them holding different strings for one PIN —
    making ``_synced_entry_data`` see a diff that isn't there and costing
    every upgrading user a spurious entry reload. Genuinely different PINs
    still get their own encoding.
    """
    if CONF_CODE not in mapping:
        return
    raw = mapping.pop(CONF_CODE)
    # Storage is JSON, so a hand-edited entry can hand us an int, a list, or
    # null. Coerce rather than trust: an int would die in hash_pin's
    # .encode(), and a list isn't even hashable as a memo key — both raise
    # out of async_migrate_entry, which fails the whole entry and stops the
    # integration loading. An unusable PIN the user can clear in the options
    # dialog is a much better outcome, and coercing keeps the realistic case
    # (a JSON number that was meant as a PIN) working exactly as intended.
    plain_code = "" if raw is None else str(raw)
    if plain_code not in seen:
        seen[plain_code] = encode_pin(plain_code)
    mapping[CONF_CODE_HASH], mapping[CONF_CODE_IS_NUMERIC] = seen[plain_code]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Reject pre-v3 entries; bump v3 → v4 → v5 (hash the plain-text PIN)."""
    if config_entry.version < 3:
        _LOGGER.error(
            "Config entry %s uses format v%s which is no longer supported. "
            "Please remove this integration entry and re-add it.",
            config_entry.entry_id,
            config_entry.version,
        )
        _notify(hass, "migration_required", "migration_required")
        return False

    if config_entry.version == 3:
        new_data = dict(config_entry.data)
        new_data.pop(CONF_TOKEN, None)
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=4)

    if config_entry.version == 4:
        # Both entry.data (fresh installs, or pre-options-flow entries) and
        # entry.options (once the options flow has run at least once — see
        # _OPTIONS_MANAGED_FIELDS) may carry a plain-text CONF_CODE.
        new_data = dict(config_entry.data)
        new_options = dict(config_entry.options)
        seen: dict[str, tuple[str | None, bool]] = {}
        _hash_legacy_plaintext_code(new_data, seen)
        _hash_legacy_plaintext_code(new_options, seen)
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, options=new_options, version=5
        )

    return True


def _build_config_dict(entry: ConfigEntry) -> tuple[dict[str, Any], bool]:
    """Build config dict from entry.data + entry.options.

    Returns the config dict and a flag indicating whether sign-in is needed
    (True if any device ID fields are missing from entry.data).
    """

    def _opt(key: str, default: Any = None) -> Any:
        """Read from options first, then data, then default."""
        return entry.options.get(key, entry.data.get(key, default))

    config = OrderedDict()
    config[CONF_USERNAME] = entry.data[CONF_USERNAME]
    config[CONF_PASSWORD] = entry.data.get(CONF_PASSWORD, "")
    config[CONF_REFRESH_TOKEN] = entry.data.get(CONF_REFRESH_TOKEN, "")
    config[CONF_COUNTRY] = entry.data.get(CONF_COUNTRY, None)
    config[CONF_CODE_HASH] = _opt(CONF_CODE_HASH, None)
    config[CONF_CODE_IS_NUMERIC] = _opt(CONF_CODE_IS_NUMERIC, False)
    config[CONF_CODE_ARM_REQUIRED] = _opt(
        CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
    )
    config[CONF_LOCK_CODE_REQUIRED] = _opt(
        CONF_LOCK_CODE_REQUIRED, DEFAULT_LOCK_CODE_REQUIRED
    )
    config[CONF_SCAN_INTERVAL] = _opt(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    config[CONF_DELAY_CHECK_OPERATION] = _opt(
        CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
    )
    config[CONF_OPERATION_POLL_TIMEOUT] = _opt(
        CONF_OPERATION_POLL_TIMEOUT, DEFAULT_OPERATION_POLL_TIMEOUT
    )
    config[CONF_ENTRY_ID] = entry.entry_id
    config[CONF_NOTIFY_GROUP] = _opt(CONF_NOTIFY_GROUP, "")
    config[CONF_FORCE_ARM_NOTIFICATIONS] = _opt(
        CONF_FORCE_ARM_NOTIFICATIONS, DEFAULT_FORCE_ARM_NOTIFICATIONS
    )
    config[CONF_AUTO_FORCE_ARM] = _opt(CONF_AUTO_FORCE_ARM, DEFAULT_AUTO_FORCE_ARM)
    config[CONF_ENABLE_ACTIVITY_POLLING] = _opt(
        CONF_ENABLE_ACTIVITY_POLLING, DEFAULT_ENABLE_ACTIVITY_POLLING
    )
    config = add_device_information(config)

    # Read mapping config (options override data)
    config[CONF_MAP_HOME] = _opt(CONF_MAP_HOME)
    config[CONF_MAP_AWAY] = _opt(CONF_MAP_AWAY)
    config[CONF_MAP_NIGHT] = _opt(CONF_MAP_NIGHT)
    config[CONF_MAP_CUSTOM] = _opt(CONF_MAP_CUSTOM)
    config[CONF_MAP_VACATION] = _opt(CONF_MAP_VACATION)
    # Runtime-learned unsupported commands (data-only — not user-editable).
    # Persisted shape is ``{<installation.number>: [<commands>...]}``; the
    # legacy v5.0.1-pre flat-list ``[<commands>...]`` is preserved verbatim
    # so ``BaseVerisureOwaAlarmPanel._read_unsupported_for_installation``
    # can migrate it on the next persist. Deep-copy lists/dicts so later
    # in-place mutations don't leak back into ``entry.data``.
    _raw_unsupported = entry.data.get(CONF_UNSUPPORTED_COMMANDS, {})
    if isinstance(_raw_unsupported, dict):
        config[CONF_UNSUPPORTED_COMMANDS] = {
            k: list(v) for k, v in _raw_unsupported.items()
        }
    elif isinstance(_raw_unsupported, list):
        config[CONF_UNSUPPORTED_COMMANDS] = list(_raw_unsupported)
    else:
        config[CONF_UNSUPPORTED_COMMANDS] = {}

    need_sign_in = False
    if CONF_DEVICE_ID in entry.data:
        config[CONF_DEVICE_ID] = entry.data[CONF_DEVICE_ID]
    else:
        need_sign_in = True
    if CONF_UNIQUE_ID in entry.data:
        config[CONF_UNIQUE_ID] = entry.data[CONF_UNIQUE_ID]
    else:
        need_sign_in = True
    if CONF_DEVICE_INDIGITALL in entry.data:
        config[CONF_DEVICE_INDIGITALL] = entry.data[CONF_DEVICE_INDIGITALL]
    else:
        need_sign_in = True

    return config, need_sign_in


# Consecutive setup attempts whose stored refresh token crashed xSRefreshLogin
# before setup gives up retrying and asks for re-authentication (#568). At
# setup the token comes straight off disk with no evidence it was ever valid,
# and every diagnosed crash was a dead token; one retry (HA's first backoff,
# a few seconds) absorbs a momentary server blip. The count lives in hass.data because
# each retry builds a fresh hub, and is keyed by username like ``sessions``:
# co-tenant entries retry the same token and alternate as session creator.
# Only handing back a live client resets it — other transient failures in
# between neither count nor reset.
_SETUP_REFRESH_CRASH_REAUTH_THRESHOLD = 2


def _note_setup_refresh_crash(hass: HomeAssistant, username: str) -> int:
    """Bump and return the account's consecutive setup-time crash count."""
    streaks = hass.data[DOMAIN].setdefault("refresh_crash_streaks", {})
    streaks[username] = streaks.get(username, 0) + 1
    return streaks[username]


def _clear_setup_refresh_crash(hass: HomeAssistant, username: str) -> None:
    """Forget the account's setup-time crash count: a live session proved the token."""
    hass.data[DOMAIN].get("refresh_crash_streaks", {}).pop(username, None)


async def _login_or_raise(
    hass: HomeAssistant,
    client: VerisureHub,
    username: str,
    *,
    retry_other_family: bool = False,
) -> None:
    """Log the hub in, mapping failures to HA's setup exceptions.

    A streak of refresh-login crashes (see _SETUP_REFRESH_CRASH_REAUTH_THRESHOLD)
    becomes ConfigEntryAuthFailed like a credential rejection; HA's own reauth
    card is the user-facing notice for that path, so unlike the credential
    branches it raises no persistent notification of its own.

    ``retry_other_family`` marks a first attempt the caller will repeat on
    another address family. A failure to establish the connection is then
    re-raised as-is rather than mapped, so the attempt about to be retried does
    not notify the user, log an error or count towards the crash streak. Every
    other failure — including a timeout waiting for a reply — takes the mapping
    path, as it does for every other caller.
    """
    try:
        await client.login()
    except TwoFactorRequiredError:
        _notify(hass, "2fa_error", "two_factor_required")
        raise
    except AuthenticationError as err:
        _notify(hass, "login_error", "login_failed", {"error": str(err)})
        _LOGGER.error(
            "Could not log in to Verisure: %s",
            err.log_detail(),
        )
        raise
    except VerisureOwaError as err:
        # On the first of two family attempts (retry_other_family), re-raise a
        # connection that never opened untouched: the caller is about to repeat
        # it on another address family, so it must not notify, log, or count
        # towards the refresh-crash streak. Every other error — timeouts waiting
        # for a reply included — takes the mapping path below. (The isinstance
        # guard narrows err for pyright; pylint doesn't narrow across `and`, so
        # its no-member on the guarded attribute is a false positive.)
        if (
            retry_other_family
            and isinstance(err, APIConnectionError)
            and err.connection_never_established  # pylint: disable=no-member
        ):
            raise
        # Log the full detail — the SensitiveDataFilter scrubs known
        # secrets — but never embed the raw response body in the
        # user-facing ConfigEntryNotReady text, which doesn't go
        # through the filter.
        _LOGGER.error(
            "Unable to connect to Verisure: %s",
            err.log_detail(),
        )
        if (
            is_refresh_login_crash(err)
            and _note_setup_refresh_crash(hass, username)
            >= _SETUP_REFRESH_CRASH_REAUTH_THRESHOLD
        ):
            raise ConfigEntryAuthFailed(
                "Stored refresh token keeps crashing the Verisure "
                "refresh-login call; re-authentication required"
            ) from None
        raise ConfigEntryNotReady(
            f"Unable to connect to Verisure: {err.message}"
        ) from None


_IPV4_FALLBACK_LOG = (
    "Could not reach Verisure over IPv4 (%s); retrying with the default lookup, "
    "which also asks for IPv6"
)


async def _login_ipv4_then_any(
    initial: VerisureHub,
    login: Callable[[VerisureHub, bool], Awaitable[None]],
    rebuild: Callable[[], VerisureHub] | None,
) -> VerisureHub:
    """Log ``initial`` in over IPv4, falling back to the default IPv4+IPv6 lookup.

    Verisure's customer endpoint publishes no IPv6 address in any country this
    integration supports, so the IPv6 half of the combined lookup aiohttp issues
    by default can only ever come back empty here. On some networks that empty
    answer fails the whole lookup instead of falling back to the IPv4 address
    that resolved fine, and the alarm sits at unavailable (issue #606). Asking
    for IPv4 only skips a question with no useful answer.

    The fallback covers the opposite network: a host with no IPv4 route of its
    own, which reaches IPv4-only servers through NAT64/DNS64 and so needs the
    IPv6 address its resolver synthesises. ``rebuild`` makes the fallback hub on
    ``AF_UNSPEC``; it is None when the caller must not swap its hub out — a
    shared hub that entries or other setup dialogs hold — and the connection
    error then propagates unchanged.

    Only a connection that never opened is retried: a rejected password must fail
    once and reach the user, and a slow reply must not become a second sign-in
    that could end the session. ``login`` is told which attempt it is (True for
    the first) so a caller that maps errors can leave the first attempt's
    connection error untouched for the check below to read.
    """
    try:
        await login(initial, True)
        return initial
    except APIConnectionError as err:
        # Re-checked here, never merely trusted from ``login`` (which may be
        # tightened independently): only a connection that never opened may be
        # retried, and only when the caller owns the hub we are about to swap.
        if not err.connection_never_established or rebuild is None:
            raise
        _LOGGER.info(_IPV4_FALLBACK_LOG, err)
        hub = rebuild()
        await login(hub, False)
        return hub


async def _login_ipv4_first(
    hass: HomeAssistant, config: dict[str, Any], entry: ConfigEntry, username: str
) -> VerisureHub:
    """Log a fresh setup hub in over IPv4, falling back to both families.

    See ``_login_ipv4_then_any`` for the why. Each hub is built on Home
    Assistant's per-family client, which HA caches and closes at shutdown, so
    setup never releases it.
    """

    def build(family: socket.AddressFamily) -> VerisureHub:
        return VerisureHub(
            config, entry, async_get_clientsession(hass, family=family), hass
        )

    async def login(hub: VerisureHub, first: bool) -> None:
        # retry_other_family leaves the first attempt's never-established
        # connection error unmapped, so _login_ipv4_then_any can read the flag.
        await _login_or_raise(hass, hub, username, retry_other_family=first)

    return await _login_ipv4_then_any(
        build(socket.AF_INET), login, lambda: build(socket.AF_UNSPEC)
    )


def _new_session_record(hub: VerisureHub) -> dict[str, Any]:
    """Build a shared-session record; its creator adds itself as a holder next.

    ``holders`` names everyone using the hub: config entry ids, plus a key per
    open config flow that signed in with or borrowed it. The record is dropped
    once nobody holds it.
    """
    return {"hub": hub, "holders": set()}


def _take_session_hold(session: dict[str, Any], holder: str) -> None:
    """Record ``holder`` (an entry id or a flow's key) as using the session.

    A hold counts once per holder, however many times it is taken: Home
    Assistant retries a setup that raised ConfigEntryNotReady without unloading
    first, so the same entry reaches ``_get_or_create_session`` again and must
    not take a second hold.
    """
    session["holders"].add(holder)


def _drop_session_hold(session: dict[str, Any], holder: str) -> None:
    """Forget ``holder``'s hold; one that held nothing leaves the others alone."""
    session["holders"].discard(holder)


def _release_session_hold(
    sessions: dict[str, Any], username: str, session: dict[str, Any], holder: str
) -> bool:
    """Drop ``holder``'s hold and unregister the session once nobody holds it.

    Returns True when nobody holds it any more. It is removed from ``sessions``
    only while it is still the record registered there, so a holder of a record
    that has since been replaced never removes its replacement.
    """
    _drop_session_hold(session, holder)
    if session["holders"]:
        return False
    if sessions.get(username) is session:
        sessions.pop(username)
    return True


def _attach_token_persistence(hub: VerisureHub, entry: ConfigEntry) -> None:
    """Save the hub's rotated refresh tokens to ``entry``, starting now.

    The current token is written at once, since it may have rotated past the
    one ``entry`` stored. A condemned token is not written: it would replace
    the entry's own token, which may be a fresh one from reauth that setup
    still has to try.
    """
    hub.config_entry = entry
    if not hub.refresh_token_is_dead:
        hub.persist_current_refresh_token()


async def _get_or_create_session(
    hass: HomeAssistant, config: dict[str, Any], entry: ConfigEntry
) -> VerisureHub:
    """Get or create the shared VerisureHub and record this entry as a holder.

    Multiple config entries for the same username share a single
    VerisureHub / VerisureOwaClient session to avoid duplicate logins
    and WAF rate-limit blocks.  A per-username lock prevents concurrent
    async_setup_entry calls from creating duplicate hubs.
    """
    username = config[CONF_USERNAME]
    sessions = hass.data[DOMAIN].setdefault("sessions", {})
    setup_locks = hass.data[DOMAIN].setdefault("setup_locks", {})
    if username not in setup_locks:
        setup_locks[username] = asyncio.Lock()

    async with setup_locks[username]:
        if username in sessions:
            session = sessions[username]
            # Hold it before anything below awaits: a config flow closing in
            # the meantime would otherwise unregister it as held by nobody.
            _take_session_hold(session, entry.entry_id)
            client: VerisureHub = session["hub"]
            # The config-flow hub is built before the ConfigEntry exists, so it
            # starts detached (config_entry=None) and is registered in
            # ``sessions`` by the flow. When HA then sets up the freshly-created
            # entry we land here and must attach it, otherwise rotated refresh
            # tokens can never be persisted (issue #557): _persist_refresh_token
            # reports ``no-config-entry`` and the stale on-disk token triggers
            # the xSRefreshLogin 'fr' crash on the next restart.
            if client.config_entry is None:
                _attach_token_persistence(client, entry)
            # A shared client condemned by a crash streak, reached with a token
            # that is not the one it condemned: the reauth flow wrote a fresh
            # token into this entry and reloaded it, but the co-tenant kept
            # the session alive, so the reload lands here instead of on a
            # fresh hub. Try the new token on the shared client.
            stored_token = config.get(CONF_REFRESH_TOKEN)
            if (
                client.refresh_token_is_dead
                and stored_token
                and stored_token != client.get_refresh_token()
            ):
                client.adopt_refresh_token(stored_token)
                await _login_or_raise(hass, client, username)
        else:
            client = await _login_ipv4_first(hass, config, entry, username)
            sessions[username] = _new_session_record(client)
            _take_session_hold(sessions[username], entry.entry_id)

    # Either branch hands back a live session, which proves the stored token.
    _clear_setup_refresh_crash(hass, username)
    return client


def _get_or_create_api_queue(
    hass: HomeAssistant,
    session: VerisureHub,
    config: dict[str, Any],
    entry: ConfigEntry,
) -> None:
    """Create or reuse an ApiQueue for the session's API domain.

    WAF rate-limits by IP per domain, so entries sharing a domain share a queue.
    Sets session.api_queue as a side effect.
    """
    domain_url = ApiDomains().get_url(config[CONF_COUNTRY])
    api_queues = hass.data[DOMAIN].setdefault("api_queues", {})
    if domain_url not in api_queues:
        api_queues[domain_url] = ApiQueue(
            interval=config[CONF_DELAY_CHECK_OPERATION],
        )
        _LOGGER.debug(
            "[setup] Created ApiQueue %s for domain %s (country=%s, entry=%s)",
            id(api_queues[domain_url]),
            domain_url,
            config[CONF_COUNTRY],
            entry.entry_id,
        )
    else:
        _LOGGER.info(
            "Reusing ApiQueue %s for domain %s (country=%s, entry=%s)",
            id(api_queues[domain_url]),
            domain_url,
            config[CONF_COUNTRY],
            entry.entry_id,
        )
    session.api_queue = api_queues[domain_url]


async def _fetch_and_cache_installations(
    hass: HomeAssistant,
    hub: VerisureHub,
    entry: ConfigEntry,
) -> list[VerisureDevice]:
    """Fetch installations and services, populating caches.

    Uses cached data from the config flow when available, otherwise
    fetches from the API (e.g. on HA restart).

    Returns a list of VerisureDevice wrappers for this entry's
    installations.
    """
    # Cache keyed by username so that entries for different accounts (e.g.
    # Italian and Spanish installations on separate Verisure accounts) do not
    # accidentally share each other's installation list.
    username = entry.data.get(CONF_USERNAME, entry.entry_id)
    install_cache_key = f"installations_cache_{username}"
    install_cache = hass.data[DOMAIN].get(install_cache_key)
    if (
        install_cache is not None
        and time.monotonic() - install_cache["time"] < API_CACHE_TTL
    ):
        all_installations: list[Installation] = install_cache["data"]
    else:
        all_installations = await hub.api_queue.submit(
            hub.client.list_installations,
            priority=ApiQueue.FOREGROUND,
        )
        hass.data[DOMAIN][install_cache_key] = {
            "data": all_installations,
            "time": time.monotonic(),
        }
    target_number = entry.data.get(CONF_INSTALLATION)
    if target_number:
        entry_installations = [
            inst for inst in all_installations if inst.number == target_number
        ]
    else:
        # Legacy entries without CONF_INSTALLATION get all
        entry_installations = all_installations

    # Use cached services from config flow if available and fresh,
    # otherwise fetch from API (e.g. on HA restart).
    svc_cache = hass.data[DOMAIN].get("cached_services")
    cached_services = (
        svc_cache["data"]
        if svc_cache is not None
        and time.monotonic() - svc_cache["time"] < API_CACHE_TTL
        else None
    )

    devices: list[VerisureDevice] = []
    for installation in entry_installations:
        if cached_services and installation.number in cached_services:
            # Pre-populate from config flow cache
            hub.services_cache[installation.number] = cached_services[
                installation.number
            ]
        elif installation.number not in hub.services_cache:
            # HA restart: fetch directly (bypass queue — we just logged
            # in, no WAF risk yet) so platforms don't block on queue.
            hub.services_cache[installation.number] = await hub.client.get_services(
                installation
            )
        devices.append(VerisureDevice(installation))
    return devices


ALIAS_DOMAIN = "verisure_owa"


def _entity_target(domain: str) -> dict[str, Any]:
    """Build a service ``target`` scoped to this integration's entities.

    Both the ``entity`` filter list *and* its inner ``domain`` must be lists.
    ``async_set_service_schema`` copies ``target`` through unchanged — unlike
    ``services.yaml``, which HA normalises with ``cv.ensure_list`` at every
    level (``helpers/selector.py``). Two failures follow from a bare mapping:

    * A bare ``entity`` mapping is iterated to its string keys by HA's
      automation-editor lookup, raising ``AttributeError`` and aborting the
      shared cross-integration lookup — breaking the action/target picker for
      *every* integration.
    * A bare ``domain`` string reaches ``_AutomationComponentLookupData.create``
      unnormalised, where ``set(config.get("domain", []))`` turns
      ``"alarm_control_panel"`` into a set of single characters, so the filter
      then matches no entity and these services are never offered for their own
      entities.

    Constructing both shapes here once keeps both bugs unrepresentable at the
    call sites (guarded by
    ``tests/test_init.py::TestServiceDescriptionTargets``).
    """
    return {"entity": [{"integration": DOMAIN, "domain": [domain]}]}


# Tuples of (service_name, supports_response, schema_for_async_set_service_schema).
# Every service the integration registers under `DOMAIN` (= "securitas") via
# platform.async_register_entity_service is also exposed under `verisure_owa.<X>`
# below — both are equal first-class names in HA's eyes. Docs/services.yaml
# steer users toward the verisure_owa.* form so a future domain rename costs
# them less (see docs/FUTURE_MIGRATION_PLAN.md).
_ALIASED_SERVICES: tuple[tuple[str, SupportsResponse, dict[str, Any]], ...] = (
    (
        "force_arm",
        SupportsResponse.NONE,
        {
            "name": "Force arm",
            "description": (
                "Force-arm the alarm, overriding non-blocking exceptions (e.g. "
                "open windows) from a previous failed arm attempt."
            ),
            "fields": {
                "code": {
                    "name": "PIN code",
                    "description": (
                        "Optional. If supplied, validated against the configured "
                        "PIN before completing the force-arm. Most callers don't "
                        "need this — the prior arm attempt that produced the "
                        "force-arm context already validated the PIN."
                    ),
                    "example": "1234",
                    "selector": {"text": {"type": "password"}},
                },
            },
            "target": _entity_target("alarm_control_panel"),
        },
    ),
    (
        "force_arm_cancel",
        SupportsResponse.NONE,
        {
            "name": "Cancel force arm",
            "description": (
                "Cancel a pending force-arm and dismiss the arming-exception "
                "notification."
            ),
            "fields": {},
            "target": _entity_target("alarm_control_panel"),
        },
    ),
    (
        "suppress_arm_exception_prompt",
        SupportsResponse.NONE,
        {
            "name": "Suppress arm-exception prompt",
            "description": (
                "Suppress the next 'force-arm required' prompt for this panel "
                "and send a 'force-armed' confirmation instead. Fired by the "
                "alarm card's auto-force-arm option just before it arms; not "
                "intended for manual use."
            ),
            "fields": {},
            "target": _entity_target("alarm_control_panel"),
        },
    ),
)


def _register_verisure_owa_entity_service(
    hass: HomeAssistant,
    service_name: str,
    component_domain: str,
    method_name: str,
    *,
    schema: dict | None = None,
    voluptuous_schema: vol.Schema | None = None,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> None:
    """Register an entity service directly under ``verisure_owa.<service_name>``.

    EntityPlatform.async_register_entity_service is bound to the platform's
    DOMAIN (= "securitas"), so it can only create securitas.<X> services.
    For v5+ services that have no backwards-compat reason to also exist as
    securitas.<X>, we register a regular hass service under verisure_owa
    whose handler does the entity-id-to-entity dispatch itself (the same
    job platform.async_register_entity_service does internally).

    ``component_domain`` is the entity-platform domain ("alarm_control_panel",
    "camera", "sensor") whose EntityComponent owns the target entities.
    """
    if hass.services.has_service(ALIAS_DOMAIN, service_name):
        return

    async def _handler(call: ServiceCall):
        component: EntityComponent | None = hass.data.get(component_domain)
        if component is None:
            raise HomeAssistantError(
                f"Platform '{component_domain}' is not loaded; cannot "
                f"dispatch verisure_owa.{service_name}"
            )
        entity_ids = await _async_extract_service_entity_ids(call)
        method_kwargs = {k: v for k, v in call.data.items() if k != "entity_id"}
        responses: dict[str, Any] = {}
        for eid in entity_ids:
            entity = component.get_entity(eid)
            if entity is None:
                continue
            method = getattr(entity, method_name, None)
            if method is None:
                continue
            entity.async_set_context(call.context)
            result = await method(**method_kwargs)
            if supports_response == SupportsResponse.ONLY:
                responses[eid] = result
        return responses if supports_response == SupportsResponse.ONLY else None

    hass.services.async_register(
        ALIAS_DOMAIN,
        service_name,
        _handler,
        schema=voluptuous_schema,
        supports_response=supports_response,
    )
    if schema is not None:
        async_set_service_schema(hass, ALIAS_DOMAIN, service_name, schema)


def register_v5_entity_services(hass: HomeAssistant) -> None:
    """Register v5+ entity services under verisure_owa.* only.

    These services never had a securitas.* form in any released version,
    so no backwards-compat alias is needed.  Idempotent — safe to call
    on every config-entry setup.
    """
    for spec in _V5_ENTITY_SERVICES:
        _register_verisure_owa_entity_service(hass, **spec)


# Declarative specs for register_v5_entity_services.  Each entry is
# kwargs for _register_verisure_owa_entity_service; refresh_alarm,
# capture_image and refresh_activity_log share the default
# voluptuous_schema=None / supports_response=NONE so only the
# fetch_activity_image entry overrides them.
_V5_ENTITY_SERVICES: tuple[dict[str, Any], ...] = (
    {
        "service_name": "refresh_alarm",
        "component_domain": "alarm_control_panel",
        "method_name": "async_manual_refresh",
        "schema": {
            "name": "Refresh alarm",
            "description": (
                "Full alarm-status round-trip refresh — supersedes the "
                "deprecated VerisureRefreshButton entity."
            ),
            "fields": {},
            "target": _entity_target("alarm_control_panel"),
        },
    },
    {
        "service_name": "capture_image",
        "component_domain": "camera",
        "method_name": "async_manual_capture",
        "schema": {
            "name": "Capture image",
            "description": (
                "Request a fresh image capture from a Verisure camera — "
                "supersedes the deprecated VerisureCaptureButton entity."
            ),
            "fields": {},
            "target": _entity_target("camera"),
        },
    },
    {
        "service_name": "refresh_activity_log",
        "component_domain": "sensor",
        "method_name": "async_manual_refresh",
        "schema": {
            "name": "Refresh activity log",
            "description": (
                "Foreground-refresh the activity timeline for an installation."
            ),
            "fields": {},
            "target": _entity_target("sensor"),
        },
    },
    {
        "service_name": "fetch_activity_image",
        "component_domain": "sensor",
        "method_name": "async_fetch_image",
        "voluptuous_schema": vol.Schema(
            {
                vol.Required("id_signal"): str,
                vol.Required("signal_type"): vol.All(vol.Coerce(str)),
            },
            extra=vol.ALLOW_EXTRA,
        ),
        "supports_response": SupportsResponse.ONLY,
        "schema": {
            "name": "Fetch activity image",
            "description": (
                "On-demand historical image fetch for image-request events. "
                "Returns base64-encoded image bytes plus a mime_type field so "
                "the Lovelace card can render the image inline."
            ),
            "fields": {
                "id_signal": {
                    "name": "Signal ID",
                    "description": "The id_signal of the activity event.",
                    "required": True,
                    "selector": {"text": {}},
                },
                "signal_type": {
                    "name": "Signal type",
                    "description": "The signal_type of the activity event.",
                    "required": True,
                    "selector": {"text": {}},
                },
            },
            "target": _entity_target("sensor"),
        },
    },
)


def register_service_aliases(hass: HomeAssistant) -> None:
    """Register every service under both ``securitas.*`` and ``verisure_owa.*``.

    The ``securitas.*`` form is what platform.async_register_entity_service
    creates automatically (manifest domain). This function also registers
    each service under ``verisure_owa.*`` with a handler that forwards to
    the ``securitas.*`` implementation. ``async_set_service_schema`` attaches
    a rich UI description so the verisure_owa form shows up in the picker
    with full field validation, identical to the securitas form.

    The two are functionally equal in HA's eyes; docs/services.yaml steer
    users toward the ``verisure_owa.*`` form so the deferred completion of
    the domain rename (see docs/FUTURE_MIGRATION_PLAN.md) is a low-cost change
    for their automations.
    """
    if hass.services.has_service(ALIAS_DOMAIN, _ALIASED_SERVICES[0][0]):
        return  # already registered

    for service_name, supports_response, schema in _ALIASED_SERVICES:

        async def _alias_handler(
            call: ServiceCall,
            _name: str = service_name,
            _supports_response: SupportsResponse = supports_response,
        ) -> dict[str, Any] | None:
            return await hass.services.async_call(
                DOMAIN,
                _name,
                dict(call.data),
                blocking=True,
                context=call.context,
                return_response=_supports_response == SupportsResponse.ONLY,
            )

        hass.services.async_register(
            ALIAS_DOMAIN,
            service_name,
            _alias_handler,
            supports_response=supports_response,
        )
        async_set_service_schema(hass, ALIAS_DOMAIN, service_name, schema)


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:  # pylint: disable=unused-argument
    """Integration-wide setup, called once regardless of config entries.

    Surfaces a Repairs issue if an orphaned ``custom_components/verisure_owa/``
    directory is left on disk from a failed v5.0.1 upgrade — the v5.0.1 shim
    installed under ``custom_components/securitas/`` depended on a
    ``verisure_owa`` integration directory that HACS never deployed
    (one-directory-per-repo limit). After upgrading to v5.0.2 the stale
    ``verisure_owa/`` folder no longer does anything; the Repair tells the
    user to delete it manually.
    """
    orphan = Path(hass.config.path("custom_components", "verisure_owa"))
    if orphan.is_dir():
        from homeassistant.helpers import issue_registry as ir

        ir.async_create_issue(
            hass,
            DOMAIN,
            "orphan_verisure_owa_directory",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="orphan_verisure_owa_directory",
            translation_placeholders={"path": str(orphan)},
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Establish connection with Verisure."""
    # One-shot per-entry: rewrite any pre-v5 entity unique_ids to the
    # canonical v4_securitas_direct.<...> form so HACS upgraders don't
    # get duplicated entities with _2 suffixes. Idempotent; safe to run
    # on every setup.
    await migrate_unique_ids(hass, entry)

    config, need_sign_in = _build_config_dict(entry)

    # Register card static path + Lovelace resource early so the card
    # is available even when login fails (ConfigEntryNotReady).
    if hass.http and not hass.data.get(DOMAIN, {}).get("card_registered"):
        panel_dir = str(Path(__file__).parent / "www")
        await hass.http.async_register_static_paths(
            [
                # cache_headers=True gives the (large) card bundles a long
                # max-age so the browser / companion app serves them from cache
                # instead of re-downloading on every cold dashboard open — which
                # made the alarm chip render 5-10s late on a slow network.
                #
                # Safe on THIS path because every URL the integration emits here
                # is cache-busted:
                #  - registered entry points via _card_url's ?v=<hash>-<version>
                #    (content-hash — busts whenever the file changes), and
                #  - their bare cross-module imports (shared.js, card-utils.js)
                #    carry a ?v=<version> query stamped into the import specifiers
                #    (enforced by card-cache-busting.test.js).
                # The shared modules are version- (not hash-) busted, which is
                # sufficient because users only receive new files via a HACS
                # update, which by definition bumps the manifest version, and the
                # test forces the stamps to track that version — so every
                # delivered change yields new URLs and nothing is served stale.
                StaticPathConfig(
                    "/verisure-owa-panel",
                    panel_dir,
                    cache_headers=True,
                ),
                # Legacy path kept indefinitely so anyone who hardcoded a
                # /securitas_panel/... URL into a Markdown card, picture-glance,
                # or external link before v5 doesn't break. cache_headers=False
                # here (revalidation): these are user-hardcoded URLs WITHOUT a
                # ?v= bust token, so a long max-age would pin them stale for ~31
                # days after an update. Revalidation keeps them fresh. The
                # bytes we actually want hard-cached are served via
                # /verisure-owa-panel above.
                StaticPathConfig(
                    "/securitas_panel",
                    panel_dir,
                    cache_headers=False,
                ),
            ]
        )
        # Register the lightweight chip/badge module FIRST so the always-visible
        # alarm chip renders ASAP on cold load. Resource order matters in the
        # add_extra_js_url fallback: the URLs inject as ordered
        # <script type="module"> tags that execute in document order, so the
        # heavy alarm card must not precede the chip.
        await _register_card_resource(
            hass, CHIP_CARD_BASE_URL, CHIP_CARD_URL, "chip_card_resource_id"
        )
        await _register_card_resource(hass, CARD_BASE_URL, CARD_URL, "card_resource_id")
        await _register_card_resource(
            hass, CAMERA_CARD_BASE_URL, CAMERA_CARD_URL, "camera_card_resource_id"
        )
        await _register_card_resource(
            hass,
            ACTIVITY_LOG_CARD_BASE_URL,
            ACTIVITY_LOG_CARD_URL,
            "activity_log_card_resource_id",
        )
        await _register_card_resource(
            hass, MORE_INFO_BASE_URL, MORE_INFO_MODULE_URL, "more_info_resource_id"
        )
        hass.data.setdefault(DOMAIN, {})["card_registered"] = True

    # Register verisure_owa.* service aliases alongside the securitas.* primary
    # registrations. Both forms are functionally equal; docs steer users toward
    # the verisure_owa form for forward compatibility with the deferred domain
    # rename (see docs/FUTURE_MIGRATION_PLAN.md).
    register_service_aliases(hass)
    # v5+ entity services that only ever existed under verisure_owa.*
    # (refresh_alarm, capture_image, refresh_activity_log, fetch_activity_image).
    # Registered manually because platform.async_register_entity_service is
    # bound to the integration's DOMAIN (securitas).
    register_v5_entity_services(hass)

    hass.data.setdefault(DOMAIN, {})

    # Set up log filters — must be on handlers, not the logger, because
    # logger-level filters don't apply to child logger records.
    if "log_filter" not in hass.data[DOMAIN]:
        log_filter = SensitiveDataFilter()
        transient_filter = TransientCoordinatorErrorFilter()
        for handler in logging.getLogger().handlers:
            handler.addFilter(log_filter)
            handler.addFilter(transient_filter)
        hass.data[DOMAIN]["log_filter"] = log_filter
        hass.data[DOMAIN]["transient_log_filter"] = transient_filter
    else:
        log_filter = hass.data[DOMAIN]["log_filter"]

    log_filter.update_secret("username", config[CONF_USERNAME])
    if config.get(CONF_PASSWORD):
        log_filter.update_secret("password", config[CONF_PASSWORD])

    hass.data[DOMAIN][CONF_ENTRY_ID] = entry.entry_id
    if not need_sign_in:
        try:
            client = await _get_or_create_session(hass, config, entry)
        except TwoFactorRequiredError as err:
            raise ConfigEntryAuthFailed("2FA required — please reauthenticate") from err
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

        _get_or_create_api_queue(hass, client, config, entry)

        entry.async_on_unload(entry.add_update_listener(async_update_options))

        try:
            devices = await _fetch_and_cache_installations(hass, client, entry)
        except VerisureOwaError as err:
            _LOGGER.error("Unable to connect to Verisure: %s", err.log_detail())
            raise ConfigEntryNotReady("Unable to connect to Verisure") from None

        # ── Create coordinators ──────────────────────────────────────
        scan_interval = timedelta(seconds=config[CONF_SCAN_INTERVAL])
        alarm_coord: AlarmCoordinator | None = None
        sentinel_coord: SentinelCoordinator | None = None
        lock_coord: LockCoordinator | None = None
        activity_coord: ActivityCoordinator | None = None

        # Use the first installation for shared coordinators.
        # (Each config entry is scoped to one installation via CONF_INSTALLATION.)
        if devices:
            first_installation = devices[0].installation
            alarm_coord = AlarmCoordinator(
                hass,
                client.client,
                client.api_queue,
                first_installation,
                update_interval=scan_interval,
                config_entry=entry,
            )

            # Background polling is opt-in. When off (default) the coordinator
            # runs on-demand only (update_interval=None) — the activity-log
            # card drives refreshes while it's on screen. When on, it polls
            # every _DEFAULT_ACTIVITY_INTERVAL so verisure_owa_activity event
            # automations keep firing even with no card open.
            activity_coord = ActivityCoordinator(
                hass,
                client.client,
                client.api_queue,
                first_installation,
                config_entry=entry,
                update_interval=(
                    _DEFAULT_ACTIVITY_INTERVAL
                    if config[CONF_ENABLE_ACTIVITY_POLLING]
                    else None
                ),
            )

            # Discover sentinel and lock services from cached service list.
            # On failure, skip pre-population so the coordinator's
            # _populate_capabilities can retry on the first refresh — otherwise
            # a transient network error would lock has_peri/has_annex to False
            # for the coordinator lifetime.
            try:
                services = await client.get_services(first_installation)
            except VerisureOwaError:
                services = []
            else:
                capabilities = client.client.get_supported_commands(
                    first_installation.number
                )
                alarm_coord.populate_capabilities_from_data(services, capabilities)
                # Publish detected capabilities for the options-flow race
                # window (before entry data is stored under entry.entry_id).
                _publish_flow_capabilities(
                    hass,
                    first_installation.number,
                    alarm_coord.has_peri,
                    alarm_coord.has_annex,
                )

            # Sentinel coordinator — needs a sentinel service AND a zone.
            # An account can subscribe to CONFORT without a Sentinel device
            # installed (issue #498): the API then returns null attributes and
            # an empty xSComfort device list, so no zone exists anywhere. With
            # an empty zone the air-quality query 500s on every poll and the
            # coordinator fails forever, so skip it unless a zone is present.
            for service in services:
                if service.request in SENTINEL_SERVICE_NAMES and service.attributes:
                    zone = service.attributes[0].value
                    sentinel_coord = SentinelCoordinator(
                        hass,
                        client.client,
                        client.api_queue,
                        first_installation,
                        service=service,
                        zone=zone,
                        config_entry=entry,
                    )
                    break  # one sentinel coordinator per installation

            # Lock coordinator — if any lock service exists
            lock_service_names = {"DOORLOCK", "DANALOCK"}
            if any(s.request in lock_service_names for s in services):
                lock_coord = LockCoordinator(
                    hass,
                    client.client,
                    client.api_queue,
                    first_installation,
                    update_interval=scan_interval,
                    config_entry=entry,
                )

        # Wire bus-event emission for the activity timeline at the
        # integration level (not the sensor level) so verisure_owa_activity
        # automations keep working even if the user disables the
        # ActivityLogSensor entity.  Attaching here also starts the
        # coordinator's periodic timer so polling continues for as long as
        # the integration is loaded. Let ConfigEntry own the unsubscribe
        # callback so failed setup and successful unload share one cleanup path.
        if activity_coord is not None and devices:
            entry.async_on_unload(
                attach_activity_listener(
                    hass, activity_coord, devices[0].installation.number
                )
            )

        # Store per-entry data
        entry_data: dict[str, Any] = {
            "hub": client,
            "devices": devices,
            "alarm_coordinator": alarm_coord,
            "sentinel_coordinator": sentinel_coord,
            "lock_coordinator": lock_coord,
            "activity_coordinator": activity_coord,
            "config_entry": entry,
        }
        # Signalled by _async_discover_devices once lock discovery has either
        # populated registered_locks or definitively failed. The options-flow
        # Lock Automation step awaits this so it doesn't render before
        # discovery knows the actual device_ids. Only created when a lock
        # coordinator exists — installations without a lock service skip the
        # step unconditionally and never look at the event.
        if lock_coord is not None:
            entry_data["lock_discovery_complete"] = asyncio.Event()
        hass.data[DOMAIN][entry.entry_id] = entry_data

        # Schedule non-blocking first refresh for each coordinator. Skip the
        # activity coordinator when background polling is off — it's on-demand
        # only (the card triggers the first fetch when viewed), so an idle
        # install makes no activity API calls.
        for coord in filter(
            None, [alarm_coord, sentinel_coord, lock_coord, activity_coord]
        ):
            if (
                activity_coord is not None
                and coord is activity_coord
                and activity_coord.update_interval is None
            ):
                continue
            entry.async_create_background_task(
                hass,
                coord.async_refresh(),
                f"verisure_owa_refresh_{coord.name}",
            )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Discover cameras and locks in the background after setup completes.
        # This avoids blocking startup with API calls.
        entry.async_create_background_task(
            hass,
            _async_discover_devices(hass, entry),
            f"verisure_owa_discover_{entry.entry_id}",
        )

        return True
    raise ConfigEntryNotReady(
        "Config entry missing device IDs. Delete and re-add the integration."
    )


def _release_shared_session(
    hass: HomeAssistant,
    sessions: dict[str, Any],
    username: str,
    leaving: ConfigEntry,
) -> None:
    """Release ``leaving``'s hold on a shared session; pop it once no one holds it.

    Releasing a hold an entry never took cannot take one away from an entry
    that did, which stops a co-tenant's session being pulled out from under it.

    When the session survives but the entry being released is the one the hub
    saves rotated refresh tokens to, hand that over to another entry holding
    the session, even one still setting up or waiting to retry, or one whose
    setup failed while holding it, so its stored token does not go stale and
    hit the xSRefreshLogin 'fr' crash (issue #557) on its next restart. When
    only config flows hold it, detach the hub, so the next entry set up on it
    attaches itself.
    """
    session = sessions[username]
    # An entry that never took a hold leaves the holders alone. Counting
    # the leaver out regardless would pop the session out from under a
    # co-tenant that is still using it.
    if _release_session_hold(sessions, username, session, leaving.entry_id):
        return

    hub: VerisureHub = session["hub"]
    if hub.config_entry is not leaving:
        return
    successor = _token_successor(hass, session)
    if successor is None:
        hub.config_entry = None
    else:
        _attach_token_persistence(hub, successor)


def _token_successor(
    hass: HomeAssistant, session: dict[str, Any]
) -> ConfigEntry | None:
    """Pick the holding entry to save tokens to, a loaded one first.

    Flow keys resolve to no entry and are skipped.
    """
    holding = [
        entry
        for holder in session["holders"]
        if (entry := hass.config_entries.async_get_entry(holder)) is not None
    ]
    return min(
        holding,
        key=lambda entry: (entry.state is not ConfigEntryState.LOADED, entry.entry_id),
        default=None,
    )


# An entry setting up or waiting to retry may hold no session yet (it failed,
# or is still signing in, before taking one) but still needs the integration.
_ENTRY_STATES_IN_USE = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.SETUP_RETRY,
    # Home Assistant before 2025.3 has no such state: an entry being unloaded
    # stays LOADED, which is already listed.
    *(
        [ConfigEntryState.UNLOAD_IN_PROGRESS]
        if hasattr(ConfigEntryState, "UNLOAD_IN_PROGRESS")
        else []
    ),
)


def _integration_in_use(hass: HomeAssistant, exclude: ConfigEntry | None) -> bool:
    """Whether a session is held, an entry uses the integration, or a setup
    dialog is open.

    A dialog signing in afresh holds no session until its sign-in finishes.
    Reauth dialogs do not count: their steps sign in on a hub of their own and
    never touch the shared data (the entry's reload sets it up again), and HA
    aborts them only after the entry's ``async_remove_entry`` has run, so
    counting them would leave the integration set up once that entry is
    deleted. Options dialogs live in another manager and read the shared data
    only through ``get``.
    """
    if hass.data.get(DOMAIN, {}).get("sessions"):
        return True
    if any(
        entry.state in _ENTRY_STATES_IN_USE
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry is not exclude
    ):
        return True
    # HA drops a closing flow from its progress before calling the flow's
    # async_remove, so that flow never counts itself.
    return any(
        flow.get("context", {}).get("source") != SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress_by_handler(
            DOMAIN, include_uninitialized=True
        )
    )


async def _async_teardown_domain_if_unused(
    hass: HomeAssistant, exclude: ConfigEntry | None = None
) -> None:
    """Tear the integration down once nothing uses it.

    ``exclude`` is the entry being unloaded, which does not count as using it.
    """
    if DOMAIN not in hass.data or _integration_in_use(hass, exclude):
        return
    await _async_teardown_domain(hass, exclude)


async def _async_teardown_domain(
    hass: HomeAssistant, exclude: ConfigEntry | None = None
) -> None:
    """Undo the integration-wide setup: log filters, cards, service aliases.

    Stops before the aliases and the shared data if something started using the
    integration while the cards were being removed; ``exclude`` is the entry
    being unloaded, which does not count.
    """
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None:
        return
    # Forgotten as they are removed, so anything that sets up during the
    # awaits below adds its own instead of counting on these.
    log_filter = domain_data.pop("log_filter", None)
    transient_log_filter = domain_data.pop("transient_log_filter", None)
    domain_data.pop("card_registered", None)
    for handler in logging.getLogger().handlers:
        if log_filter:
            handler.removeFilter(log_filter)
        if transient_log_filter:
            handler.removeFilter(transient_log_filter)

    await _unregister_card_resource(hass, CARD_URL, "card_resource_id")
    await _unregister_card_resource(hass, CHIP_CARD_URL, "chip_card_resource_id")
    await _unregister_card_resource(hass, CAMERA_CARD_URL, "camera_card_resource_id")
    await _unregister_card_resource(
        hass, ACTIVITY_LOG_CARD_URL, "activity_log_card_resource_id"
    )
    await _unregister_card_resource(hass, MORE_INFO_MODULE_URL, "more_info_resource_id")

    # A setup dialog or entry may have started using the integration while
    # the cards were being removed.
    if _integration_in_use(hass, exclude):
        return

    # Left registered, a call to verisure_owa.force_arm would proxy to a
    # securitas service that no longer exists.
    for service_name, _supports_response, _schema in _ALIASED_SERVICES:
        if hass.services.has_service(ALIAS_DOMAIN, service_name):
            hass.services.async_remove(ALIAS_DOMAIN, service_name)

    hass.data.pop(DOMAIN, None)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Release a deleted entry's hold on its session if unloading did not.

    Home Assistant unloads only a loaded entry before deleting it. An entry
    whose setup failed after taking its hold (waiting to retry, or needing
    reauth) still holds the session here.
    """
    domain_data = hass.data.get(DOMAIN)
    username = entry.data.get(CONF_USERNAME)
    if domain_data is None or not username:
        return
    lock = domain_data.get("setup_locks", {}).get(username) or asyncio.Lock()
    async with lock:
        sessions = domain_data.get("sessions", {})
        session = sessions.get(username)
        if session is not None and entry.entry_id in session["holders"]:
            _release_shared_session(hass, sessions, username, entry)
    await _async_teardown_domain_if_unused(hass)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS):
        return False

    # Release this entry's hold (under the same lock used for creation)
    username = config_entry.data.get(CONF_USERNAME)
    sessions = hass.data.get(DOMAIN, {}).get("sessions", {})
    setup_locks = hass.data.get(DOMAIN, {}).get("setup_locks", {})
    if username and username in sessions:
        lock = setup_locks.get(username) or asyncio.Lock()
        async with lock:
            # A closing config flow lets go without this lock, so the session
            # may be gone by the time the lock is ours.
            if username in sessions:
                _release_shared_session(hass, sessions, username, config_entry)

    # Clean up per-entry data
    hass.data[DOMAIN].pop(config_entry.entry_id, None)

    await _async_teardown_domain_if_unused(hass, exclude=config_entry)

    return True
