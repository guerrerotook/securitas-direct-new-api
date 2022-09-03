"""Securitas Direct API implementation."""
from datetime import datetime
import json
import logging
import secrets
from typing import Union
from uuid import uuid4

from aiohttp import ClientSession, ClientResponse

from .dataTypes import (
    AirQuality,
    ArmStatus,
    ArmType,
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

_LOGGER = logging.getLogger(__name__)


class ApiManager:
    """Securitas Direct API."""

    def __init__(
        self,
        username: str,
        password: str,
        country: str,
        language: str,
        http_client: ClientSession,
        device_id: str,
        uuid: str,
        id_device_indigitall: str,
    ) -> None:
        """Create the object."""
        self.username = username
        self.password = password
        self.country = country
        self.language = language
        self.api_url = ApiDomains().get_url(language=language)
        self.authentication_token: str = None
        self.authentication_otp_challenge: bool = False
        self.authentication_otp_challenge_value: tuple[str, int] = None
        self.http_client = http_client
        self.refresh_token_value: str = None
        # device specific configuration for the API
        self.device_id: str = device_id
        self.uuid: str = uuid
        self.id_device_indigitall: str = id_device_indigitall
        self.device_brand = "samsung"
        self.device_name = "SM-S901U"  # Samsung Galaxy S22
        self.device_os_version = "12"
        self.device_resolution = ""
        self.device_type = ""
        self.device_version = "10.61.0"
        self.apollo_operation_id: str = secrets.token_hex(64)

    async def _execute_request(self, content, operation: str) -> ClientResponse:

        app: str = json.dumps({"appVersion": self.device_version, "origin": "native"})
        headers = {
            "app": app,
            "User-Agent": "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.5005.124 Safari/537.36 Edg/102.0.1245.41",
            "X-APOLLO-OPERATION-ID": self.apollo_operation_id,
            "X-APOLLO-OPERATION-NAME": operation,
            "extension": '{"mode":"full"}',
        }

        if self.authentication_token is not None:
            authorization_value = {
                "user": self.username,
                "id": self._generate_id(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWA_10",
                "hash": self.authentication_token,
            }
            headers["auth"] = json.dumps(authorization_value)

        if self.authentication_otp_challenge:
            authorization_value = {
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
            "Making request with device_id "
            + self.device_id
            + ", uuid "
            + self.uuid
            + " and idDeviceIndigitall "
            + self.id_device_indigitall
        )
        _LOGGER.debug("--------------Content---------------")
        _LOGGER.debug(content)
        _LOGGER.debug("--------------Headers---------------")
        _LOGGER.debug(headers)
        async with self.http_client.post(
            self.api_url, headers=headers, json=content
        ) as response:
            ClientResponse
            response_text: str = await response.text()
            _LOGGER.debug("--------------Response--------------")
        _LOGGER.debug(response_text)
        error_login: bool = await self._check_errros(response_text)
        if error_login:
            return await self._execute_request(content, operation)

        return response

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

    async def _check_errros(self, value: str) -> bool:
        if value is not None:
            response = json.loads(value)
            if "errors" in response:
                for error_item in response["errors"]:
                    if "message" in error_item:
                        if error_item["message"] == "Invalid token: Expired":
                            self.authentication_token = None
                            _LOGGER.info("Login is expired. Login again")
                            succeed: tuple[bool, str] = await self.login()
                            _LOGGER.debug("Re-loging result " + str(succeed[0]))
                            return succeed[0]
                        else:
                            _LOGGER.error(error_item["message"])
        return False

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
    ) -> Union[tuple[str, list[OtpPhone]], bool]:
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

        self.authentication_otp_challenge = True
        if otp_succeed:
            self.authentication_otp_challenge_value = (auth_otp_hash, sms_code)
        response: ClientResponse = await self._execute_request(
            content, "mkValidateDevice"
        )
        result_json = json.loads(await response.text())
        self.authentication_otp_challenge = False
        self.authentication_otp_challenge_value = None
        if "errors" in result_json:
            data = result_json["errors"][0]["data"]
            otp_hash = data["auth-otp-hash"]
            phones: list[OtpPhone] = []
            for item in data["auth-phones"]:
                phones.append(OtpPhone(item["id"], item["phone"]))
            return (otp_hash, phones)
        else:
            # self.refresh_token_value = result_json["data"]["xSValidateDevice"][
            #     "refreshToken"
            # ]
            self.authentication_token = result_json["data"]["xSValidateDevice"]["hash"]
            return True

    async def refresh_token(self) -> bool:
        """Send the OTP device challange."""
        content = {
            "operationName": "RefreshLogin",
            "variables": {
                "refreshToken": self.refresh_token_value,
                "id": uuid4(),
                "country": self.country,
                "lang": self.language,
                "callby": "OWA_10",
            },
            "query": "mutation RefreshLogin($refreshToken: String!, $id: String!, $country: String!, $lang: String!, $callby: String!, $idDevice: String!, $idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: String!, $deviceOsVersion: String!, $uuid: String!) {\n  xSRefreshLogin(refreshToken: $refreshToken, id: $id, country: $country, lang: $lang, callby: $callby, idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, deviceType: $deviceType, deviceVersion: $deviceVersion, deviceResolution: $deviceResolution, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, uuid: $uuid) {\n    __typename\n    res\n    msg\n    hash\n    refreshToken\n    legals\n    changePassword\n    needDeviceAuthorization\n    mainUser\n  }\n}",
        }
        self.authentication_otp_challenge = True
        response: ClientResponse = await self._execute_request(content, "RefreshLogin")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return []
        self.authentication_otp_challenge = False
        return result_json["data"]["xSSendOtp"]["res"]

    async def send_otp(self, device_id: int, auth_otp_hash: str) -> bool:
        """Send the OTP device challange."""
        content = {
            "operationName": "mkSendOTP",
            "variables": {
                "recordId": device_id,
                "otpHash": auth_otp_hash,
            },
            "query": "mutation mkSendOTP($recordId: Int!, $otpHash: String!) {\n  xSSendOtp(recordId: $recordId, otpHash: $otpHash) {\n    res\n    msg\n  }\n}\n",
        }
        self.authentication_otp_challenge = True
        response: ClientResponse = await self._execute_request(content, "mkSendOTP")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return []
        self.authentication_otp_challenge = False
        return result_json["data"]["xSSendOtp"]["res"]

    async def login(self) -> tuple[bool, str]:
        """Login."""
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
        response: ClientResponse = await self._execute_request(content, "mkLoginToken")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return (False, error_message)

        if result_json["data"]["xSLoginToken"]["needDeviceAuthorization"]:
            return (False, "2FA")

        self.authentication_token = result_json["data"]["xSLoginToken"]["hash"]
        return (True, "None")

    async def list_installations(self) -> list[Installation]:
        """list securitas direct installations."""
        content = {
            "operationName": "mkInstallationList",
            "query": "query mkInstallationList {\n  xSInstallations {\n    installations {\n      numinst\n      alias\n      panel\n      type\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n    }\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(
            content, "mkInstallationList"
        )
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            print(error_message)
            return []

        result: list[Installation] = []
        raw_installations = result_json["data"]["xSInstallations"]["installations"]
        for item in raw_installations:
            installation_item: Installation = Installation(
                int(item["numinst"]),
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
            )
            result.append(installation_item)
        return result

    async def check_alarm(self, installation: Installation) -> str:
        """Check status of the alarm."""
        content = {
            "operationName": "CheckAlarm",
            "variables": {
                "numinst": str(installation.number),
                "panel": installation.panel,
            },
            "query": "query CheckAlarm($numinst: String!, $panel: String!) {\n  xSCheckAlarm(numinst: $numinst, panel: $panel) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "CheckAlarm")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        return result_json["data"]["xSCheckAlarm"]["referenceId"]

    async def get_all_services(self, installation: Installation) -> list[Service]:
        """Get the list of all services available to the user."""
        content = {
            "operationName": "Srv",
            "variables": {"numinst": str(installation.number)},
            "query": "query Srv($numinst: String!, $uuid: String) {\n  xSSrv(numinst: $numinst, uuid: $uuid) {\n    res\n    msg\n    language\n    installation {\n      id\n      alarm\n      due\n      tracker\n      numinst\n      parentNuminst\n      alias\n      panel\n      line\n      aliasInst\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n      sim\n      instIbs\n      timebox\n      dtmf\n      oper\n      services {\n        id\n        idService\n        active\n        visible\n        bde\n        isPremium\n        codOper\n        totalDevice\n        request\n        multipleReq\n        numDevicesMr\n        secretWord\n        minWrapperVersion\n        description\n        loc\n        unprotectActive\n        unprotectDeviceStatus\n        devices {\n          id\n          code\n          numDevices\n          cost\n          type\n          name\n        }\n        camerasArlo {\n          id\n          model\n          connectedToInstallation\n          usedForAlarmVerification\n          offer\n          name\n          locationHint\n          batteryLevel\n          connectivity\n          createdDate\n          modifiedDate\n          latestThumbnailUri\n        }\n        attributes {\n          name\n          attributes {\n            name\n            value\n            active\n          }\n        }\n        listdiy {\n          type\n          idMant\n          state\n          idZone\n          canBeResent\n          guide\n          tutorial\n          name\n          alias\n          intime\n          steps {\n            pos\n            img\n            advice\n            text\n          }\n        }\n        listprompt {\n          idNot\n          text\n          type\n        }\n      }\n      configRepoUser {\n        hasCode\n        pinCodeConf {\n          pinCodeLength\n        }\n        alarmPartitions {\n          id\n          enterStates\n          leaveStates\n        }\n      }\n    }\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "Srv")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        result: list[Service] = []
        raw_data = result_json["data"]["xSSrv"]["installation"]["services"]
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
                    item["loc"],
                    bool(item["unprotectActive"]),
                    item["unprotectDeviceStatus"],
                    [],
                    [],
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
                "numinst": str(installation.number),
                "zone": str(service.attributes.attributes[0].value),
            },
            "query": "query Sentinel($numinst: String!, $zone: String!) {\n  xSAllConfort(numinst: $numinst, zone: $zone) {\n    res\n    msg\n    ddi {\n      zone\n      alias\n      zonePrevious\n      aliasPrevious\n      zoneNext\n      aliasNext\n      moreDdis\n      status {\n        airQuality\n        airQualityMsg\n        humidity\n        temperature\n      }\n      forecast {\n        city\n        currentTemp\n        currentHum\n        description\n        forecastImg\n        day1 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day2 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day3 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day4 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n        day5 {\n          forecastImg\n          maxTemp\n          minTemp\n          value\n        }\n      }\n    }\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "Sentinel")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        raw_data = result_json["data"]["xSAllConfort"][0]["ddi"]["status"]
        return Sentinel(
            result_json["data"]["xSAllConfort"][0]["ddi"]["alias"],
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
                "numinst": str(installation.number),
                "zone": str(service.attributes.attributes[0].value),
            },
            "query": "query AirQualityGraph($numinst: String!, $zone: String!) {\n  xSAirQ(numinst: $numinst, zone: $zone) {\n    res\n    msg\n    graphData {\n      status {\n        avg6h\n        avg6hMsg\n        avg24h\n        avg24hMsg\n        avg7d\n        avg7dMsg\n        avg4w\n        avg4wMsg\n        current\n        currentMsg\n      }\n      daysTotal\n      days {\n        id\n        value\n      }\n      hoursTotal\n      hours {\n        id\n        value\n      }\n      weeksTotal\n      weeks {\n        id\n        value\n      }\n    }\n  }\n}",
        }
        response: ClientResponse = await self._execute_request(
            content, "AirQualityGraph"
        )
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        raw_data = result_json["data"]["xSAirQ"]["graphData"]["status"]
        return AirQuality(
            int(raw_data["current"]),
            raw_data["currentMsg"],
        )

    async def check_general_status(self, installation: Installation) -> SStatus:
        """Check current status of the alarm."""
        content = {
            "operationName": "Status",
            "variables": {"numinst": str(installation.number)},
            "query": "query Status($numinst: String!) {\n  xSStatus(numinst: $numinst) {\n    status\n    timestampUpdate\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "Status")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        raw_data = result_json["data"]["xSStatus"]
        return SStatus(raw_data["status"], raw_data["timestampUpdate"])

    async def check_alarm_status(
        self, installation: Installation, reference_id: str, count: int
    ) -> CheckAlarmStatus:
        """Check status of the operation check alarm."""
        content = {
            "operationName": "CheckAlarmStatus",
            "variables": {
                "numinst": str(installation.number),
                "panel": installation.panel,
                "referenceId": reference_id,
                "idService": "11",
                "counter": count,
            },
            "query": "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: String!, $referenceId: String!) {\n  xSCheckAlarmStatus(numinst: $numinst, idService: $idService, panel: $panel, referenceId: $referenceId) {\n    res\n    msg\n    status\n    numinst\n    protomResponse\n    protomResponseDate\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(
            content, "CheckAlarmStatus"
        )
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        raw_data = result_json["data"]["xSCheckAlarmStatus"]
        return CheckAlarmStatus(
            raw_data["res"],
            raw_data["msg"],
            raw_data["status"],
            raw_data["numinst"],
            raw_data["protomResponse"],
            raw_data["protomResponseDate"],
        )

    async def arm_alarm(
        self, installation: Installation, mode: str, current_status: str
    ) -> tuple[bool, str]:
        """Arms the alarm in the specified mode."""
        content = {
            "operationName": "xSArmPanel",
            "variables": {
                "request": mode,
                "numinst": str(installation.number),
                "panel": installation.panel,
                "currentStatus": current_status,
            },
            "query": "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!, $panel: String!, $pin: String, $currentStatus: String) {\n  xSArmPanel(numinst: $numinst, request: $request, panel: $panel, pin: $pin, currentStatus: $currentStatus) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "xSArmPanel")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        if result_json["data"]["xSArmPanel"]["res"] == "OK":
            return (True, result_json["data"]["xSArmPanel"]["referenceId"])
        else:
            return (False, result_json["data"]["xSArmPanel"]["msg"])

    async def check_arm_status(
        self,
        installation: Installation,
        reference_id: str,
        mode: str,
        counter: int,
        current_status: str,
    ) -> ArmStatus:
        """Check progress of the alarm."""
        content = {
            "operationName": "ArmStatus",
            "variables": {
                "request": mode,
                "numinst": str(installation.number),
                "panel": installation.panel,
                "currentStatus": current_status,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": "query ArmStatus($numinst: String!, $request: ArmCodeRequest, $panel: String!, $referenceId: String!, $counter: Int!) {\n  xSArmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "ArmStatus")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        raw_data = result_json["data"]["xSArmStatus"]
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

    async def disarm_alarm(
        self, installation: Installation, current_status: str
    ) -> tuple[bool, str]:
        """Disarm the alarm."""
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": "DARM1",
                "numinst": str(installation.number),
                "panel": installation.panel,
                "currentStatus": current_status,
            },
            "query": "mutation xSDisarmPanel($numinst: String!, $request: DisarmCodeRequest!, $panel: String!, $pin: String) {\n  xSDisarmPanel(numinst: $numinst, request: $request, panel: $panel, pin: $pin) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "xSDisarmPanel")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        if result_json["data"]["xSDisarmPanel"]["res"] == "OK":
            return (True, result_json["data"]["xSDisarmPanel"]["referenceId"])
        else:
            return (False, result_json["data"]["xSDisarmPanel"]["msg"])

    async def check_disarm_status(
        self,
        installation: Installation,
        reference_id: str,
        arm_type: ArmType,
        counter: int,
        current_status: str,
    ) -> DisarmStatus:
        """Check progress of the alarm."""
        content = {
            "operationName": "DisarmStatus",
            "variables": {
                "request": "DARM" + str(arm_type.value),
                "numinst": str(installation.number),
                "panel": installation.panel,
                "currentStatus": current_status,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": "query DisarmStatus($numinst: String!, $panel: String!, $referenceId: String!, $counter: Int!, $request: DisarmCodeRequest) {\n  xSDisarmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response: ClientResponse = await self._execute_request(content, "DisarmStatus")
        result_json = json.loads(await response.text())
        if "errors" in result_json:
            error_message = result_json["errors"][0]["message"]
            return error_message

        raw_data = result_json["data"]["xSDisarmStatus"]
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
