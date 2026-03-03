"""Tests for ApiManager alarm operations (check, arm, disarm, status)."""

from unittest.mock import AsyncMock

import pytest

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    ArmStatus,
    CheckAlarmStatus,
    DisarmStatus,
    Installation,
    SStatus,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    ArmingExceptionError,
    SecuritasDirectError,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def installation():
    """Create a test installation."""
    return Installation(
        number="123456",
        alias="Home",
        panel="SDVFAST",
        type="PLUS",
    )


@pytest.fixture
def authed_api(api):
    """ApiManager with auth checks mocked out and zero delay."""
    api._check_authentication_token = AsyncMock()
    api._check_capabilities_token = AsyncMock()
    api.delay_check_operation = 0
    return api


# ── check_alarm() ────────────────────────────────────────────────────────────


class TestCheckAlarm:
    async def test_success_returns_reference_id(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-abc-123",
                }
            }
        }

        result = await authed_api.check_alarm(installation)

        assert result == "ref-abc-123"

    async def test_calls_auth_and_capabilities_checks(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-123",
                }
            }
        }

        await authed_api.check_alarm(installation)

        authed_api._check_authentication_token.assert_awaited_once()
        authed_api._check_capabilities_token.assert_awaited_once_with(installation)

    async def test_none_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSCheckAlarm": None}}

        with pytest.raises(SecuritasDirectError, match="xSCheckAlarm response is None"):
            await authed_api.check_alarm(installation)


# ── check_alarm_status() ─────────────────────────────────────────────────────


class TestCheckAlarmStatus:
    async def test_success_immediate_ok_returns_check_alarm_status(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSCheckAlarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "ARMED",
                    "numinst": "123456",
                    "protomResponse": "PROT_OK",
                    "protomResponseDate": "2026-01-15",
                }
            }
        }

        result = await authed_api.check_alarm_status(
            installation, "ref-123", timeout=10
        )

        assert isinstance(result, CheckAlarmStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARMED"
        assert result.InstallationNumer == "123456"
        assert result.protomResponse == "PROT_OK"

    async def test_polls_on_wait_then_returns_ok(
        self, authed_api, mock_execute, installation
    ):
        wait_response = {
            "data": {
                "xSCheckAlarmStatus": {
                    "res": "WAIT",
                    "msg": "Waiting",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "",
                    "protomResponseDate": "",
                }
            }
        }
        ok_response = {
            "data": {
                "xSCheckAlarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "DISARMED",
                    "numinst": "123456",
                    "protomResponse": "PROT_DISARMED",
                    "protomResponseDate": "2026-01-15",
                }
            }
        }
        mock_execute.side_effect = [wait_response, ok_response]

        result = await authed_api.check_alarm_status(
            installation, "ref-123", timeout=10
        )

        assert result.operation_status == "OK"
        assert result.status == "DISARMED"
        assert mock_execute.call_count == 2

    async def test_none_check_alarm_status_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSCheckAlarmStatus": None}}

        with pytest.raises(
            SecuritasDirectError, match="xSCheckAlarmStatus response is None"
        ):
            await authed_api.check_alarm_status(installation, "ref-123", timeout=10)


# ── arm_alarm() ──────────────────────────────────────────────────────────────


