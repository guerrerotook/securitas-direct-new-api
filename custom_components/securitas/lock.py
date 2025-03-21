import asyncio
import datetime
from datetime import timedelta
import logging
from typing import Any

import homeassistant.components.lock as lock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CODE, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
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
    CommandType,
    DisarmStatus,
    Installation,
    SecuritasDirectError,
    SmartLockMode,
    SmartLockModeStatus,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=20)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Securitas Direct based on config_entry."""
    client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
    locks = []
    securitas_devices: list[SecuritasDirectDevice] = hass.data[DOMAIN].get(
        CONF_INSTALLATION_KEY
    )
    for devices in securitas_devices:
        locks.append(
            SecuritasLock(
                devices.installation,
                #state=LockState.LOCKED,
                client=client,
                hass=hass,
            )
        )
    async_add_entities(locks, True)


class SecuritasLock(lock.LockEntity):
    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
    ) -> None:
        self._state = "2" # locked
        self._changed_by: str = ""
        self._device: str = installation.address
        self.entity_id: str = f"securitas_direct.{installation.number}"
        self._attr_unique_id: str = f"securitas_direct.{installation.number}"
        self._time: datetime.datetime = datetime.datetime.now()
        self._message: str = ""
        self.installation: Installation = installation
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self.client: SecuritasHub = client
        self.hass: HomeAssistant = hass
        self._update_interval: timedelta = timedelta(
            seconds=client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

        self._update_unsub = async_track_time_interval(
            hass, self.async_update_status, self._update_interval
        )
        
        self._attr_device_info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            manufacturer="Securitas Direct",
            model=installation.panel,
            name=installation.alias,
            hw_version=installation.type,
        )
        #self.async_update_status(state)

    def __force_state(self, state: str) -> None:
        self._last_status = self._state
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
    def name(self) -> str:
        """Return the name of the device."""
        return "Puerta"

    @property
    def changed_by(self) -> str:
        """Return the last change triggered by."""
        return self._changed_by

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        if self._update_unsub:
            self._update_unsub()  # Unsubscribe from updates

    async def async_update(self) -> None:
        await self.async_update_status()
    
    async def async_update_status(self, now=None) -> None:
        self._state = await self.get_lock_state()

    async def get_lock_state(self) -> str:
        smartlock_status: SmartLockMode = await self.client.session.get_lock_current_mode(
            self.installation
        )
        return smartlock_status.lockStatus

    @property
    def is_locked(self) -> bool:
        if self._state == "2":
            return True
        else:
            return False

    @property
    def is_open(self) -> bool:
        if self._state == "1":
            return True
        else:
            return False

    @property
    def is_locking(self) -> bool:
        return False

    @property
    def is_unlocking(self) -> bool:
        return False

    @property
    def is_opening(self) -> bool:
        return False

    @property
    def is_jammed(self) -> bool:
        return False

    async def async_lock(self, **kwargs):
        lock_status: SmartLockModeStatus = SmartLockModeStatus()
        try:
            lock_status = await self.client.session.change_lock_mode(self.installation, True)
        except SecuritasDirectError as err:
            _LOGGER.error(err.args)
            return
        
        self._state = "2"

    async def async_unlock(self, **kwargs):
        lock_status: SmartLockModeStatus = SmartLockModeStatus()
        try:
            lock_status = await self.client.session.change_lock_mode(self.installation, False)
        except SecuritasDirectError as err:
            _LOGGER.error(err.args)
            return
        
        self._state = "1"

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return (
            0
        )