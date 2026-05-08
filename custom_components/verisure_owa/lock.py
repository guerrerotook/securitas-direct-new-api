"""Verisure OWA smart lock platform."""

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

from . import DOMAIN, VerisureHub
from .const import (
    CONF_LOCK_AUTOMATIONS,
    CIRCUIT_INTERIOR,
    CIRCUIT_PERIMETER,
    CIRCUIT_ANNEX,
    LOCK_CIRCUITS,
)
from .coordinators import LockCoordinator
from .entity import VerisureEntity
from .verisure_owa_api import (
    Installation,
    VerisureOwaError,
    SmartLock,
)
from .api_queue import ApiQueue
from .verisure_owa_api.client import SMARTLOCK_DEVICE_ID
from .verisure_owa_api.models import (
    AlarmState,
    InteriorMode,
    PerimeterMode,
    AnnexMode,
)

if TYPE_CHECKING:
    from .verisure_owa_api import SmartLockMode

_LOGGER = logging.getLogger(__name__)


def _armed_circuits(state: AlarmState) -> set[str]:
    """Return the set of circuit labels currently armed (mode != OFF)."""
    armed: set[str] = set()
    if state.interior != InteriorMode.OFF:
        armed.add(CIRCUIT_INTERIOR)
    if state.perimeter != PerimeterMode.OFF:
        armed.add(CIRCUIT_PERIMETER)
    if state.annex != AnnexMode.OFF:
        armed.add(CIRCUIT_ANNEX)
    return armed

# Service request name that identifies a smart-lock capability
DOORLOCK_SERVICE = "DOORLOCK"

# lockStatus codes returned by the Verisure smart-lock API
LOCK_STATUS_UNKNOWN = "0"
LOCK_STATUS_UNLOCKED = "1"
LOCK_STATUS_LOCKED = "2"
LOCK_STATUS_UNLOCKING = "3"
LOCK_STATUS_LOCKING = "4"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Verisure OWA lock entities.

    No API calls are made here.  Lock devices are discovered
    asynchronously after startup and added via the stored callback.
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data["lock_add_entities"] = async_add_entities