class TestArmAlarm:
    async def test_success_returns_arm_status(
        self, authed_api, mock_execute, installation
    ):
        initial_response = {
            "data": {
                "xSArmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-arm-123",
                }
            }
        }
        status_response = {
            "data": {
                "xSArmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "ARMED_TOTAL",
                    "numinst": "123456",
                    "protomResponse": "PROT_ARMED",
                    "protomResponseDate": "2026-01-15",
                    "requestId": "req-001",
                    "error": "",
                }
            }
        }
        mock_execute.side_effect = [initial_response, status_response]

        result = await authed_api.arm_alarm(installation, "ARM1")

        assert isinstance(result, ArmStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARMED_TOTAL"
        assert result.InstallationNumer == "123456"
        assert result.requestId == "req-001"

    async def test_non_ok_res_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSArmPanel": {
                    "res": "ERROR",
                    "msg": "Panel not responding",
                    "referenceId": "ref-123",
                }
            }
        }

        with pytest.raises(SecuritasDirectError, match="Panel not responding"):
            await authed_api.arm_alarm(installation, "ARM1")

    async def test_none_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSArmPanel": None}}

        with pytest.raises(SecuritasDirectError, match="xSArmPanel response is None"):
            await authed_api.arm_alarm(installation, "ARM1")

    async def test_errors_only_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        """GraphQL validation error (no data key) raises SecuritasDirectError instead of KeyError."""
        mock_execute.return_value = {
            "errors": [
                {
                    "message": 'Value "ARMNIGHT1PERI1" does not exist in "ArmCodeRequest" enum.',
                    "extensions": {"code": "BAD_USER_INPUT"},
                }
            ]
        }

        with pytest.raises(SecuritasDirectError, match="does not exist"):
            await authed_api.arm_alarm(installation, "ARMNIGHT1PERI1")

    async def test_polls_check_arm_status_on_wait(
        self, authed_api, mock_execute, installation
    ):
        initial_response = {
            "data": {
                "xSArmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-arm-456",
                }
            }
        }
        wait_response = {
            "data": {
                "xSArmStatus": {
                    "res": "WAIT",
                    "msg": "Waiting",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "",
                    "protomResponseDate": "",
                    "requestId": "",
                    "error": "",
                }
            }
        }
        ok_response = {
            "data": {
                "xSArmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "ARMED_TOTAL",
                    "numinst": "123456",
                    "protomResponse": "PROT_ARMED",
                    "protomResponseDate": "2026-01-15",
                    "requestId": "req-002",
                    "error": "",
                }
            }
        }
        mock_execute.side_effect = [initial_response, wait_response, ok_response]

        result = await authed_api.arm_alarm(installation, "ARM1")

        assert result.operation_status == "OK"
        assert result.status == "ARMED_TOTAL"
        # 1 for xSArmPanel + 2 for _check_arm_status (WAIT then OK)
        assert mock_execute.call_count == 3

    async def test_non_blocking_exception_raises_arming_exception_error(
        self, authed_api, mock_execute, installation
    ):
        """When the API returns a NON_BLOCKING error with allowForcing, raise ArmingExceptionError."""
        initial_response = {
            "data": {
                "xSArmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-arm-exc",
                }
            }
        }
        exception_response = {
            "data": {
                "xSArmStatus": {
                    "res": "ERROR",
                    "msg": "error_mpj_exception",
                    "status": None,
                    "protomResponse": None,
                    "protomResponseDate": "2026-02-28T16:03:13Z",
                    "numinst": None,
                    "requestId": None,
                    "error": {
                        "code": "102",
                        "type": "NON_BLOCKING",
                        "allowForcing": True,
                        "exceptionsNumber": 1,
                        "referenceId": "ref-arm-exc",
                        "suid": "123456VI4ucRGS5Q==",
                    },
                }
            }
        }
        get_exceptions_response = {
            "data": {
                "xSGetExceptions": {
                    "res": "OK",
                    "msg": None,
                    "exceptions": [
                        {"status": "0", "deviceType": "MG", "alias": "Kitchen Door"},
                    ],
                }
            }
        }
        mock_execute.side_effect = [
            initial_response,
            exception_response,
            get_exceptions_response,
        ]

        with pytest.raises(ArmingExceptionError) as exc_info:
            await authed_api.arm_alarm(installation, "ARMDAY1")

        assert exc_info.value.reference_id == "ref-arm-exc"
        assert exc_info.value.suid == "123456VI4ucRGS5Q=="
        assert len(exc_info.value.exceptions) == 1
        assert exc_info.value.exceptions[0]["alias"] == "Kitchen Door"

    async def test_force_arm_passes_force_params(
        self, authed_api, mock_execute, installation
    ):
        """When force_arming_remote_id and suid are provided, they appear in the request."""
        initial_response = {
            "data": {
                "xSArmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-force-arm",
                }
            }
        }
        status_response = {
            "data": {
                "xSArmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "ARMED",
                    "numinst": "123456",
                    "protomResponse": "P",
                    "protomResponseDate": "2026-02-28",
                    "requestId": "req-force",
                    "error": None,
                }
            }
        }
        mock_execute.side_effect = [initial_response, status_response]

        result = await authed_api.arm_alarm(
            installation,
            "ARMDAY1",
            force_arming_remote_id="ref-original",
            suid="123456VI4ucRGS5Q==",
        )

        assert result.operation_status == "OK"
        assert result.protomResponse == "P"

        # Check the xSArmPanel call included force params
        arm_call = mock_execute.call_args_list[0]
        arm_variables = arm_call[0][0]["variables"]
        assert arm_variables["forceArmingRemoteId"] == "ref-original"
        assert arm_variables["suid"] == "123456VI4ucRGS5Q=="

        # Check the ArmStatus poll also included forceArmingRemoteId
        status_call = mock_execute.call_args_list[1]
        status_variables = status_call[0][0]["variables"]
        assert status_variables["forceArmingRemoteId"] == "ref-original"

    async def test_blocking_error_does_not_raise_arming_exception(
        self, authed_api, mock_execute, installation
    ):
        """A BLOCKING error (allowForcing=false) should not raise ArmingExceptionError."""
        initial_response = {
            "data": {
                "xSArmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-arm-block",
                }
            }
        }
        blocking_error_response = {
            "data": {
                "xSArmStatus": {
                    "res": "ERROR",
                    "msg": "error_blocking",
                    "status": None,
                    "protomResponse": None,
                    "protomResponseDate": "2026-02-28",
                    "numinst": None,
                    "requestId": None,
                    "error": {
                        "code": "103",
                        "type": "BLOCKING",
                        "allowForcing": False,
                        "exceptionsNumber": 0,
                        "referenceId": "ref-arm-block",
                        "suid": "",
                    },
                }
            }
        }
        mock_execute.side_effect = [initial_response, blocking_error_response]

        # Should exit the loop (not WAIT, not forceable) and return status
        # with protomResponse=None — which is fine, the caller handles it
        result = await authed_api.arm_alarm(installation, "ARM1")
        assert result.protomResponse is None

    async def test_get_exceptions_method(self, authed_api, mock_execute, installation):
        """Test _get_exceptions returns parsed exception list."""
        mock_execute.return_value = {
            "data": {
                "xSGetExceptions": {
                    "res": "OK",
                    "msg": None,
                    "exceptions": [
                        {"status": "0", "deviceType": "MG", "alias": "Front Door"},
                        {"status": "0", "deviceType": "MG", "alias": "Window"},
                    ],
                }
            }
        }

        result = await authed_api._get_exceptions(installation, "ref-123", "suid-123")

        assert len(result) == 2
        assert result[0]["alias"] == "Front Door"
        assert result[1]["alias"] == "Window"


