"""Tests for ApiManager smart lock operations."""

import pytest
from unittest.mock import AsyncMock

from custom_components.securitas.securitas_direct_new_api.models import (
    Installation,
    SmartLock,
    SmartLockMode,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
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
        assert result.device_id == ""  # not in response, uses default
        assert result.reference_id == "ref1"
        assert result.zone_id == "z1"
        assert result.serial_number == "SN001"
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
        assert result.reference_id == ""
        assert result.serial_number == ""
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
        assert result.features.hold_back_latch_time == 3
        assert result.features.calibration_type == 0
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
        assert result[0].lock_status == "2"

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
        assert result[0].lock_status == "1"

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

        assert result[0].device_id == "02"

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
        assert result[0].device_id == "01"
        assert result[0].lock_status == "2"
        assert result[0].status_timestamp == "111"
        assert result[1].device_id == "02"
        assert result[1].lock_status == "1"
        assert result[1].status_timestamp == "222"

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

        assert result[0].status_timestamp == "1772728828235"


# ── submit_danalock_config_request() ──────────────────────────────────────


class TestSubmitDanalockConfigRequest:
    async def test_returns_reference_id(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSGetDanalockConfig": {
                    "res": "OK",
                    "msg": "alarm-manager.processed.request",
                    "referenceId": "abc-123",
                }
            }
        }

        result = await authed_api.submit_danalock_config_request(installation)

        assert result == "abc-123"

    async def test_variables_passed_correctly(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetDanalockConfig": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-1",
                }
            }
        }

        await authed_api.submit_danalock_config_request(installation, "02")

        call_args = mock_execute.call_args[0][0]
        assert call_args["variables"]["deviceId"] == "02"
        assert call_args["variables"]["deviceType"] == "DR"
        assert call_args["variables"]["numinst"] == installation.number
        assert call_args["variables"]["panel"] == installation.panel

    async def test_no_reference_id_raises(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSGetDanalockConfig": {
                    "res": "OK",
                    "msg": "",
                }
            }
        }

        with pytest.raises(SecuritasDirectError, match="referenceId"):
            await authed_api.submit_danalock_config_request(installation)


# ── check_danalock_config_status() ────────────────────────────────────────


class TestCheckDanalockConfigStatus:
    async def test_returns_wait_response(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSGetDanalockConfigStatus": {
                    "res": "WAIT",
                    "msg": "peripherals.processing.request",
                    "features": None,
                }
            }
        }

        result = await authed_api.check_danalock_config_status(installation, "ref-1", 1)

        assert result["res"] == "WAIT"

    async def test_counter_passed_in_variables(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetDanalockConfigStatus": {
                    "res": "WAIT",
                    "msg": "",
                }
            }
        }

        await authed_api.check_danalock_config_status(installation, "ref-1", 3)

        call_args = mock_execute.call_args[0][0]
        assert call_args["variables"]["counter"] == 3
        assert call_args["variables"]["referenceId"] == "ref-1"


# ── parse_danalock_config_response() ──────────────────────────────────────


class TestParseDanalockConfigResponse:
    def test_parses_features(self, authed_api):
        """Features from Danalock config status are parsed into SmartLock."""
        raw = {
            "res": "OK",
            "msg": "peripherals.lock-configuration-request.success",
            "deviceNumber": "001",
            "features": {
                "holdBackLatchTime": 3,
                "calibrationType": 0,
                "autolock": {"active": None, "timeout": None},
            },
        }

        result = authed_api.parse_danalock_config_response(raw)

        assert isinstance(result, SmartLock)
        assert result.res == "OK"
        assert result.features is not None
        assert result.features.hold_back_latch_time == 3
        assert result.features.calibration_type == 0

    def test_parses_autolock(self, authed_api):
        """Autolock config is parsed correctly."""
        raw = {
            "res": "OK",
            "deviceNumber": "001",
            "features": {
                "holdBackLatchTime": 5,
                "calibrationType": 1,
                "autolock": {"active": True, "timeout": "1800"},
            },
        }

        result = authed_api.parse_danalock_config_response(raw)

        assert result.features.hold_back_latch_time == 5
        assert result.features.autolock is not None
        assert result.features.autolock.active is True
        assert result.features.autolock.timeout == "1800"

    def test_no_features_returns_none_features(self, authed_api):
        """Danalock config with no features field."""
        raw = {
            "res": "OK",
            "msg": "success",
            "deviceNumber": "001",
            "features": None,
        }

        result = authed_api.parse_danalock_config_response(raw)

        assert result.res == "OK"
        assert result.features is None

    def test_device_id_from_device_number(self, authed_api):
        """deviceNumber from response is used as deviceId."""
        raw = {"res": "OK", "deviceNumber": "002", "features": None}

        result = authed_api.parse_danalock_config_response(raw)

        assert result.device_id == "002"

    def test_device_id_fallback(self, authed_api):
        """Falls back to provided device_id when deviceNumber is missing."""
        raw = {"res": "OK", "features": None}

        result = authed_api.parse_danalock_config_response(raw, "03")

        assert result.device_id == "03"
