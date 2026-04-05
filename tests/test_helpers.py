"""Tests for ApiManager helper methods."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)

from .conftest import make_jwt


# ── _decode_auth_token() ────────────────────────────────────────────────────


class TestDecodeAuthToken:
    def test_decodes_valid_jwt_and_sets_expiry(self, api):
        """Valid JWT should return decoded dict and set authentication_token_exp."""
        token = make_jwt(exp_minutes=30)
        result = api._decode_auth_token(token)

        assert result is not None
        assert "exp" in result
        assert isinstance(api.authentication_token_exp, datetime)
        assert api.authentication_token_exp > datetime.now()

    def test_returns_none_on_invalid_token(self, api):
        """Invalid JWT string should return None and not crash."""
        result = api._decode_auth_token("not-a-valid-jwt")
        assert result is None

    def test_handles_jwt_without_exp_claim(self, api):
        """JWT without 'exp' claim should return decoded dict but not update expiry."""
        token = jwt.encode({"sub": "test"}, "secret", algorithm="HS256")
        old_exp = api.authentication_token_exp
        result = api._decode_auth_token(token)

        assert result is not None
        assert "sub" in result
        assert api.authentication_token_exp == old_exp

    def test_returns_none_on_none_input(self, api):
        """None input should return None gracefully."""
        result = api._decode_auth_token(None)
        assert result is None


# ── _extract_response_data() ────────────────────────────────────────────────


class TestExtractResponseData:
    def test_extracts_nested_data(self, api):
        """Should return response['data'][field_name] when present."""
        response = {"data": {"xSFoo": {"res": "OK", "msg": ""}}}
        result = api._extract_response_data(response, "xSFoo")
        assert result == {"res": "OK", "msg": ""}

    def test_raises_when_data_key_missing(self, api):
        """Should raise SecuritasDirectError when 'data' key is absent."""
        response = {"errors": [{"message": "bad"}]}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")

    def test_raises_when_data_is_none(self, api):
        """Should raise SecuritasDirectError when response['data'] is None."""
        response = {"data": None}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")

    def test_raises_when_field_is_none(self, api):
        """Should raise SecuritasDirectError when the named field is None."""
        response = {"data": {"xSFoo": None}}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")

    def test_raises_when_field_missing(self, api):
        """Should raise SecuritasDirectError when the named field doesn't exist."""
        response = {"data": {"xSBar": {"res": "OK"}}}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")


# ── _poll_operation() ────────────────────────────────────────────────────────


