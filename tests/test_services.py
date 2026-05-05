"""Tests for SecuritasClient service methods."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from custom_components.securitas.securitas_direct_new_api.models import (
    Attribute,
    Installation,
    Sentinel,
    Service,
    SmartLockMode,
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
    api._ensure_capabilities = AsyncMock()
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
    async def test_returns_installation_objects(self, authed_api, mock_execute):
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

        result = await authed_api.list_installations()

        assert len(result) == 1
        inst = result[0]
        assert isinstance(inst, Installation)
        assert inst.number == "123"
        assert inst.alias == "Home"
        assert inst.panel == "SDVFAST"
        assert inst.type == "PLUS"
        assert inst.name == "John"
        assert inst.last_name == "Doe"
        assert inst.address == "123 St"
        assert inst.city == "Madrid"
        assert inst.postal_code == "28001"
        assert inst.province == "Madrid"
        assert inst.email == "j@e.com"
        assert inst.phone == "555"

    async def test_multiple_installations(self, authed_api, mock_execute):
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

        result = await authed_api.list_installations()

        assert len(result) == 2
        assert result[0].number == "111"
        assert result[1].number == "222"

    async def test_none_xsinstallations_raises_error(self, authed_api, mock_execute):
        mock_execute.return_value = {"data": {"xSInstallations": None}}

        with pytest.raises(SecuritasDirectError, match="Invalid response"):
            await authed_api.list_installations()

    async def test_empty_installations_returns_empty(self, authed_api, mock_execute):
        mock_execute.return_value = {"data": {"xSInstallations": {"installations": []}}}

        result = await authed_api.list_installations()

        assert result == []


# ── get_all_services() ────────────────────────────────────────────────────────


class TestGetAllServices:
    async def test_returns_service_objects(
        self, authed_api, mock_execute, installation
    ):
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

        result = await authed_api.get_services(installation)

        assert len(result) == 1
        svc = result[0]
        assert isinstance(svc, Service)
        assert svc.id_service == 1
        assert svc.active is True
        assert svc.request == "CONFORT"
        assert svc.description == "Sentinel"
        assert len(svc.attributes) == 1  # type: ignore[arg-type]
        assert svc.attributes[0].name == "zone"  # type: ignore[index]
        assert svc.attributes[0].value == "1"  # type: ignore[index]

    async def test_sets_capabilities_and_exp(
        self, authed_api, mock_execute, installation
    ):
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

        await authed_api.get_services(installation)

        cap_entry = authed_api._capabilities.get(installation.number)
        assert cap_entry is not None
        assert cap_entry[0] == capabilities_jwt
        assert cap_entry[1] > datetime.now()

    async def test_none_installation_data_returns_empty(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSSrv": {"installation": None}}}

        result = await authed_api.get_services(installation)

        assert result == []

    async def test_none_services_returns_empty(
        self, authed_api, mock_execute, installation
    ):
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

        result = await authed_api.get_services(installation)

        assert result == []

    async def test_none_capabilities_returns_empty(
        self, authed_api, mock_execute, installation
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

        result = await authed_api.get_services(installation)

        assert result == []

    async def test_cap_lookup_uses_installation_number_not_first_entry(
        self, authed_api, mock_execute
    ):
        """JWT cap extraction uses the matching 'ins' field, not installations[0].

        When a JWT contains multiple installation entries, get_services must pick
        the entry whose 'ins' field matches installation.number.  Previously the
        code always read installations[0], which would return the wrong cap set
        for the second (or later) installation.
        """
        # Build an installation whose number is "222222"
        installation_b = Installation(
            number="222222", alias="Office", panel="SDVFAST", type="PLUS"
        )

        caps_for_home = ["ARM", "ARMDAY", "ARMNIGHT", "PERI"]
        caps_for_office = ["ARM", "ARMANNEX", "DARMANNEX"]

        multi_install_jwt = make_jwt(
            exp_minutes=60,
            installations=[
                {"ins": "111111", "cap": caps_for_home},
                {"ins": "222222", "cap": caps_for_office},
            ],
        )
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": [],
                        "capabilities": multi_install_jwt,
                    }
                }
            }
        }

        await authed_api.get_services(installation_b)

        cap_entry = authed_api._capabilities.get(installation_b.number)
        assert cap_entry is not None
        # Must be the cap set for "222222", not "111111"
        assert cap_entry[2] == frozenset(caps_for_office)

    async def test_cap_lookup_falls_back_to_empty_when_no_match(
        self, authed_api, mock_execute
    ):
        """When no JWT installation entry matches, cap_set falls back to empty frozenset."""
        installation_x = Installation(
            number="999999", alias="Unknown", panel="SDVFAST", type="PLUS"
        )

        no_match_jwt = make_jwt(
            exp_minutes=60,
            installations=[
                {"ins": "111111", "cap": ["ARM", "PERI"]},
            ],
        )
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": [],
                        "capabilities": no_match_jwt,
                    }
                }
            }
        }

        await authed_api.get_services(installation_x)

        cap_entry = authed_api._capabilities.get(installation_x.number)
        assert cap_entry is not None
        assert cap_entry[2] == frozenset()


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
                                "airQualityCode": 2,
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
        assert result.air_quality == "2"

    async def test_error_response_raises(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {"errors": [{"message": "Something went wrong"}]}

        with pytest.raises(SecuritasDirectError):
            await authed_api.get_sentinel_data(installation, mock_service)

    async def test_none_xscomfort_raises(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {"data": {"xSComfort": None}}

        with pytest.raises(SecuritasDirectError):
            await authed_api.get_sentinel_data(installation, mock_service)

    async def test_missing_air_quality_code_returns_empty_string(
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
                            },
                            "zone": "1",
                        }
                    ],
                }
            }
        }

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result.air_quality == ""
        assert result.temperature == 22
        assert result.humidity == 45

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
                                "airQualityCode": 2,
                            },
                            "zone": "99",
                        }
                    ],
                }
            }
        }

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result == Sentinel(alias="", air_quality="", humidity=0, temperature=0)


# ── send_otp() ────────────────────────────────────────────────────────────────


class TestSendOtp:
    async def test_returns_res_value(self, authed_api, mock_execute):
        mock_execute.return_value = {"data": {"xSSendOtp": {"res": "OK", "msg": ""}}}

        result = await authed_api.send_otp(device_id=1, auth_otp_hash="hash123")

        assert result == "OK"

    async def test_none_response_raises_error(self, authed_api, mock_execute):
        mock_execute.return_value = {"data": {"xSSendOtp": None}}

        with pytest.raises(SecuritasDirectError, match="xSSendOtp response is None"):
            await authed_api.send_otp(device_id=1, auth_otp_hash="hash123")


# ── logout() ─────────────────────────────────────────────────────────────────


class TestLogout:
    async def test_calls_execute_request_with_logout(self, authed_api, mock_execute):
        mock_execute.return_value = {}

        await authed_api.logout()

        mock_execute.assert_awaited_once()
        call_args = mock_execute.call_args
        content = call_args[0][0]
        headers = call_args[0][1]
        assert content["operationName"] == "Logout"
        assert headers["X-APOLLO-OPERATION-NAME"] == "Logout"


# ── Additional sentinel / air quality edge cases ─────────────────────────────


class TestGetSentinelDataEdgeCases:
    async def test_get_sentinel_data_with_no_attributes_returns_empty(
        self, authed_api, mock_execute, installation
    ):
        """Service with no attributes returns empty Sentinel."""
        service_no_attrs = Service(
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
            attributes=[],
            listdiy=[],
            listprompt=[],
            installation=installation,
        )
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
                                "airQualityCode": 2,
                            },
                            "zone": "1",
                        }
                    ],
                }
            }
        }

        result = await authed_api.get_sentinel_data(installation, service_no_attrs)

        assert result == Sentinel(alias="", air_quality="", humidity=0, temperature=0)


class TestGetAirQualityData:
    """Tests for get_air_quality_data (xSAirQuality API)."""

    async def test_returns_air_quality_from_hours(
        self, authed_api, mock_execute, installation
    ):
        """Parses hours[-1].value as numeric air quality."""
        from tests.mock_graphql import graphql_air_quality

        mock_execute.return_value = graphql_air_quality(
            hour_value="114", status_current=1
        )

        result = await authed_api.get_air_quality_data(installation, "1")

        assert result is not None
        assert result.value == 114
        assert result.status_current == 1

    async def test_raises_on_errors(self, authed_api, mock_execute, installation):
        """Raises SecuritasDirectError when response has errors."""
        mock_execute.return_value = {"errors": [{"message": "fail"}]}

        with pytest.raises(SecuritasDirectError):
            await authed_api.get_air_quality_data(installation, "1")

    async def test_returns_status_when_hours_null(
        self, authed_api, mock_execute, installation
    ):
        """Returns status even when hours is null (issue #428 — Chipre)."""
        from tests.mock_graphql import graphql_air_quality

        mock_execute.return_value = graphql_air_quality(status_current=1, hours=None)

        result = await authed_api.get_air_quality_data(installation, "1")

        assert result is not None
        assert result.value is None
        assert result.status_current == 1

    async def test_raises_when_xsairquality_null(
        self, authed_api, mock_execute, installation
    ):
        """Raises SecuritasDirectError when xSAirQuality is null."""
        mock_execute.return_value = {
            "data": {
                "xSAirQuality": None,
            }
        }

        with pytest.raises(SecuritasDirectError):
            await authed_api.get_air_quality_data(installation, "1")


class TestGetAllServicesEdgeCases:
    async def test_null_xssrv_returns_empty_list(
        self, authed_api, mock_execute, installation
    ):
        """When xSSrv response is None, returns empty list."""
        mock_execute.return_value = {"data": {"xSSrv": None}}

        result = await authed_api.get_services(installation)

        assert result == []


# ── check_alarm / check_alarm_status tests ───────────────────────────────────


# ── Dataclass field tests ────────────────────────────────────────────────────


class TestDataclassFields:
    def test_smart_lock_mode_has_device_id(self):
        mode = SmartLockMode(res="OK", lockStatus="2", deviceId="02")
        assert mode.device_id == "02"

    def test_smart_lock_mode_device_id_defaults_empty(self):
        mode = SmartLockMode(res="OK", lockStatus="2")
        assert mode.device_id == ""
