"""Shared fixtures for securitas-direct-new-api integration tests."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from .mock_graphql import MockGraphQLServer

from custom_components.securitas import (
    CONF_CODE_ARM_REQUIRED,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENTRY_ID,
    CONF_HAS_PERI,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SecuritasDirectDevice,
    SecuritasHub,
)
from custom_components.securitas.securitas_direct_new_api.client import SecuritasClient
from custom_components.securitas.securitas_direct_new_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.securitas_direct_new_api.const import (
    PERI_DEFAULTS,
    STD_DEFAULTS,
)
from custom_components.securitas.securitas_direct_new_api.models import Installation
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)


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


# ── SecuritasClient fixture ──────────────────────────────────────────────────


@pytest.fixture
def mock_transport():
    """Create a mock HttpTransport."""
    return AsyncMock(spec=HttpTransport)


@pytest.fixture
def api(mock_transport):
    """Create a SecuritasClient instance with test credentials."""
    return SecuritasClient(
        transport=mock_transport,
        country="ES",
        language="es_ES",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
    )


@pytest.fixture
def mock_execute(api, mock_transport):
    """Patch transport.execute on the api instance and return the AsyncMock."""
    return mock_transport.execute


# ── Integration test helpers ────────────────────────────────────────────────


def make_installation(**overrides) -> Installation:
    """Factory for Installation dataclass with sensible defaults."""
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
    return Installation(**defaults)  # type: ignore[arg-type]


def make_config_entry_data(
    *,
    username: str = "test@example.com",
    password: str = "test-password",
    country: str = "ES",
    code: str = "",
    has_peri: bool = False,
    code_arm_required: bool = False,
    scan_interval: int = DEFAULT_SCAN_INTERVAL,
    delay_check_operation: float = DEFAULT_DELAY_CHECK_OPERATION,
    device_id: str = "test-device-id",
    unique_id: str = "test-uuid",
    id_device_indigitall: str = "test-indigitall",
    map_home: str | None = None,
    map_away: str | None = None,
    map_night: str | None = None,
    map_custom: str | None = None,
    map_vacation: str | None = None,
    notify_group: str = "",
) -> dict:
    """Build config entry data dict with sensible defaults."""
    defaults = PERI_DEFAULTS if has_peri else STD_DEFAULTS
    return {
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        CONF_COUNTRY: country,
        CONF_CODE: code,
        CONF_HAS_PERI: has_peri,
        CONF_CODE_ARM_REQUIRED: code_arm_required,
        CONF_SCAN_INTERVAL: scan_interval,
        CONF_DELAY_CHECK_OPERATION: delay_check_operation,
        CONF_DEVICE_ID: device_id,
        CONF_UNIQUE_ID: unique_id,
        CONF_DEVICE_INDIGITALL: id_device_indigitall,
        CONF_MAP_HOME: map_home if map_home is not None else defaults[CONF_MAP_HOME],
        CONF_MAP_AWAY: map_away if map_away is not None else defaults[CONF_MAP_AWAY],
        CONF_MAP_NIGHT: map_night
        if map_night is not None
        else defaults[CONF_MAP_NIGHT],
        CONF_MAP_CUSTOM: map_custom
        if map_custom is not None
        else defaults[CONF_MAP_CUSTOM],
        CONF_MAP_VACATION: map_vacation
        if map_vacation is not None
        else defaults[CONF_MAP_VACATION],
        CONF_NOTIFY_GROUP: notify_group,
    }


def make_securitas_hub_mock(**overrides) -> MagicMock:
    """Create a MagicMock mimicking SecuritasHub."""
    hub = MagicMock(spec=SecuritasHub)
    hub.client = AsyncMock()
    hub.country = "ES"
    hub.lang = "es"
    hub.config = {}
    hub.services = {1: []}
    hub.sentinel_services = []
    hub.installations = []
    hub.login = AsyncMock()
    hub.validate_device = AsyncMock()
    hub.send_sms_code = AsyncMock()
    hub.refresh_token = AsyncMock()
    hub.send_opt = AsyncMock()
    hub._services_cache = {}
    hub.get_services = AsyncMock(return_value=[])
    hub.logout = AsyncMock(return_value=True)
    hub.update_overview = AsyncMock()
    hub.get_authentication_token = MagicMock(return_value=FAKE_JWT)
    hub.set_authentication_token = MagicMock()
    for key, val in overrides.items():
        setattr(hub, key, val)
    return hub


# ── Integration mock server fixture ─────────────────────────────────────────


@pytest.fixture
def mock_server() -> MockGraphQLServer:
    """Create a fresh MockGraphQLServer wired to a mock aiohttp ClientSession."""
    return MockGraphQLServer()


def setup_integration_data(
    hass,
    client: MagicMock,
    devices: list[SecuritasDirectDevice] | None = None,
    entry_id: str = "test-entry-id",
) -> None:
    """Populate hass.data[DOMAIN] the way async_setup_entry does."""
    if devices is None:
        devices = [SecuritasDirectDevice(make_installation())]
    hass.data[DOMAIN] = {
        CONF_ENTRY_ID: entry_id,
        entry_id: {
            "hub": client,
            "devices": devices,
        },
    }
