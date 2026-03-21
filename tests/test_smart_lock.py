"""Tests for ApiManager smart lock operations."""

import pytest
from unittest.mock import AsyncMock

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
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
    async def test_success_returns_all_fields(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Front Door",
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

        assert result.res == "OK"
        assert result.location == "Front Door"
        assert result.features is None
        assert result.deviceId == ""  # not in response, uses default
        assert result.referenceId == "ref1"
        assert result.zoneId == "z1"
        assert result.serialNumber == "SN001"
        assert result.family == "DR"
        assert result.label == "lock1"

    async def test_device_id_passed_to_query(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Back Door",
                }
            }
        }

        await authed_api.get_smart_lock_config(installation, device_id="02")

        call_args = mock_execute.call_args[0][0]
        assert call_args["variables"]["deviceId"] == "02"

    async def test_missing_fields_use_defaults(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "Hall",
                }
            }
        }

        result = await authed_api.get_smart_lock_config(installation)

        assert result.res == "OK"
        assert result.location == "Hall"
        assert result.referenceId == ""
        assert result.serialNumber == ""
        assert result.family == ""
        assert result.label == ""

    async def test_error_in_response_returns_empty_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"errors": [{"message": "Something went wrong"}]}

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res is None
        assert result.location is None

    async def test_none_data_returns_empty_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSGetSmartlockConfig": None}}

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res is None
        assert result.location is None

    async def test_no_data_key_returns_empty_smart_lock(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"something_else": "value"}

        result = await authed_api.get_smart_lock_config(installation)

        assert isinstance(result, SmartLock)
        assert result.res is None
        assert result.location is None

    async def test_features_parsed_from_response(
        self, authed_api, mock_execute, installation
    ):
        """Features from xSGetSmartlockConfig are parsed into SmartLock."""
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "referenceId": None,
                    "zoneId": "DR02",
                    "serialNumber": "326V8W84",
                    "location": "Pl_0_Hall",
                    "family": "User",
                    "label": "Cerradura",
                    "features": {
                        "holdBackLatchTime": 3,
                        "calibrationType": 0,
                        "autolock": {
                            "active": True,
                            "timeout": "1800",
                        },
                    },
                }
            }
        }
        result = await authed_api.get_smart_lock_config(installation, "02")
        assert result.features is not None
        assert result.features.holdBackLatchTime == 3
        assert result.features.calibrationType == 0
        assert result.features.autolock is not None
        assert result.features.autolock.active is True
        assert result.features.autolock.timeout == "1800"

    async def test_no_features_in_response(
        self, authed_api, mock_execute, installation
    ):
        """SmartLock with no features field returns features=None."""
        mock_execute.return_value = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "referenceId": None,
                    "zoneId": "DR01",
                    "serialNumber": "ABC123",
                    "location": "Hall",
                    "family": "User",
                    "label": "Lock",
                    "features": None,
                }
            }
        }
        result = await authed_api.get_smart_lock_config(installation, "01")
        assert result.features is None


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
