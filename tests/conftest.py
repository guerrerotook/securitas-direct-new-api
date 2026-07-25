"""Shared fixtures for the Verisure OWA HA integration tests."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)

from custom_components.securitas import (
    CONF_CODE_ARM_REQUIRED,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_ENTRY_ID,
    CONF_FORCE_ARM_NOTIFICATIONS,
    CONF_MAP_AWAY,
    CONF_MAP_CUSTOM,
    CONF_MAP_HOME,
    CONF_MAP_NIGHT,
    CONF_MAP_VACATION,
    CONF_NOTIFY_GROUP,
    DEFAULT_DELAY_CHECK_OPERATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    VerisureDevice,
    VerisureHub,
)
from custom_components.securitas.verisure_owa_api.client import (
    VerisureOwaClient,
)
from custom_components.securitas.verisure_owa_api.const import (
    PERI_DEFAULTS,
    STD_DEFAULTS,
)
from custom_components.securitas.verisure_owa_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.verisure_owa_api.models import Installation

from .mock_graphql import MockGraphQLServer

# ── integration-marker auto-application ───────────────────────────────────────
#
# Tests that import `homeassistant` or `tests.mock_graphql`, or request the
# `mock_server` fixture, are integration tests. Rather than relying on developers
# to remember `pytestmark = pytest.mark.integration` on every such file, we
# auto-apply the marker at collection time. See tests/test_markers.py for the
# meta-test that pins the expected file set.

_INTEGRATION_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(?:homeassistant|tests\.mock_graphql|\.mock_graphql)",
    re.MULTILINE,
)


def _file_is_integration(path: Path) -> bool:
    try:
        source = path.read_text()
    except OSError:
        return False
    return bool(_INTEGRATION_IMPORT_RE.search(source))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-apply the `integration` marker to tests touching external surfaces."""
    file_cache: dict[Path, bool] = {}
    for item in items:
        path = Path(str(item.fspath))
        if path not in file_cache:
            file_cache[path] = _file_is_integration(path)
        uses_mock_server = "mock_server" in getattr(item, "fixturenames", ())
        if file_cache[path] or uses_mock_server:
            item.add_marker(pytest.mark.integration)


# ── JWT helpers ──────────────────────────────────────────────────────────────

SECRET = "test-secret"


def make_jwt(exp_minutes: int = 15, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=UTC) + timedelta(minutes=exp_minutes)
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


# ── VerisureOwaClient fixture ──────────────────────────────────────────────────


@pytest.fixture
def mock_transport():
    """Create a mock HttpTransport."""
    return AsyncMock(spec=HttpTransport)


@pytest.fixture
def api(mock_transport):
    """Create a VerisureOwaClient instance with test credentials."""
    return VerisureOwaClient(
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
    force_arm_notifications: bool = True,
    enable_activity_polling: bool | None = None,
) -> dict:
    """Build config entry data dict with sensible defaults.

    ``has_peri`` controls which default mappings are used but is no longer
    stored in entry data — capability detection is now runtime-only.
    """
    defaults = PERI_DEFAULTS if has_peri else STD_DEFAULTS

    def _mapping(key: str, override: str | None) -> dict[str, str]:
        """Build {key: value} from explicit override → default → omit."""
        if override is not None:
            return {key: override}
        if key in defaults:
            return {key: defaults[key]}
        return {}

    return {
        CONF_USERNAME: username,
        CONF_PASSWORD: password,
        CONF_COUNTRY: country,
        CONF_CODE: code,
        CONF_CODE_ARM_REQUIRED: code_arm_required,
        CONF_SCAN_INTERVAL: scan_interval,
        CONF_DELAY_CHECK_OPERATION: delay_check_operation,
        CONF_DEVICE_ID: device_id,
        CONF_UNIQUE_ID: unique_id,
        CONF_DEVICE_INDIGITALL: id_device_indigitall,
        **_mapping(CONF_MAP_HOME, map_home),
        **_mapping(CONF_MAP_AWAY, map_away),
        **_mapping(CONF_MAP_NIGHT, map_night),
        **_mapping(CONF_MAP_CUSTOM, map_custom),
        **_mapping(CONF_MAP_VACATION, map_vacation),
        CONF_NOTIFY_GROUP: notify_group,
        CONF_FORCE_ARM_NOTIFICATIONS: force_arm_notifications,
        **(
            {}
            if enable_activity_polling is None
            else {"enable_activity_polling": enable_activity_polling}
        ),
    }


def make_securitas_hub_mock(**overrides) -> MagicMock:
    """Create a MagicMock mimicking VerisureHub."""
    hub = MagicMock(spec=VerisureHub)
    hub.client = AsyncMock()
    hub.client.get_supported_commands = MagicMock(return_value=frozenset())
    hub.country = "ES"
    hub.lang = "es"
    hub.config = {}
    hub.services = {1: []}
    hub.sentinel_services = []
    hub.login = AsyncMock()
    hub.validate_device = AsyncMock()
    hub.send_sms_code = AsyncMock()
    hub.refresh_token = AsyncMock()
    hub.send_opt = AsyncMock()
    hub._services_cache = {}
    hub.get_services = AsyncMock(return_value=[])
    hub.get_authentication_token = MagicMock(return_value=FAKE_JWT)
    hub.get_refresh_token = MagicMock(return_value=FAKE_REFRESH_TOKEN)
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
    devices: list[VerisureDevice] | None = None,
    entry_id: str = "test-entry-id",
) -> None:
    """Populate hass.data[DOMAIN] the way async_setup_entry does."""
    if devices is None:
        devices = [VerisureDevice(make_installation())]
    hass.data[DOMAIN] = {
        CONF_ENTRY_ID: entry_id,
        entry_id: {
            "hub": client,
            "devices": devices,
        },
    }
