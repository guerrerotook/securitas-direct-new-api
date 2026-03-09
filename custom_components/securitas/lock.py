import datetime
from datetime import timedelta
import logging
from typing import Any

import homeassistant.components.lock as lock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import (
    CONF_INSTALLATION_KEY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
)
from .securitas_direct_new_api import (
    Installation,
    SecuritasDirectError,
    SmartLock,
    SmartLockMode,
)
from .securitas_direct_new_api.apimanager import SMARTLOCK_DEVICE_ID
from .securitas_direct_new_api.dataTypes import Service

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=20)

# Service request name that identifies a smart-lock capability
DOORLOCK_SERVICE = "DOORLOCK"

# lockStatus codes returned by the Securitas smart-lock API
LOCK_STATUS_UNKNOWN = "0"
LOCK_STATUS_OPEN = "1"
LOCK_STATUS_LOCKED = "2"
LOCK_STATUS_OPENING = "3"
LOCK_STATUS_LOCKING = "4"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct lock entities from config entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    locks = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )
    for device in securitas_devices:
        services: list[Service] = await client.get_services(device.installation)
        has_doorlock = any(s.request == DOORLOCK_SERVICE for s in services)
        if not has_doorlock:
            continue

        # Discover individual lock devices from the API
        lock_modes: list[SmartLockMode] = (
            await client.session.get_lock_current_mode(device.installation)
        )

        if not lock_modes:
            # Fallback: API didn't return any lock info, create a single lock
            # with default device ID for backward compatibility
            _LOGGER.warning(
                "No lock devices discovered for installation %s, "
                "using default device ID",
                device.installation.number,
            )
            lock_config = await client.session.get_smart_lock_config(
                device.installation
            )
            locks.append(
                SecuritasLock(
                    installation=device.installation,
                    client=client,
                    hass=hass,
                    device_id=SMARTLOCK_DEVICE_ID,
                    lock_config=lock_config,
                    initial_status=LOCK_STATUS_UNKNOWN,
                )
            )
            continue

        for lock_mode in lock_modes:
            device_id = lock_mode.deviceId or SMARTLOCK_DEVICE_ID
            # Fetch per-lock config (location, serial, etc.)
            try:
                lock_config: SmartLock = (
                    await client.session.get_smart_lock_config(
                        device.installation, device_id=device_id
                    )
                )
            except SecuritasDirectError:
                _LOGGER.warning(
                    "Could not fetch config for lock device %s, using defaults",
                    device_id,
                )
                lock_config = SmartLock(deviceId=device_id)

            locks.append(
                SecuritasLock(
                    installation=device.installation,
                    client=client,
                    hass=hass,
                    device_id=device_id,
                    lock_config=lock_config,
                    initial_status=lock_mode.lockStatus,
                )
            )

    if not locks:
        _LOGGER.debug("No Securitas Direct %s services found", DOORLOCK_SERVICE)
        return

    async_add_entities(locks, True)


