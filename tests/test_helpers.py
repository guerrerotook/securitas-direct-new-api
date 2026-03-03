"""Tests for ApiManager helper methods."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from aiohttp import ClientConnectorError
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
        api.delay_check_operation = 0

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
        api.delay_check_operation = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 3

    async def test_retries_on_transient_error(self, api):
        """Should catch transient errors and continue polling."""
        conn_err = ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("connection reset")
        )
        check_fn = AsyncMock(
            side_effect=[
                conn_err,
                {"res": "OK", "msg": "done"},
            ]
        )
        api.delay_check_operation = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 2

    async def test_raises_on_non_transient_error(self, api):
        """Should immediately raise non-transient errors."""
        check_fn = AsyncMock(
            side_effect=SecuritasDirectError("bad request", None)
        )
        api.delay_check_operation = 0

        with pytest.raises(SecuritasDirectError, match="bad request"):
            await api._poll_operation(check_fn)

    async def test_timeout_raises(self, api):
        """Should raise TimeoutError when wall-clock timeout is exceeded."""
        check_fn = AsyncMock(return_value={"res": "WAIT", "msg": ""})
        api.delay_check_operation = 0

        with pytest.raises(TimeoutError, match="timed out"):
            await api._poll_operation(check_fn, timeout=0.05)

    async def test_also_polls_on_specific_message(self, api):
        """Should continue polling when continue_on_msg matches response msg."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "ERROR", "msg": "alarm-manager.error_no_response_to_request"},
                {"res": "OK", "msg": "done"},
            ]
        )
        api.delay_check_operation = 0

        result = await api._poll_operation(
            check_fn,
            continue_on_msg="alarm-manager.error_no_response_to_request",
        )
        assert result["res"] == "OK"
        assert check_fn.call_count == 2
