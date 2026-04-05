"""Securitas Direct smart lock platform."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components import lock
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, SecuritasHub
from .coordinators import LockCoordinator
from .securitas_direct_new_api import (
    Installation,
    SecuritasDirectError,
    SmartLock,
)
from .api_queue import ApiQueue
from .securitas_direct_new_api.client import SMARTLOCK_DEVICE_ID

if TYPE_CHECKING:
    from .securitas_direct_new_api import SmartLockMode

_LOGGER = logging.getLogger(__name__)

# Service request name that identifies a smart-lock capability
DOORLOCK_SERVICE = "DOORLOCK"

# lockStatus codes returned by the Securitas smart-lock API
LOCK_STATUS_UNKNOWN = "0"
LOCK_STATUS_UNLOCKED = "1"
LOCK_STATUS_LOCKED = "2"
LOCK_STATUS_UNLOCKING = "3"
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


class SecuritasLock(CoordinatorEntity[LockCoordinator], lock.LockEntity):
    """Representation of a Securitas Direct smart lock."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: LockCoordinator,
        installation: Installation,
        client: SecuritasHub,
        device_id: str = SMARTLOCK_DEVICE_ID,
        initial_status: str = LOCK_STATUS_LOCKED,
        lock_config: SmartLock | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._installation = installation
        self._client = client
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
                lock_config.serial_number
                if lock_config and lock_config.serial_number
                else None
            ),
        )

        self._operation_in_progress: bool = False
        self._config_retry_unsubs: list[Callable[[], None]] = []

    # -- Properties ----------------------------------------------------------

    @property
    def installation(self) -> Installation:
        """Return the installation."""
        return self._installation

    @property
    def client(self) -> SecuritasHub:
        """Return the client hub."""
        return self._client

    @property
    def lock_config(self) -> SmartLock | None:
        """Return the current lock configuration."""
        return self._lock_config

    @property
    def device_id(self) -> str:
        """Return the device ID."""
        return self._device_id

    def update_lock_config(self, lock_config: SmartLock) -> None:
        """Update lock configuration after deferred retry."""
        self._lock_config = lock_config
        if lock_config.location:
            self._attr_name = lock_config.location
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"v4_securitas_direct.{self._installation.number}_lock_{self._device_id}",
                )
            },
            via_device=(DOMAIN, f"v4_securitas_direct.{self._installation.number}"),
            name=self._attr_name,
            manufacturer="Securitas Direct",
            model=lock_config.family or None,
            serial_number=lock_config.serial_number or None,
        )
        self.async_write_ha_state()

    def add_config_retry_unsub(self, unsub: Callable[[], None]) -> None:
        """Track a config retry cancel handle for cleanup on removal."""
        self._config_retry_unsubs.append(unsub)

    # -- Coordinator integration ---------------------------------------------

    @property
    def _current_mode(self) -> SmartLockMode | None:
        """Find this lock's mode in coordinator data."""
        if self.coordinator.data is None:
            return None
        for mode in self.coordinator.data.modes:
            if mode.device_id == self._device_id:
                return mode
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator.

        Skip coordinator-driven state writes while a lock/unlock
        operation is in progress to avoid overwriting transitional state.
        """
        if self._operation_in_progress:
            return

        # Sync _state from coordinator data
        mode = self._current_mode
        if mode is not None and mode.lock_status != LOCK_STATUS_UNKNOWN:
            self._state = mode.lock_status

        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        await super().async_will_remove_from_hass()
        for unsub in self._config_retry_unsubs:
            unsub()
        self._config_retry_unsubs.clear()

    # -- State properties ----------------------------------------------------

    @property
    def changed_by(self) -> str:  # type: ignore[override]
        """Return the last change triggered by."""
        return self._changed_by

    @property
    def is_locked(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_LOCKED

    @property
    def is_open(self) -> bool:  # type: ignore[override]
        return False

    @property
    def is_locking(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_LOCKING

    @property
    def is_unlocking(self) -> bool:  # type: ignore[override]
        return self._state == LOCK_STATUS_UNLOCKING

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
            attrs["hold_back_latch_time"] = cfg.features.hold_back_latch_time
            if cfg.features.autolock:
                attrs["autolock_active"] = cfg.features.autolock.active
                attrs["autolock_timeout"] = cfg.features.autolock.timeout
        return attrs

    # -- Lock/unlock operations ----------------------------------------------

    def _force_state(self, state: str) -> None:
        """Force entity state and schedule HA update."""
        self._last_state = self._state
        self._state = state
        if self.hass is not None:
            self.async_schedule_update_ha_state()

    async def _change_lock_mode(
        self,
        lock_state: bool,
        transitional_state: str,
        optimistic_state: str,
        operation: str,
    ) -> None:
        """Send lock command, then poll for real status.

        Sets a transitional state (e.g. LOCKING) immediately, sends the
        command (which waits for the lock to physically act), then fetches
        the actual lock status from the API.
        """
        self._operation_in_progress = True
        self._force_state(transitional_state)
        try:
            try:
                await self._client.change_lock_mode(
                    self._installation, lock_state, self._device_id
                )
            except SecuritasDirectError as err:
                self._state = self._last_state
                self.async_write_ha_state()
                _LOGGER.error(
                    "%s operation failed for %s device %s: %s",
                    operation,
                    self._installation.number,
                    self._device_id,
                    err.log_detail(),
                )
                return

            # Fetch the real status from the API now that the lock has had
            # time to act.  Catch broadly: aiohttp can raise TimeoutError,
            # ClientError etc. in addition to SecuritasDirectError.
            try:
                real_state = await self._get_lock_state(priority=ApiQueue.FOREGROUND)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                real_state = LOCK_STATUS_UNKNOWN

            if real_state != LOCK_STATUS_UNKNOWN:
                self._state = real_state
            else:
                self._state = optimistic_state
            self.async_write_ha_state()
        finally:
            self._operation_in_progress = False
            await self.coordinator.async_request_refresh()

    async def _get_lock_state(self, *, priority: int | None = None) -> str:
        """Return the current lock status from the API."""
        lock_modes: list[SmartLockMode] = await self._client.get_lock_modes(
            self._installation, priority=priority
        )
        for mode in lock_modes:
            if mode.device_id == self._device_id:
                return mode.lock_status
        return LOCK_STATUS_UNKNOWN

    async def async_lock(self, **kwargs: Any) -> None:
        await self._change_lock_mode(
            lock_state=True,
            transitional_state=LOCK_STATUS_LOCKING,
            optimistic_state=LOCK_STATUS_LOCKED,
            operation="Lock",
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._change_lock_mode(
            lock_state=False,
            transitional_state=LOCK_STATUS_UNLOCKING,
            optimistic_state=LOCK_STATUS_UNLOCKED,
            operation="Unlock",
        )

    async def async_open(self, **kwargs: Any) -> None:
        await self._change_lock_mode(
            lock_state=False,
            transitional_state=LOCK_STATUS_UNLOCKING,
            optimistic_state=LOCK_STATUS_UNLOCKED,
            operation="Open",
        )

    @property
    def supported_features(self) -> lock.LockEntityFeature:  # type: ignore[override]
        """Return the list of supported features."""
        cfg = self._lock_config
        if (
            cfg
            and cfg.features
            and cfg.features.hold_back_latch_time
            and cfg.features.hold_back_latch_time > 0
        ):
            return lock.LockEntityFeature.OPEN
        return lock.LockEntityFeature(0)