class TestPollOperation:
    async def test_returns_result_on_first_non_wait(self, api):
        """Should return immediately when check_fn returns non-WAIT result."""
        check_fn = AsyncMock(return_value={"res": "OK", "msg": "done"})
        api.poll_delay = 0

        result = await api._poll_operation(check_fn)
        assert result == {"res": "OK", "msg": "done"}
        assert check_fn.call_count == 1

    async def test_polls_until_non_wait(self, api):
        """Should keep polling while result is WAIT, then return final result."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "WAIT", "msg": ""},
                {"res": "WAIT", "msg": ""},
                {"res": "OK", "msg": "done"},
            ]
        )
        api.poll_delay = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 3

    async def test_retries_on_transient_timeout_error(self, api):
        """Should catch asyncio.TimeoutError and continue polling."""
        check_fn = AsyncMock(
            side_effect=[
                asyncio.TimeoutError("connection timeout"),
                {"res": "OK", "msg": "done"},
            ]
        )
        api.poll_delay = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 2

    async def test_raises_on_non_transient_error(self, api):
        """Should immediately raise non-transient errors (no http_status)."""
        check_fn = AsyncMock(side_effect=SecuritasDirectError("bad request"))
        api.poll_delay = 0

        with pytest.raises(SecuritasDirectError, match="bad request"):
            await api._poll_operation(check_fn)

    async def test_retries_on_409_conflict(self, api):
        """Should retry on SecuritasDirectError with http_status=409 (server busy)."""
        err_409 = SecuritasDirectError(
            "alarm-manager.alarm_process_error", http_status=409
        )
        check_fn = AsyncMock(
            side_effect=[
                err_409,
                {"res": "OK", "msg": "done"},
            ]
        )
        api.poll_delay = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 2

    async def test_raises_on_non_409_securitas_error(self, api):
        """Should immediately raise SecuritasDirectError with non-409 http_status."""
        err_500 = SecuritasDirectError("server error", http_status=500)
        check_fn = AsyncMock(side_effect=err_500)
        api.poll_delay = 0

        with pytest.raises(SecuritasDirectError, match="server error"):
            await api._poll_operation(check_fn)

    async def test_timeout_raises(self, api):
        """Should raise OperationTimeoutError when wall-clock timeout is exceeded."""
        from custom_components.securitas.securitas_direct_new_api.exceptions import (
            OperationTimeoutError,
        )

        check_fn = AsyncMock(return_value={"res": "WAIT", "msg": ""})
        api.poll_delay = 0

        with pytest.raises(OperationTimeoutError, match="timed out"):
            await api._poll_operation(check_fn, timeout=0.05)

    async def test_also_polls_on_specific_message(self, api):
        """Should continue polling when continue_on_msg matches response msg."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "ERROR", "msg": "alarm-manager.error_no_response_to_request"},
                {"res": "OK", "msg": "done"},
            ]
        )
        api.poll_delay = 0

        result = await api._poll_operation(
            check_fn,
            continue_on_msg="alarm-manager.error_no_response_to_request",
        )
        assert result["res"] == "OK"
        assert check_fn.call_count == 2


# ── _check_authentication_token() error handling ────────────────────────────


class TestCheckAuthenticationTokenErrorHandling:
    async def test_falls_back_to_login_on_securitas_error(self, api):
        """Should fall back to login() when refresh raises SecuritasDirectError."""
        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(
            side_effect=SecuritasDirectError("refresh failed")
        )
        api.login = AsyncMock()

        await api._check_authentication_token()
        api.login.assert_called_once()

    async def test_falls_back_to_login_on_timeout(self, api):
        """Should fall back to login() when refresh raises asyncio.TimeoutError."""
        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(side_effect=asyncio.TimeoutError())
        api.login = AsyncMock()

        await api._check_authentication_token()
        api.login.assert_called_once()

    async def test_falls_back_to_login_on_timeout_error(self, api):
        """Should fall back to login() when refresh raises asyncio.TimeoutError."""
        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))
        api.login = AsyncMock()

        await api._check_authentication_token()
        api.login.assert_called_once()

    async def test_does_not_catch_unexpected_exceptions(self, api):
        """Should NOT catch unexpected exceptions like ValueError."""
        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(side_effect=ValueError("unexpected"))
        api.login = AsyncMock()

        with pytest.raises(ValueError, match="unexpected"):
            await api._check_authentication_token()


# ── logout() token cleanup ──────────────────────────────────────────────────


class TestLogoutTokenCleanup:
    async def test_clears_tokens_on_successful_logout(self, api, mock_execute):
        """Logout should clear all stored tokens."""
        api.authentication_token = "some-token"
        api.refresh_token_value = "some-refresh"
        api.authentication_token_exp = datetime.now()
        api.login_timestamp = 12345

        mock_execute.return_value = {"data": {"xSLogout": True}}
        await api.logout()

        assert api.authentication_token is None
        assert api.refresh_token_value == ""
        assert api.authentication_token_exp == datetime.min
        assert api.login_timestamp == 0

    async def test_clears_tokens_even_on_failed_logout(self, api, mock_execute):
        """Tokens should be cleared even if the logout API call fails."""
        api.authentication_token = "some-token"
        api.refresh_token_value = "some-refresh"
        api.authentication_token_exp = datetime.now()
        api.login_timestamp = 12345

        mock_execute.side_effect = SecuritasDirectError("logout failed")

        with pytest.raises(SecuritasDirectError):
            await api.logout()

        assert api.authentication_token is None
        assert api.refresh_token_value == ""
