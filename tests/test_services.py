"""Tests for ApiManager service methods."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    Attribute,
    Installation,
    OperationStatus,
    Sentinel,
    Service,
    SmartLockMode,
    SmartLockModeStatus,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    ArmingExceptionError,
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

        with pytest.raises(
            SecuritasDirectError, match="xSInstallations response is None"
        ):
            await api.list_installations()

    async def test_empty_installations_returns_empty(self, api, mock_execute):
        mock_execute.return_value = {"data": {"xSInstallations": {"installations": []}}}

        result = await api.list_installations()

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

        result = await authed_api.get_all_services(installation)

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

        await authed_api.get_all_services(installation)

        assert installation.capabilities == capabilities_jwt
        assert installation.capabilities_exp > datetime.now()

    async def test_none_installation_data_returns_empty(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = {"data": {"xSSrv": {"installation": None}}}

        result = await authed_api.get_all_services(installation)

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

        result = await authed_api.get_all_services(installation)

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

        result = await authed_api.get_all_services(installation)

        assert result == []

    async def test_get_all_services_extracts_alarm_partitions(
        self, authed_api, mock_execute, installation
    ):
        """get_all_services should store alarmPartitions on the installation."""
        capabilities_jwt = make_jwt(exp_minutes=60)
        partitions = [
            {"id": "1", "enterStates": ["T", "A", "P", "Q", "E"], "leaveStates": ["D"]}
        ]
        mock_execute.return_value = {
            "data": {
                "xSSrv": {
                    "installation": {
                        "services": [],
                        "capabilities": capabilities_jwt,
                        "configRepoUser": {"alarmPartitions": partitions},
                    }
                }
            }
        }

        await authed_api.get_all_services(installation)

        assert installation.alarm_partitions == partitions


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

    async def test_error_response_returns_empty_sentinel(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {"errors": [{"message": "Something went wrong"}]}

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result == Sentinel("", "", 0, 0)

    async def test_none_xscomfort_returns_empty_sentinel(
        self, authed_api, mock_execute, installation, mock_service
    ):
        mock_execute.return_value = {"data": {"xSComfort": None}}

        result = await authed_api.get_sentinel_data(installation, mock_service)

        assert result == Sentinel("", "", 0, 0)

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

        assert result == Sentinel("", "", 0, 0)


# ── send_otp() ────────────────────────────────────────────────────────────────


class TestSendOtp:
    async def test_returns_res_value(self, api, mock_execute):
        mock_execute.return_value = {"data": {"xSSendOtp": {"res": "OK", "msg": ""}}}

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

        assert result == Sentinel("", "", 0, 0)


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

    async def test_returns_none_on_errors(self, authed_api, mock_execute, installation):
        """Returns None when response has errors."""
        mock_execute.return_value = {"errors": [{"message": "fail"}]}

        result = await authed_api.get_air_quality_data(installation, "1")

        assert result is None

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

    async def test_returns_status_when_hours_empty(
        self, authed_api, mock_execute, installation
    ):
        """Returns status even when hours list is empty."""
        from tests.mock_graphql import graphql_air_quality

        mock_execute.return_value = graphql_air_quality(status_current=1, hours=[])

        result = await authed_api.get_air_quality_data(installation, "1")

        assert result is not None
        assert result.value is None
        assert result.status_current == 1

    async def test_returns_none_when_xsairquality_null(
        self, authed_api, mock_execute, installation
    ):
        """Returns None when xSAirQuality is null."""
        mock_execute.return_value = {
            "data": {
                "xSAirQuality": None,
            }
        }

        result = await authed_api.get_air_quality_data(installation, "1")

        assert result is None


class TestGetAllServicesEdgeCases:
    async def test_null_xssrv_returns_empty_list(
        self, authed_api, mock_execute, installation
    ):
        """When xSSrv response is None, returns empty list."""
        mock_execute.return_value = {"data": {"xSSrv": None}}

        result = await authed_api.get_all_services(installation)

        assert result == []


# ── check_alarm / check_alarm_status tests ───────────────────────────────────


class TestCheckAlarm:
    async def test_check_alarm_returns_reference_id(
        self, authed_api, mock_execute, installation
    ):
        """check_alarm returns the reference ID string."""
        mock_execute.return_value = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "msg": "",
                    "referenceId": "ref-abc-123",
                }
            }
        }

        result = await authed_api.check_alarm(installation)

        assert result == "ref-abc-123"


class TestCheckAlarmStatus:
    async def test_check_alarm_status_returns_status(
        self, authed_api, mock_execute, installation
    ):
        """check_alarm_status returns OperationStatus dataclass."""
        from custom_components.securitas.securitas_direct_new_api.dataTypes import (
            OperationStatus,
        )

        # Return immediate (non-WAIT) response so no loop
        mock_execute.return_value = {
            "data": {
                "xSCheckAlarmStatus": {
                    "res": "OK",
                    "msg": "",
                    "status": "ARM1",
                    "numinst": "123456",
                    "protomResponse": "PROT_RESP",
                    "protomResponseDate": "2024-01-01",
                }
            }
        }

        result = await authed_api.check_alarm_status(installation, "ref-abc-123")

        assert isinstance(result, OperationStatus)
        assert result.operation_status == "OK"
        assert result.status == "ARM1"
        assert result.installation_number == "123456"
        assert result.protomResponse == "PROT_RESP"


# ── Dataclass field tests ────────────────────────────────────────────────────


class TestDataclassFields:
    def test_smart_lock_mode_has_device_id(self):
        mode = SmartLockMode(res="OK", lockStatus="2", deviceId="02")
        assert mode.deviceId == "02"

    def test_smart_lock_mode_device_id_defaults_empty(self):
        mode = SmartLockMode(res="OK", lockStatus="2")
        assert mode.deviceId == ""


# ── Submit request + single-poll methods for ApiQueue ─────────────────────────


class TestSubmitRequestMethods:
    """Tests for submit request + single-poll methods used by ApiQueue."""

    async def test_submit_arm_request_returns_reference_id(
        self, authed_api, installation
    ):
        authed_api._execute_request = AsyncMock(
            return_value={
                "data": {
                    "xSArmPanel": {
                        "res": "OK",
                        "msg": "processed",
                        "referenceId": "ref-123",
                    }
                }
            }
        )
        ref = await authed_api.submit_arm_request(installation, "ARM1")
        assert ref == "ref-123"

    async def test_submit_arm_request_error_raises(self, authed_api, installation):
        authed_api._execute_request = AsyncMock(
            return_value={
                "data": {
                    "xSArmPanel": {
                        "res": "ERROR",
                        "msg": "failed",
                        "referenceId": None,
                    }
                }
            }
        )
        with pytest.raises(SecuritasDirectError):
            await authed_api.submit_arm_request(installation, "ARM1")

    async def test_submit_disarm_request_returns_reference_id(
        self, authed_api, installation
    ):
        authed_api._execute_request = AsyncMock(
            return_value={
                "data": {
                    "xSDisarmPanel": {
                        "res": "OK",
                        "msg": "processed",
                        "referenceId": "ref-456",
                    }
                }
            }
        )
        ref = await authed_api.submit_disarm_request(installation, "DARM1")
        assert ref == "ref-456"

    async def test_check_arm_status_delegates(self, authed_api, installation):
        authed_api._execute_request = AsyncMock(
            return_value={
                "data": {
                    "xSArmStatus": {
                        "res": "WAIT",
                        "msg": "processing",
                        "status": None,
                        "protomResponse": None,
                        "protomResponseDate": None,
                        "numinst": "123",
                        "requestId": None,
                        "error": None,
                    }
                }
            }
        )
        raw = await authed_api.check_arm_status(installation, "ref-123", "ARM1", 1)
        assert raw["res"] == "WAIT"

    async def test_check_disarm_status_delegates(self, authed_api, installation):
        authed_api._execute_request = AsyncMock(
            return_value={
                "data": {
                    "xSDisarmStatus": {
                        "res": "WAIT",
                        "msg": "processing",
                        "status": None,
                        "protomResponse": None,
                        "protomResponseDate": None,
                        "numinst": "123",
                        "requestId": None,
                        "error": None,
                    }
                }
            }
        )
        raw = await authed_api.check_disarm_status(installation, "ref-456", "DARM1", 1)
        assert raw["res"] == "WAIT"

    async def test_submit_change_lock_mode_request_returns_reference_id(
        self, authed_api, installation
    ):
        authed_api._execute_request = AsyncMock(
            return_value={
                "data": {
                    "xSChangeSmartlockMode": {
                        "res": "OK",
                        "msg": "ok",
                        "referenceId": "ref-lock",
                    }
                }
            }
        )
        ref = await authed_api.submit_change_lock_mode_request(installation, True, "01")
        assert ref == "ref-lock"


# ── Result-processing helpers ────────────────────────────────────────────────


class TestResultProcessing:
    """Tests for result-processing helpers."""

    async def test_process_arm_result_success(self, authed_api, installation):
        raw = {
            "res": "OK",
            "msg": "armed",
            "status": "ARMED",
            "protomResponse": "P",
            "protomResponseDate": "2026-01-01",
            "numinst": "123",
            "requestId": "req1",
            "error": None,
        }
        result = await authed_api.process_arm_result(raw, installation)
        assert isinstance(result, OperationStatus)
        assert result.protomResponse == "P"
        assert authed_api.protom_response == "P"

    async def test_process_arm_result_error_raises(self, authed_api, installation):
        raw = {
            "res": "ERROR",
            "msg": "fault",
            "status": None,
            "protomResponse": None,
            "protomResponseDate": None,
            "numinst": "123",
            "requestId": None,
            "error": {"type": "BLOCKING", "description": "fault"},
        }
        with pytest.raises(SecuritasDirectError):
            await authed_api.process_arm_result(raw, installation)

    async def test_process_arm_result_non_blocking_raises_arming_exception(
        self, authed_api, installation
    ):
        raw = {
            "res": "ERROR",
            "msg": "exception",
            "status": None,
            "protomResponse": None,
            "protomResponseDate": None,
            "numinst": "123",
            "requestId": None,
            "error": {
                "type": "NON_BLOCKING",
                "allowForcing": True,
                "referenceId": "ref-err",
                "suid": "suid-1",
            },
        }
        authed_api._get_exceptions = AsyncMock(
            return_value=[{"alias": "Window", "status": "OPEN", "deviceType": "SENSOR"}]
        )
        with pytest.raises(ArmingExceptionError) as exc_info:
            await authed_api.process_arm_result(raw, installation)
        assert exc_info.value.reference_id == "ref-err"
        assert exc_info.value.suid == "suid-1"
        assert len(exc_info.value.exceptions) == 1

    async def test_process_disarm_result_success(self, authed_api, installation):
        raw = {
            "res": "OK",
            "msg": "disarmed",
            "status": "DISARMED",
            "protomResponse": "D",
            "protomResponseDate": "2026-01-01",
            "numinst": "123",
            "requestId": "req2",
            "error": None,
        }
        result = authed_api.process_disarm_result(raw)
        assert isinstance(result, OperationStatus)
        assert result.protomResponse == "D"
        assert authed_api.protom_response == "D"

    async def test_process_disarm_result_error_raises(self, authed_api, installation):
        raw = {
            "res": "ERROR",
            "msg": "fail",
            "status": None,
            "protomResponse": None,
            "protomResponseDate": None,
            "numinst": "123",
            "requestId": None,
            "error": {"type": "BLOCKING"},
        }
        with pytest.raises(SecuritasDirectError):
            authed_api.process_disarm_result(raw)

    async def test_process_lock_mode_result_success(self, authed_api, installation):
        raw = {
            "res": "OK",
            "msg": "locked",
            "protomResponse": "L",
            "status": "LOCKED",
        }
        result = authed_api.process_lock_mode_result(raw)
        assert isinstance(result, SmartLockModeStatus)
        assert result.protomResponse == "L"
        assert authed_api.protom_response == "L"
