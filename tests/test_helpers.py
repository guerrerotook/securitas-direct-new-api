"""Tests for ApiManager helper methods."""

from datetime import datetime

import jwt

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
