"""Background discovery for cameras and locks.

Cameras and locks are discovered asynchronously after async_setup_entry
returns so a transient API failure during discovery doesn't block the
integration from coming up. Each discovery path is best-effort: failures
are logged but never raise.
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
    from .verisure_owa_api import Installation

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
                new_lock._entry_id = entry.entry_id  # noqa: SLF001  # pylint: disable=protected-access
            locks.append(new_lock)
            # Register the lock so the options flow can discover it.
            entry_data.setdefault("registered_locks", []).append(
                {
                    "device_id": device_id,
                    "alias": new_lock._attr_name or device_id,  # noqa: SLF001  # pylint: disable=protected-access
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


async def _async_discover_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Discover cameras and locks in the background after setup.

    Locks run before cameras so a user opening the Lock Automation options
    step doesn't wait on the camera-device query in between. The shared
    ApiQueue still serializes all calls, so this is purely a reorder, not a
    parallelization — request rate is unchanged.
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
    finally:
        # Always signal completion so the options-flow await unblocks even
        # when discovery raised mid-way. Only set when the entry actually
        # has a lock service — otherwise the event was never created.
        if lock_event is not None:
            lock_event.set()
