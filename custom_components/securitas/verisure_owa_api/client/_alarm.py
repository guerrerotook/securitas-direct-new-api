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

# Map of panel ``error.type`` values to human-readable labels. Used as the
# label when the ``msg`` is a terse bare code (e.g. ``alarm-manager.errdca3``)
# and the structured ``error_*#zone`` form isn't available.
_ERROR_TYPE_LABELS: dict[str, str] = {
    "BLOCKING": "Blocking error",
    "NON_BLOCKING": "Non-blocking error",
    "TECHNICAL_ERROR": "Technical error",
}

_ALARM_MANAGER_PREFIX = "alarm-manager."

# Surfaced when the panel rejects an arm/disarm because the user's
# state mapping asks for a mode the panel isn't configured to support.
# Exported so tests can build the same expected message without
# duplicating the wording.
PANEL_REJECTION_TEMPLATE = (
    "Unsupported operation `{msg}` — check the Alarm State Mappings "
    "in Settings > Devices > Verisure OWA > ⚙️"
)


def humanize_panel_error_msg(msg: str, error: dict[str, Any] | None = None) -> str:
    """Convert a raw panel error to a short label suitable for a notification.

    Four input shapes the panel actually emits in the wild, all under the
    ``alarm-manager.`` namespace plus a pass-through for anything else:

    1. ``alarm-manager.error_<code>[#zone_id]`` — the structured form. Known
       codes get a curated label; unknown ones get the code title-cased.
       If a ``#zone_id`` suffix is present, the underscore-separated path
       is shown in parens.
    2. ``alarm-manager.err<bare-code>`` (e.g. ``alarm-manager.errdca3``) —
       terse internal codes with no human-readable suffix. When the caller
       passes ``error`` (the structured ``error`` field from the response)
       and it has a ``type``, we surface the type label and keep the raw
       code in parens for support. Without the error dict, we fall back
       to title-casing the bare code.
    3. ``alarm-manager.<single-token>`` outside the err* family (e.g.
       ``usm8``, ``usm9``) — panel rejected the requested action because
       the user's alarm state mappings ask for a mode the panel isn't
       configured to support. Point the user at the mappings rather than
       guessing at each code's meaning. The dot-free body check excludes
       success/progress messages like ``alarm-manager.processed.request``.
    4. Anything else — passed through unchanged so non-panel error
       messages (network errors, library exceptions, etc.) and
       alarm-manager success messages aren't mangled.

    Pre-v5 (and v5.0.0/.1) surfaced shapes 1 and 2 raw via the
    ``arm_failed`` notification, producing user-facing text like
    ``Arm command failed: alarm-manager.error_mg_open_zone#Pl_Home_Cocina_Puertajardi``
    or ``Arm command failed: alarm-manager.errdca3``.
    """
    if not msg:
        return ""
    if not msg.startswith(_ALARM_MANAGER_PREFIX):
        return msg
    body = msg.removeprefix(_ALARM_MANAGER_PREFIX)

    if body.startswith("error_"):
        code, sep, suffix = body.removeprefix("error_").partition("#")
        label = (
            _KNOWN_PANEL_ERROR_CODES.get(code) or code.replace("_", " ").capitalize()
        )
        if sep and suffix:
            zone_path = " / ".join(suffix.split("_"))
            return f"{label} ({zone_path})"
        return label

    # err* must be checked before the dot-free fallback — bare err codes
    # like ``errdca3`` also have no dot in the body and would otherwise be
    # captured by the panel-rejection shape.
    if body.startswith("err"):
        if error and (error_type := error.get("type")):
            type_label = _ERROR_TYPE_LABELS.get(
                error_type, error_type.replace("_", " ").capitalize()
            )
            return f"{type_label} ({msg})"
        return body.capitalize()

    if "." not in body:
        return PANEL_REJECTION_TEMPLATE.format(msg=msg)

    return msg


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
                    f"Arm command failed: {humanize_panel_error_msg(raw_msg, error)}"
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
            error = raw.get("error")
            error_info = error or {}
            if error_info.get("type") != "NON_BLOCKING":
                raw_msg = raw.get("msg", "unknown error")
                raise VerisureOwaError(
                    f"Disarm command failed: {humanize_panel_error_msg(raw_msg, error)}"
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
