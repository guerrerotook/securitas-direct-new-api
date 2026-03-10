"""Tests for ApiManager smart lock operations."""

import pytest
from unittest.mock import AsyncMock

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    DanalockConfig,
    Installation,
    SmartLock,
    SmartLockMode,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def installation():
    return Installation(number="123456", alias="Home", panel="SDVFAST", type="PLUS")


@pytest.fixture
def authed_api(api):
    api._check_authentication_token = AsyncMock()
    api._check_capabilities_token = AsyncMock()
    api.delay_check_operation = 0
    return api


# ── get_smart_lock_config() ─────────────────────────────────────────────────


class TestGetSmartLockConfig:
    async def test_success_returns_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Front Door",
                    "type": 1,
                    "referenceId": "ref1",
                    "zoneId": "z1",
                    "serialNumber": "SN001",
                    "family": "DR",
                    "label": "lock1",
                    "features": None,
                }
            }
        }

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res == "OK"
        assert result.location == "Front Door"
        assert result.type == 1

    async def test_error_in_response_returns_empty_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"errors": [{"message": "Something went wrong"}]}

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res is None
        assert result.location is None
        assert result.type is None

    async def test_none_data_returns_empty_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSGetSmartlockConfig": None}}

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res is None
        assert result.location is None
        assert result.type is None

    async def test_no_data_key_returns_empty_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"something_else": "value"}

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res is None
        assert result.location is None
        assert result.type is None


# ── get_lock_current_mode() ─────────────────────────────────────────────────


