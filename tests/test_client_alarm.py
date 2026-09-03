"""Tests for VerisureOwaClient alarm methods — arm, disarm, check_alarm, get_general_status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from custom_components.securitas.verisure_owa_api.client import (
    VerisureOwaClient,
)
from custom_components.securitas.verisure_owa_api.exceptions import (
    ArmingExceptionError,
    OperationTimeoutError,
    VerisureOwaError,
)
from custom_components.securitas.verisure_owa_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.verisure_owa_api.models import (
    Installation,
    OperationStatus,
    SStatus,
)

# ── JWT helpers ──────────────────────────────────────────────────────────────

SECRET = "test-secret"


def make_jwt(exp_minutes: int = 15, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=UTC) + timedelta(minutes=exp_minutes)
    payload = {"exp": exp, "sub": "test-user", **extra_claims}
    return jwt.encode(payload, SECRET, algorithm="HS256")


FAKE_JWT = make_jwt(exp_minutes=15)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_installation(**overrides) -> Installation:
    """Factory for Installation with sensible defaults."""
    defaults = {
        "number": "123456",
        "alias": "Home",
        "panel": "SDVFAST",
        "type": "PLUS",
        "name": "John",
        "last_name": "Doe",
        "address": "123 St",
        "city": "Madrid",
        "postal_code": "28001",
        "province": "Madrid",
        "email": "test@example.com",
        "phone": "555-1234",
    }
    defaults.update(overrides)
    return Installation(**defaults)


def _pre_auth(client: VerisureOwaClient) -> None:
    """Set up a valid auth token so _ensure_auth is a no-op."""
    client.authentication_token = FAKE_JWT
    client._authentication_token_exp = datetime.now() + timedelta(hours=1)
    # Stub get_services to avoid NotImplementedError on _ensure_capabilities
    client.get_services = AsyncMock(return_value=[])


# ── Response builders ────────────────────────────────────────────────────────


def arm_submit_response(reference_id: str = "ref-arm-123") -> dict:
    """Build a mock xSArmPanel response."""
    return {
        "data": {
            "xSArmPanel": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def arm_status_response(
    *,
    res: str = "OK",
    status: str = "ARMED",
    protom_response: str = "T",
    error: dict | str | None = None,
    msg: str = "",
) -> dict:
    """Build a mock xSArmStatus response."""
    return {
        "data": {
            "xSArmStatus": {
                "res": res,
                "msg": msg,
                "status": status,
                "numinst": "123456",
                "protomResponse": protom_response,
                "protomResponseDate": "2024-01-01 12:00:00",
                "requestId": "req-123",
                "error": error or "",
            }
        }
    }


def disarm_submit_response(reference_id: str = "ref-disarm-456") -> dict:
    """Build a mock xSDisarmPanel response."""
    return {
        "data": {
            "xSDisarmPanel": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def disarm_status_response(
    *,
    res: str = "OK",
    status: str = "DISARMED",
    protom_response: str = "D",
    error: dict | str | None = None,
) -> dict:
    """Build a mock xSDisarmStatus response."""
    return {
        "data": {
            "xSDisarmStatus": {
                "res": res,
                "msg": "",
                "status": status,
                "numinst": "123456",
                "protomResponse": protom_response,
                "protomResponseDate": "2024-01-01 12:00:00",
                "requestId": "req-456",
                "error": error or "",
            }
        }
    }


def check_alarm_submit_response(reference_id: str = "ref-check-789") -> dict:
    """Build a mock xSCheckAlarm response."""
    return {
        "data": {
            "xSCheckAlarm": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def check_alarm_status_response(
    *,
    res: str = "OK",
    status: str = "ARMED",
    protom_response: str = "T",
) -> dict:
    """Build a mock xSCheckAlarmStatus response."""
    return {
        "data": {
            "xSCheckAlarmStatus": {
                "res": res,
                "msg": "",
                "status": status,
                "numinst": "123456",
                "protomResponse": protom_response,
                "protomResponseDate": "2024-01-01 12:00:00",
            }
        }
    }


def general_status_response(
    *,
    status: str = "ARMED",
    timestamp_update: str = "2024-01-01 12:00:00",
    wifi_connected: bool = True,
) -> dict:
    """Build a mock xSStatus response."""
    return {
        "data": {
            "xSStatus": {
                "status": status,
                "timestampUpdate": timestamp_update,
                "wifiConnected": wifi_connected,
                "exceptions": None,
            }
        }
    }


def exceptions_response(
    *,
    res: str = "OK",
    exceptions: list[dict] | None = None,
) -> dict:
    """Build a mock xSGetExceptions response."""
    return {
        "data": {
            "xSGetExceptions": {
                "res": res,
                "msg": "",
                "exceptions": exceptions,
            }
        }
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def transport():
    """Create a mock HttpTransport."""
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport):
    """Create a VerisureOwaClient with test credentials, mocked transport, fast polling."""
    c = VerisureOwaClient(
        transport=transport,
        country="ES",
        language="es",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        poll_delay=0.0,
        poll_timeout=2.0,
    )
    _pre_auth(c)
    return c


# ── Arm tests ────────────────────────────────────────────────────────────────


class TestArm:
    async def test_arm_success(self, client, transport):
        """Submit arm + poll through WAIT states, returns OperationStatus."""
        transport.execute.side_effect = [
            # 1. submit: xSArmPanel returns referenceId
            arm_submit_response("ref-arm-001"),
            # 2. poll: first check returns WAIT
            arm_status_response(res="WAIT", status=""),
            # 3. poll: second check returns OK
            arm_status_response(res="OK", status="ARMED", protom_response="T"),
        ]

        inst = _make_installation()
        result = await client.arm(inst, "ARM1")

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARMED"
        assert result.protom_response == "T"
        # protom_response should be updated on the client
        assert client.protom_response == "T"

    async def test_arm_without_protom_response_does_not_raise(self, client, transport):
        """If the API response omits protomResponse, arm() preserves the previous value."""
        submit = arm_submit_response("ref-arm-005")
        status = arm_status_response(res="OK", status="ARMED")
        del status["data"]["xSArmStatus"]["protomResponse"]
        transport.execute.side_effect = [submit, status]

        inst = _make_installation()
        client.protom_response = "previous-T"
        result = await client.arm(inst, "ARM1")

        assert result.operation_status == "OK"
        assert client.protom_response == "previous-T"

    async def test_arm_arming_exception_error(self, client, transport):
        """NON_BLOCKING error with allowForcing raises ArmingExceptionError."""
        transport.execute.side_effect = [
            # 1. submit
            arm_submit_response("ref-arm-002"),
            # 2. poll: returns ERROR with NON_BLOCKING
            arm_status_response(
                res="ERROR",
                error={
                    "code": "EX001",
                    "type": "NON_BLOCKING",
                    "allowForcing": True,
                    "exceptionsNumber": 1,
                    "referenceId": "exc-ref-001",
                    "suid": "suid-001",
                },
            ),
            # 3. _get_exceptions poll: first returns WAIT
            exceptions_response(res="WAIT"),
            # 4. _get_exceptions poll: returns OK with exceptions
            exceptions_response(
                res="OK",
                exceptions=[
                    {
                        "status": "OPEN",
                        "deviceType": "WINDOW",
                        "alias": "Kitchen Window",
                    }
                ],
            ),
        ]

        inst = _make_installation()
        with pytest.raises(ArmingExceptionError) as exc_info:
            await client.arm(inst, "ARM1")

        assert exc_info.value.reference_id == "exc-ref-001"
        assert exc_info.value.suid == "suid-001"
        assert len(exc_info.value.exceptions) == 1
        assert exc_info.value.exceptions[0]["alias"] == "Kitchen Window"

    async def test_arm_zone_open_arming_exception_error(self, client, transport):
        """ZONE error with allowForcing raises ArmingExceptionError (FR panels).

        French SDVFAST panels report open-zone rejections as ``type: "ZONE"``
        (not ``NON_BLOCKING``) while still setting ``allowForcing: True``. This
        must still raise ArmingExceptionError so the force-arm flow triggers.
        See issue #583.
        """
        transport.execute.side_effect = [
            # 1. submit
            arm_submit_response("ref-arm-zone-001"),
            # 2. poll: returns ERROR with ZONE type
            arm_status_response(
                res="ERROR",
                error={
                    "code": "ERR_ZONE_OPEN",
                    "type": "ZONE",
                    "allowForcing": True,
                    "exceptionsNumber": 1,
                    "referenceId": "exc-ref-zone",
                    "suid": "suid-zone",
                },
            ),
            # 3. _get_exceptions poll: first returns WAIT
            exceptions_response(res="WAIT"),
            # 4. _get_exceptions poll: returns OK with exceptions
            exceptions_response(
                res="OK",
                exceptions=[
                    {
                        "status": "OPEN",
                        "deviceType": "DOOR",
                        "alias": "Main door",
                    }
                ],
            ),
        ]

        inst = _make_installation()
        with pytest.raises(ArmingExceptionError) as exc_info:
            await client.arm(inst, "ARM1")

        assert exc_info.value.reference_id == "exc-ref-zone"
        assert exc_info.value.suid == "suid-zone"
        assert len(exc_info.value.exceptions) == 1
        assert exc_info.value.exceptions[0]["alias"] == "Main door"

    async def test_arm_zone_not_forceable_still_lists_sensor(self, client, transport):
        """ZONE without allowForcing warns but does not enable force-arm."""
        transport.execute.side_effect = [
            arm_submit_response("ref-arm-zone-002"),
            arm_status_response(
                res="ERROR",
                error={
                    "code": "ERR_ZONE_OPEN",
                    "type": "ZONE",
                    "allowForcing": False,
                    "exceptionsNumber": 1,
                    "referenceId": "exc-ref-zone-blocked",
                    "suid": "suid-zone-blocked",
                },
            ),
            exceptions_response(
                res="OK",
                exceptions=[
                    {"status": "OPEN", "deviceType": "DOOR", "alias": "Main door"}
                ],
            ),
        ]

        with pytest.raises(ArmingExceptionError) as exc_info:
            await client.arm(_make_installation(), "ARM1")

        assert exc_info.value.allow_forcing is False
        assert exc_info.value.exceptions[0]["alias"] == "Main door"

    async def test_arm_zone_exception_without_reference_does_not_poll_exceptions(
        self, client, transport
    ):
        """A ZONE rejection with no referenceId/suid raises immediately.

        A genuinely-blocking arming rejection can arrive as ZONE/NON_BLOCKING
        with no referenceId and no suid. There is nothing to fetch or force
        without a reference, so arm() must surface ArmingExceptionError right
        away with an empty exceptions list — never poll xSGetExceptions, which
        would hang on WAIT for the full poll timeout then raise
        OperationTimeoutError. See finding F3.

        Force-arming targets the bypass via referenceId/suid, so with both
        absent it cannot work (an empty force id degrades to a plain re-arm
        that just re-hits this rejection). ``allow_forcing`` must therefore be
        reported as False even when the API claims ``allowForcing: True``, so
        the UI never offers a Force Arm button that would loop.
        """
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return arm_submit_response("ref-arm-noref")
            if call_count == 2:
                return arm_status_response(
                    res="ERROR",
                    error={
                        "code": "ERR_ZONE_OPEN",
                        "type": "ZONE",
                        "allowForcing": True,
                        "exceptionsNumber": 1,
                        "referenceId": "",
                        "suid": "",
                    },
                )
            # Any further call is the xSGetExceptions poll; hold it in WAIT so
            # the current (buggy) code would poll until the timeout expires.
            return exceptions_response(res="WAIT")

        transport.execute.side_effect = _side_effect
        # Keep the red-phase timeout short so the buggy path fails fast.
        client.poll_timeout = 0.2

        with pytest.raises(ArmingExceptionError) as exc_info:
            await client.arm(_make_installation(), "ARM1")

        assert exc_info.value.exceptions == []
        # API said allowForcing:True, but with no referenceId/suid forcing is
        # impossible — must not advertise a non-functional Force Arm button.
        assert exc_info.value.allow_forcing is False
        assert exc_info.value.reference_id == ""
        assert exc_info.value.suid == ""
        # With no sensor aliases the message must not dangle a trailing colon.
        assert (
            str(exc_info.value)
            == "Arming blocked by open sensors (no sensor details available)"
        )

        # xSGetExceptions must never be requested — nothing to fetch without a
        # referenceId or suid.
        requested_ops = [
            call.args[0]["operationName"] for call in transport.execute.call_args_list
        ]
        assert "xSGetExceptions" not in requested_ops

    async def test_arm_mpj_exception_with_unknown_type_is_arming_exception(
        self, client, transport
    ):
        """The canonical MPJ exception message survives backend type drift.

        ``allowForcing`` is the panel's explicit safety gate.  When it is true,
        a known ``error_mpj_exception`` must enter the arming-exception flow
        even if a panel reports a new ``error.type`` value, so Home Assistant
        can fetch and display the affected sensors instead of showing the raw
        backend message.
        """
        transport.execute.side_effect = [
            arm_submit_response("ref-arm-mpj-001"),
            arm_status_response(
                res="ERROR",
                msg="error_mpj_exception",
                error={
                    "code": "102",
                    "type": "MPJ_EXCEPTION",
                    "allowForcing": True,
                    "exceptionsNumber": 3,
                    "referenceId": "exc-ref-mpj",
                    "suid": "suid-mpj",
                },
            ),
            exceptions_response(
                res="OK",
                exceptions=[
                    {"status": "0", "deviceType": "MG", "alias": "Kitchen"},
                    {"status": "0", "deviceType": "MG", "alias": "Bedroom"},
                    {"status": "0", "deviceType": "MG", "alias": "Office"},
                ],
            ),
        ]

        with pytest.raises(ArmingExceptionError) as exc_info:
            await client.arm(_make_installation(), "ARM1")

        assert exc_info.value.reference_id == "exc-ref-mpj"
        assert exc_info.value.suid == "suid-mpj"
        assert [item["alias"] for item in exc_info.value.exceptions] == [
            "Kitchen",
            "Bedroom",
            "Office",
        ]

    async def test_arm_mpj_exception_without_allow_forcing_lists_sensors(
        self, client, transport
    ):
        """Spain panels can report open sensors but prohibit force-arming."""
        transport.execute.side_effect = [
            arm_submit_response("ref-arm-mpj-002"),
            arm_status_response(
                res="ERROR",
                msg="error_mpj_exception",
                error={
                    "code": "102",
                    "type": "NON_BLOCKING",
                    "allowForcing": False,
                    "exceptionsNumber": 3,
                    "referenceId": "exc-ref-mpj-blocked",
                    "suid": "suid-mpj-blocked",
                },
            ),
            exceptions_response(
                res="OK",
                exceptions=[
                    {"status": "0", "deviceType": "MG", "alias": "Kitchen"},
                    {"status": "0", "deviceType": "MG", "alias": "Bedroom"},
                    {"status": "0", "deviceType": "MG", "alias": "Office"},
                ],
            ),
        ]

        with pytest.raises(ArmingExceptionError) as exc_info:
            await client.arm(_make_installation(), "ARM1")

        assert exc_info.value.allow_forcing is False
        assert [item["alias"] for item in exc_info.value.exceptions] == [
            "Kitchen",
            "Bedroom",
            "Office",
        ]

    async def test_unrelated_mpj_error_does_not_become_sensor_warning(
        self, client, transport
    ):
        """MPJ command errors without exceptions retain the failure path."""
        transport.execute.side_effect = [
            arm_submit_response("ref-arm-mpj-003"),
            arm_status_response(
                res="ERROR",
                msg="error_mpj_exception",
                error={
                    "code": "101",
                    "type": "BLOCKING",
                    "allowForcing": False,
                    "exceptionsNumber": 0,
                    "referenceId": "ref-partition-error",
                    "suid": "",
                },
            ),
        ]

        with pytest.raises(
            VerisureOwaError,
            match="Arm command failed: error_mpj_exception",
        ):
            await client.arm(_make_installation(), "ARM1")

    async def test_arm_with_force_id(self, client, transport):
        """force_id is passed as forceArmingRemoteId in submit variables."""
        transport.execute.side_effect = [
            arm_submit_response("ref-arm-003"),
            arm_status_response(res="OK", protom_response="T"),
        ]

        inst = _make_installation()
        await client.arm(inst, "ARM1", force_id="force-123", suid="suid-xyz")

        # Check the submit call includes forceArmingRemoteId
        submit_call = transport.execute.call_args_list[0]
        content = submit_call[0][0]
        assert content["variables"]["forceArmingRemoteId"] == "force-123"
        assert content["variables"]["suid"] == "suid-xyz"

    async def test_arm_timeout(self, client, transport):
        """Raises OperationTimeoutError when poll never completes."""
        # Use a callable side_effect: first call returns the submit response,
        # all subsequent calls return WAIT forever.
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return arm_submit_response("ref-arm-004")
            return arm_status_response(res="WAIT")

        transport.execute.side_effect = _side_effect

        inst = _make_installation()
        client.poll_timeout = 0.1

        with pytest.raises(OperationTimeoutError):
            await client.arm(inst, "ARM1")

    async def test_arm_blocking_error(self, client, transport):
        """BLOCKING error type raises VerisureOwaError."""
        transport.execute.side_effect = [
            arm_submit_response("ref-arm-005"),
            arm_status_response(
                res="ERROR",
                error={
                    "code": "E001",
                    "type": "BLOCKING",
                    "allowForcing": False,
                    "exceptionsNumber": 0,
                    "referenceId": "",
                    "suid": "",
                },
            ),
        ]

        inst = _make_installation()
        with pytest.raises(VerisureOwaError, match="Arm command failed"):
            await client.arm(inst, "ARM1")


# ── Disarm tests ─────────────────────────────────────────────────────────────


class TestDisarm:
    async def test_disarm_success(self, client, transport):
        """Submit disarm + poll, returns OperationStatus."""
        transport.execute.side_effect = [
            disarm_submit_response("ref-disarm-001"),
            disarm_status_response(res="WAIT"),
            disarm_status_response(res="OK", status="DISARMED", protom_response="D"),
        ]

        inst = _make_installation()
        result = await client.disarm(inst, "DARM1")

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "DISARMED"
        assert client.protom_response == "D"

    async def test_disarm_blocking_error(self, client, transport):
        """BLOCKING error raises VerisureOwaError."""
        transport.execute.side_effect = [
            disarm_submit_response("ref-disarm-002"),
            disarm_status_response(
                res="ERROR",
                error={
                    "code": "E001",
                    "type": "BLOCKING",
                    "allowForcing": False,
                },
            ),
        ]

        inst = _make_installation()
        with pytest.raises(VerisureOwaError, match="Disarm command failed"):
            await client.disarm(inst, "DARM1")


# ── Check alarm tests ───────────────────────────────────────────────────────


class TestCheckAlarm:
    async def test_check_alarm_success(self, client, transport):
        """Submit check + poll, returns OperationStatus."""
        transport.execute.side_effect = [
            check_alarm_submit_response("ref-check-001"),
            check_alarm_status_response(res="WAIT"),
            check_alarm_status_response(res="OK", status="ARMED", protom_response="T"),
        ]

        inst = _make_installation()
        result = await client.check_alarm(inst)

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARMED"
        assert client.protom_response == "T"

    async def test_check_alarm_without_protom_response_does_not_raise(
        self, client, transport
    ):
        """If the API response omits protomResponse, check_alarm() preserves the previous value."""
        check_submit = check_alarm_submit_response("ref-check-002")
        status = check_alarm_status_response(res="OK", status="ARMED")
        del status["data"]["xSCheckAlarmStatus"]["protomResponse"]
        transport.execute.side_effect = [check_submit, status]

        inst = _make_installation()
        client.protom_response = "previous-T"
        result = await client.check_alarm(inst)

        assert result.operation_status == "OK"
        assert client.protom_response == "previous-T"


# ── Get general status tests ────────────────────────────────────────────────


class TestGetGeneralStatus:
    async def test_get_general_status_success(self, client, transport):
        """Single call returns SStatus, no polling."""
        transport.execute.return_value = general_status_response(
            status="ARMED",
            timestamp_update="2024-01-01 12:00:00",
            wifi_connected=True,
        )

        inst = _make_installation()
        result = await client.get_general_status(inst)

        assert isinstance(result, SStatus)
        assert result.status == "ARMED"
        assert result.timestamp_update == "2024-01-01 12:00:00"
        assert result.wifi_connected is True
        # Only one transport call — no polling
        assert transport.execute.call_count == 1


# ── Golden contract tests ──────────────────────────────────────────────────


class TestAlarmRequestContracts:
    """Assert exact wire-protocol payloads for alarm GraphQL operations.

    These golden contract tests verify that the client sends the correct
    operationName, variables, and structure in every request, using hardcoded
    literal values to catch any drift or hallucination in the refactored code.
    """

    async def test_check_alarm_submit_payload(self, client, transport):
        """check_alarm sends correct CheckAlarm submit and CheckAlarmStatus poll payloads."""
        submit_response = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-1",
                }
            }
        }
        poll_response = {
            "data": {
                "xSCheckAlarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "T",
                    "protomResponseDate": "",
                    "requestId": "req-1",
                    "error": None,
                }
            }
        }
        transport.execute.side_effect = [submit_response, poll_response]

        inst = _make_installation()
        await client.check_alarm(inst)

        assert transport.execute.call_count == 2

        # ── Submit call ──
        submit_content = transport.execute.call_args_list[0][0][0]
        assert submit_content["operationName"] == "CheckAlarm"
        assert submit_content["variables"]["numinst"] == "123456"
        assert submit_content["variables"]["panel"] == "SDVFAST"

        # ── Poll call ──
        poll_content = transport.execute.call_args_list[1][0][0]
        assert poll_content["operationName"] == "CheckAlarmStatus"
        assert poll_content["variables"]["numinst"] == "123456"
        assert poll_content["variables"]["panel"] == "SDVFAST"
        assert poll_content["variables"]["referenceId"] == "ref-1"
        assert poll_content["variables"]["idService"] == "11"

    async def test_arm_submit_payload(self, client, transport):
        """arm sends correct xSArmPanel submit payload with currentStatus and armAndLock."""
        client.protom_response = "D"

        submit_response = {
            "data": {
                "xSArmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-arm",
                }
            }
        }
        poll_response = {
            "data": {
                "xSArmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "T",
                    "protomResponseDate": "",
                    "requestId": "req-1",
                    "error": None,
                }
            }
        }
        transport.execute.side_effect = [submit_response, poll_response]

        inst = _make_installation()
        await client.arm(inst, "ARM1")

        # ── Submit call ──
        submit_content = transport.execute.call_args_list[0][0][0]
        assert submit_content["operationName"] == "xSArmPanel"
        assert submit_content["variables"]["request"] == "ARM1"
        assert submit_content["variables"]["numinst"] == "123456"
        assert submit_content["variables"]["panel"] == "SDVFAST"
        assert submit_content["variables"]["currentStatus"] == "D"
        assert submit_content["variables"]["armAndLock"] is False

    async def test_disarm_submit_payload(self, client, transport):
        """disarm sends correct xSDisarmPanel submit payload with currentStatus."""
        client.protom_response = "T"

        submit_response = {
            "data": {
                "xSDisarmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-dis",
                }
            }
        }
        poll_response = {
            "data": {
                "xSDisarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "D",
                    "protomResponseDate": "",
                    "requestId": "req-1",
                    "error": None,
                }
            }
        }
        transport.execute.side_effect = [submit_response, poll_response]

        inst = _make_installation()
        await client.disarm(inst, "DARM1")

        # ── Submit call ──
        submit_content = transport.execute.call_args_list[0][0][0]
        assert submit_content["operationName"] == "xSDisarmPanel"
        assert submit_content["variables"]["request"] == "DARM1"
        assert submit_content["variables"]["numinst"] == "123456"
        assert submit_content["variables"]["panel"] == "SDVFAST"
        assert submit_content["variables"]["currentStatus"] == "T"

    async def test_get_general_status_payload(self, client, transport):
        """get_general_status sends correct Status query with numinst only."""
        transport.execute.return_value = {
            "data": {
                "xSStatus": {
                    "status": "T",
                    "timestampUpdate": "2024-01-01",
                    "wifiConnected": True,
                }
            }
        }

        inst = _make_installation()
        await client.get_general_status(inst)

        assert transport.execute.call_count == 1

        content = transport.execute.call_args[0][0]
        assert content["operationName"] == "Status"
        assert content["variables"] == {"numinst": "123456"}
