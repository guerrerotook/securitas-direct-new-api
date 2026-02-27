"""Tests for ApiManager service methods."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from custom_components.securitas.securitas_direct_new_api.apimanager import ApiManager
from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    AirQuality,
    Attribute,
    Installation,
    OtpPhone,
    Sentinel,
    Service,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)

from .conftest import make_jwt

pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def installation():
    return Installation(number="123456", alias="Home", panel="SDVFAST", type="PLUS")


@pytest.fixture
def authed_api(api):
    api._check_authentication_token = AsyncMock()
    api._check_capabilities_token = AsyncMock()
    return api


@pytest.fixture
def mock_service(installation):
    """A Service with a zone-1 attribute, suitable for sentinel / air quality calls."""
    return Service(
        id=1,
        id_service=1,
        active=True,
        visible=True,
        bde=False,
        is_premium=False,
        cod_oper=False,
        total_device=0,
        request="CONFORT",
        multiple_req=False,
        num_devices_mr=0,
        secret_word=False,
        min_wrapper_version=None,
        description="Sentinel",
        attributes=[Attribute(name="zone", value="1", active=True)],
        listdiy=[],
        listprompt=[],
        installation=installation,
    )


# ── list_installations() ─────────────────────────────────────────────────────


class TestListInstallations:
    async def test_returns_installation_objects(self, api, mock_execute):
        mock_execute.return_value = {
            "data": {
                "xSInstallations": {
                    "installations": [
                        {
                            "numinst": "123",
                            "alias": "Home",
                            "panel": "SDVFAST",
                            "type": "PLUS",
                            "name": "John",
                            "surname": "Doe",
                            "address": "123 St",
                            "city": "Madrid",
                            "postcode": "28001",
                            "province": "Madrid",
                            "email": "j@e.com",
                            "phone": "555",
                        }
                    ]
                }
            }
        }

        result = await api.list_installations()

        assert len(result) == 1
        inst = result[0]
        assert isinstance(inst, Installation)
        assert inst.number == "123"
        assert inst.alias == "Home"
        assert inst.panel == "SDVFAST"
        assert inst.type == "PLUS"
        assert inst.name == "John"
        assert inst.lastName == "Doe"
        assert inst.address == "123 St"
        assert inst.city == "Madrid"
        assert inst.postalCode == "28001"
        assert inst.province == "Madrid"
        assert inst.email == "j@e.com"
        assert inst.phone == "555"

    async def test_multiple_installations(self, api, mock_execute):
        mock_execute.return_value = {
            "data": {
                "xSInstallations": {
                    "installations": [
                        {
                            "numinst": "111",
                            "alias": "Home",
                            "panel": "P1",
                            "type": "PLUS",
                            "name": "A",
                            "surname": "B",
                            "address": "",
                            "city": "",
                            "postcode": "",
                            "province": "",
                            "email": "",
                            "phone": "",
                        },
                        {
                            "numinst": "222",
                            "alias": "Office",
                            "panel": "P2",
                            "type": "BASIC",
                            "name": "C",
                            "surname": "D",
                            "address": "",
                            "city": "",
                            "postcode": "",
                            "province": "",
                            "email": "",
                            "phone": "",
                        },
                    ]
                }
            }
        }

        result = await api.list_installations()

        assert len(result) == 2
        assert result[0].number == "111"
        assert result[1].number == "222"

    async def test_none_xsinstallations_raises_error(self, api, mock_execute):
        mock_execute.return_value = {"data": {"xSInstallations": None}}

        with pytest.raises(SecuritasDirectError, match="xSInstallations response is None"):
            await api.list_installations()

    async def test_empty_installations_returns_empty(self, api, mock_execute):
        mock_execute.return_value = {
            "data": {"xSInstallations": {"installations": []}}
        }

        result = await api.list_installations()

        assert result == []


# ── get_all_services() ────────────────────────────────────────────────────────


class TestGetAllServices:
    async def test_returns_service_objects(self, api, mock_execute, installation):
        capabilities_jwt = make_jwt(exp_minutes=60)
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": [
                            {
                                "idService": 1,
                                "active": True,
                                "visible": True,
                                "bde": False,
                                "isPremium": False,
                                "codOper": False,
                                "request": "CONFORT",
                                "minWrapperVersion": None,
                                "totalDevice": 0,
                                "description": "Sentinel",
                                "attributes": {
                                    "attributes": [
                                        {"name": "zone", "value": "1", "active": True}
                                    ]
                                },
                            }
                        ],
                        "capabilities": capabilities_jwt,
                    }
                }
            }
        }

        result = await api.get_all_services(installation)

        assert len(result) == 1
        svc = result[0]
        assert isinstance(svc, Service)
        assert svc.id_service == 1
        assert svc.active is True
        assert svc.request == "CONFORT"
        assert svc.description == "Sentinel"
        assert len(svc.attributes) == 1
        assert svc.attributes[0].name == "zone"
        assert svc.attributes[0].value == "1"

    async def test_sets_capabilities_and_exp(self, api, mock_execute, installation):
        capabilities_jwt = make_jwt(exp_minutes=60)
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": [
                            {
                                "idService": 1,
                                "active": True,
                                "visible": True,
                                "bde": False,
                                "isPremium": False,
                                "codOper": False,
                                "request": "CONFORT",
                                "minWrapperVersion": None,
                                "totalDevice": 0,
                                "attributes": None,
                            }
                        ],
                        "capabilities": capabilities_jwt,
                    }
                }
            }
        }

        await api.get_all_services(installation)

        assert installation.capabilities == capabilities_jwt
        assert installation.capabilities_exp > datetime.now()

    async def test_none_installation_data_returns_empty(
        self, api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSSrv": {"installation": None}}}

        result = await api.get_all_services(installation)

        assert result == []

    async def test_none_services_returns_empty(self, api, mock_execute, installation):
        capabilities_jwt = make_jwt(exp_minutes=60)
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": None,
                        "capabilities": capabilities_jwt,
                    }
                }
            }
        }

        result = await api.get_all_services(installation)

        assert result == []

    async def test_none_capabilities_returns_empty(
        self, api, mock_execute, installation
    ):
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": [
                            {
                                "idService": 1,
                                "active": True,
                                "visible": True,
                                "bde": False,
                                "isPremium": False,
                                "codOper": False,
                                "request": "CONFORT",
                                "minWrapperVersion": None,
                                "totalDevice": 0,
                                "attributes": None,
                            }
                        ],
                        "capabilities": None,
                    }
                }
            }
        }

        result = await api.get_all_services(installation)

        assert result == []


# ── get_sentinel_data() ───────────────────────────────────────────────────────


class TestGetSentinelData:
    async def test_returns_sentinel_with_correct_data(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {
            "data": {
                "xSComfort": {
                    "res": "OK",
                    "devices": [
                        {
                            "alias": "Living",
                            "status": {
                                "temperature": 22,
                                "humidity": 45,
                                "airQualityCode": "GOOD",
                            },
                            "zone": "1",
                        }
                    ],
                }
            }
        }

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert isinstance(result, Sentinel)
        assert result.alias == "Living"
        assert result.temperature == 22
        assert result.humidity == 45

    async def test_error_response_returns_empty_sentinel(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {
            "errors": [{"message": "Something went wrong"}]
        }

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result == Sentinel("", "", 0, 0)

    async def test_none_xscomfort_returns_empty_sentinel(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {"data": {"xSComfort": None}}

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result == Sentinel("", "", 0, 0)

    async def test_device_not_found_returns_empty_sentinel(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {
            "data": {
                "xSComfort": {
                    "res": "OK",
                    "devices": [
                        {
                            "alias": "Bedroom",
                            "status": {
                                "temperature": 18,
                                "humidity": 50,
                                "airQualityCode": "GOOD",
                            },
                            "zone": "99",
                        }
                    ],
                }
            }
        }

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result == Sentinel("", "", 0, 0)


# ── get_air_quality_data() ────────────────────────────────────────────────────


class TestGetAirQualityData:
    async def test_returns_air_quality(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {
            "data": {
                "xSAirQ": {
                    "graphData": {
                        "status": {"current": 85, "currentMsg": "Good"}
                    }
                }
            }
        }

        result = await authed_api.get_air_quality_data(installation, mock_service)

        assert isinstance(result, AirQuality)
        assert result.value == 85
        assert result.message == "Good"

    async def test_error_response_returns_empty_air_quality(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {
            "errors": [{"message": "Something went wrong"}]
        }

        result = await authed_api.get_air_quality_data(installation, mock_service)

        assert result == AirQuality(0, "")

    async def test_none_xsairq_returns_empty_air_quality(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {"data": {"xSAirQ": None}}

        result = await authed_api.get_air_quality_data(installation, mock_service)

        assert result == AirQuality(0, "")


# ── send_otp() ────────────────────────────────────────────────────────────────


class TestSendOtp:
    async def test_returns_res_value(self, api, mock_execute):
        mock_execute.return_value = {
            "data": {"xSSendOtp": {"res": "OK", "msg": ""}}
        }

        result = await api.send_otp(device_id=1, auth_otp_hash="hash123")

        assert result == "OK"

    async def test_none_response_raises_error(self, api, mock_execute):
        mock_execute.return_value = {"data": {"xSSendOtp": None}}

        with pytest.raises(SecuritasDirectError, match="xSSendOtp response is None"):
            await api.send_otp(device_id=1, auth_otp_hash="hash123")


# ── logout() ─────────────────────────────────────────────────────────────────


class TestLogout:
    async def test_calls_execute_request_with_logout(self, api, mock_execute):
        mock_execute.return_value = {}

        await api.logout()

        mock_execute.assert_awaited_once()
        call_args = mock_execute.call_args
        content = call_args[0][0]
        operation = call_args[0][1]
        assert content["operationName"] == "Logout"
        assert operation == "Logout"
