"""Tests for ApiManager smart lock operations."""

import pytest
from unittest.mock import AsyncMock

from custom_components.securitas.securitas_direct_new_api.apimanager import ApiManager
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    Installation,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
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
        mock_execute.return_value = {
            "errors": [{"message": "Something went wrong"}]
        }

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
                    "smartlockInfo": [
                        {"lockStatus": "2", "deviceId": "01"}
                    ],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert isinstance(result, SmartLockMode)
        assert result.res == "OK"
        assert result.lockStatus == "2"

    async def test_success_returns_open_status(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSGetLockCurrentMode": {
                    "res": "OK",
                    "smartlockInfo": [
                        {"lockStatus": "1", "deviceId": "01"}
                    ],
                }
            }
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert isinstance(result, SmartLockMode)
        assert result.res == "OK"
        assert result.lockStatus == "1"

    async def test_error_in_response_returns_default_mode(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "errors": [{"message": "Something went wrong"}]
        }

        result = await authed_api.get_lock_current_mode(installation)

        assert isinstance(result, SmartLockMode)
        assert result.res is None
        assert result.lockStatus == "0"

    async def test_none_data_returns_default_mode(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSGetLockCurrentMode": None}}

        result = await authed_api.get_lock_current_mode(installation)

        assert isinstance(result, SmartLockMode)
        assert result.res is None
        assert result.lockStatus == "0"


# ── change_lock_mode() ──────────────────────────────────────────────────────


class TestChangeLockMode:
    async def test_lock_success_returns_status(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.side_effect = [
            {
                "data": {
                    "xSChangeSmartlockMode": {
                        "res": "OK",
                        "msg": "",
                        "referenceId": "ref123",
                    }
                }
            },
            {
                "data": {
                    "xSChangeSmartlockModeStatus": {
                        "res": "OK",
                        "msg": "",
                        "protomResponse": "D",
                        "status": "locked",
                    }
                }
            },
        ]

        result = await authed_api.change_lock_mode(installation, lock=True)

        assert isinstance(result, SmartLockModeStatus)
        assert result.requestId == "OK"
        assert result.message == ""
        assert result.protomResponse == "D"
        assert result.status == "locked"

    async def test_unlock_success_returns_status(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.side_effect = [
            {
                "data": {
                    "xSChangeSmartlockMode": {
                        "res": "OK",
                        "msg": "",
                        "referenceId": "ref456",
                    }
                }
            },
            {
                "data": {
                    "xSChangeSmartlockModeStatus": {
                        "res": "OK",
                        "msg": "",
                        "protomResponse": "D",
                        "status": "unlocked",
                    }
                }
            },
        ]

        result = await authed_api.change_lock_mode(installation, lock=False)

        assert isinstance(result, SmartLockModeStatus)
        assert result.requestId == "OK"
        assert result.message == ""
        assert result.protomResponse == "D"
        assert result.status == "unlocked"

    async def test_non_ok_initial_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSChangeSmartlockMode": {
                    "res": "ERROR",
                    "msg": "Lock unavailable",
                    "referenceId": "ref789",
                }
            }
        }

        with pytest.raises(SecuritasDirectError, match="Lock unavailable"):
            await authed_api.change_lock_mode(installation, lock=True)

    async def test_none_initial_response_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {"xSChangeSmartlockMode": None}
        }

        with pytest.raises(
            SecuritasDirectError, match="xSChangeSmartlockMode response is None"
        ):
            await authed_api.change_lock_mode(installation, lock=True)

    async def test_missing_reference_id_raises_error(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSChangeSmartlockMode": {
                    "res": "OK",
                    "msg": "",
                }
            }
        }

        with pytest.raises(SecuritasDirectError, match="No referenceId"):
            await authed_api.change_lock_mode(installation, lock=True)

    async def test_polls_when_status_is_wait(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.side_effect = [
            # Initial change request
            {
                "data": {
                    "xSChangeSmartlockMode": {
                        "res": "OK",
                        "msg": "",
                        "referenceId": "ref999",
                    }
                }
            },
            # First poll returns WAIT
            {
                "data": {
                    "xSChangeSmartlockModeStatus": {
                        "res": "WAIT",
                        "msg": "",
                        "protomResponse": "",
                        "status": "",
                    }
                }
            },
            # Second poll returns OK
            {
                "data": {
                    "xSChangeSmartlockModeStatus": {
                        "res": "OK",
                        "msg": "",
                        "protomResponse": "D",
                        "status": "locked",
                    }
                }
            },
        ]

        result = await authed_api.change_lock_mode(installation, lock=True)

        assert isinstance(result, SmartLockModeStatus)
        assert result.requestId == "OK"
        assert result.protomResponse == "D"
        assert result.status == "locked"
        # 1 initial request + 2 status polls = 3 calls total
        assert mock_execute.call_count == 3
