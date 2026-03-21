"""Securitas Direct smart lock platform."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components import lock

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasHub,
)
from .entity import SecuritasEntity
from .securitas_direct_new_api import (
    Installation,
    SecuritasDirectError,
    SmartLock,
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
        lock_config: SmartLock | None = None,
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
        self._lock_config: SmartLock | None = lock_config

        # Name: prefer lock_config.location if non-empty, else fallback
        name = (
            lock_config.location
            if lock_config and lock_config.location
            else f"{installation.alias} Lock {device_id}"
        )
        self._attr_name = name
        self._attr_unique_id = (
            f"v4_securitas_direct.{installation.number}_lock_{device_id}"
        )

        # Override device_info: each lock gets its own device, linked to
        # the installation device via via_device.
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"v4_securitas_direct.{installation.number}_lock_{device_id}")
            },
            via_device=(DOMAIN, f"v4_securitas_direct.{installation.number}"),
            name=name,
            manufacturer="Securitas Direct",
            model=lock_config.family if lock_config and lock_config.family else None,
            serial_number=(
                lock_config.serialNumber
                if lock_config and lock_config.serialNumber
                else None
            ),
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
        cfg = self._lock_config
        if cfg and cfg.features:
            attrs["hold_back_latch_time"] = cfg.features.holdBackLatchTime
            if cfg.features.autolock:
                attrs["autolock_active"] = cfg.features.autolock.active
                attrs["autolock_timeout"] = cfg.features.autolock.timeout
        return attrs

    async def _change_lock_mode(
        self,
        lock_state: bool,
        transitional_state: str,
        optimistic_state: str,
        operation: str,
    ) -> None:
        """Send lock command, then poll for real status.

        Sets a transitional state (e.g. LOCKING) immediately, sends the
        command, then fetches the actual lock status from the API.  Falls
        back to the optimistic state if the fresh poll returns UNKNOWN.
        """
        self._force_state(transitional_state)
        try:
            await self.client.change_lock_mode(
                self.installation, lock_state, self._device_id
            )
        except SecuritasDirectError as err:
            self._state = self._last_state
            self.async_write_ha_state()
            _LOGGER.error(
                "%s operation failed for %s device %s: %s",
                operation,
                self.installation.number,
                self._device_id,
                err.log_detail(),
            )
            return

        # Fetch the real status from the API now that the command has
        # been acknowledged.  Fall back to optimistic state on failure.
        try:
            real_state = await self.get_lock_state()
        except SecuritasDirectError:
            real_state = LOCK_STATUS_UNKNOWN

        self._state = (
            real_state if real_state != LOCK_STATUS_UNKNOWN else optimistic_state
        )
        self.async_write_ha_state()

    async def async_lock(self, **kwargs):
        await self._change_lock_mode(
            lock_state=True,
            transitional_state=LOCK_STATUS_LOCKING,
            optimistic_state=LOCK_STATUS_LOCKED,
            operation="Lock",
        )

    async def async_unlock(self, **kwargs):
        await self._change_lock_mode(
            lock_state=False,
            transitional_state=LOCK_STATUS_OPENING,
            optimistic_state=LOCK_STATUS_OPEN,
            operation="Unlock",
        )

    async def async_open(self, **kwargs):
        await self._change_lock_mode(
            lock_state=False,
            transitional_state=LOCK_STATUS_OPENING,
            optimistic_state=LOCK_STATUS_OPEN,
            operation="Open",
        )

    @property
    def supported_features(self) -> lock.LockEntityFeature:  # type: ignore[override]
        """Return the list of supported features."""
        cfg = self._lock_config
        if (
            cfg
            and cfg.features
            and cfg.features.holdBackLatchTime
            and cfg.features.holdBackLatchTime > 0
        ):
            return lock.LockEntityFeature.OPEN
        return lock.LockEntityFeature(0)
