"""Securitas Direct API implementation."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import logging
import secrets
from typing import Any
from uuid import uuid4

import jwt

from .dataTypes import (
    AirQuality,
    Attribute,
    CameraDevice,
    Installation,
    LockAutolock,
    LockFeatures,
    OperationStatus,
    OtpPhone,
    Sentinel,
    Service,
    SStatus,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
    ThumbnailResponse,
)
from .exceptions import (
    AccountBlockedError,
    ArmingExceptionError,
    Login2FAError,
    LoginError,
    SecuritasDirectError,
)
from .graphql_queries import (
    AIR_QUALITY_QUERY,
    ARM_PANEL_MUTATION,
    ARM_STATUS_QUERY,
    CHANGE_LOCK_MODE_MUTATION,
    CHANGE_LOCK_MODE_STATUS_QUERY,
    CHECK_ALARM_QUERY,
    CHECK_ALARM_STATUS_QUERY,
    DANALOCK_CONFIG_QUERY,
    DANALOCK_CONFIG_STATUS_QUERY,
    DEVICE_LIST_QUERY,
    DISARM_PANEL_MUTATION,
    DISARM_STATUS_QUERY,
    GENERAL_STATUS_QUERY,
    GET_EXCEPTIONS_QUERY,
    GET_PHOTO_IMAGES_QUERY,
    GET_THUMBNAIL_QUERY,
    INSTALLATION_LIST_QUERY,
    LOCK_CURRENT_MODE_QUERY,
    LOGIN_TOKEN_MUTATION,
    REFRESH_LOGIN_MUTATION,
    REQUEST_IMAGES_MUTATION,
    REQUEST_IMAGES_STATUS_QUERY,
    SEND_OTP_MUTATION,
    SENTINEL_QUERY,
    SERVICES_QUERY,
    SMARTLOCK_CONFIG_QUERY,
    VALIDATE_DEVICE_MUTATION,
)
from .http_client import SecuritasHttpClient

_LOGGER = logging.getLogger(__name__)

# API protocol constants (re-exported for backwards compatibility)
from .http_client import API_CALLBY  # noqa: E402

# Smart-lock device identifiers expected by the Securitas API
SMARTLOCK_DEVICE_TYPE = "DR"
SMARTLOCK_DEVICE_ID = "01"
SMARTLOCK_KEY_TYPE = "0"

# Service ID used when polling CheckAlarmStatus
ALARM_STATUS_SERVICE_ID = "11"


def _parse_lock_features(raw_features: dict | None) -> LockFeatures | None:
    """Parse lock features from a raw API response dict."""
    if not raw_features:
        return None
    autolock = None
    if raw_autolock := raw_features.get("autolock"):
        autolock = LockAutolock(
            active=raw_autolock.get("active"),
            timeout=raw_autolock.get("timeout"),
        )
    return LockFeatures(
        holdBackLatchTime=raw_features.get("holdBackLatchTime", 0),
        calibrationType=raw_features.get("calibrationType", 0),
        autolock=autolock,
    )


# Extra settle delay after a lock-mode change completes (multiples of delay_check_operation)

# Device types for camera devices in xSDeviceList
CAMERA_DEVICE_TYPES = {"QR", "YR", "YP", "QP"}

# Image request parameters
IMAGE_RESOLUTION = 0
IMAGE_MEDIA_TYPE = 1
IMAGE_DEVICE_TYPE_MAP: dict[str, int] = {"QR": 106, "YR": 106, "YP": 103, "QP": 107}


def generate_uuid() -> str:
    """Create a device id."""
    return str(uuid4()).replace("-", "")[0:16]


def generate_device_id(_lang: str) -> str:
    """Create a device identifier for the API."""
    return secrets.token_urlsafe(16) + ":APA91b" + secrets.token_urlsafe(130)[0:134]


class ApiManager(SecuritasHttpClient):
    """Securitas Direct API — business operations."""

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

    @staticmethod
    def _is_account_blocked(result_json: dict) -> bool:
        """Check if a login response indicates the account is blocked (error 60052)."""
        errors = result_json.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and isinstance(first.get("data"), dict):
                return first["data"].get("err") == "60052"
        return False

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
            "query": VALIDATE_DEVICE_MUTATION,
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
                    error_data = err.args[1]["errors"][0]["data"]
                    # Only return OTP data if it actually contains OTP fields;
                    # otherwise the error is unrelated (e.g. invalid code format)
                    if "auth-otp-hash" in error_data or "auth-phones" in error_data:
                        return self._extract_otp_data(error_data)
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
            "query": REFRESH_LOGIN_MUTATION,
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
            "query": SEND_OTP_MUTATION,
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
            "query": LOGIN_TOKEN_MUTATION,
        }

        response = {}
        try:
            response = await self._execute_request(content, "mkLoginToken")
        except SecuritasDirectError as err:
            result_json: dict | None = err.args[1] if len(err.args) > 1 else None
            message = str(err.args[0]) if err.args else "Login failed"
            if result_json is not None:
                # Check for account-blocked error (60052)
                if self._is_account_blocked(result_json):
                    raise AccountBlockedError(message, result_json) from err
                if result_json.get("data"):
                    data = result_json["data"]
                    if data.get("xSLoginToken"):
                        if data["xSLoginToken"].get("needDeviceAuthorization"):
                            # needs a 2FA
                            raise Login2FAError(message, result_json) from err
                    raise LoginError(message, result_json) from err
                # Has response dict = server responded with error
                # → login failure.
                raise LoginError(message, result_json) from err
            # No response dict = network/connection error
            # → let propagate.
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
                raise SecuritasDirectError("Failed to decode authentication token")
        else:
            # Token is null, this is expected for 2FA
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

    async def list_installations(self) -> list[Installation]:
        """List securitas direct installations."""
        content = {
            "operationName": "mkInstallationList",
            "query": INSTALLATION_LIST_QUERY,
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
            "query": CHECK_ALARM_QUERY,
        }
        data = await self._execute_graphql(
            content, "CheckAlarm", "xSCheckAlarm", installation
        )
        return data["referenceId"]

    async def get_all_services(self, installation: Installation) -> list[Service]:
        """Get the list of all services available to the user."""
        content = {
            "operationName": "Srv",
            "variables": {"numinst": installation.number, "uuid": self.uuid},
            "query": SERVICES_QUERY,
        }
        await self._check_authentication_token()
        self._register_installation(installation)
        response = await self._execute_request(content, "Srv", installation)

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

        config_repo = installation_data.get("configRepoUser") or {}
        installation.alarm_partitions = config_repo.get("alarmPartitions") or []

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
            "query": SENTINEL_QUERY,
        }

        await self._ensure_auth(installation)
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

        air_quality_code = target_device["status"].get("airQualityCode")
        return Sentinel(
            target_device["alias"],
            str(air_quality_code) if air_quality_code is not None else "",
            int(target_device["status"]["humidity"]),
            int(target_device["status"]["temperature"]),
            zone=target_device.get("zone", ""),
        )

    async def get_air_quality_data(
        self, installation: Installation, zone: str
    ) -> AirQuality | None:
        """Get air quality data from xSAirQuality API."""
        content = {
            "operationName": "AirQuality",
            "variables": {
                "numinst": installation.number,
                "zone": zone,
            },
            "query": AIR_QUALITY_QUERY,
        }

        await self._ensure_auth(installation)
        response = await self._execute_request(content, "AirQuality", installation)

        if "errors" in response:
            return None

        air_quality = response.get("data", {}).get("xSAirQuality")
        if air_quality is None:
            return None

        aq_data = air_quality.get("data")
        if aq_data is None:
            return None

        # Use hours[-1].value for the most recent hourly reading
        hours = aq_data.get("hours", [])
        if not hours:
            return None

        try:
            value = int(hours[-1].get("value", 0))
        except (ValueError, TypeError):
            return None

        status = aq_data.get("status", {})
        return AirQuality(
            value=value,
            status_current=int(status.get("current", 0)),
        )

    async def check_general_status(self, installation: Installation) -> SStatus:
        """Check current status of the alarm."""
        content = {
            "operationName": "Status",
            "variables": {"numinst": installation.number},
            "query": GENERAL_STATUS_QUERY,
        }
        await self._ensure_auth(installation)
        response = await self._execute_request(content, "Status", installation)

        if "errors" in response:
            _LOGGER.error(response)
            return SStatus(None, None)

        if "data" in response:
            raw_data = response["data"]["xSStatus"]
            if raw_data is None:
                return SStatus(None, None)
            return SStatus(
                raw_data["status"],
                raw_data["timestampUpdate"],
                raw_data.get("wifiConnected"),
            )

        return SStatus(None, None)

    async def check_alarm_status(
        self,
        installation: Installation,
        reference_id: str,
    ) -> OperationStatus:
        """Return the status of the alarm."""

        async def _check() -> dict[str, Any]:
            return await self._check_alarm_status(installation, reference_id)

        raw_data = await self._poll_operation(_check)

        self.protom_response = raw_data["protomResponse"]
        return OperationStatus(
            operation_status=raw_data["res"],
            message=raw_data["msg"],
            status=raw_data["status"],
            installation_number=raw_data["numinst"],
            protomResponse=raw_data["protomResponse"],
            protomResponseData=raw_data["protomResponseDate"],
        )

    async def _check_alarm_status(
        self, installation: Installation, reference_id: str
    ) -> dict[str, Any]:
        """Check status of the operation check alarm."""
        content = {
            "operationName": "CheckAlarmStatus",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
                "idService": ALARM_STATUS_SERVICE_ID,
            },
            "query": CHECK_ALARM_STATUS_QUERY,
        }
        response = await self._execute_request(
            content, "CheckAlarmStatus", installation
        )

        check_data = self._extract_response_data(response, "xSCheckAlarmStatus")
        return check_data

    async def process_arm_result(
        self,
        raw_data: dict[str, Any],
        installation: Installation,
    ) -> OperationStatus:
        """Process raw arm poll result into OperationStatus.

        Raises ArmingExceptionError for NON_BLOCKING errors with allowForcing,
        SecuritasDirectError for other errors.
        """
        error = raw_data.get("error")
        if raw_data.get("res") == "ERROR":
            if (
                error
                and error.get("type") == "NON_BLOCKING"
                and error.get("allowForcing")
            ):
                error_ref = error.get("referenceId", "")
                error_suid = error.get("suid", "")
                exceptions = await self._get_exceptions(
                    installation, error_ref, error_suid
                )
                raise ArmingExceptionError(error_ref, error_suid, exceptions)
            error_info = error or {}
            if error_info.get("type") != "NON_BLOCKING":
                raise SecuritasDirectError(
                    f"Arm command failed: {raw_data.get('msg', 'unknown error')}",
                )

        self.protom_response = raw_data["protomResponse"]
        return OperationStatus(
            operation_status=raw_data["res"],
            message=raw_data["msg"],
            status=raw_data["status"],
            installation_number=raw_data["numinst"],
            protomResponse=raw_data["protomResponse"],
            protomResponseData=raw_data["protomResponseDate"],
            requestId=raw_data["requestId"],
            error=raw_data["error"],
        )

    def process_disarm_result(
        self,
        raw_data: dict[str, Any],
    ) -> OperationStatus:
        """Process raw disarm poll result into OperationStatus.

        Raises SecuritasDirectError for errors.
        """
        if raw_data.get("res") == "ERROR":
            error_info = raw_data.get("error") or {}
            if error_info.get("type") != "NON_BLOCKING":
                raise SecuritasDirectError(
                    f"Disarm command failed: {raw_data.get('msg', 'unknown error')}",
                )

        if raw_data.get("protomResponse"):
            self.protom_response = raw_data["protomResponse"]
        return OperationStatus(
            operation_status=raw_data.get("res", ""),
            message=raw_data.get("msg", ""),
            status=raw_data.get("status", ""),
            numinst=raw_data.get("numinst", ""),
            protomResponse=raw_data.get("protomResponse", ""),
            protomResponseData=raw_data.get("protomResponseDate", ""),
            requestId=raw_data.get("requestId", ""),
            error=raw_data.get("error"),
        )

    def process_lock_mode_result(
        self,
        raw_data: dict[str, Any],
    ) -> SmartLockModeStatus:
        """Process raw lock mode poll result into SmartLockModeStatus."""
        self.protom_response = raw_data["protomResponse"]
        return SmartLockModeStatus(
            raw_data["res"],
            raw_data["msg"],
            raw_data["protomResponse"],
            raw_data["status"],
        )

    async def check_arm_status(
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
            "query": ARM_STATUS_QUERY,
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
        query = GET_EXCEPTIONS_QUERY
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

    async def check_disarm_status(
        self,
        installation: Installation,
        reference_id: str,
        command: str,
        counter: int,
        current_status: str | None = None,
    ) -> dict[str, Any]:
        """Check progress of the alarm."""
        content = {
            "operationName": "DisarmStatus",
            "variables": {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": current_status or self.protom_response,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": DISARM_STATUS_QUERY,
        }
        response = await self._execute_request(content, "DisarmStatus", installation)

        disarm_data = self._extract_response_data(response, "xSDisarmStatus")
        return disarm_data

    async def get_smart_lock_config(
        self, installation: Installation, device_id: str = SMARTLOCK_DEVICE_ID
    ) -> SmartLock:
        """Fetch smart lock configuration for the installation."""
        content = {
            "operationName": "xSGetSmartlockConfig",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": device_id,
                "keytype": SMARTLOCK_KEY_TYPE,
            },
            "query": SMARTLOCK_CONFIG_QUERY,
        }
        await self._ensure_auth(installation)
        response = await self._execute_request(
            content, "xSGetSmartlockConfig", installation
        )

        raw_data = response.get("data", {}).get("xSGetSmartlockConfig")
        if raw_data is None:
            return SmartLock()

        return SmartLock(
            res=raw_data.get("res"),
            location=raw_data.get("location"),
            referenceId=raw_data.get("referenceId") or "",
            zoneId=raw_data.get("zoneId") or "",
            serialNumber=raw_data.get("serialNumber") or "",
            family=raw_data.get("family") or "",
            label=raw_data.get("label") or "",
            features=_parse_lock_features(raw_data.get("features")),
        )

    async def submit_danalock_config_request(
        self,
        installation: Installation,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> str:
        """Send Danalock config request and return referenceId."""
        content = {
            "operationName": "xSGetDanalockConfig",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": device_id,
            },
            "query": DANALOCK_CONFIG_QUERY,
        }
        data = await self._execute_graphql(
            content, "xSGetDanalockConfig", "xSGetDanalockConfig", installation
        )
        if "referenceId" not in data:
            raise SecuritasDirectError("No referenceId in Danalock config response")
        return data["referenceId"]

    async def check_danalock_config_status(
        self,
        installation: Installation,
        reference_id: str,
        counter: int,
    ) -> dict[str, Any]:
        """Check progress of Danalock config request."""
        content = {
            "operationName": "xSGetDanalockConfigStatus",
            "variables": {
                "numinst": installation.number,
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": DANALOCK_CONFIG_STATUS_QUERY,
        }
        response = await self._execute_request(
            content, "xSGetDanalockConfigStatus", installation
        )
        return self._extract_response_data(response, "xSGetDanalockConfigStatus")

    @staticmethod
    def parse_danalock_config_response(
        raw: dict[str, Any], device_id: str = SMARTLOCK_DEVICE_ID
    ) -> SmartLock:
        """Parse a successful Danalock config status response into SmartLock."""
        return SmartLock(
            res=raw.get("res"),
            deviceId=raw.get("deviceNumber") or device_id,
            features=_parse_lock_features(raw.get("features")),
        )

    async def get_lock_current_mode(
        self, installation: Installation
    ) -> list[SmartLockMode]:
        """Get the current mode of all smart locks."""
        content = {
            "operationName": "xSGetLockCurrentMode",
            "variables": {
                "numinst": installation.number,
            },
            "query": LOCK_CURRENT_MODE_QUERY,
        }
        await self._ensure_auth(installation)
        response = await self._execute_request(
            content, "xSGetLockCurrentMode", installation
        )

        raw_data = response.get("data", {}).get("xSGetLockCurrentMode")
        if raw_data is None:
            return []
        modes: list[SmartLockMode] = []
        for info in raw_data.get("smartlockInfo") or []:
            lock_status = info.get("lockStatus")
            if lock_status is None:
                continue
            modes.append(
                SmartLockMode(
                    res=raw_data["res"],
                    lockStatus=lock_status,
                    deviceId=info.get("deviceId", ""),
                    statusTimestamp=info.get("statusTimestamp", ""),
                )
            )
        return modes

    async def check_change_lock_mode(
        self,
        installation: Installation,
        reference_id: str,
        counter: int,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> dict[str, Any]:
        """Check progress of lock mode change operation."""
        content = {
            "operationName": "xSChangeSmartlockModeStatus",
            "variables": {
                "counter": counter,
                "deviceId": device_id,
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
            },
            "query": CHANGE_LOCK_MODE_STATUS_QUERY,
        }
        response = await self._execute_request(
            content, "xSChangeSmartlockModeStatus", installation
        )

        lock_status_data = self._extract_response_data(
            response, "xSChangeSmartlockModeStatus"
        )
        return lock_status_data

    # ── Submit request + single-poll methods (for ApiQueue) ────────────

    async def submit_arm_request(
        self,
        installation: Installation,
        command: str,
        force_arming_remote_id: str | None = None,
        suid: str | None = None,
    ) -> str:
        """Send arm mutation and return referenceId (no polling)."""
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
            "query": ARM_PANEL_MUTATION,
        }
        data = await self._execute_graphql(
            content, "xSArmPanel", "xSArmPanel", installation
        )
        return data["referenceId"]

    async def submit_disarm_request(
        self,
        installation: Installation,
        command: str,
    ) -> str:
        """Send disarm mutation and return referenceId (no polling)."""
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": self.protom_response,
            },
            "query": DISARM_PANEL_MUTATION,
        }
        data = await self._execute_graphql(
            content, "xSDisarmPanel", "xSDisarmPanel", installation
        )
        return data["referenceId"]

    async def submit_change_lock_mode_request(
        self,
        installation: Installation,
        lock: bool,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> str:
        """Send change lock mode mutation and return referenceId (no polling)."""
        content = {
            "operationName": "xSChangeSmartlockMode",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": device_id,
                "lock": lock,
            },
            "query": CHANGE_LOCK_MODE_MUTATION,
        }
        data = await self._execute_graphql(
            content, "xSChangeSmartlockMode", "xSChangeSmartlockMode", installation
        )
        if "referenceId" not in data:
            raise SecuritasDirectError("No referenceId in response")
        return data["referenceId"]

    async def get_device_list(self, installation: Installation) -> list[CameraDevice]:
        """Get list of camera devices (QR, YR, YP, QP) for an installation."""
        content = {
            "operationName": "xSDeviceList",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": DEVICE_LIST_QUERY,
        }
        raw = await self._execute_graphql(
            content, "xSDeviceList", "xSDeviceList", installation, check_ok=False
        )
        devices = raw.get("devices", [])
        result: list[CameraDevice] = []
        for d in devices:
            if d.get("type") not in CAMERA_DEVICE_TYPES or d.get("isActive") is False:
                continue
            code = int(d["code"]) if str(d.get("code", "")).isdigit() else None
            result.append(
                CameraDevice(
                    id=d["id"],
                    code=code or 0,
                    zone_id=d["zoneId"]
                    or (f"{d['type']}{code:02d}" if code is not None else d["id"]),
                    name=d["name"],
                    device_type=d["type"],
                    serial_number=d.get("serialNumber"),
                )
            )
        return result

    async def request_images(
        self, installation: Installation, device_code: int, device_type: str = "QR"
    ) -> str:
        """Request the panel to capture a new image. Returns referenceId."""
        # NOTE: the Verisure website omits resolution, mediaType, and deviceType
        # for YR (PIR camera) requests, but sending them works fine for all types.
        content = {
            "operationName": "RequestImages",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "devices": [device_code],
                "resolution": IMAGE_RESOLUTION,
                "mediaType": IMAGE_MEDIA_TYPE,
                "deviceType": IMAGE_DEVICE_TYPE_MAP.get(device_type, 106),
            },
            "query": REQUEST_IMAGES_MUTATION,
        }
        raw = await self._execute_graphql(
            content, "RequestImages", "xSRequestImages", installation
        )
        return raw["referenceId"]

    async def check_request_images_status(
        self,
        installation: Installation,
        device_code: int,
        reference_id: str,
        counter: int = 1,
    ) -> dict:
        """Check status of image request."""
        content = {
            "operationName": "RequestImagesStatus",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "devices": [device_code],
                "referenceId": reference_id,
                "counter": counter,
            },
            "query": REQUEST_IMAGES_STATUS_QUERY,
        }
        response = await self._execute_request(
            content, "RequestImagesStatus", installation
        )
        return self._extract_response_data(response, "xSRequestImagesStatus")

    async def get_thumbnail(
        self, installation: Installation, device_type: str, zone_id: str
    ) -> ThumbnailResponse:
        """Fetch the latest thumbnail image for a camera device."""
        content = {
            "operationName": "mkGetThumbnail",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "device": device_type,
                "zoneId": zone_id,
            },
            "query": GET_THUMBNAIL_QUERY,
        }
        raw = await self._execute_graphql(
            content, "mkGetThumbnail", "xSGetThumbnail", installation, check_ok=False
        )
        return ThumbnailResponse(
            id_signal=raw.get("idSignal"),
            device_code=raw.get("deviceCode"),
            device_alias=raw.get("deviceAlias"),
            timestamp=raw.get("timestamp"),
            signal_type=raw.get("signalType"),
            image=raw.get("image"),
        )

    async def get_photo_images(
        self, installation: Installation, id_signal: str, signal_type: str
    ) -> bytes | None:
        """Fetch the full-resolution images for a completed capture.

        Uses the idSignal obtained from get_thumbnail to call xSGetPhotoImages.
        Returns the decoded JPEG bytes of the highest-quality BINARY image, or
        None if no usable image is found.
        """
        content = {
            "operationName": "mkGetPhotoImages",
            "variables": {
                "numinst": installation.number,
                "idSignal": id_signal,
                "signalType": signal_type,
                "panel": installation.panel,
            },
            "query": GET_PHOTO_IMAGES_QUERY,
        }
        raw = await self._execute_graphql(
            content,
            "mkGetPhotoImages",
            "xSGetPhotoImages",
            installation,
            check_ok=False,
        )
        devices = raw.get("devices") or []
        if not devices:
            return None
        images = devices[0].get("images") or []
        binary_images = [
            img for img in images if img.get("type") == "BINARY" and img.get("image")
        ]
        if not binary_images:
            return None
        best = max(binary_images, key=lambda img: len(img["image"]))
        try:
            return base64.b64decode(best["image"])
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return None
