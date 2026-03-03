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
    """Set up Securitas Direct based on config_entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    locks = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )
    for device in securitas_devices:
        services: list[Service] = await client.get_services(device.installation)
        for service in services:
            _LOGGER.debug("Service: %s", service.request)
            if service.request == DOORLOCK_SERVICE:
                locks.append(
                    SecuritasLock(
                        device.installation,
                        client=client,
                        hass=hass,
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
    ) -> None:
        self._state = LOCK_STATUS_LOCKED
        self._last_state = LOCK_STATUS_LOCKED
        self._new_state: str = LOCK_STATUS_LOCKED
        self._changed_by: str = ""
        self._device: str = installation.address
        self.entity_id: str = f"securitas_direct.{installation.number}"
        self._attr_unique_id: str | None = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message: str = ""
        self.installation: Installation = installation
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._device_id: str = SMARTLOCK_DEVICE_ID
        self.client: SecuritasHub = client
        self.hass: HomeAssistant = hass
        self._update_interval: timedelta = timedelta(
            seconds=client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

        self._update_unsub = async_track_time_interval(
            hass, self.async_update_status, self._update_interval
        )

        self._attr_device_info: DeviceInfo | None = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )

    def __force_state(self, state: str) -> None:
        self._last_state = self._state
        self._state = state
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
        return self.installation.alias

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
        try:
            self._new_state = await self.get_lock_state()
            if self._new_state != LOCK_STATUS_UNKNOWN:
                self._state = self._new_state
        except SecuritasDirectError as err:
            _LOGGER.error("Error updating Securitas lock state: %s", err)

    async def get_lock_state(self) -> str:
        smartlock_status: SmartLockMode = (
            await self.client.session.get_lock_current_mode(self.installation)
        )
        if smartlock_status.deviceId:
            self._device_id = smartlock_status.deviceId
        return smartlock_status.lockStatus

    @property
    def is_locked(self) -> bool:  # type: ignore[override]
        if self._state == LOCK_STATUS_LOCKED:
            return True
        else:
            return False

    @property
    def is_open(self) -> bool:  # type: ignore[override]
        if self._state == LOCK_STATUS_OPEN:
            return True
        else:
            return False

    @property
    def is_locking(self) -> bool:  # type: ignore[override]
        if self._state == LOCK_STATUS_LOCKING:
            return True
        else:
            return False

    @property
    def is_unlocking(self) -> bool:  # type: ignore[override]
        return False

    @property
    def is_opening(self) -> bool:  # type: ignore[override]
        if self._state == LOCK_STATUS_OPENING:
            return True
        else:
            return False

    @property
    def is_jammed(self) -> bool:  # type: ignore[override]
        return False

    async def async_lock(self, **kwargs):
        self.__force_state(LOCK_STATUS_LOCKING)
        try:
            await self.client.session.change_lock_mode(
                self.installation, True, self._device_id
            )
        except SecuritasDirectError as err:
            _LOGGER.error(err.args)
            return

        self._state = LOCK_STATUS_LOCKED

    async def async_unlock(self, **kwargs):
        self.__force_state(LOCK_STATUS_OPENING)
        try:
            await self.client.session.change_lock_mode(
                self.installation, False, self._device_id
            )
        except SecuritasDirectError as err:
            _LOGGER.error(err.args)
            return

        self._state = LOCK_STATUS_OPEN

    @property
    def supported_features(self) -> int:  # type: ignore[override]
        """Return the list of supported features."""
        return 0