# ── disarm_alarm() ───────────────────────────────────────────────────────────


class TestDisarmAlarm:
    async def test_success_returns_disarm_status(
        self, authed_api, mock_execute, installation
    ):
        initial_response = {
            "data": {
                "xSDisarmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-disarm-123",
                }
            }
        }
        status_response = {
            "data": {
                "xSDisarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "DISARMED",
                    "numinst": "123456",
                    "protomResponse": "PROT_DISARMED",
                    "protomResponseDate": "2026-01-15",
                    "requestId": "req-003",
                    "error": "",
                }
            }
        }
        mock_execute.side_effect = [initial_response, status_response]

        result = await authed_api.disarm_alarm(installation, "DARM1")

        assert isinstance(result, DisarmStatus)
        assert result.operation_status == "OK"
        assert result.status == "DISARMED"
        assert result.numinst == "123456"
        assert result.requestId == "req-003"

    async def test_non_ok_res_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSDisarmPanel": {
                    "res": "ERROR",
                    "msg": "Panel offline",
                    "referenceId": "ref-123",
                }
            }
        }

        with pytest.raises(SecuritasDirectError, match="Panel offline"):
            await authed_api.disarm_alarm(installation, "DARM1")

    async def test_none_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSDisarmPanel": None}}

        with pytest.raises(SecuritasDirectError, match="xSDisarmPanel response is None"):
            await authed_api.disarm_alarm(installation, "DARM1")

    async def test_errors_only_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        """GraphQL validation error (no data key) raises SecuritasDirectError instead of KeyError."""
        mock_execute.return_value = {
            "errors": [
                {
                    "message": "4: Requested data not found error.",
                    "name": "ApiError",
                    "data": {"res": "ERROR", "err": "4", "status": 404},
                }
            ]
        }

        with pytest.raises(SecuritasDirectError, match="data not found"):
            await authed_api.disarm_alarm(installation, "DARM1DARMPERI")

    async def test_polls_check_disarm_status_on_wait(
        self, authed_api, mock_execute, installation
    ):
        initial_response = {
            "data": {
                "xSDisarmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-disarm-456",
                }
            }
        }
        wait_response = {
            "data": {
                "xSDisarmStatus": {
                    "res": "WAIT",
                    "msg": "",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "",
                    "protomResponseDate": "",
                    "requestId": "",
                    "error": "",
                }
            }
        }
        ok_response = {
            "data": {
                "xSDisarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "DISARMED",
                    "numinst": "123456",
                    "protomResponse": "PROT_DISARMED",
                    "protomResponseDate": "2026-01-15",
                    "requestId": "req-004",
                    "error": "",
                }
            }
        }
        mock_execute.side_effect = [initial_response, wait_response, ok_response]

        result = await authed_api.disarm_alarm(installation, "DARM1")

        assert result.operation_status == "OK"
        assert result.status == "DISARMED"
        # 1 for xSDisarmPanel + 2 for _check_disarm_status (WAIT then OK)
        assert mock_execute.call_count == 3

    async def test_timeout_raises_when_always_wait(
        self, authed_api, mock_execute, installation
    ):
        """When the panel keeps returning WAIT, _poll_operation times out."""
        initial_response = {
            "data": {
                "xSDisarmPanel": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-disarm-789",
                }
            }
        }
        wait_response = {
            "data": {
                "xSDisarmStatus": {
                    "res": "WAIT",
                    "msg": "",
                    "status": "",
                    "numinst": "123456",
                    "protomResponse": "",
                    "protomResponseDate": "",
                    "requestId": "",
                    "error": "",
                }
            }
        }

        # First call returns initial_response, all subsequent return WAIT
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return initial_response
            return wait_response

        mock_execute.side_effect = _side_effect

        # _poll_operation uses wall-clock timeout; use a short one via monkeypatch
        original_poll = authed_api._poll_operation

        async def _short_timeout_poll(check_fn, **kwargs):
            kwargs.setdefault("timeout", 0.05)
            return await original_poll(check_fn, **kwargs)

        authed_api._poll_operation = _short_timeout_poll

        with pytest.raises(TimeoutError, match="timed out"):
            await authed_api.disarm_alarm(installation, "DARM1")


# ── check_general_status() ───────────────────────────────────────────────────


class TestCheckGeneralStatus:
    async def test_success_returns_sstatus(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSStatus": {
                    "status": "ARMED_TOTAL",
                    "timestampUpdate": "2026-01-15T10:30:00Z",
                    "exceptions": [],
                }
            }
        }

        result = await authed_api.check_general_status(installation)

        assert isinstance(result, SStatus)
        assert result.status == "ARMED_TOTAL"
        assert result.timestampUpdate == "2026-01-15T10:30:00Z"

    async def test_errors_in_response_returns_none_sstatus(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"errors": [{"message": "Something went wrong"}]}

        result = await authed_api.check_general_status(installation)

        assert isinstance(result, SStatus)
        assert result.status is None
        assert result.timestampUpdate is None

    async def test_none_xsstatus_returns_none_sstatus(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSStatus": None}}

        result = await authed_api.check_general_status(installation)

        assert isinstance(result, SStatus)
        assert result.status is None
        assert result.timestampUpdate is None
