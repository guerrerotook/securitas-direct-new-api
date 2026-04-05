"""Tests for SecuritasClient sensor and installation/services methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.client import (
    SecuritasClient,
)
from custom_components.securitas.securitas_direct_new_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.securitas_direct_new_api.models import (
    AirQuality,
    Attribute,
    Installation,
    Sentinel,
    Service,
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
FAKE_CAPABILITIES_JWT = make_jwt(exp_minutes=30)


# ── Helpers ──────────────────────────────────────────────────────────────────


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


def _make_service(**overrides) -> Service:
    """Factory for Service with sensible defaults."""
    defaults = {
        "id": 1,
        "id_service": 1,
        "active": True,
        "visible": True,
        "bde": False,
        "is_premium": False,
        "cod_oper": False,
        "total_device": 0,
        "request": "SVL",
        "attributes": [Attribute(name="zone", value="1", active=True)],
    }
    defaults.update(overrides)
    return Service(**defaults)


def _pre_auth(client: SecuritasClient) -> None:
    """Set up a valid auth token so _ensure_auth is a no-op."""
    client.authentication_token = FAKE_JWT
    client._authentication_token_exp = datetime.now() + timedelta(hours=1)
    # Store capabilities so _ensure_capabilities is a no-op
    client._capabilities["123456"] = (
        FAKE_CAPABILITIES_JWT,
        datetime.now() + timedelta(hours=1),
    )


def _pre_auth_no_caps(client: SecuritasClient) -> None:
    """Set up auth token only, no capabilities (for testing get_services)."""
    client.authentication_token = FAKE_JWT
    client._authentication_token_exp = datetime.now() + timedelta(hours=1)


# ── Response builders ────────────────────────────────────────────────────────


def sentinel_response(
    *,
    res: str = "OK",
    devices: list[dict] | None = None,
    forecast: dict | None = None,
) -> dict:
    """Build a mock xSComfort response."""
    return {
        "data": {
            "xSComfort": {
                "res": res,
                "devices": devices,
                "forecast": forecast,
            }
        }
    }


def air_quality_response(
    *,
    res: str = "OK",
    data: dict | None = None,
) -> dict:
    """Build a mock xSAirQuality response."""
    return {
        "data": {
            "xSAirQuality": {
                "res": res,
                "data": data,
            }
        }
    }


def installation_list_response(installations: list[dict]) -> dict:
    """Build a mock xSInstallations response."""
    return {
        "data": {
            "xSInstallations": {
                "installations": installations,
            }
        }
    }


def services_response(
    *,
    res: str = "OK",
    numinst: str = "123456",
    capabilities: str | None = None,
    services: list[dict] | None = None,
    config_repo_user: dict | None = None,
) -> dict:
    """Build a mock xSSrv response."""
    if capabilities is None:
        capabilities = FAKE_CAPABILITIES_JWT
    return {
        "data": {
            "xSSrv": {
                "res": res,
                "msg": "",
                "installation": {
                    "numinst": numinst,
                    "capabilities": capabilities,
                    "services": services or [],
                    "configRepoUser": config_repo_user,
                },
            }
        }
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def transport():
    """Create a mock HttpTransport."""
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport):
    """Create a SecuritasClient with test credentials, mocked transport, fast polling."""
    c = SecuritasClient(
        transport=transport,
        country="ES",
        language="es",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        poll_delay=0.0,
        poll_timeout=2.0,
    )
    _pre_auth(c)
    return c


@pytest.fixture
def client_no_caps(transport):
    """Create a SecuritasClient without capabilities (for get_services tests)."""
    c = SecuritasClient(
        transport=transport,
        country="ES",
        language="es",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        poll_delay=0.0,
        poll_timeout=2.0,
    )
    _pre_auth_no_caps(c)
    return c


# ── get_sentinel_data tests ──────────────────────────────────────────────────


class TestGetSentinelData:
    async def test_returns_sentinel(self, client, transport):
        """Successful call returns Sentinel with correct values."""
        transport.execute.return_value = sentinel_response(
            devices=[
                {
                    "alias": "Living Room",
                    "status": {
                        "temperature": 22,
                        "humidity": 45,
                        "airQualityCode": 3,
                    },
                    "zone": "1",
                },
                {
                    "alias": "Bedroom",
                    "status": {
                        "temperature": 19,
                        "humidity": 50,
                        "airQualityCode": 2,
                    },
                    "zone": "2",
                },
            ],
            forecast={
                "city": "Madrid",
                "currentTemp": 25,
                "currentHum": 40,
            },
        )

        inst = _make_installation()
        service = _make_service(
            attributes=[Attribute(name="zone", value="1", active=True)]
        )
        result = await client.get_sentinel_data(inst, service)

        assert isinstance(result, Sentinel)
        assert result.alias == "Living Room"
        assert result.temperature == 22
        assert result.humidity == 45
        assert result.air_quality == "3"
        assert result.zone == "1"

    async def test_zone_not_found_returns_empty_sentinel(self, client, transport):
        """Returns empty Sentinel when zone not found in devices."""
        transport.execute.return_value = sentinel_response(
            devices=[
                {
                    "alias": "Bedroom",
                    "status": {
                        "temperature": 19,
                        "humidity": 50,
                        "airQualityCode": 2,
                    },
                    "zone": "2",
                },
            ],
        )

        inst = _make_installation()
        service = _make_service(
            attributes=[Attribute(name="zone", value="99", active=True)]
        )
        result = await client.get_sentinel_data(inst, service)

        assert isinstance(result, Sentinel)
        assert result.alias == ""
        assert result.temperature == 0


# ── get_air_quality_data tests ───────────────────────────────────────────────


class TestGetAirQualityData:
    async def test_returns_air_quality(self, client, transport):
        """Successful call returns AirQuality with correct values."""
        transport.execute.return_value = air_quality_response(
            data={
                "status": {"current": 85, "avg6h": 80, "avg24h": 78},
                "hours": [
                    {"id": "1", "value": "70"},
                    {"id": "2", "value": "75"},
                    {"id": "3", "value": "82"},
                ],
            }
        )

        inst = _make_installation()
        result = await client.get_air_quality_data(inst, "1")

        assert isinstance(result, AirQuality)
        assert result.value == 82
        assert result.status_current == 85

    async def test_returns_none_when_no_data(self, client, transport):
        """Returns None when data field is None."""
        transport.execute.return_value = air_quality_response(data=None)

        inst = _make_installation()
        result = await client.get_air_quality_data(inst, "1")

        assert result is None

    async def test_returns_none_when_no_hours(self, client, transport):
        """Returns None when hours list is empty."""
        transport.execute.return_value = air_quality_response(
            data={
                "status": {"current": 85},
                "hours": [],
            }
        )

        inst = _make_installation()
        result = await client.get_air_quality_data(inst, "1")

        assert result is None


# ── list_installations tests ─────────────────────────────────────────────────


class TestListInstallations:
    async def test_returns_list_of_installations(self, client, transport):
        """Successful call returns a list of Installation instances."""
        # list_installations does not need capabilities, only auth
        transport.execute.return_value = installation_list_response(
            [
                {
                    "numinst": "123456",
                    "alias": "Home",
                    "panel": "SDVFAST",
                    "type": "PLUS",
                    "name": "John",
                    "surname": "Doe",
                    "address": "123 St",
                    "city": "Madrid",
                    "postcode": "28001",
                    "province": "Madrid",
                    "email": "test@example.com",
                    "phone": "555-1234",
                },
                {
                    "numinst": "789012",
                    "alias": "Office",
                    "panel": "SDVFAST",
                    "type": "PLUS",
                    "name": "Jane",
                    "surname": "Doe",
                    "address": "456 Ave",
                    "city": "Barcelona",
                    "postcode": "08001",
                    "province": "Barcelona",
                    "email": "jane@example.com",
                    "phone": "555-5678",
                },
            ]
        )

        result = await client.list_installations()

        assert len(result) == 2
        assert all(isinstance(i, Installation) for i in result)
        assert result[0].number == "123456"
        assert result[0].alias == "Home"
        assert result[1].number == "789012"
        assert result[1].alias == "Office"


# ── get_services tests ───────────────────────────────────────────────────────


class TestGetServices:
    async def test_returns_services_and_stores_capabilities(
        self, client_no_caps, transport
    ):
        """get_services returns Service list and stores capabilities in _capabilities."""
        transport.execute.return_value = services_response(
            numinst="123456",
            capabilities=FAKE_CAPABILITIES_JWT,
            services=[
                {
                    "idService": 1,
                    "active": True,
                    "visible": True,
                    "bde": False,
                    "isPremium": False,
                    "codOper": False,
                    "request": "ARM",
                    "minWrapperVersion": "1.0",
                    "unprotectActive": False,
                    "unprotectDeviceStatus": None,
                    "instDate": None,
                    "genericConfig": None,
                    "attributes": {
                        "attributes": [
                            {"name": "zone", "value": "1", "active": True},
                        ]
                    },
                },
                {
                    "idService": 14,
                    "active": True,
                    "visible": True,
                    "bde": False,
                    "isPremium": True,
                    "codOper": False,
                    "request": "SVL",
                    "minWrapperVersion": "2.0",
                    "unprotectActive": False,
                    "unprotectDeviceStatus": None,
                    "instDate": None,
                    "genericConfig": None,
                    "attributes": None,
                },
            ],
            config_repo_user={
                "alarmPartitions": [
                    {"id": "1", "enterStates": ["ARM"], "leaveStates": ["DARM"]},
                ]
            },
        )

        inst = _make_installation()
        result = await client_no_caps.get_services(inst)

        # Check services returned
        assert len(result) == 2
        assert all(isinstance(s, Service) for s in result)
        assert result[0].id_service == 1
        assert result[0].request == "ARM"
        assert result[0].active is True
        assert len(result[0].attributes) == 1
        assert result[0].attributes[0].name == "zone"
        assert result[1].id_service == 14
        assert result[1].is_premium is True

        # Check capabilities stored in client._capabilities, NOT on installation
        assert "123456" in client_no_caps._capabilities
        token, expiry = client_no_caps._capabilities["123456"]
        assert token == FAKE_CAPABILITIES_JWT
        assert isinstance(expiry, datetime)
        assert expiry > datetime.now()

    async def test_returns_empty_list_when_no_installation_data(
        self, client_no_caps, transport
    ):
        """Returns empty list when installation data is None."""
        transport.execute.return_value = {
            "data": {
                "xSSrv": {
                    "res": "OK",
                    "msg": "",
                    "installation": None,
                }
            }
        }

        inst = _make_installation()
        result = await client_no_caps.get_services(inst)

        assert result == []

    async def test_returns_empty_list_when_no_services(self, client_no_caps, transport):
        """Returns empty list when services is None."""
        transport.execute.return_value = services_response(
            services=None,
            capabilities=FAKE_CAPABILITIES_JWT,
        )

        # Override so services is None in the response
        transport.execute.return_value["data"]["xSSrv"]["installation"]["services"] = (
            None
        )

        inst = _make_installation()
        result = await client_no_caps.get_services(inst)

        assert result == []

    async def test_returns_empty_list_when_no_capabilities(
        self, client_no_caps, transport
    ):
        """Returns empty list when capabilities is None."""
        transport.execute.return_value = services_response(
            capabilities=None,
            services=[
                {
                    "idService": 1,
                    "active": True,
                    "visible": True,
                    "bde": False,
                    "isPremium": False,
                    "codOper": False,
                    "request": "ARM",
                    "minWrapperVersion": "1.0",
                    "unprotectActive": False,
                    "unprotectDeviceStatus": None,
                    "instDate": None,
                    "genericConfig": None,
                    "attributes": None,
                },
            ],
        )

        # Override so capabilities is None
        transport.execute.return_value["data"]["xSSrv"]["installation"][
            "capabilities"
        ] = None

        inst = _make_installation()
        result = await client_no_caps.get_services(inst)

        assert result == []
