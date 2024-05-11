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
    """Securitas Direct API."""

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
        self.http_client = http_client
        self.refresh_token_value: str = ""

        # device specific configuration for the API
        self.device_id: str = device_id
        self.uuid: str = uuid
        self.id_device_indigitall: str = id_device_indigitall
        self.device_brand = "samsung"
        self.device_name = "SM-S901U"  # Samsung Galaxy S22
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
        # _LOGGER.debug("--------------Content---------------")
        # _LOGGER.debug(content)
        # _LOGGER.debug("--------------Headers---------------")
        # _LOGGER.debug(headers)
        try:
            async with self.http_client.post(
                self.api_url, headers=headers, json=content
            ) as response:
                response_text: str = await response.text()
        except ClientConnectorError as err:
            raise SecuritasDirectError(
                f"Connection error with URL {self.api_url}", None, headers, content
            ) from err

        _LOGGER.debug("--------------Response--------------")
        _LOGGER.debug(response_text)

        try:
            # error_login: bool = await self._check_errros(response_text)
            # if error_login:
            # response_text: str = await self._execute_request(
            #     content, operation, installation
            # )
            response_dict = json.loads(response_text)
        except json.JSONDecodeError as err:
            _LOGGER.error("Problems decoding response %s", response_text)
            raise SecuritasDirectError(err.msg, None, headers, content) from err

        if "errors" in response_dict:
            raise SecuritasDirectError(
                response_dict["errors"][0]["message"], response_dict, headers, content
            )

        return response_dict

    async def _check_errros(self, value: str) -> bool:
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

    async def _check_capabilities_token(self, installation: Installation) -> None:
        """Check the capabilities token and get a new one if needed."""

        _LOGGER.debug(
            "Capabilities token expires %s and now is %s",
            self.authentication_token_exp,
            datetime.now(),
        )

        if (installation.capabilities == "") or (
            datetime.now() + timedelta(minutes=1) > installation.capabilities_exp
        ):
            _LOGGER.debug("Expired capabilities token, getting a new one")
            await self.get_all_services(installation)

    async def _check_authentication_token(self) -> None:
        """Check expiration of the authentication token and get a new one if needed."""

        _LOGGER.debug(
            "Authentication token expires %s and now is %s",
            self.authentication_token_exp,
            datetime.now(),
        )

        if (self.authentication_token is None) or (
            datetime.now() + timedelta(minutes=1) > self.authentication_token_exp
        ):
            _LOGGER.debug("Authentication token expired, logging in again")
            await self.login()

    def _generate_id(self) -> str:
        current: datetime = datetime.now()
        return (
            "OWA_______________"
            + self.username
            + "_______________"
            + str(current.year)
            + str(current.month)
            + str(current.day)
            + str(current.hour)
            + str(current.minute)
            + str(current.microsecond)
        )

    async def logout(self):
        """Logout."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        await self._execute_request(content, "Logout")

    async def validate_device(
        self, otp_succeed: bool, auth_otp_hash: str, sms_code: str
    ) -> tuple[str, list[OtpPhone]]:
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
            "query": "mutation mkValidateDevice($idDevice: String, $idDeviceIndigitall: String, $uuid: String, $deviceName: String, $deviceBrand: String, $deviceOsVersion: String, $deviceVersion: String) {\n  xSValidateDevice(idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, uuid: $uuid, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, deviceVersion: $deviceVersion) {\n    res\n    msg\n    hash\n    refreshToken\n    legals\n  }\n}\n",
        }

        if otp_succeed:
            self.authentication_otp_challenge_value = (auth_otp_hash, sms_code)
        response = {}
        try:
            response = await self._execute_request(content, "mkValidateDevice")
            self.authentication_otp_challenge_value = None
        except SecuritasDirectError as err:
            # the API call fails but we want the phone data in the response
            data = err.args[1]["errors"][0]["data"]
            otp_hash = data["auth-otp-hash"]
            phones: list[OtpPhone] = []
            for item in data["auth-phones"]:
                phones.append(OtpPhone(item["id"], item["phone"]))
            return (otp_hash, phones)

        self.authentication_token = response["data"]["xSValidateDevice"]["hash"]
        return (None, None)

    async def refresh_token(self) -> bool:
        """Send a login refresh."""
        content = {
            "operationName": "RefreshLogin",
            "variables": {
                "refreshToken": self.refresh_token_value,
                "uuid": self.uuid,  # uuid4(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWA_10",
            },
            "query": "mutation RefreshLogin($refreshToken: String!, $id: String!, $country: String!, $lang: String!, $callby: String!, $idDevice: String!, $idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: String!, $deviceOsVersion: String!, $uuid: String!) {\n  xSRefreshLogin(refreshToken: $refreshToken, id: $id, country: $country, lang: $lang, callby: $callby, idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, deviceType: $deviceType, deviceVersion: $deviceVersion, deviceResolution: $deviceResolution, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, uuid: $uuid) {\n    __typename\n    res\n    msg\n    hash\n    refreshToken\n    legals\n    changePassword\n    needDeviceAuthorization\n    mainUser\n  }\n}",
        }
        response = await self._execute_request(content, "RefreshLogin")

        return response["data"]["xSSendOtp"]["res"]

    async def send_otp(self, device_id: int, auth_otp_hash: str) -> bool:
        """Send the OTP device challenge."""
        content = {
            "operationName": "mkSendOTP",
            "variables": {
                "recordId": device_id,
                "otpHash": auth_otp_hash,
            },
            "query": "mutation mkSendOTP($recordId: Int!, $otpHash: String!) {\n  xSSendOtp(recordId: $recordId, otpHash: $otpHash) {\n    res\n    msg\n  }\n}\n",
        }
        response = await self._execute_request(content, "mkSendOTP")

        return response["data"]["xSSendOtp"]["res"]

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

        response = {}
        try:
            response = await self._execute_request(content, "mkLoginToken")
        except SecuritasDirectError as err:
            result_json = err.args[1]
            if result_json["data"]:
                if result_json["data"]["xSLoginToken"]:
                    if result_json["data"]["xSLoginToken"]["needDeviceAuthorization"]:
                        # needs a 2FA
                        raise Login2FAError(err.args) from err

            raise LoginError(err.args) from err

        self.authentication_token = response["data"]["xSLoginToken"]["hash"]
        self.login_timestamp = int(datetime.now().timestamp() * 1000)

        try:
            token = jwt.decode(
                self.authentication_token,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
        except jwt.exceptions.DecodeError as err:
            raise SecuritasDirectError(
                f"Failed to decode authentication token {self.authentication_token}"
            ) from err

        if "exp" in token:
            self.authentication_token_exp = datetime.fromtimestamp(token["exp"])

    async def list_installations(self) -> list[Installation]:
        """List securitas direct installations."""
        content = {
            "operationName": "mkInstallationList",
            "query": "query mkInstallationList {\n  xSInstallations {\n    installations {\n      numinst\n      alias\n      panel\n      type\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n    }\n  }\n}\n",
        }
        response = await self._execute_request(content, "mkInstallationList")

        result: list[Installation] = []
        raw_installations = response["data"]["xSInstallations"]["installations"]
        for item in raw_installations:
            installation_item: Installation = Installation(
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
            result.append(installation_item)
        return result

    async def check_alarm(self, installation: Installation) -> str:
        """Check status of the alarm."""
        content = {
            "operationName": "CheckAlarm",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": "query CheckAlarm($numinst: String!, $panel: String!) {\n  xSCheckAlarm(numinst: $numinst, panel: $panel) {\n    res\n    msg\n    referenceId\n  }\n}\n",
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
            "query": "query Srv($numinst: String!, $uuid: String) {\n  xSSrv(numinst: $numinst, uuid: $uuid) {\n    res\n    msg\n    language\n    installation {\n      id\n      numinst\n      alias\n      status\n      panel\n      sim\n      instIbs\n      services {\n        id\n        idService\n        active\n        visible\n        bde\n        isPremium\n        codOper\n        totalDevice\n        request\n        multipleReq\n        numDevicesMr\n        secretWord\n        minWrapperVersion\n        description\n        unprotectActive\n        unprotectDeviceStatus\n        instDate\n        genericConfig {\n          total\n          attributes {\n            key\n            value\n          }\n        }\n        devices {\n          id\n          code\n          numDevices\n          cost\n          type\n          name\n        }\n        camerasArlo {\n          id\n          model\n          connectedToInstallation\n          usedForAlarmVerification\n          offer\n          name\n          locationHint\n          batteryLevel\n          connectivity\n          createdDate\n          modifiedDate\n          latestThumbnailUri\n        }\n        attributes {\n          name\n          attributes {\n            name\n            value\n            active\n          }\n        }\n        listdiy {\n          idMant\n          state\n        }\n        listprompt {\n          idNot\n          text\n          type\n          customParam\n          alias\n        }\n      }\n      configRepoUser {\n        alarmPartitions {\n          id\n          enterStates\n          leaveStates\n        }\n      }\n      capabilities\n    }\n  }\n}",
        }
        response = await self._execute_request(content, "Srv")

        result: list[Service] = []
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
        except jwt.exceptions.DecodeError as err:
            raise SecuritasDirectError(
                f"Failed to decode capabilities token {installation.capabilities}"
            ) from err

        if "exp" in token:
            installation.capabilities_exp = datetime.fromtimestamp(token["exp"])

        # json_services = json.dumps(raw_data)
        # result = json.loads(json_services)
        for item in raw_data:
            root_attributes: Attributes = Attributes("", [])
            if item["attributes"] is not None and "name" in item["attributes"]:
                attribute_list: list[Attribute] = []
                for attribute_item in item["attributes"]["attributes"]:
                    attribute_list.append(
                        Attribute(
                            attribute_item["name"],
                            attribute_item["value"],
                            bool(attribute_item["active"]),
                        )
                    )
                root_attributes = Attributes(item["attributes"]["name"], attribute_list)
            result.append(
                Service(
                    int(item["id"]),
                    int(item["idService"]),
                    bool(item["active"]),
                    bool(item["visible"]),
                    bool(item["bde"]),
                    bool(item["isPremium"]),
                    bool(item["codOper"]),
                    int(item["totalDevice"]),
                    item["request"],
                    bool(item["multipleReq"]),
                    int(item["numDevicesMr"]),
                    bool(item["secretWord"]),
                    item["minWrapperVersion"],
                    item["description"],
                    root_attributes,
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
        content = {
            "operationName": "Sentinel",
            "variables": {
                "numinst": installation.number,
                "zone": str(service.attributes.attributes[0].value),
            },
            "query": "query Sentinel($numinst: String!, $zone: String!) {\n  xSAllConfort(numinst: $numinst, zone: $zone) {\n    res\n    msg\n    ddi {\n      zone\n      alias\n      zonePrevious\n      aliasPrevious\n      zoneNext\n      aliasNext\n      moreDdis\n      status {\n        airQuality\n        airQualityMsg\n        humidity\n        temperature\n      }\n      forecast {\n        city\n        currentTemp\n        currentHum\n        description\n        forecastImg\n        day1 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day2 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day3 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day4 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day5 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n      }\n    }\n  }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "Sentinel")

        raw_data = response["data"]["xSAllConfort"][0]["ddi"]["status"]
        return Sentinel(
            response["data"]["xSAllConfort"][0]["ddi"]["alias"],
            raw_data["airQualityMsg"],
            int(raw_data["humidity"]),
            int(raw_data["temperature"]),
        )

    async def get_air_quality_data(
        self, installation: Installation, service: Service
    ) -> AirQuality:
        """Get sentinel status."""
        content = {
            "operationName": "AirQualityGraph",
            "variables": {
                "numinst": installation.number,
                "zone": str(service.attributes.attributes[0].value),
            },
            "query": "query AirQualityGraph($numinst: String!, $zone: String!) {\n  xSAirQ(numinst: $numinst, zone: $zone) {\n    res\n    msg\n    graphData {\n      status {\n        avg6h\n        avg6hMsg\n        avg24h\n        avg24hMsg\n        avg7d\n        avg7dMsg\n        avg4w\n        avg4wMsg\n        current\n        currentMsg\n      }\n      daysTotal\n      days {\n        id\n        value\n      }\n      hoursTotal\n      hours {\n        id\n        value\n      }\n      weeksTotal\n      weeks {\n        id\n        value\n      }\n    }\n  }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "AirQualityGraph")

        raw_data = response["data"]["xSAirQ"]["graphData"]["status"]
        return AirQuality(
            int(raw_data["current"]),
            raw_data["currentMsg"],
        )

    async def check_general_status(self, installation: Installation) -> SStatus:
        """Check current status of the alarm."""
        content = {
            "operationName": "Status",
            "variables": {"numinst": installation.number},
            "query": "query Status($numinst: String!) {\n  xSStatus(numinst: $numinst) {\n    status\n    timestampUpdate\n    exceptions {\n      status\n      deviceType\n      alias\n    }\n  }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "Status", installation)

        raw_data = response["data"]["xSStatus"]
        return SStatus(raw_data["status"], raw_data["timestampUpdate"])

    async def check_alarm_status(
        self, installation: Installation, reference_id: str, timeout: int = 10
    ) -> CheckAlarmStatus:
        """Return the status of the alarm."""
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        count = 1
        raw_data: dict[str, Any] = {}
        max_count = timeout / max(1, self.delay_check_operation)

        while ((count == 1) or (raw_data.get("res") == "WAIT")) and (
            count <= max_count
        ):
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_alarm_status(installation, reference_id, count)
            count += 1

        self.protom_response = raw_data["protomResponse"]
        return CheckAlarmStatus(
            raw_data["res"],
            raw_data["msg"],
            raw_data["status"],
            raw_data["numinst"],
            raw_data["protomResponse"],
            raw_data["protomResponseDate"],
        )

    async def _check_alarm_status(
        self, installation: Installation, reference_id: str, count: int
    ) -> dict[str, Any]:
        """Check status of the operation check alarm."""
        content = {
            "operationName": "CheckAlarmStatus",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
                "idService": "11",
                "counter": count,
            },
            "query": "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: String!, $referenceId: String!) {\n  xSCheckAlarmStatus(numinst: $numinst, idService: $idService, panel: $panel, referenceId: $referenceId) {\n    res\n    msg\n    status\n    numinst\n    protomResponse\n    protomResponseDate\n  }\n}\n",
        }
        response = await self._execute_request(
            content, "CheckAlarmStatus", installation
        )

        return response["data"]["xSCheckAlarmStatus"]

    async def arm_alarm(
        self, installation: Installation, mode: SecDirAlarmState
    ) -> ArmStatus:
        """Arms the alarm in the specified mode."""
        content = {
            "operationName": "xSArmPanel",
            "variables": {
                "request": self.command_map[mode],
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
            },
            "query": "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!, $panel: String!, $currentStatus: String) {\n  xSArmPanel(numinst: $numinst, request: $request, panel: $panel, currentStatus: $currentStatus) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "xSArmPanel", installation)
        response = response["data"]["xSArmPanel"]
        if response["res"] != "OK":
            raise SecuritasDirectError(response["msg"], response)

        reference_id = response["referenceId"]

        count = 1
        raw_data: dict[str, Any] = {}
        while (count == 1) or (raw_data.get("res") == "WAIT"):
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_arm_status(
                installation, reference_id, mode, count
            )
            count += 1

        self.protom_response = raw_data["protomResponse"]
        return ArmStatus(
            raw_data["res"],
            raw_data["msg"],
            raw_data["status"],
            raw_data["numinst"],
            raw_data["protomResponse"],
            raw_data["protomResponseDate"],
            raw_data["requestId"],
            raw_data["error"],
        )

    async def _check_arm_status(
        self,
        installation: Installation,
        reference_id: str,
        mode: SecDirAlarmState,
        counter: int,
    ) -> dict[str, Any]:
        """Check progress of the alarm."""
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
            "query": "query ArmStatus($numinst: String!, $request: ArmCodeRequest, $panel: String!, $referenceId: String!, $counter: Int!) {\n  xSArmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response = await self._execute_request(content, "ArmStatus", installation)

        raw_data = response["data"]["xSArmStatus"]
        return raw_data

    async def disarm_alarm(self, installation: Installation) -> DisarmStatus:
        """Disarm the alarm."""
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": self.command_map[SecDirAlarmState.TOTAL_DISARMED],
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
            },
            "query": "mutation xSDisarmPanel($numinst: String!, $request: DisarmCodeRequest!, $panel: String!) {\n  xSDisarmPanel(numinst: $numinst, request: $request, panel: $panel) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "xSDisarmPanel", installation)
        response = response["data"]["xSDisarmPanel"]
        if response["res"] != "OK":
            raise SecuritasDirectError(response["msg"], response)

        reference_id = response["referenceId"]

        count = 1
        raw_data: dict[str, Any] = {}
        while (count == 1) or raw_data.get("res") == "WAIT":
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_disarm_status(
                installation,
                reference_id,
                SecDirAlarmState.TOTAL_DISARMED,
                count,
            )
            count = count + 1

        self.protom_response = raw_data["protomResponse"]
        return DisarmStatus(
            raw_data["error"],
            raw_data["msg"],
            raw_data["numinst"],
            raw_data["protomResponse"],
            raw_data["protomResponseDate"],
            raw_data["requestId"],
            raw_data["res"],
            raw_data["status"],
        )

    async def _check_disarm_status(
        self,
        installation: Installation,
        reference_id: str,
        arm_type: SecDirAlarmState,
        counter: int,
    ) -> dict[str, Any]:
        """Check progress of the alarm."""
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
            "query": "query DisarmStatus($numinst: String!, $panel: String!, $referenceId: String!, $counter: Int!, $request: DisarmCodeRequest) {\n  xSDisarmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response = await self._execute_request(content, "DisarmStatus", installation)

        return response["data"]["xSDisarmStatus"]
