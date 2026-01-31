"""Securitas Direct API implementation."""
import asyncio
from datetime import datetime, timedelta
import json
import logging
import secrets
from typing import Any, Optional
from uuid import uuid4

from aiohttp import ClientConnectorError, ClientSession
import jwt

from .const import COMMAND_MAP, CommandType, SecDirAlarmState
from .dataTypes import (
    AirQuality,
    ArmStatus,
    Attribute,
    Attributes,
    CheckAlarmStatus,
    DisarmStatus,
    Installation,
    OtpPhone,
    Sentinel,
    Service,
    SStatus,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
)
from .domains import ApiDomains
from .exceptions import Login2FAError, LoginError, SecuritasDirectError

_LOGGER = logging.getLogger(__name__)


def generate_uuid() -> str:
    """Create a device id."""
    return str(uuid4()).replace("-", "")[0:16]


def generate_device_id(lang: str) -> str:
    """Create a device identifier for the API."""
    return secrets.token_urlsafe(16) + ":APA91b" + secrets.token_urlsafe(130)[0:134]


class ApiManager:
    """Securitas Direct API.

    NOTE: http_client (aiohttp.ClientSession) is expected to be created,
    reused and closed outside this class to avoid leaking HTTP sessions.
    """

    def __init__(
        self,
        username: str,
        password: str,
        country: str,
        http_client: ClientSession,
        device_id: str,
        uuid: str,
        id_device_indigitall: str,
        command_type: CommandType,
        delay_check_operation: int = 2,
    ) -> None:
        """Create the object."""
        self.username = username
        self.password = password
        domains = ApiDomains()
        self.country = country.upper()
        self.language = domains.get_language(country)
        self.api_url = domains.get_url(country)
        self.command_map = COMMAND_MAP[command_type]
        self.delay_check_operation: int = delay_check_operation
        self.protom_response: str = ""
        self.authentication_token: str = ""
        self.authentication_token_exp: datetime = datetime.min
        self.login_timestamp: int = 0
        self.authentication_otp_challenge_value: Optional[tuple[str, str]] = None
        # http_client is injected from outside and should be reused (no new sessions here)
        self.http_client = http_client
        self.refresh_token_value: str = ""

        # device specific configuration for the API
        self.device_id: str = device_id
        self.uuid: str = uuid
        self.id_device_indigitall: str = id_device_indigitall
        self.device_brand = "samsung"
        self.device_name = "SM-S901U"
        self.device_os_version = "12"
        self.device_resolution = ""
        self.device_type = ""
        self.device_version = "10.102.0"
        self.apollo_operation_id: str = secrets.token_hex(64)

    async def _execute_request(
        self, content, operation: str, installation: Optional[Installation] = None
    ) -> dict[str, Any]:
        """Send request to Securitas' API."""
        app: str = json.dumps({"appVersion": self.device_version, "origin": "native"})
        headers = {
            "app": app,
            "User-Agent": "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.5005.124 Safari/537.36 Edg/102.0.1245.41",
            "X-APOLLO-OPERATION-ID": self.apollo_operation_id,
            "X-APOLLO-OPERATION-NAME": operation,
            "extension": '{"mode":"full"}',
        }
        if installation is not None:
            headers["numinst"] = installation.number
            headers["panel"] = installation.panel
            headers["X-Capabilities"] = installation.capabilities
        if self.authentication_token != "":
            authorization_value = {
                "loginTimestamp": self.login_timestamp,
                "user": self.username,
                "id": self._generate_id(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWA_10",
                "hash": self.authentication_token,
            }
            headers["auth"] = json.dumps(authorization_value)
        if operation in ["mkValidateDevice", "RefreshLogin", "mkSendOTP"]:
            authorization_value = {
                "loginTimestamp": self.login_timestamp,
                "user": self.username,
                "id": self._generate_id(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWA_10",
                "hash": "",
                "refreshToken": "",
            }
            headers["auth"] = json.dumps(authorization_value)
        if self.authentication_otp_challenge_value is not None:
            authorization_value = {
                "token": self.authentication_otp_challenge_value[1],
                "type": "OTP",
                "otpHash": self.authentication_otp_challenge_value[0],
            }
            headers["security"] = json.dumps(authorization_value)
        _LOGGER.debug(
            "Making request %s with device_id %s, uuid %s and idDeviceIndigitall %s",
            operation,
            self.device_id,
            self.uuid,
            self.id_device_indigitall,
        )
        try:
            async with self.http_client.post(
                self.api_url, headers=headers, json=content
            ) as response:
                response_text: str = await response.text()
        except Exception as err:
            # FIX: Si hay error de red, lanzamos excepción antes de intentar leer JSON
            raise SecuritasDirectError(
                f"Connection error with URL {self.api_url}: {str(err)}", None, headers, content
            ) from err
        _LOGGER.debug("----------------------Response----------------------")
        _LOGGER.debug(response_text)
        try:
            response_dict = json.loads(response_text)
        except json.JSONDecodeError as err:
            _LOGGER.error("Problems decoding response %s", response_text)
            raise SecuritasDirectError(err.msg, None, headers, content) from err
        if (
            "errors" in response_dict
            and isinstance(response_dict["errors"], dict)
            and "data" in response_dict["errors"]
            and "reason" in response_dict["errors"]["data"]
        ):
            raise SecuritasDirectError(
                response_dict["errors"]["data"]["reason"],
                response_dict,
                headers,
                content,
            )
        return response_dict

    async def _check_errros(self, value: str) -> bool:
        """Check errors in raw JSON string and auto-login on session issues."""
        if value is not None:
            response = json.loads(value)
            if "errors" in response:
                for error_item in response["errors"]:
                    if "message" in error_item:
                        if (
                            error_item["message"]
                            == "Invalid session. Please, try again later."
                            or error_item["message"] == "Invalid token: Expired"
                            or error_item["message"]
                            == "Required request header 'x-installationNumber' for method parameter type String is not present"
                        ):
                            self.authentication_token = None
                            _LOGGER.info("Login is expired. Login again")
                            await self.login()
                            return True
                        else:
                            _LOGGER.error(error_item["message"])
                            return False
        # Si no hay errores relevantes, devolvemos False explícitamente
        return False

    async def _check_capabilities_token(self, installation: Installation) -> None:
        """Check the capabilities token and get a new one if needed."""
        if (installation.capabilities == "") or (
            datetime.now() + timedelta(minutes=1) > installation.capabilities_exp
        ):
            _LOGGER.debug("Expired capabilities token, getting a new one")
            await self.get_all_services(installation)

    async def _check_authentication_token(self) -> None:
        """Check expiration of the authentication token and get a new one if needed."""
        if (not self.authentication_token) or (
            datetime.now() + timedelta(minutes=1) > self.authentication_token_exp
        ):
            _LOGGER.debug("Authentication token expired, logging in again")
            await self.login()

    def _generate_id(self) -> str:
        current: datetime = datetime.now()
        return (
            "OWA____________"
            + self.username
            + "____________"
            + current.strftime("%Y%m%d%H%M%S%f")
        )

    async def logout(self):
        """Logout."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n xSLogout\n}\n",
        }
        await self._execute_request(content, "Logout")

    def _extract_otp_data(self, data) -> tuple[str, list[OtpPhone]]:
        if not data:
            return (None, [])
        otp_hash = data.get("auth-otp-hash")
        phones: list[OtpPhone] = []
        for item in data.get("auth-phones", []):
            phones.append(OtpPhone(item["id"], item["phone"]))
        return (otp_hash, phones)

    async def validate_device(self, otp_succeed: bool = False, auth_otp_hash: str = None, sms_code: str = None) -> tuple:
        """Validate the device."""
        content = {
            "operationName": "mkValidateDevice",
            "variables": {
                "idDevice": self.device_id,
                "idDeviceIndigitall": self.id_device_indigitall,
                "uuid": self.uuid,
                "deviceName": self.device_name,
                "deviceBrand": self.device_brand,
                "deviceOsVersion": self.device_os_version,
                "deviceVersion": self.device_version,
            },
            "query": "mutation mkValidateDevice($idDevice: String, $idDeviceIndigitall: String, $uuid: String, $deviceName: String, $deviceBrand: String, $deviceOsVersion: String, $deviceVersion: String) {\n xSValidateDevice(idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, uuid: $uuid, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, deviceVersion: $deviceVersion) {\n res\n msg\n hash\n refreshToken\n legals\n }\n}\n",
        }
        if otp_succeed:
            self.authentication_otp_challenge_value = (auth_otp_hash, sms_code)
        try:
            response = await self._execute_request(content, "mkValidateDevice")
            self.authentication_otp_challenge_value = None
            self.authentication_token = response["data"]["xSValidateDevice"]["hash"]
            return (None, None)
        except SecuritasDirectError as err:
            # FIX: Comprobar None para evitar crash por DNS/Red
            if len(err.args) > 1 and err.args[1] is not None:
                try:
                    return self._extract_otp_data(err.args[1]["errors"][0]["data"])
                except (KeyError, IndexError, TypeError):
                    pass
            raise err

    async def refresh_token(self) -> bool:
        """Send a login refresh."""
        content = {
            "operationName": "RefreshLogin",
            "variables": {
                "refreshToken": self.refresh_token_value,
                "uuid": self.uuid,
                "country": self.country,
                "lang": self.language,
                "callby": "OWA_10",
            },
            "query": "mutation RefreshLogin($refreshToken: String!, $id: String!, $country: String!, $lang: String!, $callby: String!, $idDevice: String!, $idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: String!, $deviceOsVersion: String!, $uuid: String!) {\n xSRefreshLogin(refreshToken: $refreshToken, id: $id, country: $country, lang: $lang, callby: $callby, idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, deviceType: $deviceType, deviceVersion: $deviceVersion, deviceResolution: $deviceResolution, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, uuid: $uuid) {\n __typename\n res\n msg\n hash\n refreshToken\n legals\n changePassword\n needDeviceAuthorization\n mainUser\n }\n}",
        }
        response = await self._execute_request(content, "RefreshLogin")
        return response["data"]["xSRefreshLogin"]["res"] == "OK"

    async def send_otp(self, device_id: int, auth_otp_hash: str) -> bool:
        """Send the OTP device challenge."""
        content = {
            "operationName": "mkSendOTP",
            "variables": {
                "recordId": device_id,
                "otpHash": auth_otp_hash,
            },
            "query": "mutation mkSendOTP($recordId: Int!, $otpHash: String!) {\n xSSendOtp(recordId: $recordId, otpHash: $otpHash) {\n res\n msg\n }\n}\n",
        }
        response = await self._execute_request(content, "mkSendOTP")
        return response["data"]["xSSendOtp"]["res"] == "OK"

    async def login(self) -> None:
        """Send Login info and sets authentication token."""
        content = {
            "operationName": "mkLoginToken",
            "variables": {
                "user": self.username,
                "password": self.password,
                "id": self._generate_id(),
                "country": self.country,
                "callby": "OWA_10",
                "lang": self.language,
                "idDevice": self.device_id,
                "idDeviceIndigitall": self.id_device_indigitall,
                "deviceType": self.device_type,
                "deviceVersion": self.device_version,
                "deviceResolution": self.device_resolution,
                "deviceName": self.device_name,
                "deviceBrand": self.device_brand,
                "deviceOsVersion": self.device_os_version,
                "uuid": self.uuid,
            },
            "query": "mutation mkLoginToken($user: String!, $password: String!, $id: String!, $country: String!, $lang: String!, $callby: String!, $idDevice: String!, $idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: String!, $deviceOsVersion: String!, $uuid: String!) { xSLoginToken(user: $user, password: $password, country: $country, lang: $lang, callby: $callby, id: $id, idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, deviceType: $deviceType, deviceVersion: $deviceVersion, deviceResolution: $deviceResolution, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, uuid: $uuid) { __typename res msg hash refreshToken legals changePassword needDeviceAuthorization mainUser } }",
        }
        try:
            response = await self._execute_request(content, "mkLoginToken")
        except SecuritasDirectError as err:
            result_json = err.args[1] if len(err.args) > 1 else None
            if result_json and result_json.get("data"):
                if result_json["data"].get("xSLoginToken"):
                    if result_json["data"]["xSLoginToken"].get("needDeviceAuthorization"):
                        raise Login2FAError(err.args) from err
            raise LoginError(err.args) from err
        if "errors" in response:
            _LOGGER.error("Login error %s", response["errors"][0]["message"])
            raise LoginError(response["errors"][0]["message"], response)
        if response["data"]["xSLoginToken"].get("needDeviceAuthorization", False):
            raise Login2FAError("2FA authentication required", response)
        if response["data"]["xSLoginToken"]["hash"] is not None:
            self.authentication_token = response["data"]["xSLoginToken"]["hash"]
            self.login_timestamp = int(datetime.now().timestamp() * 1000)
            try:
                token = jwt.decode(
                    self.authentication_token,
                    algorithms=["HS256"],
                    options={"verify_signature": False},
                )
                if "exp" in token:
                    self.authentication_token_exp = datetime.fromtimestamp(
                        token["exp"]
                    )
            except jwt.exceptions.DecodeError as err:
                raise SecuritasDirectError(
                    f"Failed to decode authentication token {self.authentication_token}"
                ) from err
        else:
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

    async def list_installations(self) -> list[Installation]:
        """List securitas direct installations."""
        content = {
            "operationName": "mkInstallationList",
            "query": "query mkInstallationList {\n xSInstallations {\n installations {\n numinst\n alias\n panel\n type\n name\n surname\n address\n city\n postcode\n province\n email\n phone\n }\n }\n}\n",
        }
        response = await self._execute_request(content, "mkInstallationList")
        result: list[Installation] = []
        raw_installations = response["data"]["xSInstallations"]["installations"]
        for item in raw_installations:
            result.append(
                Installation(
                    item["numinst"],
                    item["alias"],
                    item["panel"],
                    item["type"],
                    item["name"],
                    item["surname"],
                    item["address"],
                    item["city"],
                    item["postcode"],
                    item["province"],
                    item["email"],
                    item["phone"],
                    "",
                    datetime.min,
                )
            )
        return result

    async def check_alarm(self, installation: Installation) -> str:
        """Check status of the alarm."""
        content = {
            "operationName": "CheckAlarm",
            "variables": {"numinst": installation.number, "panel": installation.panel},
            "query": "query CheckAlarm($numinst: String!, $panel: String!) {\n xSCheckAlarm(numinst: $numinst, panel: $panel) {\n res\n msg\n referenceId\n }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "CheckAlarm", installation)
        return response["data"]["xSCheckAlarm"]["referenceId"]

    async def get_all_services(self, installation: Installation) -> list[Service]:
        """Get the list of all services available to the user."""
        content = {
            "operationName": "Srv",
            "variables": {"numinst": installation.number, "uuid": self.uuid},
            "query": "query Srv($numinst: String!, $uuid: String) {\n xSSrv(numinst: $numinst, uuid: $uuid) {\n res\n msg\n language\n installation {\n numinst\n role\n alias\n status\n panel\n sim\n instIbs\n services {\n idService\n active\n visible\n bde\n isPremium\n codOper\n request\n minWrapperVersion\n unprotectActive\n unprotectDeviceStatus\n instDate\n genericConfig {\n total\n attributes {\n key\n value\n }\n }\n attributes {\n attributes {\n name\n value\n active\n }\n }\n }\n configRepoUser {\n alarmPartitions {\n id\n enterStates\n leaveStates\n }\n }\n capabilities\n }\n }\n}",
        }
        response = await self._execute_request(content, "Srv")
        raw_data = response["data"]["xSSrv"]["installation"]["services"]
        installation.capabilities = response["data"]["xSSrv"]["installation"][
            "capabilities"
        ]
        try:
            token = jwt.decode(
                installation.capabilities,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
            if "exp" in token:
                installation.capabilities_exp = datetime.fromtimestamp(token["exp"])
        except jwt.exceptions.DecodeError as err:
            raise SecuritasDirectError(
                f"Failed to decode capabilities token {installation.capabilities}"
            ) from err
        result: list[Service] = []
        for item in raw_data:
            attribute_list: list[Attribute] = []
            attributes = item.get("attributes")
            if attributes is not None:
                for attr in attributes["attributes"]:
                    attribute_list.append(
                        Attribute(attr["name"], attr["value"], bool(attr["active"]))
                    )
            result.append(
                Service(
                    int(item["idService"]),
                    int(item["idService"]),
                    bool(item["active"]),
                    bool(item["visible"]),
                    bool(item["bde"]),
                    bool(item["isPremium"]),
                    bool(item["codOper"]),
                    int(item.get("totalDevice", 0)),
                    item["request"],
                    False,
                    0,
                    # datetime.fromtimestamp(item['instDate']/1000),
                    False,
                    item["minWrapperVersion"],
                    item.get("description", ""),
                    attribute_list,
                    [],
                    [],
                    installation,
                )
            )
        return result

    async def get_sentinel_data(
        self, installation: Installation, service: Service
    ) -> Sentinel:
        """Get sentinel status."""
        # FIX: Evitar IndexError
        if not service.attributes or len(service.attributes) == 0:
            return Sentinel("Desconocido", "", 0, 0)
        content = {
            "operationName": "Sentinel",
            "variables": {"numinst": installation.number},
            "query": "query Sentinel($numinst: String!) {\n xSComfort(numinst: $numinst) {\n res\n devices {\n alias\n status {\n temperature\n humidity\n airQualityCode\n }\n zone\n }\n }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "Sentinel", installation)
        if "errors" in response:
            return Sentinel("", "", 0, 0)
        zone = service.attributes[0].value
        for device in response["data"]["xSComfort"]["devices"]:
            if device.get("zone") == zone:
                return Sentinel(
                    device["alias"],
                    "",
                    int(device["status"]["humidity"]),
                    int(device["status"]["temperature"]),
                )
        return Sentinel("", "", 0, 0)

    async def get_air_quality_data(
        self, installation: Installation, service: Service
    ) -> AirQuality:
        """Get air quality status."""
        # FIX: Evitar IndexError
        if not service.attributes or len(service.attributes) == 0:
            return AirQuality(0, "Sin datos")
        content = {
            "operationName": "AirQualityGraph",
            "variables": {
                "numinst": installation.number,
                "zone": str(service.attributes[0].value),
            },
            "query": "query AirQualityGraph($numinst: String!, $zone: String!) {\n xSAirQ(numinst: $numinst, zone: $zone) {\n res\n msg\n graphData {\n status {\n current\n currentMsg\n }\n }\n }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "AirQualityGraph")
        if "errors" in response:
            return AirQuality(0, "")
        raw = response["data"]["xSAirQ"]["graphData"]["status"]
        return AirQuality(int(raw["current"]), raw["currentMsg"])

    async def check_general_status(self, installation: Installation) -> SStatus:
        """Check current status of the alarm."""
        content = {
            "operationName": "Status",
            "variables": {"numinst": installation.number},
            "query": "query Status($numinst: String!) {\n xSStatus(numinst: $numinst) {\n status\n timestampUpdate\n }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "Status", installation)
        if "data" in response:
            raw = response["data"]["xSStatus"]
            return SStatus(raw["status"], raw["timestampUpdate"])
        return SStatus(None, None)

    async def check_alarm_status(
        self, installation: Installation, reference_id: str, timeout: int = 10
    ) -> CheckAlarmStatus:
        """Return the status of the alarm."""
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        count = 1
        raw_data: dict[str, Any] = {}
        max_count = timeout / max(1, self.delay_check_operation)
        while ((count == 1) or (raw_data.get("res") == "WAIT")) and (count <= max_count):
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_alarm_status_internal(
                installation, reference_id, count
            )
            count = count + 1
        self.protom_response = raw_data.get("protomResponse", "")
        return CheckAlarmStatus(
            raw_data.get("res"),
            raw_data.get("msg"),
            raw_data.get("status"),
            raw_data.get("numinst"),
            raw_data.get("protomResponse"),
            raw_data.get("protomResponseDate"),
        )

    async def _check_alarm_status_internal(
        self,
        installation: Installation,
        reference_id: str,
        count: int,
    ) -> dict[str, Any]:
        content = {
            "operationName": "CheckAlarmStatus",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
                "idService": "11",
                "counter": count,
            },
            "query": "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: String!, $referenceId: String!) {\n xSCheckAlarmStatus(\n numinst: $numinst\n idService: $idService\n panel: $panel\n referenceId: $referenceId\n ) {\n res\n msg\n status\n numinst\n protomResponse\n protomResponseDate\n }\n}\n",
        }
        response = await self._execute_request(content, "CheckAlarmStatus", installation)
        return response["data"]["xSCheckAlarmStatus"]

    async def arm_alarm(
        self,
        installation: Installation,
        mode: SecDirAlarmState,
        timeout: int = 30,
    ) -> ArmStatus:
        """Arms the alarm."""
        content = {
            "operationName": "xSArmPanel",
            "variables": {
                "request": self.command_map[mode],
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
            },
            "query": "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!, $panel: String!, $currentStatus: String) {\n xSArmPanel(\n numinst: $numinst\n request: $request\n panel: $panel\n currentStatus: $currentStatus\n ) {\n res\n msg\n referenceId\n }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "xSArmPanel", installation)
        res_data = response["data"]["xSArmPanel"]
        if res_data["res"] != "OK":
            raise SecuritasDirectError(res_data["msg"], res_data)
        ref_id = res_data["referenceId"]
        count = 1
        raw_data: dict[str, Any] = {}

        # Límite de intentos basado en timeout para evitar bucles infinitos
        max_count = max(1, int(timeout / max(1, self.delay_check_operation)))

        while ((count == 1) or (raw_data.get("res") == "WAIT")) and (count <= max_count):
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_arm_status_internal(
                installation, ref_id, mode, count
            )
            count = count + 1

        if raw_data.get("res") == "WAIT":
            raise SecuritasDirectError(
                f"Timeout waiting for arm status after {timeout} seconds",
                raw_data,
            )

        self.protom_response = raw_data.get("protomResponse", "")
        return ArmStatus(
            raw_data.get("res"),
            raw_data.get("msg"),
            raw_data.get("status"),
            raw_data.get("numinst"),
            raw_data.get("protomResponse"),
            raw_data.get("protomResponseDate"),
            raw_data.get("requestId"),
            raw_data.get("error"),
        )

    async def _check_arm_status_internal(
        self,
        installation: Installation,
        reference_id: str,
        mode: SecDirAlarmState,
        counter: int,
    ) -> dict[str, Any]:
        content = {
            "operationName": "ArmStatus",
            "variables": {
                "request": self.command_map[mode],
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": "query ArmStatus($numinst: String!, $request: ArmCodeRequest, $panel: String!, $referenceId: String!, $counter: Int!) {\n xSArmStatus(\n numinst: $numinst\n panel: $panel\n referenceId: $referenceId\n counter: $counter\n request: $request\n ) {\n res\n msg\n status\n protomResponse\n protomResponseDate\n numinst\n requestId\n error {\n code\n type\n allowForcing\n exceptionsNumber\n referenceId\n }\n }\n}\n",
        }
        response = await self._execute_request(content, "ArmStatus", installation)
        return response["data"]["xSArmStatus"]

    async def disarm_alarm(
        self,
        installation: Installation,
        timeout: int = 30,
    ) -> DisarmStatus:
        """Disarm the alarm."""
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": self.command_map[SecDirAlarmState.TOTAL_DISARMED],
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": "mutation xSDisarmPanel($numinst: String!, $request: DisarmCodeRequest!, $panel: String!) {\n xSDisarmPanel(numinst: $numinst, request: $request, panel: $panel) {\n res\n msg\n referenceId\n }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "xSDisarmPanel", installation)
        res_data = response["data"]["xSDisarmPanel"]
        if res_data.get("res") != "OK":
            raise SecuritasDirectError(res_data.get("msg"), res_data)
        ref_id = res_data["referenceId"]
        count = 1
        raw_data: dict[str, Any] = {}

        # Límite de intentos basado en timeout para evitar bucles infinitos
        max_count = max(1, int(timeout / max(1, self.delay_check_operation)))

        while ((count == 1) or raw_data.get("res") == "WAIT") and (count <= max_count):
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_disarm_status_internal(
                installation,
                ref_id,
                SecDirAlarmState.TOTAL_DISARMED,
                count,
            )
            count = count + 1

        if raw_data.get("res") == "WAIT":
            raise SecuritasDirectError(
                f"Timeout waiting for disarm status after {timeout} seconds",
                raw_data,
            )

        self.protom_response = raw_data.get("protomResponse", "")
        return DisarmStatus(
            raw_data.get("error"),
            raw_data.get("msg"),
            raw_data.get("numinst"),
            raw_data.get("protomResponse"),
            raw_data.get("protomResponseDate"),
            raw_data.get("requestId"),
            raw_data.get("res"),
            raw_data.get("status"),
        )

    async def _check_disarm_status_internal(
        self,
        installation: Installation,
        reference_id: str,
        arm_type: SecDirAlarmState,
        counter: int,
    ) -> dict[str, Any]:
        content = {
            "operationName": "DisarmStatus",
            "variables": {
                "request": self.command_map[arm_type],
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": "query DisarmStatus($numinst: String!, $panel: String!, $referenceId: String!, $counter: Int!, $request: DisarmCodeRequest) {\n xSDisarmStatus(\n numinst: $numinst\n panel: $panel\n referenceId: $referenceId\n counter: $counter\n request: $request\n ) {\n res\n msg\n status\n protomResponse\n protomResponseDate\n numinst\n requestId\n error {\n code\n type\n allowForcing\n exceptionsNumber\n referenceId\n }\n }\n}\n",
        }
        response = await self._execute_request(content, "DisarmStatus", installation)
        return response["data"]["xSDisarmStatus"]

    async def get_smart_lock_config(self, installation: Installation) -> SmartLock:
        """Get the smart lock configuration."""
        content = {
            "operationName": "xSGetSmartlockConfig",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "devices": [{"deviceType": "DR", "deviceId": "01", "keytype": "0"}],
            },
            "query": "query xSGetSmartlockConfig($numinst: String!, $panel: String!, $devices: [SmartlockDevicesInfo]!) {\n xSGetSmartlockConfig(numinst: $numinst, panel: $panel, devices: $devices) {\n res\n referenceId\n zoneId\n serialNumber\n location\n family\n type\n label\n features {\n holdBackLatchTime\n calibrationType\n autolock {\n active\n timeout\n }\n }\n }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(
            content, "xSGetSmartlockConfig", installation
        )
        if "data" in response:
            raw = response["data"]["xSGetSmartlockConfig"]
            return SmartLock(raw.get("res"), raw.get("location"), raw.get("type"))
        return SmartLock(None, None, None)

    async def get_lock_current_mode(
        self, installation: Installation
    ) -> SmartLockMode:
        """Get the current mode of the smart lock."""
        content = {
            "operationName": "xSGetLockCurrentMode",
            "variables": {"numinst": installation.number},
            "query": "query xSGetLockCurrentMode($numinst: String!, $counter: Int) {\n xSGetLockCurrentMode(numinst: $numinst, counter: $counter) {\n res\n smartlockInfo {\n lockStatus\n deviceId\n }\n }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(
            content, "xSGetLockCurrentMode", installation
        )
        if "data" in response:
            raw = response["data"]["xSGetLockCurrentMode"]
            return SmartLockMode(
                raw.get("res"),
                raw["smartlockInfo"][0]["lockStatus"]
                if raw.get("smartlockInfo")
                else "0",
            )
        return SmartLockMode(None, "0")

    async def change_lock_mode(
        self,
        installation: Installation,
        lock: bool,
        timeout: int = 30,
    ) -> SmartLockModeStatus:
        """Change the mode of the smart lock."""
        content = {
            "operationName": "xSChangeSmartlockMode",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": "DR",
                "deviceId": "01",
                "lock": lock,
            },
            "query": "mutation xSChangeSmartlockMode($numinst: String!, $panel: String!, $deviceId: String!, $deviceType: String!, $lock: Boolean!) {\n xSChangeSmartlockMode(\n numinst: $numinst\n panel: $panel\n deviceId: $deviceId\n deviceType: $deviceType\n lock: $lock\n ) {\n res\n msg\n referenceId\n }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(
            content, "xSChangeSmartlockMode", installation
        )
        res_data = response["data"]["xSChangeSmartlockMode"]
        if res_data.get("res") != "OK":
            raise SecuritasDirectError(res_data.get("msg"), res_data)
        reference_id = res_data["referenceId"]
        count = 1
        raw_data: dict[str, Any] = {}

        # Límite de intentos basado en timeout para evitar bucles infinitos
        max_count = max(1, int(timeout / max(1, self.delay_check_operation)))

        while ((count == 1) or raw_data.get("res") == "WAIT") and (count <= max_count):
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_change_lock_mode_internal(
                installation,
                reference_id,
                count,
            )
            count = count + 1

        if raw_data.get("res") == "WAIT":
            raise SecuritasDirectError(
                f"Timeout waiting for smart lock mode change after {timeout} seconds",
                raw_data,
            )

        await asyncio.sleep(self.delay_check_operation * 7)
        self.protom_response = raw_data.get("protomResponse", "")
        return SmartLockModeStatus(
            raw_data.get("res"),
            raw_data.get("msg"),
            raw_data.get("protomResponse"),
            raw_data.get("status"),
        )

    async def _check_change_lock_mode_internal(
        self,
        installation: Installation,
        reference_id: str,
        counter: int,
    ) -> dict[str, Any]:
        content = {
            "operationName": "xSChangeSmartlockModeStatus",
            "variables": {
                "counter": counter,
                "deviceId": "01",
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
            },
            "query": "query xSChangeSmartlockModeStatus($numinst: String!, $panel: String!, $referenceId: String!, $deviceId: String, $counter: Int) {\n xSChangeSmartlockModeStatus(\n numinst: $numinst\n panel: $panel\n referenceId: $referenceId\n counter: $counter\n deviceId: $deviceId\n ) {\n res\n msg\n protomResponse\n status\n }\n}",
        }
        response = await self._execute_request(
            content, "xSChangeSmartlockModeStatus", installation
        )
        return response["data"]["xSChangeSmartlockModeStatus"]