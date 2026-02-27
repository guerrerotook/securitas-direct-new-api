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

        with pytest.raises(SecuritasDirectError, match="no check alarm data"):
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

        with pytest.raises(SecuritasDirectError, match="Disarm response is None"):
            await authed_api.disarm_alarm(installation, "DARM1")

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

    async def test_max_retries_exceeded_returns_last_status(
        self, authed_api, mock_execute, installation
    ):
        """When max retries exceeded, the loop breaks and returns whatever data it has."""
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
        # With delay_check_operation=0, max_retries = max(10, round(30/max(1,0)))
        # max(1, 0) = 1, 30/1 = 30, max(10, 30) = 30
        # We need more than 30 WAIT responses to exceed retries.
        # Actually with delay=0: max(1, self.delay_check_operation) = max(1, 0) = 1
        # max_retries = max(10, round(30 / 1)) = 30
        # So we need 31 WAIT responses (count goes from 1 to 31, which is > 30).
        mock_execute.side_effect = [initial_response] + [wait_response] * 31

        result = await authed_api.disarm_alarm(installation, "DARM1")

        # Should return with WAIT status rather than hanging forever
        assert isinstance(result, DisarmStatus)
        assert result.operation_status == "WAIT"


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
