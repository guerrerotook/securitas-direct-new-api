"""Background discovery for cameras, locks and zones.

Cameras, locks and zones are discovered asynchronously after
async_setup_entry returns so a transient API failure during discovery doesn't
block the integration from coming up. Each discovery path is best-effort:
failures are logged but never raise.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinators import CameraCoordinator

if TYPE_CHECKING:
    from .hub import VerisureDevice, VerisureHub
    from .lock import VerisureLock
    from .verisure_owa_api import Installation, PanelDevice

_LOGGER = logging.getLogger(__name__)

# Backoff schedule for the lock-config retry chain.
_LOCK_CONFIG_RETRY_DELAYS = (60, 120, 300)  # seconds between attempts


async def _discover_cameras(
    hass: HomeAssistant,
    hub: VerisureHub,
    installation: Installation,
    entry_data: dict[str, Any],
    entry: ConfigEntry,
) -> None:
    """Discover camera devices for an installation and add entities."""
    from .button import VerisureCaptureButton
    from .camera import VerisureCamera, VerisureCameraFull

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
        camera_coord = CameraCoordinator(
            hass,
            hub.client,
            hub.api_queue,
            installation,
            cameras=cameras,
            full_image_fetcher=hub.fetch_full_image,
            config_entry=entry,
        )
        entry_data["camera_coordinator"] = camera_coord
        entry.async_create_background_task(
            hass,
            camera_coord.async_refresh(),
            "verisure_owa_camera_refresh",
        )

        camera_add = entry_data.get("camera_add_entities")
        button_add = entry_data.get("button_add_entities")
        _LOGGER.debug(
            "[camera_discovery] Installation %s: camera_add=%s button_add=%s",
            installation.number,
            camera_add is not None,
            button_add is not None,
        )
        thumbnail_entities = [
            VerisureCamera(camera_coord, hub, installation, cam) for cam in cameras
        ]
        if camera_add:
            camera_add(
                thumbnail_entities
                + [
                    VerisureCameraFull(camera_coord, hub, installation, cam)
                    for cam in cameras
                ],
                False,
            )
        if button_add:
            button_add(
                [
                    VerisureCaptureButton(hub, installation, cam, camera_entity=thumb)
                    for cam, thumb in zip(cameras, thumbnail_entities, strict=True)
                ],
                True,
            )


def _schedule_lock_config_retry(
    hass: HomeAssistant,
    hub: VerisureHub,
    installation: Installation,
    lock_entity: VerisureLock,
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
        except Exception:  # pylint: disable=broad-exception-caught
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
    # Also tracked at entry scope so unload can cancel pending retries.
    if hub.config_entry is not None:
        entry_data = hass.data.get(DOMAIN, {}).get(hub.config_entry.entry_id)
        if entry_data is not None:
            entry_data.setdefault("lock_config_retry_unsubs", []).append(unsub)


async def _discover_locks(
    hass: HomeAssistant,
    hub: VerisureHub,
    installation: Installation,
    entry_data: dict[str, Any],
    entry: ConfigEntry | None = None,
) -> None:
    """Discover lock devices for an installation and add entities."""
    from .lock import (
        DOORLOCK_SERVICE,
        LOCK_STATUS_UNKNOWN,
        VerisureLock,
    )
    from .verisure_owa_api import SmartLock, SmartLockMode
    from .verisure_owa_api.client import SMARTLOCK_DEVICE_ID

    try:
        services = await hub.get_services(installation)
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning("Failed to get services for %s", installation.number)
        return

    has_doorlock = any(s.request == DOORLOCK_SERVICE for s in services)
    if not has_doorlock:
        return

    try:
        lock_modes: list[SmartLockMode] = await hub.get_lock_modes(
            installation, priority=hub.api_queue.FOREGROUND
        )
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
            new_lock = VerisureLock(
                coordinator=lock_coordinator,
                installation=installation,
                client=hub,
                device_id=device_id,
                initial_status=mode.lock_status,
                lock_config=lock_config,
            )
            if entry is not None:
                new_lock._entry_id = entry.entry_id  # pylint: disable=protected-access
            locks.append(new_lock)
            # Register the lock so the options flow can discover it.
            entry_data.setdefault("registered_locks", []).append(
                {
                    "device_id": device_id,
                    "alias": new_lock._attr_name or device_id,  # pylint: disable=protected-access
                }
            )
        lock_add(locks, False)
        _LOGGER.info(
            "Lock discovery for %s registered %d lock(s)",
            installation.number,
            len(locks),
        )

        # Schedule deferred config retry for locks without config.
        for lk in locks:
            if lk.lock_config is None:
                _schedule_lock_config_retry(hass, hub, installation, lk)


def _zone_unique_id_prefix(installation: Installation) -> str:
    """Return the unique_id prefix shared by every per-zone entity."""
    return f"v4_securitas_direct.{installation.number}_zone_"


def _zones_already_registered(
    hass: HomeAssistant, entry: ConfigEntry, installation: Installation
) -> bool:
    """Return True if per-zone entities were created on an earlier run.

    The evidence that the panel populates its exceptions feed is latched per
    coordinator, so it resets on every restart. Without this probe a household
    whose doors happen to be shut at startup would never re-materialise the
    entities it already had, and they would sit in the registry as
    unavailable. The registry already persists exactly the fact we need, so no
    extra Store is required — and if the user deletes the entities they simply
    come back on the next real exception.
    """
    from homeassistant.helpers import entity_registry as er

    prefix = _zone_unique_id_prefix(installation)
    registry = er.async_get(hass)
    return any(
        rle.domain == "binary_sensor" and rle.unique_id.startswith(prefix)
        for rle in er.async_entries_for_config_entry(registry, entry.entry_id)
    )


async def _discover_zones(
    hass: HomeAssistant,
    hub: VerisureHub,
    installation: Installation,
    entry_data: dict[str, Any],
    entry: ConfigEntry,
) -> None:
    """Set up per-zone binary sensors for an installation.

    Runs after camera discovery so the shared inventory fetch is already
    cached — this adds no API calls at all.

    Entities are not created eagerly. The exceptions feed is sparse, so an
    empty list is indistinguishable from a panel that never populates it; a
    zone entity created on that basis would report "closed" forever. Creation
    therefore waits until the panel has actually reported an exception (or
    until the registry shows it did so on a previous run), at which point the
    whole inventory is materialised at once — one open door brings every zone
    online, so a door that stays shut still gets its entity.
    """
    from .binary_sensor import ZoneTarget, alias_matches, build_zone_entities
    from .verisure_owa_api.client import filter_zone_devices

    add_entities = entry_data.get("binary_sensor_add_entities")
    coordinator = entry_data.get("alarm_coordinator")
    if add_entities is None or coordinator is None:
        return

    try:
        inventory = filter_zone_devices(await hub.get_devices(installation))
    except Exception:  # pylint: disable=broad-exception-caught  # background discovery must not crash
        _LOGGER.warning(
            "[zone_discovery] Failed to get devices for %s",
            installation.number,
            exc_info=True,
        )
        inventory = []

    # Duplicate panel labels make an alias genuinely ambiguous: there is no way
    # to tell which physical contact an exception refers to. Drop both rather
    # than inventing per-device state — they still surface through the orphan
    # path and the aggregates.
    by_name: dict[str, PanelDevice] = {}
    ambiguous: set[str] = set()
    for device in inventory:
        name = device.name.strip()
        if not name:
            continue
        if name in by_name:
            ambiguous.add(name)
            continue
        by_name[name] = device
    for name in ambiguous:
        by_name.pop(name, None)
    if ambiguous:
        _LOGGER.warning(
            "[zone_discovery] Installation %s: %d zone(s) share a panel label "
            "and cannot be told apart: %s. They are reported by the aggregate "
            "sensors only.",
            installation.number,
            len(ambiguous),
            sorted(ambiguous),
        )

    targets = [ZoneTarget.from_device(device) for device in by_name.values()]
    _LOGGER.debug(
        "[zone_discovery] Installation %s: %d zone(s) in inventory: %s",
        installation.number,
        len(targets),
        [t.key for t in targets],
    )

    materialised: set[str] = set()

    def _add(new_targets: list[ZoneTarget]) -> None:
        add_entities(
            build_zone_entities(coordinator, installation, new_targets, hub.hass),
            False,
        )
        materialised.update(t.match_name for t in new_targets)

    def _sync_zones() -> None:
        """Materialise zone entities once the panel proves the feed works."""
        if not coordinator.exceptions_observed:
            return
        if not materialised and targets:
            _add(targets)
        # Any alias the inventory could not account for still gets an entity:
        # a truncated label, a zone renamed after discovery, a device type not
        # yet promoted, or a failed inventory fetch.
        unknown = [
            ZoneTarget.from_alias(alias)
            for alias in coordinator.zone_exception_aliases
            if not any(alias_matches(alias, known) for known in materialised)
        ]
        if unknown:
            _LOGGER.info(
                "[zone_discovery] Installation %s: adding %d zone(s) reported by "
                "the panel but absent from the inventory: %s",
                installation.number,
                len(unknown),
                [t.name for t in unknown],
            )
            _add(unknown)

    if targets and _zones_already_registered(hass, entry, installation):
        _add(targets)

    _sync_zones()
    unsub = coordinator.async_add_listener(_sync_zones)
    entry_data.setdefault("zone_gate_unsubs", []).append(unsub)


async def _async_discover_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Discover cameras, locks and zones in the background after setup.

    Locks run before cameras so a user opening the Lock Automation options
    step doesn't wait on the camera-device query in between. The shared
    ApiQueue still serializes all calls, so this is purely a reorder, not a
    parallelization — request rate is unchanged.

    Zones run last: they reuse the peripheral inventory camera discovery has
    already cached, so they cost no additional request.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    client: VerisureHub = entry_data["hub"]
    devices: list[VerisureDevice] = entry_data["devices"]
    lock_event = entry_data.get("lock_discovery_complete")

    try:
        for device in devices:
            installation = device.installation
            await _discover_locks(hass, client, installation, entry_data, entry)
            await _discover_cameras(hass, client, installation, entry_data, entry)
            await _discover_zones(hass, client, installation, entry_data, entry)
    finally:
        # Always signal completion so the options-flow await unblocks even
        # when discovery raised mid-way. Only set when the entry actually
        # has a lock service — otherwise the event was never created.
        if lock_event is not None:
            lock_event.set()