class VerisureLock(  # type: ignore[override]
    VerisureEntity,
    CoordinatorEntity[LockCoordinator],
    lock.LockEntity,
):
    """Representation of a Verisure OWA smart lock."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: LockCoordinator,
        installation: Installation,
        client: VerisureHub,
        device_id: str = SMARTLOCK_DEVICE_ID,
        initial_status: str = LOCK_STATUS_LOCKED,
        lock_config: SmartLock | None = None,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)  # type: ignore[arg-type]
        VerisureEntity.__init__(self, installation, client)
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
        self._attr_unique_id = f"v5_verisure_owa.{installation.number}_lock_{device_id}"

        # Override device_info: each lock gets its own device, linked to
        # the installation device via via_device.
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"v5_verisure_owa.{installation.number}_lock_{device_id}")
            },
            via_device=(DOMAIN, f"v5_verisure_owa.{installation.number}"),
            name=name,
            manufacturer="Verisure",
            model=lock_config.family if lock_config and lock_config.family else None,
            serial_number=(
                lock_config.serial_number
                if lock_config and lock_config.serial_number
                else None
            ),
        )

        self._operation_in_progress: bool = False
        self._config_retry_unsubs: list[Callable[[], None]] = []

        # Auto-lock state — populated when added to hass.
        self._alarm_coordinator = None  # set by async_added_to_hass
        self._combined_alarm_panel = None  # set by async_added_to_hass
        self._alarm_listener_unsub: Callable[[], None] | None = None
        self._alarm_baseline: set[str] | None = None  # armed circuits at last update
        self._lock_on_arm_circuits: list[str] = []
        self._unlock_disarms_circuits: list[str] = []

    # -- Properties ----------------------------------------------------------

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
                    f"v5_verisure_owa.{self._installation.number}_lock_{self._device_id}",
                )
            },
            via_device=(DOMAIN, f"v5_verisure_owa.{self._installation.number}"),
            name=self._attr_name,
            manufacturer="Verisure",
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

    @callback
    def _handle_alarm_coordinator_update(self) -> None:
        """React to alarm-coordinator updates.

        Establishes a baseline on first call (no firing). On subsequent
        calls, detects disarmed→armed transitions for circuits in
        ``self._lock_on_arm_circuits`` and fires the lock if needed.
        """
        if self._alarm_coordinator is None:
            return
        new_armed = _armed_circuits(self._alarm_coordinator.alarm_state)
        prev = self._alarm_baseline
        self._alarm_baseline = new_armed
        if prev is None:
            # First update — establish baseline only.
            return
        if not self._lock_on_arm_circuits:
            return
        # Circuits that just transitioned disarmed→armed.
        newly_armed = new_armed - prev
        triggers = newly_armed.intersection(self._lock_on_arm_circuits)
        if not triggers:
            return
        # Idempotency: skip if already locked / locking / mid-operation.
        if self._operation_in_progress:
            return
        if self._state in (LOCK_STATUS_LOCKED, LOCK_STATUS_LOCKING):
            return
        # Schedule the lock as a background task — listeners must not
        # block the coordinator-update path.
        if self.hass is not None:
            self.hass.async_create_task(self._auto_lock())

    def _autolock_notification_id(self) -> str:
        return (
            f"verisure_owa_autolock_{self._installation.number}_{self._device_id}"
        )

    async def _fire_autolock_notification(
        self, *, title: str, message: str
    ) -> None:
        """Create / replace a persistent notification for an autolock event."""
        if self.hass is None:
            return
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": self._autolock_notification_id(),
                "title": title,
                "message": message,
            },
            blocking=False,
        )

    async def _auto_lock(self) -> None:
        """Perform an auto-lock-on-arm action.

        On failure (VerisureOwaError or post-call state still unlocked),
        creates a persistent notification.
        """
        await self._change_lock_mode(
            lock_state=True,
            transitional_state=LOCK_STATUS_LOCKING,
            optimistic_state=LOCK_STATUS_LOCKED,
            operation="Auto-lock",
        )
        if self._state != LOCK_STATUS_LOCKED:
            await self._fire_autolock_notification(
                title="Auto-lock failed",
                message=(
                    f"Could not lock {self._attr_name} when arming. "
                    f"The alarm is armed but the door is unlocked."
                ),
            )

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
            except VerisureOwaError as err:
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
            # ClientError etc. in addition to VerisureOwaError.
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
        await self._dispatch_unlock_disarm()
        await self._change_lock_mode(
            lock_state=False,
            transitional_state=LOCK_STATUS_UNLOCKING,
            optimistic_state=LOCK_STATUS_UNLOCKED,
            operation="Unlock",
        )

    async def async_open(self, **kwargs: Any) -> None:
        await self._dispatch_unlock_disarm()
        await self._change_lock_mode(
            lock_state=False,
            transitional_state=LOCK_STATUS_UNLOCKING,
            optimistic_state=LOCK_STATUS_UNLOCKED,
            operation="Open",
        )

    async def _dispatch_unlock_disarm(self) -> None:
        """Disarm configured circuits before unlocking.

        Skipped when no circuits are configured, when the panel is not
        registered yet, or when no configured circuit is currently
        armed. Failure handling lives in Task 9.
        """
        if not self._unlock_disarms_circuits:
            return
        if self._combined_alarm_panel is None:
            return
        if self._alarm_coordinator is None:
            return
        currently_armed = _armed_circuits(self._alarm_coordinator.alarm_state)
        targets = [
            c for c in self._unlock_disarms_circuits if c in currently_armed
        ]
        if not targets:
            return
        await self._combined_alarm_panel.execute_partial_disarm(targets)

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
