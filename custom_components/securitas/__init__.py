"""Support for Securitas Direct alarms."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import timedelta
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
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
    EVENTS_CARD_BASE_URL,
    EVENTS_CARD_URL,
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
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
    COUNTRY_CODES,
    DEFAULT_CODE,
    DEFAULT_CODE_ARM_REQUIRED,
    DEFAULT_COUNTRY,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SENTINEL_SERVICE_NAMES,
    SIGNAL_CAMERA_STATE,
)
from .coordinators import (
    ActivityCoordinator,
    AlarmCoordinator,
    CameraCoordinator,
    LockCoordinator,
    SentinelCoordinator,
)
from .hub import (  # noqa: F401 — re-exported for backwards compatibility
    SecuritasDirectDevice,
    SecuritasHub,
    _async_notify,
    _notify,
)
from .log_filter import SensitiveDataFilter
from .securitas_direct_new_api import (
    ApiDomains,
    AuthenticationError,
    Installation,
    SecuritasDirectError,
    TwoFactorRequiredError,
    generate_device_id,
    generate_uuid,
)

if TYPE_CHECKING:
    from .lock import SecuritasLock

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


def add_device_information[T: dict](config: T) -> T:
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
            CONF_FORCE_ARM_NOTIFICATIONS,
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
        _notify(hass, "migration_required", "migration_required")
        return False
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
    config[CONF_FORCE_ARM_NOTIFICATIONS] = _opt(
        CONF_FORCE_ARM_NOTIFICATIONS, DEFAULT_FORCE_ARM_NOTIFICATIONS
    )
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
    hass: HomeAssistant, config: dict[str, Any], entry: ConfigEntry
) -> SecuritasHub:
    """Get or create a shared SecuritasHub session with reference counting.

    Multiple config entries for the same username share a single
    SecuritasHub / SecuritasClient session to avoid duplicate logins
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
            except TwoFactorRequiredError:
                _notify(hass, "2fa_error", "two_factor_required")
                raise
            except AuthenticationError as err:
                _notify(hass, "login_error", "login_failed", {"error": str(err)})
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
    hub: SecuritasHub,
    entry: ConfigEntry,
) -> list[SecuritasDirectDevice]:
    """Fetch installations and services, populating caches.

    Uses cached data from the config flow when available, otherwise
    fetches from the API (e.g. on HA restart).

    Returns a list of SecuritasDirectDevice wrappers for this entry's
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
            hub.services_cache[installation.number] = await hub.client.get_services(
                installation
            )
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
        await _register_card_resource(
            hass, CAMERA_CARD_BASE_URL, CAMERA_CARD_URL, "camera_card_resource_id"
        )
        await _register_card_resource(
            hass, EVENTS_CARD_BASE_URL, EVENTS_CARD_URL, "events_card_resource_id"
        )
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
        except TwoFactorRequiredError as err:
            raise ConfigEntryAuthFailed("2FA required — please reauthenticate") from err
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

        _get_or_create_api_queue(hass, client, config, entry)

        entry.async_on_unload(entry.add_update_listener(async_update_options))

        try:
            devices = await _fetch_and_cache_installations(hass, client, entry)
        except SecuritasDirectError as err:
            _LOGGER.error("Unable to connect to Securitas Direct: %s", err.log_detail())
            raise ConfigEntryNotReady("Unable to connect to Securitas Direct") from None

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

            activity_coord = ActivityCoordinator(
                hass,
                client.client,
                client.api_queue,
                first_installation,
                config_entry=entry,
            )

            # Discover sentinel and lock services from cached service list
            try:
                services = await client.get_services(first_installation)
            except SecuritasDirectError:
                services = []

            # Sentinel coordinator — needs a sentinel service and its zone
            for service in services:
                if service.request in SENTINEL_SERVICE_NAMES:
                    zone = service.attributes[0].value if service.attributes else ""
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

        # Store per-entry data
        hass.data[DOMAIN][entry.entry_id] = {
            "hub": client,
            "devices": devices,
            "alarm_coordinator": alarm_coord,
            "sentinel_coordinator": sentinel_coord,
            "lock_coordinator": lock_coord,
            "activity_coordinator": activity_coord,
        }

        # Schedule non-blocking first refresh for each coordinator.
        # ActivityCoordinator is intentionally excluded — its first refresh
        # is triggered by ActivityLogSensor.async_added_to_hass, which also
        # attaches the bus-firing listener.  This keeps the periodic refresh
        # timer tied to the sensor's lifetime rather than the integration's.
        for coord in filter(None, [alarm_coord, sentinel_coord, lock_coord]):
            entry.async_create_background_task(
                hass,
                coord.async_refresh(),
                f"securitas_refresh_{coord.name}",
            )

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
    hass: HomeAssistant,
    hub: SecuritasHub,
    installation: Installation,
    entry_data: dict[str, Any],
    entry: ConfigEntry,
) -> None:
    """Discover camera devices for an installation and add entities."""
    from .button import SecuritasCaptureButton
    from .camera import SecuritasCamera, SecuritasCameraFull

    _LOGGER.debug(
        "[camera_discovery] Fetching camera devices for installation %s (%s)",
        installation.number,
        installation.alias,
    )
    try:
        cameras = await hub.get_camera_devices(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning(
            "[camera_discovery] Failed to get camera devices for %s",
            installation.number,
            exc_info=True,
        )
        cameras = []

    _LOGGER.debug(
        "[camera_discovery] Installation %s: found %d camera(s): %s",
        installation.number,
        len(cameras),
        [c.zone_id for c in cameras],
    )

    if cameras:
        # Create and store camera coordinator
        camera_coord = CameraCoordinator(
            hass,
            hub.client,
            hub.api_queue,
            installation,
            cameras=cameras,
            config_entry=entry,
        )
        entry_data["camera_coordinator"] = camera_coord
        entry.async_create_background_task(
            hass,
            camera_coord.async_refresh(),
            "securitas_camera_refresh",
        )

        camera_add = entry_data.get("camera_add_entities")
        button_add = entry_data.get("button_add_entities")
        _LOGGER.debug(
            "[camera_discovery] Installation %s: camera_add=%s button_add=%s",
            installation.number,
            camera_add is not None,
            button_add is not None,
        )
        if camera_add:
            camera_add(
                [
                    SecuritasCamera(camera_coord, hub, installation, cam)
                    for cam in cameras
                ]
                + [
                    SecuritasCameraFull(camera_coord, hub, installation, cam)
                    for cam in cameras
                ],
                False,
            )
        if button_add:
            button_add(
                [SecuritasCaptureButton(hub, installation, cam) for cam in cameras],
                True,
            )


_LOCK_CONFIG_RETRY_DELAYS = (60, 120, 300)  # seconds between retries


def _schedule_lock_config_retry(
    hass: HomeAssistant,
    hub: SecuritasHub,
    installation: Installation,
    lock_entity: SecuritasLock,
    attempt: int = 0,
) -> None:
    """Schedule a background retry to fetch lock config."""
    from homeassistant.helpers.event import async_call_later

    if attempt >= len(_LOCK_CONFIG_RETRY_DELAYS):
        _LOGGER.info(
            "Lock config retry exhausted for %s device %s",
            installation.number,
            lock_entity.device_id,
        )
        return

    delay = _LOCK_CONFIG_RETRY_DELAYS[attempt]

    async def _retry(_now: Any) -> None:
        # Guard: entity may have been removed while the timer was pending.
        if lock_entity.hass is None:
            return

        try:
            config = await hub.get_lock_config(
                installation,
                lock_entity.device_id,
                priority=hub.api_queue.BACKGROUND,
            )
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            config = None

        if config is not None:
            _LOGGER.info(
                "Lock config retry succeeded for %s device %s (attempt %d)",
                installation.number,
                lock_entity.device_id,
                attempt + 1,
            )
            lock_entity.update_lock_config(config)
        else:
            _LOGGER.debug(
                "Lock config retry %d failed for %s device %s, scheduling next retry",
                attempt + 1,
                installation.number,
                lock_entity.device_id,
            )
            _schedule_lock_config_retry(
                hass, hub, installation, lock_entity, attempt + 1
            )

    unsub = async_call_later(hass, delay, _retry)
    lock_entity.add_config_retry_unsub(unsub)


async def _discover_locks(
    hass: HomeAssistant,
    hub: SecuritasHub,
    installation: Installation,
    entry_data: dict[str, Any],
) -> None:
    """Discover lock devices for an installation and add entities."""
    from .lock import (
        DOORLOCK_SERVICE,
        LOCK_STATUS_UNKNOWN,
        SecuritasLock,
    )
    from .securitas_direct_new_api import SmartLock, SmartLockMode
    from .securitas_direct_new_api.client import SMARTLOCK_DEVICE_ID

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
                lock_status=LOCK_STATUS_UNKNOWN,
                device_id=SMARTLOCK_DEVICE_ID,
            )
        ]

    lock_coordinator = entry_data.get("lock_coordinator")
    lock_add = entry_data.get("lock_add_entities")
    if lock_add and lock_coordinator is not None:
        locks = []
        for mode in lock_modes:
            device_id = mode.device_id or SMARTLOCK_DEVICE_ID
            lock_config: SmartLock | None = None
            try:
                lock_config = await hub.get_lock_config(installation, device_id)
            except Exception:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "Could not fetch lock config for %s device %s",
                    installation.number,
                    device_id,
                )
            locks.append(
                SecuritasLock(
                    coordinator=lock_coordinator,
                    installation=installation,
                    client=hub,
                    device_id=device_id,
                    initial_status=mode.lock_status,
                    lock_config=lock_config,
                )
            )
        lock_add(locks, False)

        # Schedule deferred config retry for locks without config.
        for lk in locks:
            if lk.lock_config is None:
                _schedule_lock_config_retry(hass, hub, installation, lk)


async def _async_discover_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Discover cameras and locks in the background after setup."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    client: SecuritasHub = entry_data["hub"]
    devices: list[SecuritasDirectDevice] = entry_data["devices"]

    for device in devices:
        installation = device.installation
        await _discover_cameras(hass, client, installation, entry_data, entry)
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
                        # Resource already at current version — record its id
                        # so async_unload_entry can find and remove it.
                        hass.data.setdefault(DOMAIN, {})[storage_key] = item["id"]
                        return
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
        await _unregister_card_resource(
            hass, CAMERA_CARD_URL, "camera_card_resource_id"
        )
        await _unregister_card_resource(
            hass, EVENTS_CARD_URL, "events_card_resource_id"
        )
        hass.data.pop(DOMAIN, None)

    return unload_ok
