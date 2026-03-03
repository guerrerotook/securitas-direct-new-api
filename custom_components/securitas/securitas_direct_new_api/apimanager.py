"""Securitas Direct API implementation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from custom_components.securitas.log_filter import SensitiveDataFilter
from uuid import uuid4

from aiohttp import ClientConnectorError, ClientSession
import jwt

from .dataTypes import (
    AirQuality,
    ArmStatus,
    Attribute,
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
from .exceptions import (
    ArmingExceptionError,
    Login2FAError,
    LoginError,
    SecuritasDirectError,
)

_LOGGER = logging.getLogger(__name__)

# API protocol constants
API_CALLBY = "OWA_10"
API_ID_PREFIX = "OWA_______________"

# Smart-lock device identifiers expected by the Securitas API
SMARTLOCK_DEVICE_TYPE = "DR"
SMARTLOCK_DEVICE_ID = "01"
SMARTLOCK_KEY_TYPE = "0"

# Service ID used when polling CheckAlarmStatus
ALARM_STATUS_SERVICE_ID = "11"

# Default timeout (seconds) for check_alarm_status polling loop
CHECK_ALARM_STATUS_TIMEOUT = 10

# Extra settle delay after a lock-mode change completes (multiples of delay_check_operation)
LOCK_MODE_SETTLE_MULTIPLIER = 7


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
        delay_check_operation: int = 2,
        log_filter: SensitiveDataFilter | None = None,
    ) -> None:
        """Create the object."""
        self.username = username
        self.password = password
        domains = ApiDomains()
        self.country = country.upper()
        self.language = domains.get_language(country)
        self.api_url = domains.get_url(country)
        self.delay_check_operation: int = delay_check_operation

        self.protom_response: str = ""
        self.authentication_token: str | None = ""
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
        self._log_filter = log_filter

    def _register_secret(self, key: str, value: str | None) -> None:
        """Register a secret with the log filter if available."""
        if self._log_filter and value:
            self._log_filter.update_secret(key, value)

    def _register_installation(self, installation: Installation) -> None:
        """Register an installation number with the log filter."""
        if self._log_filter and installation.number:
            self._log_filter.add_installation(installation.number)

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
                "callby": API_CALLBY,
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
                "callby": API_CALLBY,
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
                http_status: int = response.status
                response_text: str = await response.text()
        except ClientConnectorError as err:
            raise SecuritasDirectError(
                f"Connection error with URL {self.api_url}", None, headers, content
            ) from err

        _LOGGER.debug("--------------Response--------------")
        _LOGGER.debug(response_text)

        if http_status >= 400:
            _LOGGER.debug(
                "HTTP %d from Securitas API for operation '%s': %s",
                http_status,
                operation,
                response_text[:500],
            )
            raise SecuritasDirectError(
                f"HTTP {http_status} from Securitas API ({operation})",
                None,
                headers,
                content,
            )

        try:
            response_dict = json.loads(response_text)
        except json.JSONDecodeError as err:
            _LOGGER.error("Problems decoding response %s", response_text)
            raise SecuritasDirectError(err.msg, None, headers, content) from err

        if "errors" in response_dict:
            errors = response_dict["errors"]
            if (
                isinstance(errors, dict)
                and "data" in errors
                and "reason" in errors["data"]
            ):
                raise SecuritasDirectError(
                    errors["data"]["reason"],
                    response_dict,
                    headers,
                    content,
                )
            elif isinstance(errors, list) and errors and "data" in response_dict:
                # Partial GraphQL response: errors list alongside a data key.
                # Only raise automatically when the operation result is null/empty
                # (all data values are None), so callers that handle partial data
                # themselves are not affected.
                data = response_dict["data"]
                all_null = data is None or (
                    isinstance(data, dict) and all(v is None for v in data.values())
                )
                if all_null:
                    first = errors[0]
                    message = (
                        first.get("message", str(first))
                        if isinstance(first, dict)
                        else str(first)
                    )
                    raise SecuritasDirectError(
                        message,
                        response_dict,
                        headers,
                        content,
                    )

        return response_dict

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
            if self.refresh_token_value:
                _LOGGER.debug("Authentication token expired, refreshing")
                try:
                    if await self.refresh_token():
                        return
                    _LOGGER.warning("Refresh token failed, falling back to login")
                except (
                    SecuritasDirectError,
                    asyncio.TimeoutError,
                    ClientConnectorError,
                ) as err:
                    _LOGGER.warning("Refresh token error, falling back to login: %s", err)
            _LOGGER.debug("Authentication token expired, logging in again")
            await self.login()

    def _generate_id(self) -> str:
        current: datetime = datetime.now()
        return (
            API_ID_PREFIX
            + self.username
            + "_______________"
            + str(current.year)
            + str(current.month)
            + str(current.day)
            + str(current.hour)
            + str(current.minute)
            + str(current.microsecond)
        )

    def _decode_auth_token(self, token_str: str | None) -> dict | None:
        """Decode a JWT auth token and update the token expiry.

        Returns the decoded claims dict, or None on failure.
        """
        if not token_str:
            return None
        try:
            decoded = jwt.decode(
                token_str,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
        except jwt.exceptions.DecodeError:
            _LOGGER.warning("Failed to decode authentication token")
            return None
        if "exp" in decoded:
            self.authentication_token_exp = datetime.fromtimestamp(decoded["exp"])
        return decoded

    def _extract_response_data(self, response: dict, field_name: str) -> dict:
        """Extract and validate response['data'][field_name].

        Raises SecuritasDirectError if the data is missing or None.
        """
        data = response.get("data")
        if data is None:
            raise SecuritasDirectError(
                f"{field_name}: no data in response", response
            )
        result = data.get(field_name)
        if result is None:
            raise SecuritasDirectError(
                f"{field_name} response is None", response
            )
        return result

    async def _poll_operation(
        self,
        check_fn,
        *,
        timeout: float = 60.0,
        continue_on_msg: str | None = None,
    ) -> dict[str, Any]:
        """Poll check_fn until result is no longer WAIT.

        Args:
            check_fn: Async callable that returns a dict with at least 'res' key.
            timeout: Wall-clock timeout in seconds (default 60).
            continue_on_msg: If set, also continue polling when response 'msg'
                matches this value (used by disarm for error_no_response_to_request).

        Returns:
            The final poll result dict.

        Raises:
            TimeoutError: If wall-clock timeout is exceeded.
            SecuritasDirectError: If a non-transient error occurs.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        result: dict[str, Any] = {}
        first = True

        while True:
            if not first and asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(
                    f"Poll operation timed out after {timeout}s, "
                    f"last response: {result}"
                )
            await asyncio.sleep(self.delay_check_operation)
            try:
                result = await check_fn()
            except (ClientConnectorError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Transient error during poll, retrying: %s", err)
                first = False
                continue

            first = False

            if result.get("res") == "WAIT":
                continue
            if continue_on_msg and result.get("msg") == continue_on_msg:
                continue
            break

        return result

    async def logout(self):
        """Logout."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        try:
            await self._execute_request(content, "Logout")
        finally:
            self.authentication_token = None
            self.refresh_token_value = ""
            self.authentication_token_exp = datetime.min
            self.login_timestamp = 0

    def _extract_otp_data(self, data) -> tuple[str | None, list[OtpPhone]]:
        if not data:
            return (None, [])
        otp_hash = data.get("auth-otp-hash")
        phones: list[OtpPhone] = []
        for item in data.get("auth-phones", []):
            phones.append(OtpPhone(item["id"], item["phone"]))
        return (otp_hash, phones)

    async def validate_device(
        self, otp_succeed: bool, auth_otp_hash: str, sms_code: str
    ) -> tuple[str | None, list[OtpPhone] | None]:
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
            self._register_secret("otp_hash", auth_otp_hash)
            self._register_secret("otp_token", sms_code)
        try:
            response = await self._execute_request(content, "mkValidateDevice")
            self.authentication_otp_challenge_value = None
        except SecuritasDirectError as err:
            # the API call fails but we want the phone data in the response
            if len(err.args) > 1 and err.args[1] is not None:
                try:
                    return self._extract_otp_data(err.args[1]["errors"][0]["data"])
                except (KeyError, IndexError, TypeError):
                    pass
            raise

        if "errors" in response and response["errors"][0]["message"] == "Unauthorized":
            # the API call succeeds but is unauthorized
            return self._extract_otp_data(response["errors"][0]["data"])

        validate_data = self._extract_response_data(response, "xSValidateDevice")
        self.authentication_token = validate_data["hash"]
        self._register_secret("auth_token", self.authentication_token)
        self._decode_auth_token(self.authentication_token)
        if validate_data.get("refreshToken"):
            self.refresh_token_value = validate_data["refreshToken"]
            self._register_secret("refresh_token", self.refresh_token_value)
        return (None, None)

    async def refresh_token(self) -> bool:
        """Send a login refresh."""
        content = {
            "operationName": "RefreshLogin",
            "variables": {
                "refreshToken": self.refresh_token_value,
                "id": self._generate_id(),
                "uuid": self.uuid,
                "country": self.country,
                "lang": self.language,
                "callby": API_CALLBY,
                "idDevice": self.device_id,
                "idDeviceIndigitall": self.id_device_indigitall,
                "deviceType": self.device_type,
                "deviceVersion": self.device_version,
                "deviceResolution": self.device_resolution,
                "deviceName": self.device_name,
                "deviceBrand": self.device_brand,
                "deviceOsVersion": self.device_os_version,
            },
            "query": "mutation RefreshLogin($refreshToken: String!, $id: String!, $country: String!, $lang: String!, $callby: String!, $idDevice: String!, $idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: String!, $deviceOsVersion: String!, $uuid: String!) {\n  xSRefreshLogin(refreshToken: $refreshToken, id: $id, country: $country, lang: $lang, callby: $callby, idDevice: $idDevice, idDeviceIndigitall: $idDeviceIndigitall, deviceType: $deviceType, deviceVersion: $deviceVersion, deviceResolution: $deviceResolution, deviceName: $deviceName, deviceBrand: $deviceBrand, deviceOsVersion: $deviceOsVersion, uuid: $uuid) {\n    __typename\n    res\n    msg\n    hash\n    refreshToken\n    legals\n    changePassword\n    needDeviceAuthorization\n    mainUser\n  }\n}",
        }
        response = await self._execute_request(content, "RefreshLogin")

        refresh_data = self._extract_response_data(response, "xSRefreshLogin")

        if refresh_data.get("res") != "OK":
            return False

        if refresh_data.get("hash"):
            self.authentication_token = refresh_data["hash"]
            self._register_secret("auth_token", self.authentication_token)
            if self._decode_auth_token(self.authentication_token) is None:
                return False
            self.login_timestamp = int(datetime.now().timestamp() * 1000)
        else:
            return False
        if refresh_data.get("refreshToken"):
            self.refresh_token_value = refresh_data["refreshToken"]
            self._register_secret("refresh_token", self.refresh_token_value)

        return True

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

        otp_data = self._extract_response_data(response, "xSSendOtp")
        return otp_data["res"]

    async def login(self) -> None:
        """Send Login info and sets authentication token."""

        content = {
            "operationName": "mkLoginToken",
            "variables": {
                "user": self.username,
                "password": self.password,
                "id": self._generate_id(),
                "country": self.country,
                "callby": API_CALLBY,
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
            result_json = err.args[1] if len(err.args) > 1 else None
            if result_json is not None and result_json.get("data"):
                if result_json["data"].get("xSLoginToken"):
                    if result_json["data"]["xSLoginToken"].get(
                        "needDeviceAuthorization"
                    ):
                        # needs a 2FA
                        raise Login2FAError(err.args) from err
                raise LoginError(err.args) from err
            # No response data (connection/network error) — let
            # SecuritasDirectError propagate so HA can retry setup
            raise

        if "errors" in response:
            _LOGGER.error("Login error %s", response["errors"][0]["message"])
            raise LoginError(response["errors"][0]["message"], response)

        # Check if 2FA is required even on successful response
        login_data = self._extract_response_data(response, "xSLoginToken")
        if login_data.get("needDeviceAuthorization", False):
            # needs a 2FA
            raise Login2FAError("2FA authentication required", response)

        if login_data.get("refreshToken"):
            self.refresh_token_value = login_data["refreshToken"]
            self._register_secret("refresh_token", self.refresh_token_value)

        if login_data["hash"] is not None:
            self.authentication_token = login_data["hash"]
            self._register_secret("auth_token", self.authentication_token)
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

            if self._decode_auth_token(self.authentication_token) is None:
                raise SecuritasDirectError(
                    "Failed to decode authentication token"
                )
        else:
            # Token is null, this is expected for 2FA
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

    async def list_installations(self) -> list[Installation]:
        """List securitas direct installations."""
        content = {
            "operationName": "mkInstallationList",
            "query": "query mkInstallationList {\n  xSInstallations {\n    installations {\n      numinst\n      alias\n      panel\n      type\n      name\n      surname\n      address\n      city\n      postcode\n      province\n      email\n      phone\n    }\n  }\n}\n",
        }
        response = await self._execute_request(content, "mkInstallationList")

        result: list[Installation] = []
        installations_data = self._extract_response_data(response, "xSInstallations")
        raw_installations = installations_data["installations"]
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

        check_alarm = self._extract_response_data(response, "xSCheckAlarm")

        return check_alarm["referenceId"]

    async def get_all_services(self, installation: Installation) -> list[Service]:
        """Get the list of all services available to the user."""
        content = {
            "operationName": "Srv",
            "variables": {"numinst": installation.number, "uuid": self.uuid},
            "query": "query Srv($numinst: String!, $uuid: String) {\n  xSSrv(numinst: $numinst, uuid: $uuid) {\n    res\n    msg\n    language\n    installation {\n      numinst\n      role\n      alias\n      status\n      panel\n      sim\n      instIbs\n      services {\n        idService\n        active\n        visible\n        bde\n        isPremium\n        codOper\n        request\n        minWrapperVersion\n        unprotectActive\n        unprotectDeviceStatus\n        instDate\n        genericConfig {\n          total\n          attributes {\n            key\n            value\n          }\n        }\n        attributes {\n          attributes {\n            name\n            value\n            active\n          }\n        }\n      }\n      configRepoUser {\n        alarmPartitions {\n          id\n          enterStates\n          leaveStates\n        }\n      }\n      capabilities\n    }\n  }\n}",
        }
        self._register_installation(installation)
        response = await self._execute_request(content, "Srv")

        installation_data = (response.get("data") or {}).get("xSSrv") or {}
        installation_data = installation_data.get("installation")
        if installation_data is None:
            _LOGGER.warning(
                "API returned no installation data for %s", installation.number
            )
            return []

        result: list[Service] = []
        raw_data = installation_data.get("services")
        if raw_data is None:
            _LOGGER.warning("API returned no services for %s", installation.number)
            return []

        capabilities = installation_data.get("capabilities")
        if capabilities is None:
            _LOGGER.warning("API returned no capabilities for %s", installation.number)
            return []

        installation.capabilities = capabilities
        try:
            token = jwt.decode(
                installation.capabilities,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
        except jwt.exceptions.DecodeError as err:
            raise SecuritasDirectError("Failed to decode capabilities token") from err

        if "exp" in token:
            installation.capabilities_exp = datetime.fromtimestamp(token["exp"])

        item: dict = {}
        for item in raw_data:
            attribute_list: list[Attribute] = []

            attributes = item.get("attributes")
            if attributes and attributes.get("attributes"):
                for attribute_item in attributes["attributes"]:
                    attribute_list.append(
                        Attribute(
                            attribute_item["name"],
                            attribute_item["value"],
                            bool(attribute_item["active"]),
                        )
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
        content = {
            "operationName": "Sentinel",
            "variables": {
                "numinst": installation.number,
            },
            "query": "query Sentinel($numinst: String!) {\n  xSComfort(numinst: $numinst) {\n    res\n    devices {\n      alias\n      status {\n        temperature\n        humidity\n        airQualityCode\n      }\n      zone\n    }\n    forecast {\n      city\n      currentHum\n      currentTemp\n      forecastCode\n      forecastedDays {\n        date\n        forecastCode\n        maxTemp\n        minTemp\n      }\n    }\n  }\n}",
        }

        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "Sentinel", installation)

        if "errors" in response:
            return Sentinel("", "", 0, 0)

        if not service.attributes or not isinstance(service.attributes, list):
            _LOGGER.warning("No attributes found for sentinel service %s", service.id)
            return Sentinel("", "", 0, 0)

        zone = service.attributes[0].value
        comfort_data = response["data"]["xSComfort"]
        if comfort_data is None:
            return Sentinel("", "", 0, 0)
        devices = comfort_data["devices"]
        target_device = None

        for device in devices:
            if device.get("zone") == zone:
                target_device = device
                break

        if target_device is None:
            return Sentinel("", "", 0, 0)

        return Sentinel(
            target_device["alias"],
            "",
            int(target_device["status"]["humidity"]),
            int(target_device["status"]["temperature"]),
        )

    async def get_air_quality_data(
        self, installation: Installation, service: Service
    ) -> AirQuality:
        """Get sentinel status."""
        zone_val = "0"
        if service.attributes and isinstance(service.attributes, list):
            zone_val = str(service.attributes[0].value)
        else:
            _LOGGER.warning(
                "No attributes found for air quality service %s", service.id
            )

        content = {
            "operationName": "AirQualityGraph",
            "variables": {
                "numinst": installation.number,
                "zone": zone_val,
            },
            "query": "query AirQualityGraph($numinst: String!, $zone: String!) {\n  xSAirQ(numinst: $numinst, zone: $zone) {\n    res\n    msg\n    graphData {\n      status {\n        avg6h\n        avg6hMsg\n        avg24h\n        avg24hMsg\n        avg7d\n        avg7dMsg\n        avg4w\n        avg4wMsg\n        current\n        currentMsg\n      }\n      daysTotal\n      days {\n        id\n        value\n      }\n      hoursTotal\n      hours {\n        id\n        value\n      }\n      weeksTotal\n      weeks {\n        id\n        value\n      }\n    }\n  }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "AirQualityGraph")

        if "errors" in response:
            return AirQuality(0, "")

        air_data = response["data"]["xSAirQ"]
        if air_data is None:
            return AirQuality(0, "")
        raw_data = air_data["graphData"]["status"]
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

        if "errors" in response:
            _LOGGER.error(response)
            return SStatus(None, None)

        if "data" in response:
            raw_data = response["data"]["xSStatus"]
            if raw_data is None:
                return SStatus(None, None)
            return SStatus(raw_data["status"], raw_data["timestampUpdate"])

        return SStatus(None, None)

    async def check_alarm_status(
        self,
        installation: Installation,
        reference_id: str,
        timeout: int = CHECK_ALARM_STATUS_TIMEOUT,
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
                "idService": ALARM_STATUS_SERVICE_ID,
                "counter": count,
            },
            "query": "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: String!, $referenceId: String!) {\n  xSCheckAlarmStatus(numinst: $numinst, idService: $idService, panel: $panel, referenceId: $referenceId) {\n    res\n    msg\n    status\n    numinst\n    protomResponse\n    protomResponseDate\n  }\n}\n",
        }
        response = await self._execute_request(
            content, "CheckAlarmStatus", installation
        )

        check_data = self._extract_response_data(response, "xSCheckAlarmStatus")
        return check_data

    async def arm_alarm(
        self,
        installation: Installation,
        command: str,
        force_arming_remote_id: str | None = None,
        suid: str | None = None,
    ) -> ArmStatus:
        """Arms the alarm in the specified mode.

        When force_arming_remote_id and suid are provided, the arm request
        overrides non-blocking exceptions (e.g. open windows) that were
        reported in a previous attempt.
        """
        variables: dict[str, Any] = {
            "request": command,
            "numinst": installation.number,
            "panel": installation.panel,
            "currentStatus": self.protom_response,
            "armAndLock": False,
        }
        if force_arming_remote_id is not None:
            variables["forceArmingRemoteId"] = force_arming_remote_id
        if suid is not None:
            variables["suid"] = suid

        content = {
            "operationName": "xSArmPanel",
            "variables": variables,
            "query": (
                "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!,"
                " $panel: String!, $currentStatus: String, $suid: String,"
                " $forceArmingRemoteId: String, $armAndLock: Boolean) {\n"
                "  xSArmPanel(numinst: $numinst, request: $request, panel: $panel,"
                " currentStatus: $currentStatus, suid: $suid,"
                " forceArmingRemoteId: $forceArmingRemoteId,"
                " armAndLock: $armAndLock) {\n"
                "    res\n    msg\n    referenceId\n  }\n}\n"
            ),
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "xSArmPanel", installation)
        arm_data = self._extract_response_data(response, "xSArmPanel")
        if arm_data["res"] != "OK":
            raise SecuritasDirectError(arm_data["msg"], response)

        reference_id = arm_data["referenceId"]

        count = 0

        async def _check():
            nonlocal count
            count += 1
            data = await self._check_arm_status(
                installation,
                reference_id,
                command,
                count,
                force_arming_remote_id,
            )
            # Detect non-blocking exception that allows forcing
            error = data.get("error")
            if (
                data.get("res") == "ERROR"
                and error
                and error.get("type") == "NON_BLOCKING"
                and error.get("allowForcing")
            ):
                error_ref = error.get("referenceId", reference_id)
                error_suid = error.get("suid", "")
                exceptions = await self._get_exceptions(
                    installation, error_ref, error_suid
                )
                raise ArmingExceptionError(error_ref, error_suid, exceptions)
            return data

        raw_data = await self._poll_operation(_check)

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
        command: str,
        counter: int,
        force_arming_remote_id: str | None = None,
    ) -> dict[str, Any]:
        """Check progress of the arm operation."""
        variables: dict[str, Any] = {
            "request": command,
            "numinst": installation.number,
            "panel": installation.panel,
            "referenceId": reference_id,
            "counter": counter,
            "armAndLock": False,
        }
        if force_arming_remote_id is not None:
            variables["forceArmingRemoteId"] = force_arming_remote_id

        content = {
            "operationName": "ArmStatus",
            "variables": variables,
            "query": (
                "query ArmStatus($numinst: String!, $request: ArmCodeRequest,"
                " $panel: String!, $referenceId: String!, $counter: Int!,"
                " $forceArmingRemoteId: String, $armAndLock: Boolean) {\n"
                "  xSArmStatus(numinst: $numinst, panel: $panel,"
                " referenceId: $referenceId, counter: $counter, request: $request,"
                " forceArmingRemoteId: $forceArmingRemoteId,"
                " armAndLock: $armAndLock) {\n"
                "    res\n    msg\n    status\n    protomResponse\n"
                "    protomResponseDate\n    numinst\n    requestId\n"
                "    error {\n      code\n      type\n      allowForcing\n"
                "      exceptionsNumber\n      referenceId\n      suid\n    }\n"
                "  }\n}\n"
            ),
        }
        response = await self._execute_request(content, "ArmStatus", installation)

        raw_data = self._extract_response_data(response, "xSArmStatus")
        return raw_data

    async def _get_exceptions(
        self,
        installation: Installation,
        reference_id: str,
        suid: str,
    ) -> list[dict[str, Any]]:
        """Fetch arming exception details (e.g. open windows/doors).

        The API returns WAIT on the first poll (counter=1) and OK on a
        subsequent poll once the panel has reported the open sensors.
        We must keep incrementing the counter until we get a non-WAIT
        response, matching the behaviour of the official app.
        """
        query = (
            "query xSGetExceptions($numinst: String!, $panel: String!,"
            " $referenceId: String!, $counter: Int!, $suid: String) {\n"
            "  xSGetExceptions(numinst: $numinst, panel: $panel,"
            " referenceId: $referenceId, counter: $counter, suid: $suid) {\n"
            "    res\n    msg\n"
            "    exceptions {\n      status\n      deviceType\n      alias\n    }\n"
            "  }\n}\n"
        )
        count = 1
        max_retries = max(10, round(30 / max(1, self.delay_check_operation)))
        data: dict[str, Any] = {}
        while count <= max_retries:
            content = {
                "operationName": "xSGetExceptions",
                "variables": {
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "referenceId": reference_id,
                    "counter": count,
                    "suid": suid,
                },
                "query": query,
            }
            response = await self._execute_request(
                content, "xSGetExceptions", installation
            )
            data = response.get("data", {}).get("xSGetExceptions", {}) or {}
            if data.get("res") == "OK":
                return data.get("exceptions") or []
            if data.get("res") != "WAIT":
                break
            await asyncio.sleep(self.delay_check_operation)
            count += 1
        _LOGGER.warning(
            "Failed to fetch arming exceptions after %d attempts: %s", count, data
        )
        return []

    async def disarm_alarm(
        self, installation: Installation, command: str
    ) -> DisarmStatus:
        """Disarm the alarm."""
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
            },
            "query": "mutation xSDisarmPanel($numinst: String!, $request: DisarmCodeRequest!, $panel: String!) {\n  xSDisarmPanel(numinst: $numinst, request: $request, panel: $panel) {\n    res\n    msg\n    referenceId\n  }\n}\n",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(content, "xSDisarmPanel", installation)
        disarm_data = self._extract_response_data(response, "xSDisarmPanel")
        if "res" in disarm_data and disarm_data["res"] != "OK":
            raise SecuritasDirectError(disarm_data["msg"], response)

        if "referenceId" not in disarm_data or "res" not in disarm_data:
            raise SecuritasDirectError("No referenceId in response", response)

        reference_id = disarm_data["referenceId"]

        count = 0

        async def _check():
            nonlocal count
            count += 1
            return await self._check_disarm_status(
                installation,
                reference_id,
                command,
                count,
            )

        raw_data = await self._poll_operation(
            _check,
            continue_on_msg="alarm-manager.error_no_response_to_request",
        )

        if raw_data.get("protomResponse"):
            self.protom_response = raw_data["protomResponse"]
        return DisarmStatus(
            raw_data.get("error"),
            raw_data.get("msg", ""),
            raw_data.get("numinst", ""),
            raw_data.get("protomResponse", ""),
            raw_data.get("protomResponseDate", ""),
            raw_data.get("requestId", ""),
            raw_data.get("res", ""),
            raw_data.get("status", ""),
        )

    async def _check_disarm_status(
        self,
        installation: Installation,
        reference_id: str,
        command: str,
        counter: int,
    ) -> dict[str, Any]:
        """Check progress of the alarm."""
        content = {
            "operationName": "DisarmStatus",
            "variables": {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": "query DisarmStatus($numinst: String!, $panel: String!, $referenceId: String!, $counter: Int!, $request: DisarmCodeRequest) {\n  xSDisarmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\n    res\n    msg\n    status\n    protomResponse\n    protomResponseDate\n    numinst\n    requestId\n    error {\n      code\n      type\n      allowForcing\n      exceptionsNumber\n      referenceId\n    }\n  }\n}\n",
        }
        response = await self._execute_request(content, "DisarmStatus", installation)

        disarm_data = self._extract_response_data(response, "xSDisarmStatus")
        return disarm_data

    async def get_smart_lock_config(self, installation: Installation) -> SmartLock:
        content = {
            "operationName": "xSGetSmartlockConfig",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "devices": [
                    {
                        "deviceType": SMARTLOCK_DEVICE_TYPE,
                        "deviceId": SMARTLOCK_DEVICE_ID,
                        "keytype": SMARTLOCK_KEY_TYPE,
                    }
                ],
            },
            "query": "query xSGetSmartlockConfig($numinst: String!, $panel: String!, $devices: [SmartlockDevicesInfo]!) {\n  xSGetSmartlockConfig(numinst: $numinst, panel: $panel, devices: $devices) {\n    res\n    referenceId\n    zoneId\n    serialNumber\n    location\n    family\n    type\n    label\n    features {\n      holdBackLatchTime\n      calibrationType\n      autolock {\n        active\n        timeout\n      }\n    }\n  }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(
            content, "xSGetSmartlockConfig", installation
        )

        if "errors" in response:
            _LOGGER.error(response)
            return SmartLock(None, None, None)

        if "data" in response:
            raw_data = response["data"]["xSGetSmartlockConfig"]
            if raw_data is None:
                return SmartLock(None, None, None)
            return SmartLock(raw_data["res"], raw_data["location"], raw_data["type"])

        return SmartLock(None, None, None)

    async def get_lock_current_mode(self, installation: Installation) -> SmartLockMode:
        content = {
            "operationName": "xSGetLockCurrentMode",
            "variables": {
                "numinst": installation.number,
            },
            "query": "query xSGetLockCurrentMode($numinst: String!, $counter: Int) {\n  xSGetLockCurrentMode(numinst: $numinst, counter: $counter) {\n    res\n    smartlockInfo {\n      lockStatus\n      deviceId\n    }\n  }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(
            content, "xSGetLockCurrentMode", installation
        )

        if "errors" in response:
            _LOGGER.error(response)
            return SmartLockMode(None, "0")

        if "data" in response:
            raw_data = response["data"]["xSGetLockCurrentMode"]
            if raw_data is None:
                return SmartLockMode(None, "0")
            lock_status = "0"
            if raw_data.get("smartlockInfo"):
                lock_status = raw_data["smartlockInfo"][0]["lockStatus"]
            return SmartLockMode(raw_data["res"], lock_status)

        return SmartLockMode(None, "0")

    async def change_lock_mode(
        self, installation: Installation, lock: bool
    ) -> SmartLockModeStatus:
        content = {
            "operationName": "xSChangeSmartlockMode",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": SMARTLOCK_DEVICE_ID,
                "lock": lock,
            },
            "query": "mutation xSChangeSmartlockMode($numinst: String!, $panel: String!, $deviceId: String!, $deviceType: String!, $lock: Boolean!) {\n  xSChangeSmartlockMode(\n    numinst: $numinst\n    panel: $panel\n    deviceId: $deviceId\n    deviceType: $deviceType\n    lock: $lock\n  ) {\n    res\n    msg\n    referenceId\n  }\n}",
        }
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)
        response = await self._execute_request(
            content, "xSChangeSmartlockMode", installation
        )
        lock_data = self._extract_response_data(response, "xSChangeSmartlockMode")
        if "res" in lock_data and lock_data["res"] != "OK":
            raise SecuritasDirectError(lock_data["msg"], response)

        if "referenceId" not in lock_data or "res" not in lock_data:
            raise SecuritasDirectError("No referenceId in response", response)

        reference_id = lock_data["referenceId"]

        count = 0

        async def _check():
            nonlocal count
            count += 1
            return await self._check_change_lock_mode(
                installation,
                reference_id,
                count,
            )

        raw_data = await self._poll_operation(_check)

        await asyncio.sleep(self.delay_check_operation * LOCK_MODE_SETTLE_MULTIPLIER)
        self.protom_response = raw_data["protomResponse"]
        return SmartLockModeStatus(
            raw_data["res"],
            raw_data["msg"],
            raw_data["protomResponse"],
            raw_data["status"],
        )

    async def _check_change_lock_mode(
        self,
        installation: Installation,
        reference_id: str,
        counter: int,
    ) -> dict[str, Any]:
        content = {
            "operationName": "xSChangeSmartlockModeStatus",
            "variables": {
                "counter": counter,
                "deviceId": SMARTLOCK_DEVICE_ID,
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
            },
            "query": "query xSChangeSmartlockModeStatus($numinst: String!, $panel: String!, $referenceId: String!, $deviceId: String, $counter: Int) {\n  xSChangeSmartlockModeStatus(\n    numinst: $numinst\n    panel: $panel\n    referenceId: $referenceId\n    counter: $counter\n    deviceId: $deviceId\n  ) {\n    res\n    msg\n    protomResponse\n    status\n  }\n}",
        }
        response = await self._execute_request(
            content, "xSChangeSmartlockModeStatus", installation
        )

        lock_status_data = self._extract_response_data(response, "xSChangeSmartlockModeStatus")
        return lock_status_data
