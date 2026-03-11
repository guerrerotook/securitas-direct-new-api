"""Support for Securitas Direct alarms."""

import asyncio
from collections import OrderedDict
import logging
from pathlib import Path
import time
from uuid import uuid4

import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_queue import ApiQueue
from .const import (  # noqa: F401 — re-exported for backwards compatibility
    API_CACHE_TTL,
    CAMERA_CARD_BASE_URL,
    CAMERA_CARD_URL,
    CARD_BASE_URL,
    CARD_URL,
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
    DEFAULT_COUNTRY,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SIGNAL_CAMERA_UPDATE,
    SIGNAL_XSSTATUS_UPDATE,
)
from .hub import (  # noqa: F401 — re-exported for backwards compatibility
    SecuritasDirectDevice,
    SecuritasHub,
    _notify_error,
)
from .log_filter import SensitiveDataFilter
from .securitas_direct_new_api import (
    ApiDomains,
    Installation,
    Login2FAError,
    LoginError,
    SecuritasDirectError,
    generate_device_id,
    generate_uuid,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_COUNTRY, default=DEFAULT_COUNTRY): str,
                vol.Optional(CONF_CODE, default=DEFAULT_CODE): str,
                vol.Optional(
                    CONF_CODE_ARM_REQUIRED, default=DEFAULT_CODE_ARM_REQUIRED
                ): bool,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def add_device_information(config: dict) -> dict:
    """Add device information to the configuration."""
    if CONF_DEVICE_ID not in config:
        config[CONF_DEVICE_ID] = generate_device_id(config[CONF_COUNTRY])

    if CONF_UNIQUE_ID not in config:
        config[CONF_UNIQUE_ID] = generate_uuid()

    if CONF_DEVICE_INDIGITALL not in config:
        config[CONF_DEVICE_INDIGITALL] = str(uuid4())

    return config


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    if any(
        entry.data.get(attrib) != entry.options.get(attrib)
        for attrib in (
            CONF_CODE,
            CONF_CODE_ARM_REQUIRED,
            CONF_SCAN_INTERVAL,
            CONF_MAP_HOME,
            CONF_MAP_AWAY,
            CONF_MAP_NIGHT,
            CONF_MAP_CUSTOM,
            CONF_MAP_VACATION,
            CONF_NOTIFY_GROUP,
        )
    ):
        # update entry replacing data with new options
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **entry.options}
        )
        await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Reject old config entries — users must delete and re-add."""
    if config_entry.version < 3:
        _LOGGER.error(
            "Config entry %s uses format v%s which is no longer supported. "
            "Please remove this integration entry and re-add it.",
            config_entry.entry_id,
            config_entry.version,
        )
        _notify_error(
            hass,
            "migration_required",
            "Securitas Direct",
            "Your Securitas Direct configuration uses an old format. "
            "Please remove the integration entry and re-add it.",
        )
        return False
    return True


def _build_config_dict(entry: ConfigEntry) -> tuple[dict, bool]:
    """Build config dict from entry.data + entry.options.

    Returns the config dict and a flag indicating whether sign-in is needed
    (True if any device ID fields are missing from entry.data).
    """

    def _opt(key, default=None):
        """Read from options first, then data, then default."""
        return entry.options.get(key, entry.data.get(key, default))

    config = OrderedDict()
    config[CONF_USERNAME] = entry.data[CONF_USERNAME]
    config[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
    config[CONF_COUNTRY] = entry.data.get(CONF_COUNTRY, None)
    config[CONF_CODE] = _opt(CONF_CODE, DEFAULT_CODE)
    config[CONF_HAS_PERI] = entry.data.get(CONF_HAS_PERI, False)
    config[CONF_CODE_ARM_REQUIRED] = _opt(
        CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
    )
    config[CONF_SCAN_INTERVAL] = _opt(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    config[CONF_DELAY_CHECK_OPERATION] = _opt(
        CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
    )
    config[CONF_ENTRY_ID] = entry.entry_id
    config[CONF_NOTIFY_GROUP] = _opt(CONF_NOTIFY_GROUP, "")
    config = add_device_information(config)

    # Read mapping config (options override data)
    config[CONF_MAP_HOME] = _opt(CONF_MAP_HOME)
    config[CONF_MAP_AWAY] = _opt(CONF_MAP_AWAY)
    config[CONF_MAP_NIGHT] = _opt(CONF_MAP_NIGHT)
    config[CONF_MAP_CUSTOM] = _opt(CONF_MAP_CUSTOM)
    config[CONF_MAP_VACATION] = _opt(CONF_MAP_VACATION)

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


async def _get_or_create_session(
    hass: HomeAssistant, config: dict, entry: ConfigEntry
) -> SecuritasHub:
    """Get or create a shared SecuritasHub session with reference counting.

    Multiple config entries for the same username share a single
    SecuritasHub / ApiManager session to avoid duplicate logins
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
            # Reuse existing session
            client: SecuritasHub = sessions[username]["hub"]
            sessions[username]["ref_count"] += 1
        else:
            # Create new session and log in
            client = SecuritasHub(config, entry, async_get_clientsession(hass), hass)
            try:
                await client.login()
            except Login2FAError:
                msg = (
                    "Securitas Direct need a 2FA SMS code."
                    "Please login again with your phone"
                )
                _notify_error(hass, "2fa_error", "Securitas Direct", msg)
                raise
            except LoginError as err:
                _notify_error(hass, "login_error", "Securitas Direct", str(err))
                _LOGGER.error(
                    "Could not log in to Securitas: %s",
                    err.log_detail(),
                )
                raise
            except SecuritasDirectError as err:
                detail = err.log_detail()
                _LOGGER.error(
                    "Unable to connect to Securitas Direct: %s",
                    detail,
                )
                raise ConfigEntryNotReady(
                    f"Unable to connect to Securitas Direct: {detail}"
                ) from None
            sessions[username] = {"hub": client, "ref_count": 1}

    return client


