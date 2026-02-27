"""Tests for ApiManager authentication flow."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import jwt as pyjwt
import pytest

from custom_components.securitas.securitas_direct_new_api.apimanager import ApiManager
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    Login2FAError,
    LoginError,
    SecuritasDirectError,
)

from .conftest import (
    FAKE_JWT,
    FAKE_REFRESH_TOKEN,
    login_response,
    make_jwt,
    refresh_response,
    validate_device_response,
)

pytestmark = pytest.mark.asyncio


# ── login() ──────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_stores_auth_token_and_expiry(self, api, mock_execute):
        mock_execute.return_value = login_response()

        await api.login()

        assert api.authentication_token == FAKE_JWT
        # Expiry should be ~15 min in the future (matching FAKE_JWT)
        assert api.authentication_token_exp > datetime.now()
        assert api.authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_stores_refresh_token(self, api, mock_execute):
        mock_execute.return_value = login_response()

        await api.login()

        assert api.refresh_token_value == FAKE_REFRESH_TOKEN

    async def test_sets_login_timestamp(self, api, mock_execute):
        mock_execute.return_value = login_response()
        before = int(datetime.now().timestamp() * 1000)

        await api.login()

        after = int(datetime.now().timestamp() * 1000)
        assert before <= api.login_timestamp <= after

    async def test_2fa_required_raises_login2fa_error(self, api, mock_execute):
        mock_execute.return_value = login_response(need_2fa=True)

        with pytest.raises(Login2FAError):
            await api.login()

    async def test_error_response_raises_login_error(self, api, mock_execute):
        mock_execute.return_value = {
            "errors": [{"message": "Invalid credentials"}],
        }

        with pytest.raises(LoginError):
            await api.login()

    async def test_execute_request_error_raises_login_error(self, api, mock_execute):
        mock_execute.side_effect = SecuritasDirectError("Connection failed", None)

        with pytest.raises(LoginError):
            await api.login()

    async def test_null_hash_sets_timestamp_for_2fa(self, api, mock_execute):
        mock_execute.return_value = login_response(hash_token=None)

        await api.login()

        assert api.login_timestamp > 0
        assert api.authentication_token == ""  # unchanged from init

    async def test_invalid_jwt_raises_error(self, api, mock_execute):
        mock_execute.return_value = login_response(hash_token="not-a-jwt")

        with pytest.raises(SecuritasDirectError, match="Failed to decode"):
            await api.login()


# ── refresh_token() ──────────────────────────────────────────────────────────


class TestRefreshToken:
    async def test_success_stores_new_tokens(self, api, mock_execute):
        new_jwt = make_jwt(exp_minutes=15)
        new_refresh = make_jwt(exp_minutes=180 * 24 * 60)
        mock_execute.return_value = refresh_response(
            hash_token=new_jwt, refresh_token=new_refresh
        )

        result = await api.refresh_token()

        assert result is True
        assert api.authentication_token == new_jwt
        assert api.refresh_token_value == new_refresh

    async def test_success_updates_expiry(self, api, mock_execute):
        mock_execute.return_value = refresh_response()

        await api.refresh_token()

        assert api.authentication_token_exp > datetime.now()
        assert api.authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_success_updates_login_timestamp(self, api, mock_execute):
        mock_execute.return_value = refresh_response()
        before = int(datetime.now().timestamp() * 1000)

        await api.refresh_token()

        after = int(datetime.now().timestamp() * 1000)
        assert before <= api.login_timestamp <= after

    async def test_non_ok_res_returns_false(self, api, mock_execute):
        mock_execute.return_value = refresh_response(res="ERROR")

        result = await api.refresh_token()

        assert result is False

    async def test_missing_hash_returns_false(self, api, mock_execute):
        resp = refresh_response()
        resp["data"]["xSRefreshLogin"]["hash"] = ""
        mock_execute.return_value = resp

        result = await api.refresh_token()

        assert result is False

    async def test_null_hash_returns_false(self, api, mock_execute):
        resp = refresh_response()
        resp["data"]["xSRefreshLogin"]["hash"] = None
        mock_execute.return_value = resp

        result = await api.refresh_token()

        assert result is False

    async def test_jwt_decode_failure_returns_false(self, api, mock_execute):
        mock_execute.return_value = refresh_response(hash_token="not-a-jwt")

        result = await api.refresh_token()

        assert result is False

    async def test_none_response_raises_error(self, api, mock_execute):
        mock_execute.return_value = {"data": {"xSRefreshLogin": None}}

        with pytest.raises(SecuritasDirectError, match="xSRefreshLogin response is None"):
            await api.refresh_token()

    async def test_does_not_store_tokens_on_failure(self, api, mock_execute):
        api.authentication_token = "old-token"
        api.refresh_token_value = "old-refresh"
        mock_execute.return_value = refresh_response(res="ERROR")

        await api.refresh_token()

        assert api.authentication_token == "old-token"
        assert api.refresh_token_value == "old-refresh"


# ── _check_authentication_token() ───────────────────────────────────────────


class TestCheckAuthenticationToken:
    async def test_valid_token_does_nothing(self, api):
        """When token is valid and not expiring soon, no action taken."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.now() + timedelta(hours=1)
        api.login = AsyncMock()
        api.refresh_token = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_not_called()
        api.refresh_token.assert_not_called()

    async def test_expired_token_with_refresh_tries_refresh_first(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min  # expired
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(return_value=True)
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_not_called()

    async def test_expired_token_refresh_fails_falls_back_to_login(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(return_value=False)
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_awaited_once()

    async def test_expired_token_refresh_exception_falls_back_to_login(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = "has-refresh-token"
        api.refresh_token = AsyncMock(side_effect=Exception("boom"))
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_awaited_once()

    async def test_expired_token_no_refresh_value_calls_login(self, api):
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min
        api.refresh_token_value = ""  # no refresh token
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_awaited_once()

    async def test_none_token_calls_login(self, api):
        api.authentication_token = None
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.login.assert_awaited_once()


# ── validate_device() ────────────────────────────────────────────────────────


class TestValidateDevice:
    async def test_success_stores_hash_and_refresh_token(self, api, mock_execute):
        mock_execute.return_value = validate_device_response()

        result = await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert result == (None, None)
        assert api.authentication_token == FAKE_JWT
        assert api.refresh_token_value == FAKE_REFRESH_TOKEN

    async def test_success_decodes_jwt_expiry(self, api, mock_execute):
        mock_execute.return_value = validate_device_response()

        await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert api.authentication_token_exp > datetime.now()
        assert api.authentication_token_exp < datetime.now() + timedelta(minutes=20)

    async def test_jwt_decode_failure_logs_warning_doesnt_crash(
        self, api, mock_execute, caplog
    ):
        mock_execute.return_value = validate_device_response(hash_token="not-a-jwt")

        result = await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert result == (None, None)
        assert api.authentication_token == "not-a-jwt"
        # Expiry stays at default
        assert api.authentication_token_exp == datetime.min
        assert "Failed to decode" in caplog.text

    async def test_no_refresh_token_in_response(self, api, mock_execute):
        resp = validate_device_response()
        resp["data"]["xSValidateDevice"]["refreshToken"] = None
        mock_execute.return_value = resp

        await api.validate_device(
            otp_succeed=True, auth_otp_hash="otp-hash", sms_code="123456"
        )

        assert api.refresh_token_value == ""  # unchanged from init

    async def test_sets_otp_challenge_when_otp_succeed(self, api, mock_execute):
        mock_execute.return_value = validate_device_response()

        await api.validate_device(
            otp_succeed=True, auth_otp_hash="my-hash", sms_code="999999"
        )

        # Should be cleared after successful validation
        assert api.authentication_otp_challenge_value is None