class SecuritasLock(lock.LockEntity):
    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
        device_id: str,
        lock_config: SmartLock | None = None,
        initial_status: str = LOCK_STATUS_LOCKED,
    ) -> None:
        self._device_id: str = device_id
        self._lock_config: SmartLock | None = lock_config
        self._state = (
            initial_status
            if initial_status != LOCK_STATUS_UNKNOWN
            else LOCK_STATUS_LOCKED
        )
        self._last_state = self._state
        self._new_state: str = self._state
        self._changed_by: str = ""
        self._device: str = installation.address
        # Unique ID includes deviceId to support multiple locks per installation
        self._attr_unique_id: str | None = (
            f"securitas_direct.{installation.number}.lock.{device_id}"
        )
        self.entity_id: str = (
            f"securitas_direct.{installation.number}_lock_{device_id}"
        )
        self._time: datetime.datetime = datetime.datetime.now()
        self._message: str = ""
        self.installation: Installation = installation
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self.client: SecuritasHub = client
        self.hass: HomeAssistant = hass
        scan_seconds = client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._update_interval: timedelta = timedelta(seconds=scan_seconds)
        if scan_seconds > 0:
            self._update_unsub = async_track_time_interval(
                hass, self.async_update_status, self._update_interval
            )
        else:
            self._update_unsub = None

        # Build DeviceInfo from lock config instead of installation-level data
        lock_name = (
            lock_config.location
            if lock_config and lock_config.location
            else f"{installation.alias} Lock {device_id}"
        )
        lock_model = (
            lock_config.family if lock_config and lock_config.family else None
        )
        lock_serial = (
            lock_config.serialNumber
            if lock_config and lock_config.serialNumber
            else None
        )

        self._attr_device_info: DeviceInfo | None = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Securitas Direct",
            model=lock_model,
            name=lock_name,
            serial_number=lock_serial,
            via_device=(DOMAIN, f"securitas_direct.{installation.number}"),
        )

    def __force_state(self, state: str) -> None:
        self._last_state = self._state
        self._state = state
        if self.hass is not None:
            self.async_schedule_update_ha_state()

    def _notify_error(self, notification_id, title: str, message: str) -> None:
        """Notify user with persistent notification."""
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="create",
                service_data={
                    "title": title,
                    "message": message,
                    "notification_id": f"{DOMAIN}.{notification_id}",
                },
            )
        )

    @property
    def name(self) -> str:  # type: ignore[override]
        """Return the name of the device."""
        if self._lock_config and self._lock_config.location:
            return self._lock_config.location
        return f"{self.installation.alias} Lock {self._device_id}"

    @property
    def changed_by(self) -> str:  # type: ignore[override]
        """Return the last change triggered by."""
        return self._changed_by

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        if self._update_unsub:
            self._update_unsub()  # Unsubscribe from updates
            self._update_unsub = None

    async def async_update(self) -> None:
        await self.async_update_status()

    async def async_update_status(self, now=None) -> None:
        if self.hass is None:
            return
        try:
            self._new_state = await self.get_lock_state()
            if self._new_state != LOCK_STATUS_UNKNOWN:
                self._state = self._new_state
        except SecuritasDirectError as err:
            _LOGGER.error("Error updating Securitas lock state: %s", err)

    async def get_lock_state(self) -> str:
        lock_modes: list[SmartLockMode] = (
            await self.client.session.get_lock_current_mode(self.installation)
        )
        # Find the entry matching this lock's device ID
        for mode in lock_modes:
            if mode.deviceId == self._device_id:
                return mode.lockStatus
        # Fallback: if only one lock returned without matching deviceId, use it
        if len(lock_modes) == 1:
            return lock_modes[0].lockStatus
        return LOCK_STATUS_UNKNOWN

    @property
    def is_locked(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_LOCKED

    @property
    def is_open(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_OPEN

    @property
    def is_locking(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_LOCKING

    @property
    def is_unlocking(self) -> bool:  # type: ignore[override]
        return False

    @property
    def is_opening(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_OPENING

    @property
    def is_jammed(self) -> bool:  # type: ignore[override]
        return False

    async def async_lock(self, **kwargs):
        self.__force_state(LOCK_STATUS_LOCKING)
        try:
            await self.client.session.change_lock_mode(
                self.installation, True, device_id=self._device_id
            )
        except SecuritasDirectError as err:
            _LOGGER.error("Lock operation failed: %s", err.args[0] if err.args else err)
            return

        self._state = LOCK_STATUS_LOCKED

    async def async_unlock(self, **kwargs):
        self.__force_state(LOCK_STATUS_OPENING)
        try:
            await self.client.session.change_lock_mode(
                self.installation, False, device_id=self._device_id
            )
        except SecuritasDirectError as err:
            _LOGGER.error(
                "Unlock operation failed: %s", err.args[0] if err.args else err
            )
            return

        self._state = LOCK_STATUS_OPEN

    @property
    def supported_features(self) -> int:  # type: ignore[override]
        """Return the list of supported features."""
        return 0