class TestGetLockCurrentMode:
    async def test_success_returns_locked_status(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": [{"lockStatus": "2", "deviceId": "01"}],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert len(result) == 1
        assert isinstance(result[0], SmartLockMode)
        assert result[0].res == "OK"
        assert result[0].lockStatus == "2"

    async def test_success_returns_open_status(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": [{"lockStatus": "1", "deviceId": "01"}],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert len(result) == 1
        assert result[0].res == "OK"
        assert result[0].lockStatus == "1"

    async def test_error_in_response_returns_empty_list(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"errors": [{"message": "Something went wrong"}]}

        result = await authed_api.get_lock_current_mode(installation)

        assert result == []

    async def test_none_data_returns_empty_list(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSGetLockCurrentMode": None}}

        result = await authed_api.get_lock_current_mode(installation)

        assert result == []

    async def test_success_extracts_device_id(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": [{"lockStatus": "2", "deviceId": "02"}],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert result[0].deviceId == "02"

    async def test_no_smartlock_info_returns_empty_list(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": None,
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert result == []

    async def test_multiple_locks_returned(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": [
                        {
                            "lockStatus": "2",
                            "deviceId": "01",
                            "statusTimestamp": "111",
                        },
                        {
                            "lockStatus": "1",
                            "deviceId": "02",
                            "statusTimestamp": "222",
                        },
                    ],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert len(result) == 2
        assert result[0].deviceId == "01"
        assert result[0].lockStatus == "2"
        assert result[0].statusTimestamp == "111"
        assert result[1].deviceId == "02"
        assert result[1].lockStatus == "1"
        assert result[1].statusTimestamp == "222"

    async def test_status_timestamp_extracted(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": [
                        {
                            "lockStatus": "1",
                            "deviceId": "01",
                            "statusTimestamp": "1772728828235",
                        }
                    ],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert result[0].statusTimestamp == "1772728828235"


# ── get_danalock_config() ──────────────────────────────────────────────────


class TestGetDanalockConfig:
    async def test_success_returns_config(self, authed_api, mock_execute, installation):
        mock_execute.side_effect = [
            # Initial request
            {
                "data": {
                    "xSGetDanalockConfig": {
                        "res": "OK",
                        "msg": "alarm-manager.processed.request",
                        "referenceId": "ref-config-123",
                    }
                }
            },
            # Poll returns config
            {
                "data": {
                    "xSGetDanalockConfigStatus": {
                        "res": "OK",
                        "msg": "peripherals.lock-configuration-request.success",
                        "action": "0",
                        "deviceNumber": "001",
                        "asyncCylinder": "0",
                        "batteryLowPercenteage": "40",
                        "lockBeforePartialArm": "1",
                        "lockBeforeFullArm": "1",
                        "unlockAfterDisarm": "0",
                        "lockBeforePerimeterArm": "1",
                        "periodicBitExtension": "10080",
                        "autoLockTime": "000",
                        "features": {
                            "holdBackLatchTime": 3,
                            "calibrationType": 0,
                            "autolock": {
                                "active": None,
                                "timeout": None,
                            },
                        },
                    }
                }
            },
        ]

        result = await authed_api.get_danalock_config(installation, "01")

        assert isinstance(result, DanalockConfig)
        assert result.action == "0"
        assert result.deviceNumber == "001"
        assert result.batteryLowPercentage == "40"
        assert result.lockBeforeFullArm == "1"
        assert result.lockBeforePartialArm == "1"
        assert result.unlockAfterDisarm == "0"
        assert result.lockBeforePerimeterArm == "1"
        assert result.autoLockTime == "000"
        assert result.features is not None
        assert result.features.holdBackLatchTime == 3
        assert result.features.calibrationType == 0
        assert result.features.autolock is not None
        assert result.features.autolock.active is None
        assert result.features.autolock.timeout is None

    async def test_poll_wait_then_success(self, authed_api, mock_execute, installation):
        mock_execute.side_effect = [
            # Initial request
            {
                "data": {
                    "xSGetDanalockConfig": {
                        "res": "OK",
                        "msg": "",
                        "referenceId": "ref-wait",
                    }
                }
            },
            # First poll: WAIT
            {
                "data": {
                    "xSGetDanalockConfigStatus": {
                        "res": "WAIT",
                        "msg": "peripherals.processing.request",
                        "action": None,
                        "deviceNumber": None,
                        "features": None,
                    }
                }
            },
            # Second poll: OK
            {
                "data": {
                    "xSGetDanalockConfigStatus": {
                        "res": "OK",
                        "msg": "peripherals.lock-configuration-request.success",
                        "action": "0",
                        "deviceNumber": "001",
                        "batteryLowPercenteage": "30",
                        "lockBeforePartialArm": "0",
                        "lockBeforeFullArm": "0",
                        "unlockAfterDisarm": "1",
                        "lockBeforePerimeterArm": "0",
                        "periodicBitExtension": "5000",
                        "autoLockTime": "060",
                        "features": {
                            "holdBackLatchTime": 5,
                            "calibrationType": 1,
                        },
                    }
                }
            },
        ]

        result = await authed_api.get_danalock_config(installation, "01")

        assert isinstance(result, DanalockConfig)
        assert result.batteryLowPercentage == "30"
        assert result.features is not None
        assert result.features.holdBackLatchTime == 5
        assert result.features.autolock is None
        # 1 initial + 2 polls = 3 calls
        assert mock_execute.call_count == 3

    async def test_initial_request_failure_returns_none(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetDanalockConfig": {
                    "res": "ERROR",
                    "msg": "not supported",
                }
            }
        }

        result = await authed_api.get_danalock_config(installation, "01")

        assert result is None

    async def test_features_none_handled(self, authed_api, mock_execute, installation):
        mock_execute.side_effect = [
            {
                "data": {
                    "xSGetDanalockConfig": {
                        "res": "OK",
                        "msg": "",
                        "referenceId": "ref-no-features",
                    }
                }
            },
            {
                "data": {
                    "xSGetDanalockConfigStatus": {
                        "res": "OK",
                        "msg": "",
                        "action": "0",
                        "deviceNumber": "001",
                        "batteryLowPercenteage": "50",
                        "features": None,
                    }
                }
            },
        ]

        result = await authed_api.get_danalock_config(installation, "01")

        assert isinstance(result, DanalockConfig)
        assert result.batteryLowPercentage == "50"
        assert result.features is None

    async def test_device_id_passed_to_query(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.side_effect = [
            {
                "data": {
                    "xSGetDanalockConfig": {
                        "res": "OK",
                        "msg": "",
                        "referenceId": "ref-dev",
                    }
                }
            },
            {
                "data": {
                    "xSGetDanalockConfigStatus": {
                        "res": "OK",
                        "action": "0",
                        "deviceNumber": "002",
                        "features": None,
                    }
                }
            },
        ]

        await authed_api.get_danalock_config(installation, "02")

        # First call should include the device_id
        query_content = mock_execute.call_args_list[0][0][0]
        assert query_content["variables"]["deviceId"] == "02"
