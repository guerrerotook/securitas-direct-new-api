"""Tests for VerisureOwaClient magnetic-contact methods."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.securitas.verisure_owa_api.client import VerisureOwaClient
from custom_components.securitas.verisure_owa_api.http_transport import HttpTransport
from custom_components.securitas.verisure_owa_api.models import (
    ContactDevice,
)

from tests.conftest import make_installation


@pytest.fixture
def transport() -> MagicMock:
    """Create a mock HTTP transport."""
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport: MagicMock) -> VerisureOwaClient:
    """Create a pre-authenticated API client."""
    result = VerisureOwaClient(
        transport=transport,
        country="FR",
        language="fr",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        poll_delay=0.0,
        poll_timeout=2.0,
    )
    result.authentication_token = "test-token"
    result._authentication_token_exp = datetime.now() + timedelta(hours=1)
    result.get_services = AsyncMock(return_value=[])
    return result


def _device_list_response(devices: list[dict] | None) -> dict:
    return {"data": {"xSDeviceList": {"res": "OK", "devices": devices}}}


def _contact_status_response(devices: list[dict] | None) -> dict:
    return {
        "data": {
            "xSGetDSRDevicesInfo": {
                "res": "OK",
                "armStatus": "disarmed",
                "timestamp": "2026-07-24 10:00:00",
                "devices": devices,
            }
        }
    }


class TestGetContactDevices:
    """Tests for magnetic-contact inventory discovery."""

    async def test_filters_active_mg_and_mr_devices(
        self, client: VerisureOwaClient, transport: MagicMock
    ) -> None:
        transport.execute.return_value = _device_list_response(
            [
                {
                    "id": "1",
                    "code": "1",
                    "zoneId": "MG01",
                    "name": "Porte entrée",
                    "type": "MG",
                    "isActive": True,
                },
                {
                    "id": "2",
                    "code": "2",
                    "zoneId": "MR02",
                    "name": "Fenêtre salon",
                    "type": "MR",
                    "isActive": True,
                },
                {
                    "id": "3",
                    "code": "3",
                    "zoneId": "QR03",
                    "name": "Caméra",
                    "type": "QR",
                    "isActive": True,
                },
                {
                    "id": "4",
                    "code": "4",
                    "zoneId": "MG04",
                    "name": "Ancienne porte",
                    "type": "MG",
                    "isActive": False,
                },
            ]
        )

        result = await client.get_contact_devices(make_installation())

        assert len(result) == 2
        assert all(isinstance(device, ContactDevice) for device in result)
        assert [device.zone_id for device in result] == ["MG01", "MR02"]

    async def test_synthesizes_zone_and_deduplicates_annex_rows(
        self, client: VerisureOwaClient, transport: MagicMock
    ) -> None:
        transport.execute.return_value = _device_list_response(
            [
                {
                    "id": "1",
                    "code": "8",
                    "zoneId": None,
                    "name": "Porte annexe",
                    "type": "MG",
                    "isActive": None,
                },
                {
                    "id": "7",
                    "code": "8",
                    "zoneId": None,
                    "name": "Porte annexe",
                    "type": "MG",
                    "isActive": None,
                },
            ]
        )

        result = await client.get_contact_devices(make_installation())

        assert len(result) == 1
        assert result[0].zone_id == "MG08"


class TestGetContactStates:
    """Tests for DSR magnetic-state parsing."""

    async def test_parses_open_and_closed_states(
        self, client: VerisureOwaClient, transport: MagicMock
    ) -> None:
        transport.execute.return_value = _contact_status_response(
            [
                {
                    "id": "1",
                    "zoneId": "MG01",
                    "magneticState": {
                        "value": "open",
                        "timestamp": "2026-07-24 09:59:58",
                    },
                    "batteryVoltage": {"value": 2.9, "timestamp": None},
                    "rssiRf": {"value": -70, "timestamp": None},
                    "firmwareVersion": {"value": "1.2", "timestamp": None},
                    "timestamp": "2026-07-24 09:59:58",
                },
                {
                    "id": "2",
                    "zoneId": "MR02",
                    "magneticState": {"value": "closed", "timestamp": None},
                },
            ]
        )

        result = await client.get_contact_states(make_installation())

        assert [state.is_open for state in result] == [True, False]
        request = transport.execute.call_args.args[0]
        assert request["operationName"] == "xSGetDSRDevicesInfo"
        assert "magneticState" in request["query"]
        assert request["variables"] == {"numinst": "123456"}

    async def test_none_device_list_returns_empty_list(
        self, client: VerisureOwaClient, transport: MagicMock
    ) -> None:
        transport.execute.return_value = _contact_status_response(None)

        result = await client.get_contact_states(make_installation())

        assert result == []
