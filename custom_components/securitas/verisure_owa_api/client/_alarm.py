"""Alarm domain: arm, disarm, check, status, exceptions."""

from __future__ import annotations

from typing import Any

from ..exceptions import ArmingExceptionError, VerisureOwaError
from ..graphql_queries import (
    ARM_PANEL_MUTATION,
    ARM_STATUS_QUERY,
    CHECK_ALARM_QUERY,
    CHECK_ALARM_STATUS_QUERY,
    DISARM_PANEL_MUTATION,
    DISARM_STATUS_QUERY,
    GENERAL_STATUS_QUERY,
    GET_EXCEPTIONS_QUERY,
)
from ..models import Installation, OperationStatus, SStatus
from ..responses import (
    ArmPanelEnvelope,
    CheckAlarmEnvelope,
    DisarmPanelEnvelope,
    GeneralStatusEnvelope,
)
from ._base import ALARM_STATUS_SERVICE_ID, _ClientBase

# Map of known ``alarm-manager.error_<code>`` codes to human-readable labels
# shown in the user-facing arm/disarm-failed notification.
# Unknown codes fall back to the title-cased raw code via ``humanize_panel_error_msg``.
_KNOWN_PANEL_ERROR_CODES: dict[str, str] = {
    "mg_open_zone": "Open zone",
    "no_response_to_request": "No response from panel",
    "status_not_found": "Status not found",
}

_ALARM_ERROR_PREFIX = "alarm-manager.error_"


def humanize_panel_error_msg(msg: str) -> str:
    """Convert a raw ``alarm-manager.error_<code>[#zone_id]`` string into a
    short label suitable for a notification.

    Pre-v5 (and v5.0.0/.1) surfaced these raw codes directly to the user
    via the ``arm_failed`` notification (``{error}`` placeholder), which
    produced messages like
    ``Arm command failed: alarm-manager.error_mg_open_zone#Pl_Home_Cocina_Puertajardi``.
    This helper turns those into something a user can read while keeping
    enough information to identify the offending zone.

    Strings that don't look like panel error codes pass through unchanged
    so non-panel error messages (network errors, library exceptions, etc.)
    aren't mangled.
    """
    if not msg or not msg.startswith(_ALARM_ERROR_PREFIX):
        return msg
    body = msg[len(_ALARM_ERROR_PREFIX) :]
    code, sep, suffix = body.partition("#")
    label = _KNOWN_PANEL_ERROR_CODES.get(code) or code.replace("_", " ").capitalize()
    if sep and suffix:
        zone_path = " / ".join(suffix.split("_"))
        return f"{label} ({zone_path})"
    return label