def _get_or_create_api_queue(
    hass: HomeAssistant,
    session: SecuritasHub,
    config: dict,
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
        _LOGGER.info(
            "Created ApiQueue %s for domain %s (country=%s, entry=%s)",
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
    hub: SecuritasHub,
    entry: ConfigEntry,
) -> list[SecuritasDirectDevice]:
    """Fetch installations and services, populating caches.

    Uses cached data from the config flow when available, otherwise
    fetches from the API (e.g. on HA restart).

    Returns a list of SecuritasDirectDevice wrappers for this entry's
    installations.
    """
    install_cache = hass.data[DOMAIN].get("installations_cache")
    if (
        install_cache is not None
        and time.monotonic() - install_cache["time"] < API_CACHE_TTL
    ):
        all_installations: list[Installation] = install_cache["data"]
    else:
        all_installations = await hub.api_queue.submit(
            hub.session.list_installations,
            priority=ApiQueue.FOREGROUND,
        )
        hass.data[DOMAIN]["installations_cache"] = {
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

    devices: list[SecuritasDirectDevice] = []
    for installation in entry_installations:
        if cached_services and installation.number in cached_services:
            # Pre-populate from config flow cache
            hub.services_cache[installation.number] = cached_services[
                installation.number
            ]
        elif installation.number not in hub.services_cache:
            # HA restart: fetch directly (bypass queue — we just logged
            # in, no WAF risk yet) so platforms don't block on queue.
            hub.services_cache[
                installation.number
            ] = await hub.session.get_all_services(installation)
        devices.append(SecuritasDirectDevice(installation))
    return devices


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Establish connection with Securitas Direct."""
    config, need_sign_in = _build_config_dict(entry)

    # Register card static path + Lovelace resource early so the card
    # is available even when login fails (ConfigEntryNotReady).
    if hass.http and not hass.data.get(DOMAIN, {}).get("card_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    "/securitas_panel",
                    str(Path(__file__).parent / "www"),
                    cache_headers=False,
                )
            ]
        )
        await _register_card_resource(hass, CARD_BASE_URL, CARD_URL, "card_resource_id")
        await _register_card_resource(hass, CAMERA_CARD_BASE_URL, CAMERA_CARD_URL, "camera_card_resource_id")
        hass.data.setdefault(DOMAIN, {})["card_registered"] = True

    hass.data.setdefault(DOMAIN, {})

    # Set up log sanitization filter — must be on handlers, not the logger,
    # because logger-level filters don't apply to child logger records.
    if "log_filter" not in hass.data[DOMAIN]:
        log_filter = SensitiveDataFilter()
        for handler in logging.getLogger().handlers:
            handler.addFilter(log_filter)
        hass.data[DOMAIN]["log_filter"] = log_filter
    else:
        log_filter = hass.data[DOMAIN]["log_filter"]

    # Register credentials immediately
    log_filter.update_secret("username", config[CONF_USERNAME])
    log_filter.update_secret("password", config[CONF_PASSWORD])

    hass.data[DOMAIN][CONF_ENTRY_ID] = entry.entry_id
    if not need_sign_in:
        try:
            client = await _get_or_create_session(hass, config, entry)
        except Login2FAError:
            return False
        except LoginError:
            return False

        _get_or_create_api_queue(hass, client, config, entry)

        entry.async_on_unload(entry.add_update_listener(async_update_options))

        try:
            devices = await _fetch_and_cache_installations(hass, client, entry)
        except SecuritasDirectError as err:
            _LOGGER.error("Unable to connect to Securitas Direct: %s", err.log_detail())
            raise ConfigEntryNotReady("Unable to connect to Securitas Direct") from None

        # Store per-entry data
        hass.data[DOMAIN][entry.entry_id] = {
            "hub": client,
            "devices": devices,
        }

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Discover cameras and locks in the background after setup completes.
        # This avoids blocking startup with API calls.
        entry.async_create_background_task(
            hass,
            _async_discover_devices(hass, entry),
            f"securitas_discover_{entry.entry_id}",
        )
        return True
    raise ConfigEntryNotReady(
        "Config entry missing device IDs. Delete and re-add the integration."
    )


async def _discover_cameras(
    hub: SecuritasHub,
    installation: Installation,
    entry_data: dict,
) -> None:
    """Discover camera devices for an installation and add entities."""
    from .button import SecuritasCaptureButton
    from .camera import SecuritasCamera

    try:
        cameras = await hub.get_camera_devices(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning("Failed to get camera devices for %s", installation.number)
        cameras = []

    if cameras:
        camera_add = entry_data.get("camera_add_entities")
        button_add = entry_data.get("button_add_entities")
        if camera_add:
            camera_add(
                [SecuritasCamera(hub, installation, cam) for cam in cameras],
                False,
            )
        if button_add:
            button_add(
                [SecuritasCaptureButton(hub, installation, cam) for cam in cameras],
                True,
            )


async def _discover_locks(
    hass: HomeAssistant,
    hub: SecuritasHub,
    installation: Installation,
    entry_data: dict,
) -> None:
    """Discover lock devices for an installation and add entities."""
    from .entity import schedule_initial_updates
    from .lock import (
        DOORLOCK_SERVICE,
        LOCK_STATUS_UNKNOWN,
        SecuritasLock,
    )
    from .securitas_direct_new_api import SmartLock, SmartLockMode
    from .securitas_direct_new_api.apimanager import SMARTLOCK_DEVICE_ID

    try:
        services = await hub.get_services(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning("Failed to get services for %s", installation.number)
        return

    has_doorlock = any(s.request == DOORLOCK_SERVICE for s in services)
    if not has_doorlock:
        return

    try:
        lock_modes: list[SmartLockMode] = await hub.get_lock_modes(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning("Failed to get lock modes for %s", installation.number)
        lock_modes = []

    if not lock_modes:
        lock_modes = [
            SmartLockMode(
                res=None,
                lockStatus=LOCK_STATUS_UNKNOWN,
                deviceId=SMARTLOCK_DEVICE_ID,
            )
        ]

    lock_add = entry_data.get("lock_add_entities")
    if lock_add:
        locks = []
        for mode in lock_modes:
            device_id = mode.deviceId or SMARTLOCK_DEVICE_ID
            lock_config: SmartLock | None = None
            try:
                lock_config = await hub.get_smart_lock_config(installation, device_id)
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "Could not fetch smart lock config for %s device %s",
                    installation.number,
                    device_id,
                )
            locks.append(
                SecuritasLock(
                    installation,
                    client=hub,
                    hass=hass,
                    device_id=device_id,
                    initial_status=mode.lockStatus,
                    lock_config=lock_config,
                )
            )
        lock_add(locks, False)
        schedule_initial_updates(hass, locks)


async def _async_discover_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Discover cameras and locks in the background after setup."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    client: SecuritasHub = entry_data["hub"]
    devices: list[SecuritasDirectDevice] = entry_data["devices"]

    for device in devices:
        installation = device.installation
        await _discover_cameras(client, installation, entry_data)
        await _discover_locks(hass, client, installation, entry_data)


async def _register_card_resource(
    hass: HomeAssistant,
    base_url: str,
    card_url: str,
    storage_key: str,
) -> None:
    """Register a card JS file as a Lovelace resource.

    Falls back to add_extra_js_url if Lovelace resources are unavailable.
    ``storage_key`` is used to track the resource ID in hass.data[DOMAIN].
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data and hasattr(lovelace_data, "resources"):
            resources = lovelace_data.resources
            if hasattr(resources, "async_create_item"):
                if not resources.loaded:
                    await resources.async_load()
                    resources.loaded = True
                for item in resources.async_items():
                    url = item.get("url", "")
                    if url == card_url:
                        return  # Already current version
                    if url.startswith(base_url):
                        await resources.async_update_item(item["id"], {"url": card_url})
                        hass.data.setdefault(DOMAIN, {})[storage_key] = item["id"]
                        return
                item = await resources.async_create_item(
                    {"res_type": "module", "url": card_url}
                )
                hass.data.setdefault(DOMAIN, {})[storage_key] = item["id"]
                return
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.debug(
            "[setup] Could not register %s as Lovelace resource, falling back to add_extra_js_url",
            base_url,
        )
    try:
        frontend.add_extra_js_url(hass, card_url)
    except (KeyError, Exception):  # pylint: disable=broad-exception-caught
        _LOGGER.debug("[setup] Could not register %s via add_extra_js_url", base_url)


async def _unregister_card_resource(
    hass: HomeAssistant,
    card_url: str,
    storage_key: str,
) -> None:
    """Remove a card Lovelace resource on unload."""
    resource_id = hass.data.get(DOMAIN, {}).get(storage_key)
    if not resource_id:
        try:
            frontend.remove_extra_js_url(hass, card_url)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data and hasattr(lovelace_data, "resources"):
            resources = lovelace_data.resources
            if hasattr(resources, "async_delete_item"):
                await resources.async_delete_item(resource_id)
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.debug("[teardown] Could not remove Lovelace resource %s", resource_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    # Decrement shared session ref count (under the same lock used for creation)
    username = config_entry.data.get(CONF_USERNAME)
    sessions = hass.data.get(DOMAIN, {}).get("sessions", {})
    setup_locks = hass.data.get(DOMAIN, {}).get("setup_locks", {})
    if username and username in sessions:
        lock = setup_locks.get(username)
        if lock:
            async with lock:
                sessions[username]["ref_count"] -= 1
                if sessions[username]["ref_count"] <= 0:
                    sessions.pop(username)
        else:
            sessions[username]["ref_count"] -= 1
            if sessions[username]["ref_count"] <= 0:
                sessions.pop(username)

    # Clean up per-entry data
    hass.data[DOMAIN].pop(config_entry.entry_id, None)

    # Check if any sessions remain — if not, do full cleanup
    remaining_sessions = hass.data.get(DOMAIN, {}).get("sessions", {})
    if not remaining_sessions:
        # Last entry unloaded — full cleanup
        log_filter = hass.data[DOMAIN].get("log_filter")
        if log_filter:
            for handler in logging.getLogger().handlers:
                handler.removeFilter(log_filter)

        await _unregister_card_resource(hass, CARD_URL, "card_resource_id")
        await _unregister_card_resource(hass, CAMERA_CARD_URL, "camera_card_resource_id")
        hass.data.pop(DOMAIN, None)

    return unload_ok
