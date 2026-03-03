"""Tests for diagnostic data from xSStatus."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    Installation,
    SStatus,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def installation():
    return Installation(number="123456", alias="Home", panel="SDVFAST", type="PLUS")


@pytest.fixture
def authed_api(api):
    api._check_authentication_token = AsyncMock()
    api._check_capabilities_token = AsyncMock()
    return api


class TestCheckGeneralStatusDiagnostics:
    async def test_returns_diagnostic_fields(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSStatus": {
                    "status": "D",
                    "timestampUpdate": "2024-01-01 12:00:00",
                    "wifiConnected": True,
                    "keepAliveDay": 42,
                    "confort_message": "Stable",
                    "exceptions": [],
                }
            }
        }

        result = await authed_api.check_general_status(installation)

        assert isinstance(result, SStatus)
        assert result.status == "D"
        assert result.wifi_connected is True
        assert result.keep_alive_day == 42
        assert result.confort_message == "Stable"

    async def test_missing_diagnostic_fields_default_to_none(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSStatus": {
                    "status": "D",
                    "timestampUpdate": "2024-01-01 12:00:00",
                    "exceptions": [],
                }
            }
        }

        result = await authed_api.check_general_status(installation)

        assert result.wifi_connected is None
        assert result.keep_alive_day is None
        assert result.confort_message is None

    async def test_error_response_returns_none_diagnostics(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"errors": [{"message": "fail"}]}

        result = await authed_api.check_general_status(installation)

        assert result.status is None
        assert result.wifi_connected is None
        assert result.keep_alive_day is None
        assert result.confort_message is None
