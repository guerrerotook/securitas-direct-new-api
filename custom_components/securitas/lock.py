"""Securitas Direct smart lock platform."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components import lock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasHub,
)
from .entity import SecuritasEntity
from .securitas_direct_new_api import (
    DanalockConfig,
    Installation,
    SecuritasDirectError,
)
from .securitas_direct_new_api.apimanager import SMARTLOCK_DEVICE_ID

if TYPE_CHECKING:
    from .securitas_direct_new_api import SmartLockMode

_LOGGER = logging.getLogger(__name__)

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
    """Set up Securitas Direct lock entities.

    No API calls are made here.  Lock devices are discovered
    asynchronously after startup and added via the stored callback.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data["lock_add_entities"] = async_add_entities


class SecuritasLock(SecuritasEntity, lock.LockEntity):
    """Representation of a Securitas Direct smart lock."""

    def __init__(
        self,
        installation: Installation,
        client: SecuritasHub,
        hass: HomeAssistant,
        device_id: str = SMARTLOCK_DEVICE_ID,
        initial_status: str = LOCK_STATUS_LOCKED,
        danalock_config: DanalockConfig | None = None,
    ) -> None:
        super().__init__(installation, client)
        self._state = (
            initial_status
            if initial_status != LOCK_STATUS_UNKNOWN
            else LOCK_STATUS_LOCKED
        )
        self._last_state = self._state
        self._new_state: str = self._state
        self._changed_by: str = ""
        self._device: str = installation.address
        self._device_id: str = device_id
        self._danalock_config: DanalockConfig | None = danalock_config
        self._danalock_config_fetched: bool = danalock_config is not None

        self._attr_name = f"{installation.alias} Lock {device_id}"
        self._attr_unique_id = (
            f"securitas_direct.{installation.number}_lock_{device_id}"
        )

        self.hass: HomeAssistant = hass
        scan_seconds = client.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self._update_interval: timedelta = timedelta(seconds=scan_seconds)
        self._scan_seconds = scan_seconds
        self._update_unsub = None

    async def async_added_to_hass(self) -> None:
        """Register timer when entity is added to HA."""
        if self._scan_seconds > 0:
            self._update_unsub = async_track_time_interval(
                self.hass, self.async_update_status, self._update_interval
            )

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
        """Update lock state."""
        await self.async_update_status()

    async def async_update_status(self, _now=None) -> None:
        """Poll lock status from the API."""
        if self.hass is None:
            return

        # Lazily fetch Danalock config on first update (avoids blocking setup)
        if not self._danalock_config_fetched:
            self._danalock_config_fetched = True
            try:
                self._danalock_config = await self.client.get_danalock_config(
                    self.installation, self._device_id
                )
                cfg = self._danalock_config
                if cfg and cfg.features and cfg.features.holdBackLatchTime > 0:
                    _LOGGER.info(
                        "Lock %s on %s supports latch hold-back (%ds) — "
                        "open-door feature enabled",
                        self._device_id,
                        self.installation.number,
                        cfg.features.holdBackLatchTime,
                    )
            except (SecuritasDirectError, KeyError, TypeError):
                _LOGGER.debug(
                    "[%s] Could not fetch Danalock config for device %s",
                    self.entity_id,
                    self._device_id,
                )

        try:
            self._new_state = await self.get_lock_state()
            if self._new_state != LOCK_STATUS_UNKNOWN:
                self._state = self._new_state
        except SecuritasDirectError as err:
            _LOGGER.error(
                "Error updating lock state for %s device %s: %s",
                self.installation.number,
                self._device_id,
                err,
            )

        # When called from timer callback (_now is not None), HA does not
        # automatically write state — we must do it explicitly.
        if _now is not None:
            self.async_write_ha_state()

    async def get_lock_state(self) -> str:
        """Return the current lock status from the API."""
        lock_modes: list[SmartLockMode] = await self.client.get_lock_modes(
            self.installation
        )
        for mode in lock_modes:
            if mode.deviceId == self._device_id:
                return mode.lockStatus
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
        return self._state == LOCK_STATUS_OPENING

    @property
    def is_opening(self) -> bool:  # type: ignore[override]
        return False

    @property
    def is_jammed(self) -> bool:  # type: ignore[override]
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[override]
        """Return lock configuration as state attributes."""
        attrs: dict[str, Any] = {}
        if self._danalock_config:
            cfg = self._danalock_config
            attrs["battery_low_threshold"] = cfg.batteryLowPercentage
            attrs["lock_before_full_arm"] = cfg.lockBeforeFullArm == "1"
            attrs["lock_before_partial_arm"] = cfg.lockBeforePartialArm == "1"
            attrs["lock_before_perimeter_arm"] = cfg.lockBeforePerimeterArm == "1"
            attrs["unlock_after_disarm"] = cfg.unlockAfterDisarm == "1"
            attrs["auto_lock_time"] = cfg.autoLockTime
            if cfg.features:
                attrs["hold_back_latch_time"] = cfg.features.holdBackLatchTime
                if cfg.features.autolock:
                    attrs["autolock_active"] = cfg.features.autolock.active
                    attrs["autolock_timeout"] = cfg.features.autolock.timeout
        return attrs

    async def async_lock(self, **kwargs):
        self._force_state(LOCK_STATUS_LOCKING)
        try:
            await self.client.change_lock_mode(self.installation, True, self._device_id)
        except SecuritasDirectError as err:
            self._state = self._last_state
            self.async_write_ha_state()
            _LOGGER.error(
                "Lock operation failed for %s device %s: %s",
                self.installation.number,
                self._device_id,
                err.log_detail(),
            )
            return

        self._state = LOCK_STATUS_LOCKED
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs):
        self._force_state(LOCK_STATUS_OPENING)
        try:
            await self.client.change_lock_mode(
                self.installation, False, self._device_id
            )
        except SecuritasDirectError as err:
            self._state = self._last_state
            self.async_write_ha_state()
            _LOGGER.error(
                "Unlock operation failed for %s device %s: %s",
                self.installation.number,
                self._device_id,
                err.log_detail(),
            )
            return

        self._state = LOCK_STATUS_OPEN
        self.async_write_ha_state()

    async def async_open(self, **kwargs):
        self._force_state(LOCK_STATUS_OPENING)
        try:
            await self.client.change_lock_mode(
                self.installation, False, self._device_id
            )
        except SecuritasDirectError as err:
            self._state = self._last_state
            self.async_write_ha_state()
            _LOGGER.error(
                "Open operation failed for %s device %s: %s",
                self.installation.number,
                self._device_id,
                err.log_detail(),
            )
            return

        self._state = LOCK_STATUS_OPEN
        self.async_write_ha_state()

    @property
    def supported_features(self) -> lock.LockEntityFeature:  # type: ignore[override]
        """Return the list of supported features."""
        cfg = self._danalock_config
        if (
            cfg
            and cfg.features
            and cfg.features.holdBackLatchTime
            and cfg.features.holdBackLatchTime > 0
        ):
            return lock.LockEntityFeature.OPEN
        return lock.LockEntityFeature(0)
