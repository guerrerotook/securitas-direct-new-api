"""Smart-lock domain: status, config (Smartlock + Danalock fallback), mode change."""

from __future__ import annotations

import logging
from typing import Any

from ..exceptions import VerisureOwaError
from ..graphql_queries import (
    CHANGE_LOCK_MODE_MUTATION,
    CHANGE_LOCK_MODE_STATUS_QUERY,
    DANALOCK_CONFIG_QUERY,
    DANALOCK_CONFIG_STATUS_QUERY,
    LOCK_CURRENT_MODE_QUERY,
    SMARTLOCK_CONFIG_QUERY,
)
from ..models import (
    Installation,
    LockFeatures,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
)
from ..responses import (
    ChangeLockModeEnvelope,
    DanalockConfigEnvelope,
    LockModeEnvelope,
    SmartlockConfigEnvelope,
)
from ._base import _ClientBase

_LOGGER = logging.getLogger(__name__)

SMARTLOCK_DEVICE_ID = "01"
SMARTLOCK_DEVICE_TYPE = "DR"
SMARTLOCK_KEY_TYPE = "0"


class _LockMixin(_ClientBase):
    """Lock status, config and mode-change."""

    async def get_lock_modes(self, installation: Installation) -> list[SmartLockMode]:
        """Get the current mode of all smart locks.

        Returns:
            A list of SmartLockMode instances, one per lock device.
        """
        content = {
            "operationName": "xSGetLockCurrentMode",
            "variables": {
                "numinst": installation.number,
            },
            "query": LOCK_CURRENT_MODE_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "xSGetLockCurrentMode",
            LockModeEnvelope,
            installation=installation,
        )
        smartlock_info = envelope.data.xSGetLockCurrentMode.smartlock_info
        if not smartlock_info:
            return []
        # Skip phantom entries with null lockStatus (e.g. SmartLock Tácito)
        return [
            SmartLockMode.model_validate(item)
            for item in smartlock_info
            if item.get("lockStatus") is not None
        ]

    async def get_lock_config(
        self,
        installation: Installation,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> SmartLock:
        """Fetch lock configuration, auto-detecting Smartlock vs Danalock API.

        Tries the fast xSGetSmartlockConfig query first.  If that returns a
        non-OK result or raises, falls back to the Danalock two-phase polling
        API.  Returns an empty SmartLock() if both paths fail.

        Args:
            installation: The installation to query.
            device_id: Lock device ID (defaults to SMARTLOCK_DEVICE_ID).

        Returns:
            SmartLock with lock configuration details, or empty SmartLock().
        """
        # ── Smartlock fast path ──
        try:
            smartlock_content = {
                "operationName": "xSGetSmartlockConfig",
                "variables": {
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "deviceType": SMARTLOCK_DEVICE_TYPE,
                    "deviceId": device_id,
                    "keytype": SMARTLOCK_KEY_TYPE,
                },
                "query": SMARTLOCK_CONFIG_QUERY,
            }
            envelope = await self._execute_graphql(
                smartlock_content,
                "xSGetSmartlockConfig",
                SmartlockConfigEnvelope,
                installation=installation,
            )
            config = envelope.data.xSGetSmartlockConfig
            if config.res == "OK":
                return config
        except VerisureOwaError as err:
            if err.http_status == 500:
                # Danalock-protocol locks return HTTP 500 to xSGetSmartlockConfig;
                # this is the expected signal to fall back, not a fault — so log
                # it concisely without a traceback to keep the logs quiet.
                _LOGGER.debug(
                    "Smartlock config unavailable for %s device %s (%s), "
                    "trying Danalock",
                    installation.number,
                    device_id,
                    err,
                )
            else:
                # Other statuses (auth, WAF, rate-limit, connection) signal a
                # real problem — keep the full traceback.
                _LOGGER.debug(
                    "Smartlock config fetch failed for %s device %s, trying Danalock",
                    installation.number,
                    device_id,
                    exc_info=True,
                )
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "Smartlock config fetch failed unexpectedly for %s device %s, "
                "trying Danalock",
                installation.number,
                device_id,
                exc_info=True,
            )

        # ── Danalock fallback (two-phase polling) ──
        try:
            return await self._get_danalock_config(installation, device_id)
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "Danalock config fetch also failed for %s device %s",
                installation.number,
                device_id,
                exc_info=True,
            )

        return SmartLock()

    async def _get_danalock_config(
        self,
        installation: Installation,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> SmartLock:
        """Fetch Danalock config via submit + poll.

        Returns:
            SmartLock with lock configuration, or SmartLock() on failure.
        """

        def status_vars(ref_id: str, counter: int) -> dict[str, Any]:
            return {
                "numinst": installation.number,
                "referenceId": ref_id,
                "counter": counter,
            }

        raw = await self._submit_and_poll(
            installation=installation,
            submit_op="xSGetDanalockConfig",
            submit_query=DANALOCK_CONFIG_QUERY,
            submit_vars={
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": device_id,
            },
            submit_envelope_cls=DanalockConfigEnvelope,
            submit_data_field="xSGetDanalockConfig",
            status_op="xSGetDanalockConfigStatus",
            status_query=DANALOCK_CONFIG_STATUS_QUERY,
            status_data_field="xSGetDanalockConfigStatus",
            status_vars_builder=status_vars,
        )

        if raw.get("res") != "OK":
            return SmartLock()

        return SmartLock(
            res=raw.get("res"),
            device_id=raw.get("deviceNumber") or device_id,
            features=LockFeatures.model_validate(raw["features"])
            if raw.get("features")
            else None,
        )

    async def change_lock_mode(
        self,
        installation: Installation,
        lock: bool,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> SmartLockModeStatus:
        """Send lock/unlock command and poll until the backend responds.

        Args:
            installation: The installation containing the lock.
            lock: True to lock, False to unlock.
            device_id: Lock device ID (defaults to SMARTLOCK_DEVICE_ID).

        Returns:
            SmartLockModeStatus with the final operation result.

        Raises:
            OperationTimeoutError: If polling times out.
        """

        def status_vars(ref_id: str, counter: int) -> dict[str, Any]:
            return {
                "counter": counter,
                "deviceId": device_id,
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": ref_id,
            }

        raw = await self._submit_and_poll(
            installation=installation,
            submit_op="xSChangeSmartlockMode",
            submit_query=CHANGE_LOCK_MODE_MUTATION,
            submit_vars={
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": device_id,
                "lock": lock,
            },
            submit_envelope_cls=ChangeLockModeEnvelope,
            submit_data_field="xSChangeSmartlockMode",
            status_op="xSChangeSmartlockModeStatus",
            status_query=CHANGE_LOCK_MODE_STATUS_QUERY,
            status_data_field="xSChangeSmartlockModeStatus",
            status_vars_builder=status_vars,
        )

        # ── Process result ──
        if raw.get("protomResponse"):
            self.protom_response = raw["protomResponse"]
        return SmartLockModeStatus.model_validate(raw)
