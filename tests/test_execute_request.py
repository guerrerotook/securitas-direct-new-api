"""Tests for _execute_request, generate_uuid, and generate_device_id."""

import json

import pytest
from aiohttp import ClientConnectorError
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.securitas.securitas_direct_new_api.apimanager import (
    ApiManager,
    generate_device_id,
    generate_uuid,
)
from custom_components.securitas.securitas_direct_new_api.dataTypes import Installation
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_response():
    """Create a mock aiohttp response."""
    response = AsyncMock()
    response.text = AsyncMock(return_value='{"data": {"test": "ok"}}')
    return response


@pytest.fixture
def mock_post(api, mock_response):
    """Mock the http_client.post context manager."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_response)
    cm.__aexit__ = AsyncMock(return_value=False)
    api.http_client.post = MagicMock(return_value=cm)
    return api.http_client.post


# ── _execute_request tests ───────────────────────────────────────────────────


class TestExecuteRequest:
    """Tests for ApiManager._execute_request."""

    async def test_success_returns_parsed_json(self, api, mock_post):
        """Successful request returns parsed JSON dict."""
        result = await api._execute_request(
            {"query": "test"}, "TestOperation"
        )
        assert result == {"data": {"test": "ok"}}

    async def test_sets_correct_headers(self, api, mock_post):
        """Request sets app, User-Agent, X-APOLLO-OPERATION-ID, and X-APOLLO-OPERATION-NAME headers."""
        await api._execute_request({"query": "test"}, "TestOperation")

        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]

        app_value = json.loads(headers["app"])
        assert app_value["appVersion"] == api.device_version
        assert app_value["origin"] == "native"
        assert "User-Agent" in headers
        assert "Mozilla" in headers["User-Agent"]
        assert headers["X-APOLLO-OPERATION-ID"] == api.apollo_operation_id
        assert headers["X-APOLLO-OPERATION-NAME"] == "TestOperation"

    async def test_includes_auth_header_when_token_set(self, api, mock_post):
        """Auth header is included when authentication_token is set."""
        api.authentication_token = "some-token"
        api.login_timestamp = 12345

        await api._execute_request({"query": "test"}, "TestOperation")

        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        assert "auth" in headers
        auth_value = json.loads(headers["auth"])
        assert auth_value["hash"] == "some-token"
        assert auth_value["user"] == "test@example.com"
        assert auth_value["country"] == "ES"
        assert auth_value["loginTimestamp"] == 12345
        assert auth_value["callby"] == "OWA_10"

    async def test_no_auth_header_when_token_empty(self, api, mock_post):
        """Auth header is NOT included when authentication_token is empty."""
        api.authentication_token = ""

        await api._execute_request({"query": "test"}, "SomeOtherOp")

        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        assert "auth" not in headers

    async def test_includes_installation_headers(self, api, mock_post):
        """numinst, panel, and X-Capabilities headers are set when installation is provided."""
        installation = Installation(
            number="12345",
            panel="PANEL-01",
            capabilities="cap1,cap2",
        )

        await api._execute_request(
            {"query": "test"}, "TestOperation", installation=installation
        )

        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        assert headers["numinst"] == "12345"
        assert headers["panel"] == "PANEL-01"
        assert headers["X-Capabilities"] == "cap1,cap2"

    async def test_client_connector_error_raises_securitas_error(
        self, api, mock_response
    ):
        """ClientConnectorError is wrapped in SecuritasDirectError."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(
            side_effect=ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("Connection refused")
            )
        )
        cm.__aexit__ = AsyncMock(return_value=False)
        api.http_client.post = MagicMock(return_value=cm)

        with pytest.raises(SecuritasDirectError, match="Connection error"):
            await api._execute_request({"query": "test"}, "TestOperation")

    async def test_invalid_json_raises_securitas_error(self, api):
        """Invalid JSON response raises SecuritasDirectError."""
        response = AsyncMock()
        response.text = AsyncMock(return_value="not valid json {{{")

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)
        api.http_client.post = MagicMock(return_value=cm)

        with pytest.raises(SecuritasDirectError):
            await api._execute_request({"query": "test"}, "TestOperation")

    async def test_error_with_reason_raises_securitas_error(self, api):
        """Response containing errors.data.reason raises SecuritasDirectError."""
        error_response = json.dumps(
            {"errors": {"data": {"reason": "Session expired"}}}
        )
        response = AsyncMock()
        response.text = AsyncMock(return_value=error_response)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)
        api.http_client.post = MagicMock(return_value=cm)

        with pytest.raises(SecuritasDirectError, match="Session expired"):
            await api._execute_request({"query": "test"}, "TestOperation")

    @pytest.mark.parametrize(
        "operation",
        ["mkValidateDevice", "RefreshLogin", "mkSendOTP"],
    )
    async def test_special_operations_set_auth_with_empty_hash(
        self, api, mock_post, operation
    ):
        """Special operations set auth header with empty hash and refreshToken."""
        # Even with a real token set, the special operations override with empty values
        api.authentication_token = "real-token"

        await api._execute_request({"query": "test"}, operation)

        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        assert "auth" in headers
        auth_value = json.loads(headers["auth"])
        assert auth_value["hash"] == ""
        assert auth_value["refreshToken"] == ""
        assert auth_value["user"] == "test@example.com"
        assert auth_value["callby"] == "OWA_10"

    async def test_sets_security_header_when_otp_challenge_set(self, api, mock_post):
        """Security header is set when authentication_otp_challenge_value is not None."""
        api.authentication_otp_challenge_value = ("otp-hash-123", "otp-token-456")

        await api._execute_request({"query": "test"}, "TestOperation")

        _, kwargs = mock_post.call_args
        headers = kwargs["headers"]
        assert "security" in headers
        security_value = json.loads(headers["security"])
        assert security_value["token"] == "otp-token-456"
        assert security_value["type"] == "OTP"
        assert security_value["otpHash"] == "otp-hash-123"


# ── generate_uuid tests ─────────────────────────────────────────────────────


class TestGenerateUuid:
    """Tests for the generate_uuid module-level function."""

    def test_returns_16_character_string(self):
        """UUID is exactly 16 characters long."""
        result = generate_uuid()
        assert len(result) == 16

    def test_contains_no_hyphens(self):
        """UUID contains no hyphens."""
        result = generate_uuid()
        assert "-" not in result

    def test_two_calls_return_different_values(self):
        """Two calls return different UUIDs."""
        a = generate_uuid()
        b = generate_uuid()
        assert a != b


# ── generate_device_id tests ────────────────────────────────────────────────


class TestGenerateDeviceId:
    """Tests for the generate_device_id module-level function."""

    def test_contains_apa91b_marker(self):
        """Device ID contains the ':APA91b' marker."""
        result = generate_device_id("ES")
        assert ":APA91b" in result

    def test_returns_expected_length(self):
        """Device ID is 163 chars: 22 (token_urlsafe(16)) + 7 (':APA91b') + 134."""
        result = generate_device_id("ES")
        assert len(result) == 22 + 7 + 134

    def test_two_calls_return_different_values(self):
        """Two calls return different device IDs."""
        a = generate_device_id("ES")
        b = generate_device_id("ES")
        assert a != b
