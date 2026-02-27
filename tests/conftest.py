"""Shared fixtures for securitas-direct-new-api integration tests."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.apimanager import ApiManager


# ── JWT helpers ──────────────────────────────────────────────────────────────

SECRET = "test-secret"


def make_jwt(exp_minutes: int = 15, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=exp_minutes)
    payload = {"exp": exp, "sub": "test-user", **extra_claims}
    return jwt.encode(payload, SECRET, algorithm="HS256")


FAKE_JWT = make_jwt(exp_minutes=15)
FAKE_JWT_EXPIRED = make_jwt(exp_minutes=-5)
FAKE_REFRESH_TOKEN = make_jwt(exp_minutes=180 * 24 * 60)  # ~180 days


# ── API response builders ───────────────────────────────────────────────────


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


def validate_device_response(
    *,
    hash_token: str = FAKE_JWT,
    refresh_token: str = FAKE_REFRESH_TOKEN,
) -> dict:
    """Build a mock xSValidateDevice response."""
    return {
        "data": {
            "xSValidateDevice": {
                "res": "OK",
                "msg": "",
                "hash": hash_token,
                "refreshToken": refresh_token,
                "legals": None,
            }
        }
    }


# ── ApiManager fixture ───────────────────────────────────────────────────────


@pytest.fixture
def mock_session():
    """Create a mock aiohttp.ClientSession (never actually used since we mock _execute_request)."""
    return MagicMock()


@pytest.fixture
def api(mock_session):
    """Create an ApiManager instance with test credentials."""
    return ApiManager(
        username="test@example.com",
        password="test-password",
        country="ES",
        http_client=mock_session,
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
    )


@pytest.fixture
def mock_execute(api):
    """Patch _execute_request on the api instance and return the AsyncMock."""
    mock = AsyncMock()
    api._execute_request = mock
    return mock
