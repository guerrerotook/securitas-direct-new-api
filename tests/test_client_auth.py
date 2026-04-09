"""Tests for SecuritasClient — auth lifecycle, typed execute, polling, headers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.client import SecuritasClient
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    AccountBlockedError,
    AuthenticationError,
    OperationTimeoutError,
    SecuritasDirectError,
    TwoFactorRequiredError,
)
from custom_components.securitas.securitas_direct_new_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.securitas_direct_new_api.models import Installation
from custom_components.securitas.securitas_direct_new_api.responses import (
    GeneralStatusEnvelope,
)

pytestmark = pytest.mark.asyncio

# ── JWT helpers ──────────────────────────────────────────────────────────────

SECRET = "test-secret"


def make_jwt(exp_minutes: int = 15, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=exp_minutes)
    payload = {"exp": exp, "sub": "test-user", **extra_claims}
    return jwt.encode(payload, SECRET, algorithm="HS256")


FAKE_JWT = make_jwt(exp_minutes=15)
FAKE_JWT_EXPIRED = make_jwt(exp_minutes=-5)
FAKE_REFRESH_TOKEN = make_jwt(exp_minutes=180 * 24 * 60)


# ── Response builders ────────────────────────────────────────────────────────


def login_response(
    *,
    hash_token: str = FAKE_JWT,
    refresh_token: str = FAKE_REFRESH_TOKEN,
    need_2fa: bool = False,
    res: str = "OK",
) -> dict:
    """Build a mock xSLoginToken response."""
    return {
        "data": {
            "xSLoginToken": {
                "__typename": "LoginToken",
                "res": res,
                "msg": "",
                "hash": hash_token,
                "refreshToken": refresh_token,
                "legals": None,
                "changePassword": False,
                "needDeviceAuthorization": need_2fa,
                "mainUser": True,
            }
        }
    }


def refresh_response(
    *,
    hash_token: str | None = None,
    refresh_token: str | None = None,
    res: str = "OK",
) -> dict:
    """Build a mock xSRefreshLogin response."""
    if hash_token is None:
        hash_token = make_jwt(exp_minutes=15)
    if refresh_token is None:
        refresh_token = make_jwt(exp_minutes=180 * 24 * 60)
    return {
        "data": {
            "xSRefreshLogin": {
                "__typename": "RefreshLogin",
                "res": res,
                "msg": "",
                "hash": hash_token,
                "refreshToken": refresh_token,
                "legals": None,
                "changePassword": False,
                "needDeviceAuthorization": False,
                "mainUser": True,
            }
        }
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────


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


@pytest.fixture
def transport():
    """Create a mock HttpTransport."""
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport):
    """Create a SecuritasClient with test credentials and mocked transport."""
    return SecuritasClient(
        transport=transport,
        country="ES",
        language="es",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
    )


# ── Login tests ──────────────────────────────────────────────────────────────


class TestLogin:
    async def test_successful_login_sets_tokens(self, client, transport):
        """Successful login sets authentication_token, refresh_token_value, login_timestamp."""
        transport.execute.return_value = login_response()

        await client.login()

        assert client.authentication_token == FAKE_JWT
        assert client.refresh_token_value == FAKE_REFRESH_TOKEN
        assert client.login_timestamp > 0

    async def test_login_sets_token_expiry(self, client, transport):
        """Login decodes the JWT and sets the token expiry."""
        transport.execute.return_value = login_response()

        await client.login()

        assert client._authentication_token_exp > datetime.now()
        assert client._authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_login_2fa_raises_two_factor_required(self, client, transport):
        """Login with needDeviceAuthorization raises TwoFactorRequiredError."""
        transport.execute.return_value = login_response(need_2fa=True)

        with pytest.raises(TwoFactorRequiredError):
            await client.login()

    async def test_login_account_blocked_raises_account_blocked(
        self, client, transport
    ):
        """Account blocked (error 60052) raises AccountBlockedError."""
        err = SecuritasDirectError("forbidden", http_status=403)
        err.response_body = {
            "errors": [{"message": "forbidden", "data": {"err": "60052"}}],
            "data": None,
        }
        transport.execute.side_effect = err

        with pytest.raises(AccountBlockedError):
            await client.login()

    async def test_login_graphql_error_raises_authentication_error(
        self, client, transport
    ):
        """GraphQL error response raises AuthenticationError."""
        transport.execute.return_value = {
            "errors": [{"message": "Invalid credentials"}],
        }

        with pytest.raises(AuthenticationError):
            await client.login()

    async def test_login_error_with_data_raises_authentication_error(
        self, client, transport
    ):
        """Error response with data raises AuthenticationError."""
        err = SecuritasDirectError("bad request", http_status=400)
        err.response_body = {
            "errors": [{"message": "bad request"}],
            "data": {"xSLoginToken": None},
        }
        transport.execute.side_effect = err

        with pytest.raises(AuthenticationError):
            await client.login()

    async def test_login_connection_error_propagates(self, client, transport):
        """Connection error (no response_body) re-raises SecuritasDirectError."""
        transport.execute.side_effect = SecuritasDirectError("Connection failed")

        with pytest.raises(SecuritasDirectError, match="Connection failed"):
            await client.login()


# ── Refresh token tests ──────────────────────────────────────────────────────


class TestRefreshToken:
    async def test_successful_refresh_updates_tokens(self, client, transport):
        """Successful refresh updates authentication_token and refresh_token_value."""
        new_jwt = make_jwt(exp_minutes=15)
        new_refresh = make_jwt(exp_minutes=180 * 24 * 60)
        transport.execute.return_value = refresh_response(
            hash_token=new_jwt, refresh_token=new_refresh
        )
        # Pre-set a refresh token value so that the refresh request is valid
        client.refresh_token_value = "old-refresh-token"

        result = await client.refresh_token()

        assert result is True
        assert client.authentication_token == new_jwt
        assert client.refresh_token_value == new_refresh
        assert client.login_timestamp > 0

    async def test_failed_refresh_returns_false(self, client, transport):
        """Failed refresh (res != OK) returns False."""
        transport.execute.return_value = refresh_response(res="ERROR")
        client.refresh_token_value = "old-refresh-token"

        result = await client.refresh_token()

        assert result is False


# ── Typed execute tests ──────────────────────────────────────────────────────


class TestTypedExecute:
    async def test_returns_typed_pydantic_envelope(self, client, transport):
        """_execute_graphql returns a typed Pydantic envelope."""
        raw = {
            "data": {
                "xSStatus": {
                    "status": "ARMED",
                    "timestampUpdate": "2024-01-01",
                    "wifiConnected": True,
                    "exceptions": None,
                }
            }
        }
        transport.execute.return_value = raw

        # Pre-authenticate to skip auth check
        client.authentication_token = FAKE_JWT
        client._authentication_token_exp = datetime.now() + timedelta(hours=1)

        result = await client._execute_graphql(
            content={"operationName": "Status", "query": "..."},
            operation="Status",
            response_type=GeneralStatusEnvelope,
        )

        assert isinstance(result, GeneralStatusEnvelope)
        assert result.data.xSStatus.status == "ARMED"

    async def test_graphql_errors_raise_securitas_error(self, client, transport):
        """GraphQL errors in response raise SecuritasDirectError."""
        raw = {
            "errors": [{"message": "Something went wrong"}],
            "data": None,
        }
        transport.execute.return_value = raw

        # Pre-authenticate
        client.authentication_token = FAKE_JWT
        client._authentication_token_exp = datetime.now() + timedelta(hours=1)

        with pytest.raises(SecuritasDirectError, match="Something went wrong"):
            await client._execute_graphql(
                content={"operationName": "Status", "query": "..."},
                operation="Status",
                response_type=GeneralStatusEnvelope,
            )

    async def test_auth_operations_skip_auth_check(self, client, transport):
        """Operations in _AUTH_OPERATIONS skip the auth check."""
        transport.execute.return_value = login_response()

        # No authentication_token set — should NOT call login for auth ops
        await client.login()

        # Verify that transport.execute was called (it wouldn't be if auth was
        # required and login itself tried to login recursively)
        assert transport.execute.call_count == 1


# ── Ensure auth tests ────────────────────────────────────────────────────────


class TestEnsureAuth:
    async def test_calls_login_when_no_token(self, client, transport):
        """Calls login when no token exists."""
        transport.execute.return_value = login_response()

        await client._ensure_auth()

        # transport.execute called once for login
        assert transport.execute.call_count == 1

    async def test_calls_refresh_when_token_expired(self, client, transport):
        """Calls refresh when token expired and refresh token available."""
        new_jwt = make_jwt(exp_minutes=15)
        transport.execute.return_value = refresh_response(hash_token=new_jwt)

        # Set up expired token with refresh token available
        client.authentication_token = FAKE_JWT_EXPIRED
        client._authentication_token_exp = datetime.now() - timedelta(minutes=5)
        client.refresh_token_value = "some-refresh-token"

        await client._ensure_auth()

        # Should have called transport.execute for the refresh
        assert transport.execute.call_count == 1
        # The operation name in the content should be RefreshLogin
        call_args = transport.execute.call_args
        content = call_args[0][0] if call_args[0] else call_args[1]["content"]
        assert content["operationName"] == "RefreshLogin"

    async def test_falls_back_to_login_when_refresh_fails(self, client, transport):
        """Falls back to login when refresh fails."""
        # First call: refresh returns ERROR; second call: login succeeds
        transport.execute.side_effect = [
            refresh_response(res="ERROR"),
            login_response(),
        ]

        client.authentication_token = FAKE_JWT_EXPIRED
        client._authentication_token_exp = datetime.now() - timedelta(minutes=5)
        client.refresh_token_value = "some-refresh-token"

        await client._ensure_auth()

        # Two calls: one for refresh, one for login
        assert transport.execute.call_count == 2


# ── Poll operation tests ─────────────────────────────────────────────────────


class TestPollOperation:
    async def test_polls_until_not_wait(self, client):
        """Polls until res != WAIT."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "WAIT"},
                {"res": "WAIT"},
                {"res": "OK", "status": "ARMED"},
            ]
        )

        result = await client._poll_operation(check_fn)

        assert result["res"] == "OK"
        assert check_fn.call_count == 3

    async def test_raises_operation_timeout_error(self, client):
        """Raises OperationTimeoutError on timeout."""
        check_fn = AsyncMock(return_value={"res": "WAIT"})

        # Use a very short timeout to speed up the test
        with pytest.raises(OperationTimeoutError):
            await client._poll_operation(check_fn, timeout=0.1)

    async def test_retries_on_409_conflict(self, client):
        """Retries on 409 Conflict."""
        err_409 = SecuritasDirectError("conflict", http_status=409)
        check_fn = AsyncMock(
            side_effect=[
                err_409,
                {"res": "OK", "status": "ARMED"},
            ]
        )

        result = await client._poll_operation(check_fn)

        assert result["res"] == "OK"
        assert check_fn.call_count == 2

    async def test_handles_continue_on_msg(self, client):
        """Continues polling when msg matches continue_on_msg."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "ERROR", "msg": "no_response_to_request"},
                {"res": "OK", "status": "DISARMED"},
            ]
        )

        result = await client._poll_operation(
            check_fn,
            continue_on_msg="no_response_to_request",
        )

        assert result["res"] == "OK"
        assert check_fn.call_count == 2

    async def test_non_409_error_propagates(self, client):
        """Non-409 SecuritasDirectError propagates."""
        err = SecuritasDirectError("server error", http_status=500)
        check_fn = AsyncMock(side_effect=err)

        with pytest.raises(SecuritasDirectError, match="server error"):
            await client._poll_operation(check_fn)


# ── Build headers tests ─────────────────────────────────────────────────────


class TestBuildHeaders:
    def test_includes_auth_header(self, client):
        """Includes auth header when token is set."""
        client.authentication_token = FAKE_JWT
        client.login_timestamp = 1234567890

        headers = client._build_headers("Status")

        assert "auth" in headers
        import json

        auth = json.loads(headers["auth"])
        assert auth["hash"] == FAKE_JWT
        assert auth["user"] == "test@example.com"
        assert auth["country"] == "ES"
        assert auth["lang"] == "es"

    def test_includes_installation_headers(self, client):
        """Includes installation headers when installation is provided."""
        client.authentication_token = FAKE_JWT
        client.login_timestamp = 1234567890
        inst = _make_installation()
        client._capabilities[inst.number] = (
            "cap-token-123",
            datetime.now() + timedelta(hours=1),
        )

        headers = client._build_headers("Status", installation=inst)

        assert headers["numinst"] == "123456"
        assert headers["panel"] == "SDVFAST"
        assert headers["X-Capabilities"] == "cap-token-123"

    def test_auth_operation_headers(self, client):
        """Auth operations (RefreshLogin, etc.) get special headers."""
        client.login_timestamp = 1234567890

        headers = client._build_headers("RefreshLogin")

        import json

        auth = json.loads(headers["auth"])
        assert auth["hash"] == ""
        assert auth["refreshToken"] == ""

    def test_no_auth_header_when_no_token(self, client):
        """No auth header when authentication_token is not set."""
        client.authentication_token = None

        headers = client._build_headers("Status")

        assert "auth" not in headers

    def test_includes_standard_headers(self, client):
        """Includes standard headers (app, User-Agent, etc.)."""
        headers = client._build_headers("Status")

        assert "app" in headers
        assert "X-APOLLO-OPERATION-NAME" in headers
        assert headers["X-APOLLO-OPERATION-NAME"] == "Status"


# ── Ensure capabilities tests ────────────────────────────────────────────────


class TestEnsureCapabilities:
    async def test_refreshes_when_no_cached_capabilities(self, client):
        """Calls get_services when no capabilities cached for installation."""
        inst = _make_installation()
        # No entry in client._capabilities
        client.get_services = AsyncMock(return_value=[])

        await client._ensure_capabilities(inst)

        client.get_services.assert_called_once_with(inst)

    async def test_refreshes_when_capabilities_expired(self, client):
        """Calls get_services when cached capabilities token is expired."""
        inst = _make_installation()
        client._capabilities[inst.number] = (
            "old-cap",
            datetime.now() - timedelta(minutes=5),
        )
        client.get_services = AsyncMock(return_value=[])

        await client._ensure_capabilities(inst)

        client.get_services.assert_called_once_with(inst)

    async def test_skips_refresh_when_capabilities_valid(self, client):
        """Skips get_services when cached capabilities token is still valid."""
        inst = _make_installation()
        client._capabilities[inst.number] = (
            "valid-cap",
            datetime.now() + timedelta(minutes=30),
        )
        client.get_services = AsyncMock(return_value=[])

        await client._ensure_capabilities(inst)

        client.get_services.assert_not_called()


# ── Logout tests ─────────────────────────────────────────────────────────────


class TestLogout:
    async def test_clears_auth_state(self, client, transport):
        """Logout clears authentication state."""
        transport.execute.return_value = {"data": {"xSLogout": True}}

        # Set up auth state
        client.authentication_token = FAKE_JWT
        client._authentication_token_exp = datetime.now() + timedelta(hours=1)
        client.refresh_token_value = "some-refresh"
        client.login_timestamp = 1234567890

        await client.logout()

        assert client.authentication_token is None
        assert client.refresh_token_value == ""
        assert client._authentication_token_exp == datetime.min
        assert client.login_timestamp == 0

    async def test_clears_state_on_transport_error(self, client, transport):
        """Logout clears state even if transport raises."""
        transport.execute.side_effect = SecuritasDirectError("gone")

        client.authentication_token = FAKE_JWT
        client.refresh_token_value = "some-refresh"

        with pytest.raises(SecuritasDirectError):
            await client.logout()

        # State should still be cleared by the finally block
        assert client.authentication_token is None
        assert client.refresh_token_value == ""


# ── Helper for pre-authenticating a client ──────────────────────────────────


def _pre_auth(client) -> None:
    """Set a client into a valid authenticated state for testing."""
    client.authentication_token = FAKE_JWT
    client._authentication_token_exp = datetime.now() + timedelta(hours=1)
    client.refresh_token_value = FAKE_REFRESH_TOKEN
    client.login_timestamp = 1234567890


# ── Auth request contract tests ─────────────────────────────────────────────


class TestAuthRequestContracts:
    """Golden-contract tests verifying exact wire-protocol payloads for auth operations.

    Every assertion uses hardcoded literal strings (never imported constants)
    so these tests catch constant-drift or hallucinated values.
    """

    # ── 1. login payload ────────────────────────────────────────────────

    async def test_login_payload(self, client, transport):
        """login() sends mkLoginToken with correct variables and device strings."""
        transport.execute.return_value = {
            "data": {
                "xSLoginToken": {
                    "res": "OK",
                    "hash": FAKE_JWT,
                    "refreshToken": "fake-refresh",
                    "needDeviceAuthorization": False,
                }
            }
        }

        await client.login()

        content = transport.execute.call_args[0][0]
        assert content["operationName"] == "mkLoginToken"

        v = content["variables"]
        assert v["user"] == "test@example.com"
        assert v["password"] == "test-password"
        assert v["country"] == "ES"
        assert v["callby"] == "OWA_10"
        assert v["lang"] == "es"
        assert v["idDevice"] == "test-device-id"
        assert v["idDeviceIndigitall"] == "test-indigitall"
        assert v["uuid"] == "test-uuid"

        # Device strings — hardcoded literals, never imported constants
        assert v["deviceBrand"] == "samsung"
        assert v["deviceName"] == "SM-S901U"
        assert v["deviceOsVersion"] == "12"
        assert v["deviceVersion"] == "10.102.0"
        assert v["deviceType"] == ""
        assert v["deviceResolution"] == ""

    # ── 2. refresh token payload ────────────────────────────────────────

    async def test_refresh_token_payload(self, client, transport):
        """refresh_token() sends RefreshLogin with correct variables and device strings."""
        transport.execute.return_value = {
            "data": {
                "xSRefreshLogin": {
                    "res": "OK",
                    "hash": FAKE_JWT,
                    "refreshToken": "new-refresh",
                }
            }
        }
        client.refresh_token_value = "fake-refresh"

        await client.refresh_token()

        content = transport.execute.call_args[0][0]
        assert content["operationName"] == "RefreshLogin"

        v = content["variables"]
        assert v["refreshToken"] == "fake-refresh"
        assert v["country"] == "ES"
        assert v["lang"] == "es"
        assert v["callby"] == "OWA_10"
        assert v["idDevice"] == "test-device-id"
        assert v["idDeviceIndigitall"] == "test-indigitall"
        assert v["uuid"] == "test-uuid"

        # Device strings
        assert v["deviceBrand"] == "samsung"
        assert v["deviceName"] == "SM-S901U"
        assert v["deviceOsVersion"] == "12"
        assert v["deviceVersion"] == "10.102.0"
        assert v["deviceType"] == ""
        assert v["deviceResolution"] == ""

    # ── 3. validate device payload ──────────────────────────────────────

    async def test_validate_device_payload(self, client, transport):
        """validate_device() sends mkValidateDevice with correct variables and device strings."""
        transport.execute.return_value = {
            "data": {
                "xSValidateDevice": {
                    "res": "OK",
                    "hash": FAKE_JWT,
                    "refreshToken": "new-refresh",
                }
            }
        }

        await client.validate_device(
            otp_succeed=True, auth_otp_hash="test-hash", sms_code="123456"
        )

        content = transport.execute.call_args[0][0]
        assert content["operationName"] == "mkValidateDevice"

        v = content["variables"]
        assert v["idDevice"] == "test-device-id"
        assert v["idDeviceIndigitall"] == "test-indigitall"
        assert v["uuid"] == "test-uuid"

        # Device strings
        assert v["deviceBrand"] == "samsung"
        assert v["deviceName"] == "SM-S901U"
        assert v["deviceOsVersion"] == "12"
        assert v["deviceVersion"] == "10.102.0"

    # ── 4. send OTP payload ─────────────────────────────────────────────

    async def test_send_otp_payload(self, client, transport):
        """send_otp() sends mkSendOTP with recordId and otpHash."""
        transport.execute.return_value = {"data": {"xSSendOtp": {"res": "OK"}}}

        await client.send_otp(device_id=42, auth_otp_hash="otp-hash-value")

        content = transport.execute.call_args[0][0]
        assert content["operationName"] == "mkSendOTP"

        v = content["variables"]
        assert v["recordId"] == 42
        assert v["otpHash"] == "otp-hash-value"

    # ── 5. logout payload ───────────────────────────────────────────────

    async def test_logout_payload(self, client, transport):
        """logout() sends Logout with empty variables."""
        transport.execute.return_value = {"data": {"xSLogout": True}}

        # Must be authenticated to have headers built
        _pre_auth(client)

        await client.logout()

        content = transport.execute.call_args[0][0]
        assert content["operationName"] == "Logout"
        assert content["variables"] == {}

    # ── 6. login sends no auth header ───────────────────────────────────

    async def test_login_sends_no_auth_header(self, client, transport):
        """login() does NOT send an auth header (token is None before login)."""
        transport.execute.return_value = {
            "data": {
                "xSLoginToken": {
                    "res": "OK",
                    "hash": FAKE_JWT,
                    "refreshToken": "fake-refresh",
                    "needDeviceAuthorization": False,
                }
            }
        }

        await client.login()

        headers = transport.execute.call_args[0][1]
        assert "auth" not in headers

    # ── 7. refresh sends empty hash header ──────────────────────────────

    async def test_refresh_sends_empty_hash_header(self, client, transport):
        """refresh_token() sends auth header with hash='' and refreshToken=''."""
        transport.execute.return_value = {
            "data": {
                "xSRefreshLogin": {
                    "res": "OK",
                    "hash": FAKE_JWT,
                    "refreshToken": "new-refresh",
                }
            }
        }
        client.refresh_token_value = "fake-refresh"

        await client.refresh_token()

        headers = transport.execute.call_args[0][1]
        auth = json.loads(headers["auth"])
        assert auth["hash"] == ""
        assert auth["refreshToken"] == ""
        assert auth["callby"] == "OWA_10"

    # ── 8. normal op sends token in auth header ─────────────────────────

    async def test_normal_op_sends_token_in_auth_header(self, client, transport):
        """get_general_status() sends auth header with hash=<token> and no refreshToken key."""
        _pre_auth(client)

        # Also need capabilities cached so _ensure_capabilities doesn't trigger
        inst = _make_installation()
        client._capabilities[inst.number] = (
            "cap-token-123",
            datetime.now() + timedelta(hours=1),
        )

        transport.execute.return_value = {
            "data": {
                "xSStatus": {
                    "status": "T",
                    "timestampUpdate": "2024-01-01",
                    "wifiConnected": True,
                }
            }
        }

        await client.get_general_status(inst)

        headers = transport.execute.call_args[0][1]
        auth = json.loads(headers["auth"])
        assert auth["hash"] == FAKE_JWT
        assert "refreshToken" not in auth