class _AlarmMixin(_ClientBase):
    """Arm/disarm/check_alarm/status helpers + arming-exception fetcher."""

    async def arm(
        self,
        installation: Installation,
        command: str,
        *,
        force_id: str | None = None,
        suid: str | None = None,
    ) -> OperationStatus:
        """Arm the alarm panel.

        Submits the ARM mutation, then polls ARM status until complete.

        Args:
            installation: The installation to arm.
            command: Arm command string (e.g. "ARM1", "ARMDAY1").
            force_id: Optional forceArmingRemoteId to override exceptions.
            suid: Optional SUID for exception handling.

        Returns:
            OperationStatus with the final arm result.

        Raises:
            ArmingExceptionError: If arming blocked by non-blocking exceptions.
            VerisureOwaError: If arming fails with a blocking error.
            OperationTimeoutError: If polling times out.
        """
        submit_vars: dict[str, Any] = {
            "request": command,
            "numinst": installation.number,
            "panel": installation.panel,
            "currentStatus": self.protom_response,
            "armAndLock": False,
        }
        if force_id is not None:
            submit_vars["forceArmingRemoteId"] = force_id
        if suid is not None:
            submit_vars["suid"] = suid

        def status_vars(ref_id: str, counter: int) -> dict[str, Any]:
            poll_vars: dict[str, Any] = {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": ref_id,
                "counter": counter,
                "armAndLock": False,
            }
            if force_id is not None:
                poll_vars["forceArmingRemoteId"] = force_id
            return poll_vars

        raw = await self._submit_and_poll(
            installation=installation,
            submit_op="xSArmPanel",
            submit_query=ARM_PANEL_MUTATION,
            submit_vars=submit_vars,
            submit_envelope_cls=ArmPanelEnvelope,
            submit_data_field="xSArmPanel",
            status_op="ArmStatus",
            status_query=ARM_STATUS_QUERY,
            status_data_field="xSArmStatus",
            status_vars_builder=status_vars,
        )

        # ── Process result ──
        error = raw.get("error")
        if raw.get("res") == "ERROR":
            if (
                error
                and error.get("type") == "NON_BLOCKING"
                and error.get("allowForcing")
            ):
                error_ref = error.get("referenceId", "")
                error_suid = error.get("suid", "")
                exceptions = await self._get_exceptions(
                    installation, error_ref, error_suid
                )
                raise ArmingExceptionError(error_ref, error_suid, exceptions)
            error_info = error or {}
            if error_info.get("type") != "NON_BLOCKING":
                raw_msg = raw.get("msg", "unknown error")
                raise VerisureOwaError(
                    f"Arm command failed: {humanize_panel_error_msg(raw_msg)}"
                )

        if raw.get("protomResponse"):
            self.protom_response = raw["protomResponse"]
        return OperationStatus.model_validate(raw)

    async def disarm(
        self,
        installation: Installation,
        command: str,
    ) -> OperationStatus:
        """Disarm the alarm panel.

        Submits the DISARM mutation, then polls DISARM status until complete.

        Args:
            installation: The installation to disarm.
            command: Disarm command string (e.g. "DARM1", "DARM1DARMPERI").

        Returns:
            OperationStatus with the final disarm result.

        Raises:
            VerisureOwaError: If disarming fails with a blocking error.
            OperationTimeoutError: If polling times out.
        """
        # Capture current status at request time for consistent polling
        current_status = self.protom_response

        def status_vars(ref_id: str, counter: int) -> dict[str, Any]:
            return {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": current_status,
                "referenceId": ref_id,
                "counter": counter,
            }

        raw = await self._submit_and_poll(
            installation=installation,
            submit_op="xSDisarmPanel",
            submit_query=DISARM_PANEL_MUTATION,
            submit_vars={
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": current_status,
            },
            submit_envelope_cls=DisarmPanelEnvelope,
            submit_data_field="xSDisarmPanel",
            status_op="DisarmStatus",
            status_query=DISARM_STATUS_QUERY,
            status_data_field="xSDisarmStatus",
            status_vars_builder=status_vars,
        )

        # ── Process result ──
        if raw.get("res") == "ERROR":
            error_info = raw.get("error") or {}
            if error_info.get("type") != "NON_BLOCKING":
                raw_msg = raw.get("msg", "unknown error")
                raise VerisureOwaError(
                    f"Disarm command failed: {humanize_panel_error_msg(raw_msg)}"
                )

        if raw.get("protomResponse"):
            self.protom_response = raw["protomResponse"]
        return OperationStatus.model_validate(raw)

    async def check_alarm(self, installation: Installation) -> OperationStatus:
        """Check the current alarm status by querying the panel.

        Submits a CHECK_ALARM query, then polls until the panel responds.

        Returns:
            OperationStatus with the current alarm state.

        Raises:
            OperationTimeoutError: If polling times out.
        """

        def status_vars(ref_id: str, _counter: int) -> dict[str, Any]:
            return {
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": ref_id,
                "idService": ALARM_STATUS_SERVICE_ID,
            }

        raw = await self._submit_and_poll(
            installation=installation,
            submit_op="CheckAlarm",
            submit_query=CHECK_ALARM_QUERY,
            submit_vars={
                "numinst": installation.number,
                "panel": installation.panel,
            },
            submit_envelope_cls=CheckAlarmEnvelope,
            submit_data_field="xSCheckAlarm",
            status_op="CheckAlarmStatus",
            status_query=CHECK_ALARM_STATUS_QUERY,
            status_data_field="xSCheckAlarmStatus",
            status_vars_builder=status_vars,
        )

        if raw.get("protomResponse"):
            self.protom_response = raw["protomResponse"]
        return OperationStatus.model_validate(raw)

    async def get_general_status(self, installation: Installation) -> SStatus:
        """Get the general alarm status (single call, no polling).

        Returns:
            SStatus with current status, timestamp, and wifi connectivity.
        """
        content = {
            "operationName": "Status",
            "variables": {"numinst": installation.number},
            "query": GENERAL_STATUS_QUERY,
        }
        envelope = await self._execute_graphql(
            content, "Status", GeneralStatusEnvelope, installation=installation
        )
        return envelope.data.xSStatus

    async def _get_exceptions(
        self,
        installation: Installation,
        reference_id: str,
        suid: str,
    ) -> list[dict[str, Any]]:
        """Fetch arming exception details (e.g. open windows/doors).

        Polls until the exceptions list is non-empty or the result is not WAIT.
        """
        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            content = {
                "operationName": "xSGetExceptions",
                "variables": {
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "referenceId": reference_id,
                    "counter": counter,
                    "suid": suid,
                },
                "query": GET_EXCEPTIONS_QUERY,
            }
            response = await self._execute_raw(
                content, "xSGetExceptions", installation=installation
            )
            data = self._extract_response_data(response, "xSGetExceptions")
            return data

        raw = await self._poll_operation(_check)
        return raw.get("exceptions") or []
