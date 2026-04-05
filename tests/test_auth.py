"""Tests for SecuritasClient authentication flow."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.securitas.securitas_direct_new_api.exceptions import (
    AccountBlockedError,
    AuthenticationError,
    SecuritasDirectError,
    TwoFactorRequiredError,
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

    async def test_2fa_required_raises_two_factor_required_error(
        self, api, mock_execute
    ):
        mock_execute.return_value = login_response(need_2fa=True)

        with pytest.raises(TwoFactorRequiredError):
            await api.login()

    async def test_error_response_raises_authentication_error(self, api, mock_execute):
        mock_execute.return_value = {
            "errors": [{"message": "Invalid credentials"}],
        }

        with pytest.raises(AuthenticationError):
            await api.login()

    async def test_execute_request_error_raises_securitas_error(
        self, api, mock_execute
    ):
        """Connection error (no response data) re-raises SecuritasDirectError."""
        mock_execute.side_effect = SecuritasDirectError("Connection failed")

        with pytest.raises(SecuritasDirectError):
            await api.login()

    async def test_null_hash_sets_timestamp_for_2fa(self, api, mock_execute):
        mock_execute.return_value = login_response(hash_token=None)  # type: ignore[arg-type]

        await api.login()

        assert api.login_timestamp > 0
        assert api.authentication_token is None  # unchanged from init

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

        with pytest.raises(
            SecuritasDirectError, match="xSRefreshLogin response is None"
        ):
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
        api.refresh_token = AsyncMock(side_effect=SecuritasDirectError("boom"))
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


# ── Additional login edge cases ──────────────────────────────────────────────


class TestLoginEdgeCases:
    async def test_error_with_need_device_authorization_raises_two_factor_required_error(
        self, api, mock_execute
    ):
        """When _execute_request raises SecuritasDirectError whose response data
        contains xSLoginToken.needDeviceAuthorization=True, TwoFactorRequiredError is raised."""
        error_response = {
            "data": {
                "xSLoginToken": {
                    "needDeviceAuthorization": True,
                    "hash": None,
                    "refreshToken": None,
                }
            }
        }
        _err = SecuritasDirectError("Session expired")
        _err.response_body = error_response
        mock_execute.side_effect = _err

        with pytest.raises(TwoFactorRequiredError):
            await api.login()

    async def test_error_response_with_data_raises_authentication_error(
        self, api, mock_execute
    ):
        """When _execute_request raises SecuritasDirectError whose response data
        has xSLoginToken but needDeviceAuthorization is False, AuthenticationError is raised."""
        error_response = {
            "data": {
                "xSLoginToken": {
                    "needDeviceAuthorization": False,
                    "hash": None,
                    "refreshToken": None,
                }
            }
        }
        _err = SecuritasDirectError("Some error")
        _err.response_body = error_response
        mock_execute.side_effect = _err

        with pytest.raises(AuthenticationError):
            await api.login()

    async def test_null_xslogintoken_raises_error(self, api, mock_execute):
        """When xSLoginToken is None in the response, SecuritasDirectError is raised."""
        mock_execute.return_value = {"data": {"xSLoginToken": None}}

        with pytest.raises(SecuritasDirectError, match="xSLoginToken response is None"):
            await api.login()

    async def test_login_stores_empty_token_for_null_hash(self, api, mock_execute):
        """When hash is None (2FA flow), auth token stays None but timestamp is set."""
        mock_execute.return_value = login_response(hash_token=None)  # type: ignore[arg-type]

        await api.login()

        assert api.authentication_token is None
        assert api.login_timestamp > 0

    async def test_account_blocked_raises_account_blocked_error(
        self, api, mock_execute
    ):
        """Error 60052 (account blocked) raises AccountBlockedError, not LoginError."""
        blocked_response = {
            "errors": [
                {
                    "message": "Utilisateur bloqué.",
                    "data": {"res": "ERROR", "err": "60052", "status": 403},
                }
            ],
            "data": {"xSLoginToken": None},
        }
        err = SecuritasDirectError("Utilisateur bloqué.")
        err.response_body = blocked_response
        mock_execute.side_effect = err

        with pytest.raises(AccountBlockedError):
            await api.login()


# ── Additional validate_device edge cases ────────────────────────────────────


class TestValidateDeviceEdgeCases:
    async def test_error_with_phone_data_returns_otp_tuple(self, api, mock_execute):
        """When _execute_request raises SecuritasDirectError with phone data in
        the error response, returns (otp_hash, phones) tuple."""
        error_response = {
            "errors": [
                {
                    "message": "Unauthorized",
                    "data": {
                        "auth-otp-hash": "challenge-hash-123",
                        "auth-phones": [
                            {"id": 1, "phone": "***456"},
                            {"id": 2, "phone": "***789"},
                        ],
                    },
                }
            ]
        }
        _err = SecuritasDirectError("Unauthorized")
        _err.response_body = error_response
        mock_execute.side_effect = _err

        result = await api.validate_device(
            otp_succeed=False, auth_otp_hash="", sms_code=""
        )

        assert result[0] == "challenge-hash-123"
        assert len(result[1]) == 2
        assert result[1][0].phone == "***456"
        assert result[1][1].phone == "***789"

    async def test_otp_not_succeed_returns_challenge_and_phones(
        self, api, mock_execute
    ):
        """When otp_succeed=False and response has errors with 'Unauthorized',
        returns the OTP challenge hash and phone list."""
        mock_execute.return_value = {
            "errors": [
                {
                    "message": "Unauthorized",
                    "data": {
                        "auth-otp-hash": "otp-hash-abc",
                        "auth-phones": [{"id": 1, "phone": "***111"}],
                    },
                }
            ]
        }

        result = await api.validate_device(
            otp_succeed=False, auth_otp_hash="", sms_code=""
        )

        assert result[0] == "otp-hash-abc"
        assert len(result[1]) == 1
        assert result[1][0].id == 1

    async def test_null_validate_data_raises_error(self, api, mock_execute):
        """When xSValidateDevice is None, SecuritasDirectError is raised."""
        mock_execute.return_value = {"data": {"xSValidateDevice": None}}

        with pytest.raises(
            SecuritasDirectError, match="xSValidateDevice response is None"
        ):
            await api.validate_device(
                otp_succeed=True, auth_otp_hash="hash", sms_code="123456"
            )


# ── Additional refresh/auth edge cases ──────────────────────────────────────


class TestRefreshTokenEdgeCases:
    async def test_refresh_token_after_expired_calls_login(self, api):
        """When refresh fails and token is expired, falls back to login."""
        api.authentication_token = FAKE_JWT
        api.authentication_token_exp = datetime.min  # expired
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(
            side_effect=SecuritasDirectError("Refresh failed")
        )
        api.login = AsyncMock()

        await api._check_authentication_token()

        api.refresh_token.assert_awaited_once()
        api.login.assert_awaited_once()
