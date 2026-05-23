"""Verisure OWA smart lock platform."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components import lock
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, VerisureHub
from .const import (
    CONF_LOCK_AUTOMATIONS,
    CIRCUIT_INTERIOR,
    CIRCUIT_PERIMETER,
    CIRCUIT_ANNEX,
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


def _ts_is_newer(read_ts: str, base_ts: str) -> bool:
    """Return True if ``read_ts`` is strictly newer than ``base_ts``.

    Lock ``statusTimestamp`` values are millisecond-epoch strings.  A reading
    of the target state only counts as a *real* actuation if its timestamp has
    advanced past the pre-command baseline — otherwise it may be a stale,
    not-yet-propagated read of the old state.  When either value is missing or
    non-numeric we can't compare, so we return False (treat as stale).  Under
    the "any fresh read is authoritative" verify semantics, a True fallback
    would short-circuit the verify loop on the very first read whenever the
    backend omitted ``statusTimestamp`` — handing back whatever pre-command
    state it echoed before the device had actuated.  Returning False keeps the
    loop polling; the quiet-success-on-target branch in ``_poll_lock_until`` is
    the safety net for genuine no-op commands that never re-stamp.
    """
    try:
        return int(read_ts) > int(base_ts)
    except (TypeError, ValueError):
        return False


# Service request name that identifies a smart-lock capability
DOORLOCK_SERVICE = "DOORLOCK"

# lockStatus codes returned by the Verisure smart-lock API
LOCK_STATUS_UNKNOWN = "0"
LOCK_STATUS_UNLOCKED = "1"
LOCK_STATUS_LOCKED = "2"
LOCK_STATUS_UNLOCKING = "3"
LOCK_STATUS_LOCKING = "4"

# Verification poll: the Verisure backend acks a lock/unlock command BEFORE the
# device physically actuates (and its status is eventually-consistent), so a
# single immediate read-back races ahead of reality.  We re-read the status up
# to LOCK_VERIFY_ATTEMPTS times, LOCK_VERIFY_DELAY seconds apart, confirming
# success the moment we see the target state with a *fresh* statusTimestamp
# (newer than the pre-command baseline).  A stale target reading does not
# confirm, which closes the "armed + silently unlocked" hole.
#
# The fresh-timestamp gate makes *success* fast (early-return), but it does NOT
# let us shorten the window: a still-completing lock and a genuinely-failed one
# both read as pre-command UNLOCKED (the door simply hasn't moved yet) and are
# indistinguishable except by waiting out the physical actuation.  So the
# ceiling must still cover the worst case.  Upstream PR #413 measured ~6s to
# start + ~4.5s to complete (~10.5s typical) and validated a 15s wait; 7
# attempts × 3s spans ~18s, comfortably past that, so we never declare failure
# before the lock has had time to act.  (This wait was lost when
# change_lock_mode moved to the generic submit-and-poll scaffold, which returns
# on the ~2s command ack.)  Until the cache removal in this branch, this
# verify silently polled a 60s TTL cache that absorbed 6 of 7 reads
# instead of hitting the backend — once that was removed, the verify
# actually polls the API on every attempt.  Tune from the statusTimestamp
# values in the verify debug logs.
LOCK_VERIFY_ATTEMPTS = 7
LOCK_VERIFY_DELAY = 3.0


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

        # Verification-poll tuning (overridable in tests).
        self._verify_attempts: int = LOCK_VERIFY_ATTEMPTS
        self._verify_delay: float = LOCK_VERIFY_DELAY

        # Auto-lock state — populated when added to hass.
        self._entry_id: str | None = None  # set externally before async_added_to_hass
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
                    f"v4_securitas_direct.{self._installation.number}_lock_{self._device_id}",
                )
            },
            via_device=(DOMAIN, f"v4_securitas_direct.{self._installation.number}"),
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
        # Skip only when a lock operation is genuinely in flight — never just
        # because the cached state reads LOCKED.  That cache is
        # eventually-consistent and can be stale (e.g. the user physically
        # unlocked moments before arming and the backend hasn't propagated it):
        # trusting it would silently leave the door unlocked while armed.
        # A redundant lock command on an already-locked door is harmless.
        if self._operation_in_progress or self._state == LOCK_STATUS_LOCKING:
            _LOGGER.debug(
                "Auto-lock-on-arm skipped for %s device %s: operation already "
                "in progress (state=%s)",
                self._installation.number,
                self._device_id,
                self._state,
            )
            return
        _LOGGER.debug(
            "Auto-lock-on-arm triggered for %s device %s: circuits %s armed "
            "(cached lock state=%s)",
            self._installation.number,
            self._device_id,
            sorted(triggers),
            self._state,
        )
        # Schedule the lock as a background task — listeners must not
        # block the coordinator-update path.
        if self.hass is not None:
            self.hass.async_create_task(self._auto_lock())

    def _autolock_notification_id(self) -> str:
        return f"verisure_owa_autolock_{self._installation.number}_{self._device_id}"

    async def _fire_autolock_notification(self, *, title: str, message: str) -> None:
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

        On a definitive failure (post-call state still unlocked), creates a
        persistent notification.  Never raises — this runs as a background
        task with no caller waiting on its result.  The post-state check
        (not the ``_change_lock_mode`` return) preserves the
        bias-to-false-negative: a redundant lock command that errors on an
        already-locked door produces a notification-worthy error reason but
        the door is in the right state, so we stay quiet here.
        """
        await self._change_lock_mode(
            lock_state=True,
            transitional_state=LOCK_STATUS_LOCKING,
            optimistic_state=LOCK_STATUS_LOCKED,
            operation="Auto-lock",
        )
        if self._state == LOCK_STATUS_UNLOCKED:
            await self._fire_autolock_notification(
                title="Auto-lock failed",
                message=(
                    f"Could not lock {self._attr_name} when arming. "
                    f"The alarm is armed but the door is unlocked."
                ),
            )

    async def async_added_to_hass(self) -> None:
        """Wire up auto-lock listener and load per-lock options."""
        await super().async_added_to_hass()
        if self.hass is None or self._entry_id is None:
            return
        entry_data = self.hass.data[DOMAIN].get(self._entry_id)
        if not entry_data:
            return
        self._alarm_coordinator = entry_data.get("alarm_coordinator")
        panels_by_inst = entry_data.get("combined_alarm_panels", {})
        self._combined_alarm_panel = panels_by_inst.get(self._installation.number)
        config_entry = entry_data.get("config_entry")
        if config_entry is not None:
            options = config_entry.options.get(CONF_LOCK_AUTOMATIONS, {})
            per_lock = options.get(self._device_id, {})
            self._lock_on_arm_circuits = list(per_lock.get("lock_on_arm", []))
            self._unlock_disarms_circuits = list(per_lock.get("unlock_disarms", []))
        # Establish baseline + subscribe.
        if self._alarm_coordinator is not None:
            # Read the current state to seed the baseline (no firing).
            self._alarm_baseline = _armed_circuits(self._alarm_coordinator.alarm_state)
            self._alarm_listener_unsub = self._alarm_coordinator.async_add_listener(
                self._handle_alarm_coordinator_update
            )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from Home Assistant."""
        await super().async_will_remove_from_hass()
        if self._alarm_listener_unsub is not None:
            self._alarm_listener_unsub()
            self._alarm_listener_unsub = None
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
    ) -> str | None:
        """Send lock command, then poll for real status.

        Sets a transitional state (e.g. LOCKING) immediately, reads a fresh
        pre-command baseline timestamp, sends the command (which waits for
        the backend's ~2s acknowledgement), then polls until a real, fresh
        status reading lands or the verify window exhausts.

        Returns ``None`` on success or on a bias-to-false-negative fallback
        (verify window exhausted with no readable status → optimistic state).
        Returns a short error reason string on definitive failure: a
        ``VerisureOwaError`` from the command itself, OR the verify loop
        confirming a fresh post-command state that is not the target.
        Callers decide how to surface failure (notification, raise, both).
        """
        self._operation_in_progress = True
        self._force_state(transitional_state)
        # Read a FRESH baseline timestamp from the API (not coordinator data,
        # which can be minutes stale or even older than the actual current
        # backend timestamp if the lock was physically moved since the last
        # coordinator update).  The verify poll needs a baseline taken at the
        # moment of the command to reliably distinguish a real actuation from
        # a stale read of any prior state.  Done AFTER setting
        # _operation_in_progress so a concurrent coordinator update can't
        # clobber the transitional state during this read.
        try:
            pre_mode = await self._read_lock_mode(priority=ApiQueue.FOREGROUND)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            pre_mode = None
        pre_ts = pre_mode.status_timestamp if pre_mode is not None else ""
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
                return err.message

            # Verify by polling the real status until it reaches the target
            # with a fresh timestamp.  The backend acks before the device
            # physically actuates, so a single immediate read races ahead of
            # the lock.
            real_state = await self._poll_lock_until(
                optimistic_state, operation, pre_ts
            )

            if real_state != LOCK_STATUS_UNKNOWN:
                self._state = real_state
            else:
                self._state = optimistic_state
            self.async_write_ha_state()

            # Definite failure: the verify loop got a fresh post-command read
            # that is neither the target nor UNKNOWN — the device reported a
            # real, wrong state (e.g. bolt blocked).  UNKNOWN stays a quiet
            # success per the bias-to-false-negative contract.
            if real_state not in (LOCK_STATUS_UNKNOWN, optimistic_state):
                return (
                    f"door reports lockStatus={real_state} after "
                    f"{operation.lower()} command (expected {optimistic_state})"
                )
            return None
        finally:
            self._operation_in_progress = False
            # Nudge the coordinator so other lock entities on the same
            # installation pick up the new state; this entity's own state
            # was already settled by _poll_lock_until above.
            await self.coordinator.async_request_refresh()

    async def _poll_lock_until(self, target: str, operation: str, pre_ts: str) -> str:
        """Re-read lock status until a fresh reading lands or the window runs out.

        Any read with a ``statusTimestamp`` newer than ``pre_ts`` is treated as
        authoritative: the device has reported its true post-command state, so we
        return immediately whether or not it matches ``target``.  Stale reads
        (``statusTimestamp <= pre_ts``) keep polling — they may be pre-command
        state propagating slowly.  When the window exhausts on stale reads but
        the value is sitting at ``target`` (a likely no-op on an already-settled
        lock that didn't re-stamp), that target value is returned as a quiet
        success.  Otherwise the last stale status is returned.  Logs every
        attempt with its ``statusTimestamp`` so the window can be tuned from logs.
        """
        last_status = LOCK_STATUS_UNKNOWN
        for attempt in range(1, self._verify_attempts + 1):
            try:
                mode = await self._read_lock_mode(priority=ApiQueue.FOREGROUND)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                mode = None

            if mode is not None:
                last_status = mode.lock_status
                fresh = _ts_is_newer(mode.status_timestamp, pre_ts)
                _LOGGER.debug(
                    "%s verify %d/%d for %s device %s: lockStatus=%s "
                    "statusTimestamp=%s (pre=%s fresh=%s target=%s)",
                    operation,
                    attempt,
                    self._verify_attempts,
                    self._installation.number,
                    self._device_id,
                    mode.lock_status,
                    mode.status_timestamp,
                    pre_ts,
                    fresh,
                    target,
                )
                if fresh:
                    # Any fresh read is authoritative — the device has spoken.  Either it
                    # matches the target (success, fast happy-path) or it doesn't (real
                    # failure with a real-state response, e.g. lock blocked).  Either way,
                    # no point polling further; return the confirmed status.
                    return last_status
            else:
                _LOGGER.debug(
                    "%s verify %d/%d for %s device %s: no status returned (target=%s)",
                    operation,
                    attempt,
                    self._verify_attempts,
                    self._installation.number,
                    self._device_id,
                    target,
                )

            if attempt < self._verify_attempts:
                await asyncio.sleep(self._verify_delay)

        _LOGGER.debug(
            "%s verify window exhausted for %s device %s after %d attempts; "
            "last lockStatus=%s (target=%s)",
            operation,
            self._installation.number,
            self._device_id,
            self._verify_attempts,
            last_status,
            target,
        )
        return last_status

    async def _read_lock_mode(
        self, *, priority: int | None = None
    ) -> SmartLockMode | None:
        """Return this device's SmartLockMode from the API, or None."""
        lock_modes: list[SmartLockMode] = await self._client.get_lock_modes(
            self._installation, priority=priority
        )
        for mode in lock_modes:
            if mode.device_id == self._device_id:
                return mode
        return None

    async def _notify_and_raise_on_failure(
        self, *, action: str, error_reason: str
    ) -> None:
        """Surface a service-call failure: persistent notification + raise.

        The notification gives UI users a record after the toast disappears;
        the raise propagates the failure to scripts/automations via the HA
        service call.  Title is "{Action} failed" (e.g. "Lock failed",
        "Unlock failed"); message includes the underlying reason for
        diagnosis.
        """
        title = f"{action} failed"
        message = f"Could not {action.lower()} {self._attr_name}: {error_reason}"
        await self._fire_autolock_notification(title=title, message=message)
        raise HomeAssistantError(message)

    async def async_lock(self, **kwargs: Any) -> None:
        error = await self._change_lock_mode(
            lock_state=True,
            transitional_state=LOCK_STATUS_LOCKING,
            optimistic_state=LOCK_STATUS_LOCKED,
            operation="Lock",
        )
        if error is not None:
            await self._notify_and_raise_on_failure(action="Lock", error_reason=error)

    async def _dispatch_unlock_disarm(self) -> bool | None:
        """Disarm configured circuits before unlocking.

        Returns:
            None  — disarm was skipped (nothing to do).
            True  — disarm was attempted and succeeded.
            False — disarm was attempted and failed (notification already fired).

        The unlock always proceeds regardless of the return value.
        """
        if not self._unlock_disarms_circuits:
            return None
        if self._combined_alarm_panel is None or self._alarm_coordinator is None:
            return None
        currently_armed = _armed_circuits(self._alarm_coordinator.alarm_state)
        targets = [c for c in self._unlock_disarms_circuits if c in currently_armed]
        if not targets:
            return None
        ok = await self._combined_alarm_panel.execute_partial_disarm(targets)
        if not ok:
            await self._fire_autolock_notification(
                title="Auto-disarm failed",
                message=(
                    f"Could not disarm before unlocking {self._attr_name}. "
                    f"The door will be unlocked but the alarm may still be armed."
                ),
            )
        return ok

    async def _perform_user_unlock(self, operation: str) -> None:
        """Concurrent disarm + unlock used by both async_unlock and async_open.

        Disarm and unlock are kicked off in parallel for latency.  Each path
        handles errors independently so neither raises from ``gather``:
        ``_dispatch_unlock_disarm`` fires "Auto-disarm failed" on its own
        failure, and ``_change_lock_mode`` rolls entity state back + returns
        a reason string on its own failure.  After gather completes we
        inspect both results and surface unlock failure to the HA service
        caller: fire "Unlock failed" notification AND raise
        HomeAssistantError so scripts/automations see it.  If the parallel
        disarm succeeded, the message is enriched to point out the
        asymmetric outcome ("alarm disarmed but door still locked").
        """
        disarm_result, unlock_error = await asyncio.gather(
            self._dispatch_unlock_disarm(),
            self._change_lock_mode(
                lock_state=False,
                transitional_state=LOCK_STATUS_UNLOCKING,
                optimistic_state=LOCK_STATUS_UNLOCKED,
                operation=operation,
            ),
        )
        if unlock_error is None:
            return
        if disarm_result is True:
            message = (
                f"{self._attr_name}: alarm has been disarmed but the door "
                f"is still locked ({unlock_error})."
            )
        else:
            message = f"Could not unlock {self._attr_name}: {unlock_error}"
        await self._fire_autolock_notification(title="Unlock failed", message=message)
        raise HomeAssistantError(message)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._perform_user_unlock("Unlock")

    async def async_open(self, **kwargs: Any) -> None:
        await self._perform_user_unlock("Open")

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
