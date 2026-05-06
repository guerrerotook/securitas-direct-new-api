"""Tests for SecuritasClient.get_activity (xSActV2 timeline)."""

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
    ActivityEvent,
    Installation,
)

pytestmark = pytest.mark.asyncio

SECRET = "test-secret"


def _make_jwt(**claims) -> str:
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=15)
    return jwt.encode(
        {"exp": exp, "sub": "test-user", **claims}, SECRET, algorithm="HS256"
    )


FAKE_JWT = _make_jwt()
FAKE_CAPABILITIES_JWT = _make_jwt()


def _make_installation(**overrides) -> Installation:
    defaults = {
        "number": "123456",
        "alias": "Home",
        "panel": "SDVFAST",
        "type": "PLUS",
    }
    defaults.update(overrides)
    return Installation(**defaults)


@pytest.fixture
def transport():
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport):
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
    c.authentication_token = FAKE_JWT
    c._authentication_token_exp = datetime.now() + timedelta(hours=1)
    c._capabilities["123456"] = (
        FAKE_CAPABILITIES_JWT,
        datetime.now() + timedelta(hours=1),
    )
    return c


def _activity_response(reg) -> dict:
    return {
        "data": {
            "xSActV2": {
                "reg": reg,
                "__typename": "XSActV2",
            }
        }
    }


def _sample_entry(**overrides) -> dict:
    base = {
        "alias": "Armed",
        "type": 701,
        "device": "VV",
        "source": "Web",
        "idSignal": "16215212397",
        "schedulerType": None,
        "myVerisureUser": "Test User",
        "time": "2026-05-05 15:00:00",
        "img": 0,
        "incidenceId": None,
        "signalType": 701,
        "interface": "03",
        "deviceName": "Ingresso",
        "keyname": None,
        "tagId": None,
        "userAuth": None,
        "exceptions": None,
        "mediaPlatform": None,
        "__typename": "XSActV2Reg",
    }
    base.update(overrides)
    return base


# ── Behaviour ────────────────────────────────────────────────────────────────


class TestGetActivity:
    async def test_returns_list_of_events(self, client, transport):
        transport.execute.return_value = _activity_response(
            [
                _sample_entry(idSignal="999"),
                _sample_entry(idSignal="998", type=720, alias="Disarmed"),
            ]
        )

        result = await client.get_activity(_make_installation())

        assert len(result) == 2
        assert all(isinstance(ev, ActivityEvent) for ev in result)
        assert result[0].id_signal == "999"
        assert result[0].alias == "Armed"
        assert result[1].id_signal == "998"
        assert result[1].type == 720

    async def test_empty_reg_returns_empty_list(self, client, transport):
        transport.execute.return_value = _activity_response([])
        result = await client.get_activity(_make_installation())
        assert result == []

    async def test_null_reg_returns_empty_list(self, client, transport):
        """When the API returns reg: null, the client treats it as no events."""
        transport.execute.return_value = _activity_response(None)
        result = await client.get_activity(_make_installation())
        assert result == []


class TestGetActivityRequestContract:
    """Golden contract: exact payload sent to the transport."""

    async def test_default_payload(self, client, transport):
        transport.execute.return_value = _activity_response([])

        await client.get_activity(_make_installation())

        call_args = transport.execute.call_args[0][0]
        assert call_args["operationName"] == "ActV2Timeline"
        assert call_args["query"]  # non-empty
        variables = call_args["variables"]
        assert variables["numinst"] == "123456"
        assert variables["panel"] == "SDVFAST"
        assert variables["numRows"] == 30
        assert variables["offset"] == 0
        assert variables["timeFilter"] == "LASTMONTH"

    async def test_custom_pagination(self, client, transport):
        transport.execute.return_value = _activity_response([])

        await client.get_activity(
            _make_installation(),
            num_rows=10,
            offset=20,
            time_filter="LASTWEEK",
        )

        variables = transport.execute.call_args[0][0]["variables"]
        assert variables["numRows"] == 10
        assert variables["offset"] == 20
        assert variables["timeFilter"] == "LASTWEEK"
