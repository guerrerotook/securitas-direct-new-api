"""Tests for ApiManager alarm operations (check, arm, disarm, status)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    Installation,
    OperationStatus,
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

        result = await authed_api.check_alarm_status(installation, "ref-123")

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARMED"
        assert result.installation_number == "123456"
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

        result = await authed_api.check_alarm_status(installation, "ref-123")

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
            await authed_api.check_alarm_status(installation, "ref-123")


# ── arm_alarm() ──────────────────────────────────────────────────────────────


class TestArmAlarm:
    """Tests for SecuritasHub.arm_alarm() which orchestrates the decomposed API methods."""

    @pytest.fixture
    def hub(self, authed_api):
        """Create a SecuritasHub with mocked session (authed_api) and zero-interval queue."""
        hub = MagicMock()
        hub.session = authed_api
        # Use a real ApiQueue with zero interval for fast tests
        from custom_components.securitas.api_queue import ApiQueue

        hub._api_queue = ApiQueue(interval=0)
        # Use the real _max_poll_attempts method
        from custom_components.securitas.hub import SecuritasHub

        hub._max_poll_attempts = SecuritasHub._max_poll_attempts.__get__(hub)
        hub.arm_alarm = SecuritasHub.arm_alarm.__get__(hub)
        return hub

    async def test_success_returns_arm_status(self, hub, installation):
        """Successful arm: submit -> check (OK) -> process returns OperationStatus."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-arm-123")
        hub.session.check_arm_status = AsyncMock(
            return_value={
                "res": "OK",
                "msg": "",
                "status": "ARMED_TOTAL",
                "numinst": "123456",
                "protomResponse": "PROT_ARMED",
                "protomResponseDate": "2026-01-15",
                "requestId": "req-001",
                "error": "",
            }
        )
        expected_result = OperationStatus(
            operation_status="OK",
            status="ARMED_TOTAL",
            installation_number="123456",
            protomResponse="PROT_ARMED",
            requestId="req-001",
        )
        hub.session.process_arm_result = AsyncMock(return_value=expected_result)

        result = await hub.arm_alarm(installation, "ARM1")

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARMED_TOTAL"
        assert result.installation_number == "123456"
        assert result.requestId == "req-001"
        hub.session.submit_arm_request.assert_awaited_once_with(installation, "ARM1")
        hub.session.process_arm_result.assert_awaited_once()

    async def test_submit_error_propagates(self, hub, installation):
        """When submit_arm_request raises SecuritasDirectError, it propagates."""
        hub.session.submit_arm_request = AsyncMock(
            side_effect=SecuritasDirectError("Panel not responding")
        )

        with pytest.raises(SecuritasDirectError, match="Panel not responding"):
            await hub.arm_alarm(installation, "ARM1")

    async def test_submit_none_response_raises_error(self, hub, installation):
        """When submit_arm_request raises due to None response, it propagates."""
        hub.session.submit_arm_request = AsyncMock(
            side_effect=SecuritasDirectError("xSArmPanel response is None")
        )

        with pytest.raises(SecuritasDirectError, match="xSArmPanel response is None"):
            await hub.arm_alarm(installation, "ARM1")

    async def test_graphql_validation_error_raises(self, hub, installation):
        """GraphQL BAD_USER_INPUT error from submit propagates as SecuritasDirectError."""
        hub.session.submit_arm_request = AsyncMock(
            side_effect=SecuritasDirectError(
                'Value "ARMNIGHT1PERI1" does not exist in "ArmCodeRequest" enum.'
            )
        )

        with pytest.raises(SecuritasDirectError, match="does not exist"):
            await hub.arm_alarm(installation, "ARMNIGHT1PERI1")

    async def test_polls_check_arm_status_on_wait(self, hub, installation):
        """Hub polls check_arm_status until res != WAIT."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-arm-456")
        wait_raw = {"res": "WAIT", "msg": "Waiting"}
        ok_raw = {
            "res": "OK",
            "msg": "",
            "status": "ARMED_TOTAL",
            "numinst": "123456",
            "protomResponse": "PROT_ARMED",
            "protomResponseDate": "2026-01-15",
            "requestId": "req-002",
            "error": "",
        }
        hub.session.check_arm_status = AsyncMock(side_effect=[wait_raw, ok_raw])
        expected_result = OperationStatus(operation_status="OK", status="ARMED_TOTAL")
        hub.session.process_arm_result = AsyncMock(return_value=expected_result)

        result = await hub.arm_alarm(installation, "ARM1")

        assert result.operation_status == "OK"
        assert result.status == "ARMED_TOTAL"
        # check_arm_status called twice (WAIT then OK)
        assert hub.session.check_arm_status.await_count == 2
        # Verify attempt counters: 1 then 2
        calls = hub.session.check_arm_status.call_args_list
        assert calls[0][0] == (installation, "ref-arm-456", "ARM1", 1)
        assert calls[1][0] == (installation, "ref-arm-456", "ARM1", 2)

    async def test_non_blocking_exception_raises_arming_exception_error(
        self, hub, installation
    ):
        """When process_arm_result raises ArmingExceptionError, it propagates through the hub."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-arm-exc")
        exception_raw = {
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
        hub.session.check_arm_status = AsyncMock(return_value=exception_raw)
        hub.session.process_arm_result = AsyncMock(
            side_effect=ArmingExceptionError(
                "ref-arm-exc",
                "123456VI4ucRGS5Q==",
                [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
            )
        )

        with pytest.raises(ArmingExceptionError) as exc_info:
            await hub.arm_alarm(installation, "ARMDAY1")

        assert exc_info.value.reference_id == "ref-arm-exc"
        assert exc_info.value.suid == "123456VI4ucRGS5Q=="
        assert len(exc_info.value.exceptions) == 1
        assert exc_info.value.exceptions[0]["alias"] == "Kitchen Door"

    async def test_force_arm_passes_force_params(self, hub, installation):
        """When force params are provided, they are passed to submit_arm_request."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-force-arm")
        ok_raw = {
            "res": "OK",
            "msg": "",
            "status": "ARMED",
            "numinst": "123456",
            "protomResponse": "P",
            "protomResponseDate": "2026-02-28",
            "requestId": "req-force",
            "error": None,
        }
        hub.session.check_arm_status = AsyncMock(return_value=ok_raw)
        expected_result = OperationStatus(operation_status="OK", protomResponse="P")
        hub.session.process_arm_result = AsyncMock(return_value=expected_result)

        result = await hub.arm_alarm(
            installation,
            "ARMDAY1",
            force_arming_remote_id="ref-original",
            suid="123456VI4ucRGS5Q==",
        )

        assert result.operation_status == "OK"
        assert result.protomResponse == "P"

        # Check submit_arm_request received force params
        hub.session.submit_arm_request.assert_awaited_once_with(
            installation,
            "ARMDAY1",
            force_arming_remote_id="ref-original",
            suid="123456VI4ucRGS5Q==",
        )

    async def test_blocking_error_raises_securitas_error_not_arming_exception(
        self, hub, installation
    ):
        """A BLOCKING error (allowForcing=false) should raise SecuritasDirectError, not ArmingExceptionError."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-arm-block")
        blocking_raw = {
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
        hub.session.check_arm_status = AsyncMock(return_value=blocking_raw)
        hub.session.process_arm_result = AsyncMock(
            side_effect=SecuritasDirectError("Arm command failed: error_blocking")
        )

        with pytest.raises(SecuritasDirectError, match="error_blocking"):
            await hub.arm_alarm(installation, "ARM1")

    async def test_arm_raises_on_technical_error(self, hub, installation):
        """TECHNICAL_ERROR from polling should raise SecuritasDirectError."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-1")
        tech_error_raw = {
            "res": "ERROR",
            "msg": "alarm-manager.error_protom_session",
            "status": None,
            "protomResponse": None,
            "protomResponseDate": None,
            "numinst": None,
            "requestId": None,
            "error": {
                "code": "alarm-manager.error_protom_session",
                "type": "TECHNICAL_ERROR",
                "allowForcing": False,
                "protomResponse": None,
            },
        }
        hub.session.check_arm_status = AsyncMock(return_value=tech_error_raw)
        hub.session.process_arm_result = AsyncMock(
            side_effect=SecuritasDirectError(
                "Arm command failed: alarm-manager.error_protom_session"
            )
        )

        with pytest.raises(SecuritasDirectError, match="error_protom_session"):
            await hub.arm_alarm(installation, "ARM1PERI1")

    async def test_timeout_raises_when_always_wait(self, hub, installation):
        """When the panel keeps returning WAIT, hub.arm_alarm times out."""
        hub.session.submit_arm_request = AsyncMock(return_value="ref-arm-timeout")
        hub.session.check_arm_status = AsyncMock(
            return_value={"res": "WAIT", "msg": "Waiting"}
        )
        # delay_check_operation=0 means _max_poll_attempts returns max(10, 30/1)=30
        # but that's fine — it will exhaust all attempts and raise TimeoutError
        hub.session.delay_check_operation = 0

        with pytest.raises(TimeoutError, match="Arm status poll timed out"):
            await hub.arm_alarm(installation, "ARM1")


class TestGetExceptions:
    """Tests for ApiManager._get_exceptions (live method on ApiManager)."""

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
    """Tests for SecuritasHub.disarm_alarm() which orchestrates the decomposed API methods."""

    @pytest.fixture
    def hub(self, authed_api):
        """Create a SecuritasHub with mocked session (authed_api) and zero-interval queue."""
        hub = MagicMock()
        hub.session = authed_api
        hub.session.protom_response = "P"
        from custom_components.securitas.api_queue import ApiQueue

        hub._api_queue = ApiQueue(interval=0)
        from custom_components.securitas.hub import SecuritasHub

        hub._max_poll_attempts = SecuritasHub._max_poll_attempts.__get__(hub)
        hub.disarm_alarm = SecuritasHub.disarm_alarm.__get__(hub)
        return hub

    async def test_success_returns_disarm_status(self, hub, installation):
        """Successful disarm: submit -> check (OK) -> process returns OperationStatus."""
        hub.session.submit_disarm_request = AsyncMock(return_value="ref-disarm-123")
        ok_raw = {
            "res": "OK",
            "msg": "",
            "status": "DISARMED",
            "numinst": "123456",
            "protomResponse": "PROT_DISARMED",
            "protomResponseDate": "2026-01-15",
            "requestId": "req-003",
            "error": "",
        }
        hub.session.check_disarm_status = AsyncMock(return_value=ok_raw)
        expected_result = OperationStatus(
            operation_status="OK",
            status="DISARMED",
            numinst="123456",
            requestId="req-003",
        )
        hub.session.process_disarm_result = MagicMock(return_value=expected_result)

        result = await hub.disarm_alarm(installation, "DARM1")

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "DISARMED"
        assert result.numinst == "123456"
        assert result.requestId == "req-003"
        hub.session.submit_disarm_request.assert_awaited_once_with(
            installation, "DARM1"
        )
        hub.session.process_disarm_result.assert_called_once_with(ok_raw)

    async def test_submit_error_propagates(self, hub, installation):
        """When submit_disarm_request raises SecuritasDirectError, it propagates."""
        hub.session.submit_disarm_request = AsyncMock(
            side_effect=SecuritasDirectError("Panel offline")
        )

        with pytest.raises(SecuritasDirectError, match="Panel offline"):
            await hub.disarm_alarm(installation, "DARM1")

    async def test_submit_none_response_raises_error(self, hub, installation):
        """When submit_disarm_request raises due to None response, it propagates."""
        hub.session.submit_disarm_request = AsyncMock(
            side_effect=SecuritasDirectError("xSDisarmPanel response is None")
        )

        with pytest.raises(
            SecuritasDirectError, match="xSDisarmPanel response is None"
        ):
            await hub.disarm_alarm(installation, "DARM1")

    async def test_graphql_validation_error_raises(self, hub, installation):
        """GraphQL validation error from submit propagates as SecuritasDirectError."""
        hub.session.submit_disarm_request = AsyncMock(
            side_effect=SecuritasDirectError("4: Requested data not found error.")
        )

        with pytest.raises(SecuritasDirectError, match="data not found"):
            await hub.disarm_alarm(installation, "DARM1DARMPERI")

    async def test_polls_check_disarm_status_on_wait(self, hub, installation):
        """Hub polls check_disarm_status until res != WAIT."""
        hub.session.submit_disarm_request = AsyncMock(return_value="ref-disarm-456")
        wait_raw = {"res": "WAIT", "msg": ""}
        ok_raw = {
            "res": "OK",
            "msg": "",
            "status": "DISARMED",
            "numinst": "123456",
            "protomResponse": "PROT_DISARMED",
            "protomResponseDate": "2026-01-15",
            "requestId": "req-004",
            "error": "",
        }
        hub.session.check_disarm_status = AsyncMock(side_effect=[wait_raw, ok_raw])
        expected_result = OperationStatus(operation_status="OK", status="DISARMED")
        hub.session.process_disarm_result = MagicMock(return_value=expected_result)

        result = await hub.disarm_alarm(installation, "DARM1")

        assert result.operation_status == "OK"
        assert result.status == "DISARMED"
        # check_disarm_status called twice (WAIT then OK)
        assert hub.session.check_disarm_status.await_count == 2
        # Verify attempt counters and current_status passed correctly
        calls = hub.session.check_disarm_status.call_args_list
        assert calls[0][0] == (installation, "ref-disarm-456", "DARM1", 1, "P")
        assert calls[1][0] == (installation, "ref-disarm-456", "DARM1", 2, "P")
        # process_disarm_result only called once (on the OK response)
        hub.session.process_disarm_result.assert_called_once_with(ok_raw)

    async def test_disarm_raises_on_technical_error(self, hub, installation):
        """TECHNICAL_ERROR from process_disarm_result should propagate."""
        hub.session.submit_disarm_request = AsyncMock(return_value="ref-1")
        tech_error_raw = {
            "res": "ERROR",
            "msg": "alarm-manager.error_protom_session",
            "status": None,
            "protomResponse": None,
            "protomResponseDate": None,
            "numinst": None,
            "requestId": None,
            "error": {
                "code": "alarm-manager.error_protom_session",
                "type": "TECHNICAL_ERROR",
                "allowForcing": False,
                "protomResponse": None,
            },
        }
        hub.session.check_disarm_status = AsyncMock(return_value=tech_error_raw)
        hub.session.process_disarm_result = MagicMock(
            side_effect=SecuritasDirectError(
                "Disarm command failed: alarm-manager.error_protom_session"
            )
        )

        with pytest.raises(SecuritasDirectError, match="error_protom_session"):
            await hub.disarm_alarm(installation, "DARM1DARMPERI")

    async def test_timeout_raises_when_always_wait(self, hub, installation):
        """When the panel keeps returning WAIT, hub.disarm_alarm times out."""
        hub.session.submit_disarm_request = AsyncMock(return_value="ref-disarm-789")
        hub.session.check_disarm_status = AsyncMock(
            return_value={"res": "WAIT", "msg": ""}
        )
        hub.session.delay_check_operation = 0

        with pytest.raises(TimeoutError, match="Disarm status poll timed out"):
            await hub.disarm_alarm(installation, "DARM1")

    async def test_captures_protom_response_at_request_time(self, hub, installation):
        """The current_status passed to check_disarm_status is captured before submit."""
        hub.session.protom_response = "ARMED_TOTAL"
        hub.session.submit_disarm_request = AsyncMock(return_value="ref-123")
        ok_raw = {
            "res": "OK",
            "msg": "",
            "status": "DISARMED",
            "numinst": "123456",
            "protomResponse": "D",
            "protomResponseDate": "2026-01-15",
            "requestId": "req-1",
            "error": "",
        }
        hub.session.check_disarm_status = AsyncMock(return_value=ok_raw)
        hub.session.process_disarm_result = MagicMock(
            return_value=OperationStatus(status="DISARMED")
        )

        await hub.disarm_alarm(installation, "DARM1")

        # Verify current_status="ARMED_TOTAL" was passed (captured before submit)
        call_args = hub.session.check_disarm_status.call_args_list[0][0]
        assert call_args[4] == "ARMED_TOTAL"


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
