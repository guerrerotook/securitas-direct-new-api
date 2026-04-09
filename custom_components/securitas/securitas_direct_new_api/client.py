"""SecuritasClient — unified API client with auth lifecycle and typed execute.

Composes an HttpTransport for the raw HTTP layer.  Business methods (arm,
disarm, check_alarm, get_general_status) are included; lock, camera, etc.
will be added in later tasks.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import uuid4

from aiohttp import ClientConnectorError
from pydantic import BaseModel, ValidationError
import jwt

from .exceptions import (
    AccountBlockedError,
    ArmingExceptionError,
    AuthenticationError,
    OperationTimeoutError,
    SecuritasDirectError,
    SessionExpiredError,
    TwoFactorRequiredError,
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
from .http_transport import HttpTransport
from .models import (
    AirQuality,
    Attribute,
    CameraDevice,
    Installation,
    LockFeatures,
    OperationStatus,
    OtpPhone,
    Sentinel,
    Service,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
    SStatus,
    ThumbnailResponse,
)
from .responses import (
    AirQualityEnvelope,
    ArmPanelEnvelope,
    ChangeLockModeEnvelope,
    CheckAlarmEnvelope,
    DanalockConfigEnvelope,
    DeviceListEnvelope,
    DisarmPanelEnvelope,
    GeneralStatusEnvelope,
    InstallationListEnvelope,
    LockModeEnvelope,
    PhotoImagesEnvelope,
    RequestImagesEnvelope,
    RequestImagesStatusEnvelope,
    SentinelEnvelope,
    SmartlockConfigEnvelope,
    ThumbnailEnvelope,
)

if TYPE_CHECKING:
    from custom_components.securitas.log_filter import SensitiveDataFilter

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# API protocol constants
API_CALLBY = "OWA_10"
API_ID_PREFIX = "OWA_______________"
ALARM_STATUS_SERVICE_ID = "11"

# Lock device constants
SMARTLOCK_DEVICE_ID = "01"
SMARTLOCK_DEVICE_TYPE = "DR"
SMARTLOCK_KEY_TYPE = "0"

# Camera / image constants
CAMERA_DEVICE_TYPES = {"QR", "YR", "YP", "QP"}
IMAGE_RESOLUTION = 0
IMAGE_MEDIA_TYPE = 1
IMAGE_DEVICE_TYPE_MAP: dict[str, int] = {"QR": 106, "YR": 106, "YP": 103, "QP": 107}


def generate_uuid() -> str:
    """Create a device id."""
    return str(uuid4()).replace("-", "")[0:16]


def generate_device_id(_lang: str) -> str:
    """Create a device identifier for the API."""
    return secrets.token_urlsafe(16) + ":APA91b" + secrets.token_urlsafe(130)[0:134]


# Operations that ARE the authentication — never require auth before calling
_AUTH_OPERATIONS = frozenset(
    {
        "mkLoginToken",
        "RefreshLogin",
        "mkSendOTP",
        "mkValidateDevice",
    }
)


class SecuritasClient:
    """Securitas Direct API client.

    Handles authentication lifecycle, typed GraphQL execution, and polling.
    Uses HttpTransport for the raw HTTP layer.
    """

    def __init__(
        self,
        transport: HttpTransport,
        country: str,
        language: str,
        username: str,
        password: str,
        *,
        device_id: str,
        uuid: str,
        id_device_indigitall: str,
        poll_delay: float = 2.0,
        poll_timeout: float = 60.0,
        log_filter: Any | None = None,
    ) -> None:
        # Transport
        self._transport = transport

        # Credentials & locale
        self.username = username
        self.password = password
        self.country = country.upper()
        self.language = language

        # Auth state
        self.authentication_token: str | None = None
        self._authentication_token_exp: datetime = datetime.min
        self.refresh_token_value: str = ""
        self.login_timestamp: int = 0
        self.protom_response: str = ""
        self.authentication_otp_challenge_value: tuple[str, str] | None = None

        # Device configuration
        self.device_id: str = device_id
        self.uuid: str = uuid
        self.id_device_indigitall: str = id_device_indigitall
        self.device_brand: str = "samsung"
        self.device_name: str = "SM-S901U"
        self.device_os_version: str = "12"
        self.device_resolution: str = ""
        self.device_type: str = ""
        self.device_version: str = "10.102.0"

        # Polling configuration
        self.poll_delay: float = poll_delay
        self.poll_timeout: float = poll_timeout

        # Capabilities tokens per installation (key: installation number)
        self._capabilities: dict[str, tuple[str, datetime]] = {}

        # Internal state
        self._apollo_operation_id: str = secrets.token_hex(64)
        self._log_filter: SensitiveDataFilter | None = log_filter

    # ── Public property for token expiry ────────────────────────────────

    @property
    def authentication_token_exp(self) -> datetime:
        """Return the authentication token expiry timestamp."""
        return self._authentication_token_exp

    @authentication_token_exp.setter
    def authentication_token_exp(self, value: datetime) -> None:
        """Set the authentication token expiry timestamp."""
        self._authentication_token_exp = value

    # ── Secret / installation registration ───────────────────────────────

    def _register_secret(self, key: str, value: str | None) -> None:
        """Register a secret with the log filter if available."""
        if self._log_filter and value:
            self._log_filter.update_secret(key, value)

    def _register_installation(self, installation: Installation) -> None:
        """Register an installation number with the log filter."""
        if self._log_filter and installation.number:
            self._log_filter.add_installation(installation.number)

    # ── Header building ──────────────────────────────────────────────────

    def _build_headers(
        self,
        operation: str,
        *,
        installation: Installation | None = None,
    ) -> dict[str, str]:
        """Build request headers for a GraphQL operation."""
        app: str = json.dumps({"appVersion": self.device_version, "origin": "native"})
        headers: dict[str, str] = {
            "app": app,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                " AppleWebKit/537.36 (KHTML, like Gecko)"
                " Chrome/102.0.5005.124 Safari/537.36"
                " Edg/102.0.1245.41"
            ),
            "X-APOLLO-OPERATION-ID": self._apollo_operation_id,
            "X-APOLLO-OPERATION-NAME": operation,
            "extension": '{"mode":"full"}',
        }

        if installation is not None:
            headers["numinst"] = installation.number
            headers["panel"] = installation.panel
            cap_entry = self._capabilities.get(installation.number)
            if cap_entry is not None:
                headers["X-Capabilities"] = cap_entry[0]

        # Auth operations that need special headers with empty hash/refreshToken.
        # Note: mkLoginToken is NOT included here — it sends credentials in
        # variables, not in the auth header. See also _AUTH_OPERATIONS which
        # includes mkLoginToken for the purpose of skipping _ensure_auth.
        if operation in {"mkValidateDevice", "RefreshLogin", "mkSendOTP"}:
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
        elif self.authentication_token is not None:
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

        if self.authentication_otp_challenge_value is not None:
            security_value = {
                "token": self.authentication_otp_challenge_value[1],
                "type": "OTP",
                "otpHash": self.authentication_otp_challenge_value[0],
            }
            headers["security"] = json.dumps(security_value)

        return headers

    # ── ID generation ────────────────────────────────────────────────────

    def _generate_id(self) -> str:
        """Generate a unique request ID."""
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

    # ── JWT decoding ─────────────────────────────────────────────────────

    def _decode_auth_token(self, token_str: str | None) -> dict[str, Any] | None:
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
            self._authentication_token_exp = datetime.fromtimestamp(decoded["exp"])
        return decoded

    # ── Response extraction ──────────────────────────────────────────────

    def _extract_response_data(
        self, response: dict[str, Any], field_name: str
    ) -> dict[str, Any]:
        """Extract and validate response['data'][field_name].

        Raises SecuritasDirectError if the data is missing or None.
        """
        data = response.get("data")
        if data is None:
            _err = SecuritasDirectError(f"{field_name}: no data in response")
            _err.response_body = response
            raise _err
        result = data.get(field_name)
        if result is None:
            _err = SecuritasDirectError(f"{field_name} response is None")
            _err.response_body = response
            raise _err
        return result

    # ── Error checking helpers ───────────────────────────────────────────

    @staticmethod
    def _is_account_blocked(result_json: dict[str, Any]) -> bool:
        """Check if a login response indicates the account is blocked (error 60052)."""
        errors = result_json.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and isinstance(first.get("data"), dict):
                return first["data"].get("err") == "60052"
        return False

    def _extract_otp_data(self, data: Any) -> tuple[str | None, list[OtpPhone]]:
        """Extract OTP hash and phone list from error data."""
        if not data:
            return (None, [])
        otp_hash = data.get("auth-otp-hash")
        phones: list[OtpPhone] = []
        for item in data.get("auth-phones", []):
            phones.append(OtpPhone(id=item["id"], phone=item["phone"]))
        return (otp_hash, phones)

    # ── GraphQL error handling ───────────────────────────────────────────

    def _check_graphql_errors(
        self,
        response_dict: dict[str, Any],
        operation: str,  # pylint: disable=unused-argument
    ) -> None:
        """Check for GraphQL-level errors in the response and raise if needed."""
        if "errors" not in response_dict:
            return

        errors = response_dict["errors"]

        # Dict-style error with data.reason
        if isinstance(errors, dict) and "data" in errors and "reason" in errors["data"]:
            _err = SecuritasDirectError(errors["data"]["reason"])
            _err.response_body = response_dict
            raise _err

        if isinstance(errors, list) and errors:
            data = response_dict.get("data")
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
                error_status = None
                if isinstance(first, dict):
                    if isinstance(first.get("data"), dict):
                        error_status = first["data"].get("status")
                    if (
                        error_status is None
                        and isinstance(first.get("extensions"), dict)
                        and first["extensions"].get("code") == "BAD_USER_INPUT"
                    ):
                        error_status = 400
                    if (
                        error_status is None
                        and isinstance(first.get("data"), dict)
                        and first["data"].get("res") == "ERROR"
                    ):
                        error_status = 400

                if error_status == 403:
                    _err = SessionExpiredError(message, http_status=403)
                    _err.response_body = response_dict
                    raise _err
                _err = SecuritasDirectError(message, http_status=error_status)
                _err.response_body = response_dict
                raise _err

    # ── Auth lifecycle ───────────────────────────────────────────────────

    async def _ensure_auth(self, installation: Installation | None = None) -> None:
        """Ensure the authentication token is valid, refreshing or logging in as needed."""
        await self._check_authentication_token()
        if installation is not None:
            await self._ensure_capabilities(installation)

    async def _check_authentication_token(self) -> None:
        """Check expiration of the authentication token and get a new one if needed."""
        if (self.authentication_token is None) or (
            datetime.now() + timedelta(minutes=1) > self._authentication_token_exp
        ):
            if self.refresh_token_value:
                _LOGGER.debug("[auth] Auth token expired, refreshing")
                try:
                    if await self.refresh_token():
                        return
                    _LOGGER.warning("Refresh token failed, falling back to login")
                except (
                    SecuritasDirectError,
                    asyncio.TimeoutError,
                ) as err:
                    _LOGGER.warning(
                        "Refresh token error, falling back to login: %s", err
                    )
            _LOGGER.debug("[auth] Auth token expired, logging in again")
            await self.login()

    async def _ensure_capabilities(self, installation: Installation) -> None:
        """Check the capabilities token and get a new one if needed."""
        entry = self._capabilities.get(installation.number)
        if entry is None or datetime.now() + timedelta(minutes=1) > entry[1]:
            _LOGGER.debug("[auth] Capabilities token expired, refreshing")
            await self.get_services(installation)

    # ── Typed GraphQL execute ────────────────────────────────────────────

    async def _execute_graphql(
        self,
        content: dict[str, Any],
        operation: str,
        response_type: type[T],
        *,
        installation: Installation | None = None,
        _retried: bool = False,
    ) -> T:
        """Execute a GraphQL operation and return a typed Pydantic envelope.

        Args:
            content: The GraphQL request body (operationName, variables, query).
            operation: Operation name for logging/headers.
            response_type: Pydantic model class to validate the response into.
            installation: Installation for capabilities token (None skips cap check).
            _retried: Internal flag to prevent infinite retry loops.

        Returns:
            A validated Pydantic model instance.
        """
        # Auth operations skip the auth check
        if operation not in _AUTH_OPERATIONS:
            await self._ensure_auth(installation)

        headers = self._build_headers(operation, installation=installation)
        response_dict = await self._transport.execute(content, headers)

        # Check for GraphQL errors — raises SessionExpiredError for 403
        try:
            self._check_graphql_errors(response_dict, operation)
        except SessionExpiredError:
            if _retried or operation in _AUTH_OPERATIONS:
                raise
            _LOGGER.debug("[auth] Session expired server-side, re-authenticating")
            self._authentication_token_exp = datetime.min
            await self._check_authentication_token()
            if installation is not None:
                await self._ensure_capabilities(installation)
            return await self._execute_graphql(
                content,
                operation,
                response_type,
                installation=installation,
                _retried=True,
            )

        # Validate as Pydantic model
        try:
            return response_type.model_validate(response_dict)
        except ValidationError as err:
            _LOGGER.error("Response validation failed: %s", err)
            _err = SecuritasDirectError(f"Invalid response for {operation}")
            _err.response_body = response_dict
            raise _err from err

    # ── Raw execute (for auth operations that don't use typed envelopes) ─

    async def _execute_raw(
        self,
        content: dict[str, Any],
        operation: str,
        *,
        installation: Installation | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL operation and return the raw dict.

        Used for auth operations (login, refresh, validate_device, send_otp)
        that need to inspect the raw response structure.
        """
        headers = self._build_headers(operation, installation=installation)
        return await self._transport.execute(content, headers)

    # ── Login ────────────────────────────────────────────────────────────

    async def login(self) -> None:
        """Login to the Securitas Direct API and set auth tokens."""
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

        response: dict[str, Any] = {}
        try:
            response = await self._execute_raw(content, "mkLoginToken")
        except SecuritasDirectError as err:
            result_json: dict[str, Any] | None = err.response_body
            if result_json is not None:
                # Check for account-blocked error (60052)
                if self._is_account_blocked(result_json):
                    _new = AccountBlockedError(err.message, http_status=err.http_status)
                    _new.response_body = result_json
                    raise _new from err
                if result_json.get("data"):
                    data = result_json["data"]
                    if data.get("xSLoginToken"):
                        if data["xSLoginToken"].get("needDeviceAuthorization"):
                            _new = TwoFactorRequiredError(
                                err.message, http_status=err.http_status
                            )
                            _new.response_body = result_json
                            raise _new from err
                    _new = AuthenticationError(err.message, http_status=err.http_status)
                    _new.response_body = result_json
                    raise _new from err
                _new = AuthenticationError(err.message, http_status=err.http_status)
                _new.response_body = result_json
                raise _new from err
            raise

        if "errors" in response:
            _LOGGER.error("Login error %s", response["errors"][0]["message"])
            _new_err = AuthenticationError(response["errors"][0]["message"])
            _new_err.response_body = response
            raise _new_err

        # Check if 2FA is required even on successful response
        login_data = self._extract_response_data(response, "xSLoginToken")
        if login_data.get("needDeviceAuthorization", False):
            _new_err = TwoFactorRequiredError("2FA authentication required")
            _new_err.response_body = response
            raise _new_err

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
            self.login_timestamp = int(datetime.now().timestamp() * 1000)

    # ── Refresh token ────────────────────────────────────────────────────

    async def refresh_token(self) -> bool:
        """Refresh the authentication token. Returns True on success."""
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
        response = await self._execute_raw(content, "RefreshLogin")

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

    # ── Logout ───────────────────────────────────────────────────────────

    async def logout(self) -> None:
        """Logout and clear authentication state."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        try:
            await self._execute_raw(content, "Logout")
        finally:
            self.authentication_token = None
            self.refresh_token_value = ""
            self._authentication_token_exp = datetime.min
            self.login_timestamp = 0

    # ── Validate device (2FA) ────────────────────────────────────────────

    async def validate_device(
        self, otp_succeed: bool, auth_otp_hash: str, sms_code: str
    ) -> tuple[str | None, list[OtpPhone] | None]:
        """Validate the device with 2FA."""
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
            response = await self._execute_raw(content, "mkValidateDevice")
            self.authentication_otp_challenge_value = None
        except SecuritasDirectError as err:
            if err.response_body is not None:
                try:
                    error_data = err.response_body["errors"][0]["data"]
                    if "auth-otp-hash" in error_data or "auth-phones" in error_data:
                        return self._extract_otp_data(error_data)
                except (KeyError, IndexError, TypeError):
                    pass
            raise

        if "errors" in response and response["errors"][0]["message"] == "Unauthorized":
            return self._extract_otp_data(response["errors"][0]["data"])

        validate_data = self._extract_response_data(response, "xSValidateDevice")
        self.authentication_token = validate_data["hash"]
        self._register_secret("auth_token", self.authentication_token)
        self._decode_auth_token(self.authentication_token)
        if validate_data.get("refreshToken"):
            self.refresh_token_value = validate_data["refreshToken"]
            self._register_secret("refresh_token", self.refresh_token_value)
        return (None, None)

    # ── Send OTP ─────────────────────────────────────────────────────────

    async def send_otp(self, device_id: int, auth_otp_hash: str) -> str:
        """Send the OTP device challenge."""
        content = {
            "operationName": "mkSendOTP",
            "variables": {
                "recordId": device_id,
                "otpHash": auth_otp_hash,
            },
            "query": SEND_OTP_MUTATION,
        }
        response = await self._execute_raw(content, "mkSendOTP")

        otp_data = self._extract_response_data(response, "xSSendOtp")
        return otp_data["res"]

    # ── Poll operation ───────────────────────────────────────────────────

    async def _poll_operation(
        self,
        check_fn: Any,
        *,
        timeout: float | None = None,
        continue_on_msg: str | None = None,
    ) -> dict[str, Any]:
        """Poll check_fn until result is no longer WAIT.

        Args:
            check_fn: Async callable that returns a dict with at least 'res' key.
            timeout: Wall-clock timeout in seconds (defaults to poll_timeout).
            continue_on_msg: If set, also continue polling when response 'msg'
                matches this value.

        Returns:
            The final poll result dict.

        Raises:
            OperationTimeoutError: If wall-clock timeout is exceeded.
            SecuritasDirectError: If a non-transient error occurs.
        """
        if timeout is None:
            timeout = self.poll_timeout

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        result: dict[str, Any] = {}
        first = True

        while True:
            if not first and loop.time() > deadline:
                raise OperationTimeoutError(
                    f"Poll operation timed out after {timeout}s, "
                    f"last response: {result}"
                )
            if not first:
                await asyncio.sleep(self.poll_delay)
            try:
                result = await check_fn()
            except (ClientConnectorError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Transient error during poll, retrying: %s", err)
                first = False
                continue
            except SecuritasDirectError as err:
                if err.http_status == 409:
                    _LOGGER.warning(
                        "Transient error (409) during poll, retrying: %s",
                        err.log_detail(),
                    )
                    first = False
                    continue
                raise

            first = False

            if result.get("res") == "WAIT":
                continue
            if continue_on_msg and result.get("msg") == continue_on_msg:
                continue
            break

        return result

    # ── Alarm operations ──────────────────────────────────────────────────

    async def arm(
        self,
        installation: Installation,
        command: str,
        *,
        force_id: str | None = None,
        suid: str | None = None,
    ) -> OperationStatus:
        """Arm the alarm panel.

        Submits the ARM mutation, then polls ARM status until complete.

        Args:
            installation: The installation to arm.
            command: Arm command string (e.g. "ARM1", "ARMDAY1").
            force_id: Optional forceArmingRemoteId to override exceptions.
            suid: Optional SUID for exception handling.

        Returns:
            OperationStatus with the final arm result.

        Raises:
            ArmingExceptionError: If arming blocked by non-blocking exceptions.
            SecuritasDirectError: If arming fails with a blocking error.
            OperationTimeoutError: If polling times out.
        """
        # ── Submit arm request ──
        variables: dict[str, Any] = {
            "request": command,
            "numinst": installation.number,
            "panel": installation.panel,
            "currentStatus": self.protom_response,
            "armAndLock": False,
        }
        if force_id is not None:
            variables["forceArmingRemoteId"] = force_id
        if suid is not None:
            variables["suid"] = suid

        content = {
            "operationName": "xSArmPanel",
            "variables": variables,
            "query": ARM_PANEL_MUTATION,
        }
        envelope = await self._execute_graphql(
            content, "xSArmPanel", ArmPanelEnvelope, installation=installation
        )
        reference_id = envelope.data.xSArmPanel.reference_id

        # ── Poll arm status ──
        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            poll_vars: dict[str, Any] = {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "referenceId": reference_id,
                "counter": counter,
                "armAndLock": False,
            }
            if force_id is not None:
                poll_vars["forceArmingRemoteId"] = force_id

            poll_content = {
                "operationName": "ArmStatus",
                "variables": poll_vars,
                "query": ARM_STATUS_QUERY,
            }
            response = await self._execute_raw(
                poll_content, "ArmStatus", installation=installation
            )
            return self._extract_response_data(response, "xSArmStatus")

        raw = await self._poll_operation(_check)

        # ── Process result ──
        error = raw.get("error")
        if raw.get("res") == "ERROR":
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
                    f"Arm command failed: {raw.get('msg', 'unknown error')}"
                )

        self.protom_response = raw["protomResponse"]
        return OperationStatus.model_validate(raw)

    async def disarm(
        self,
        installation: Installation,
        command: str,
    ) -> OperationStatus:
        """Disarm the alarm panel.

        Submits the DISARM mutation, then polls DISARM status until complete.

        Args:
            installation: The installation to disarm.
            command: Disarm command string (e.g. "DARM1", "DARM1DARMPERI").

        Returns:
            OperationStatus with the final disarm result.

        Raises:
            SecuritasDirectError: If disarming fails with a blocking error.
            OperationTimeoutError: If polling times out.
        """
        # Capture current status at request time for consistent polling
        current_status = self.protom_response

        # ── Submit disarm request ──
        content = {
            "operationName": "xSDisarmPanel",
            "variables": {
                "request": command,
                "numinst": installation.number,
                "panel": installation.panel,
                "currentStatus": current_status,
            },
            "query": DISARM_PANEL_MUTATION,
        }
        envelope = await self._execute_graphql(
            content, "xSDisarmPanel", DisarmPanelEnvelope, installation=installation
        )
        reference_id = envelope.data.xSDisarmPanel.reference_id

        # ── Poll disarm status ──
        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            poll_content = {
                "operationName": "DisarmStatus",
                "variables": {
                    "request": command,
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "currentStatus": current_status,
                    "referenceId": reference_id,
                    "counter": counter,
                },
                "query": DISARM_STATUS_QUERY,
            }
            response = await self._execute_raw(
                poll_content, "DisarmStatus", installation=installation
            )
            return self._extract_response_data(response, "xSDisarmStatus")

        raw = await self._poll_operation(_check)

        # ── Process result ──
        if raw.get("res") == "ERROR":
            error_info = raw.get("error") or {}
            if error_info.get("type") != "NON_BLOCKING":
                raise SecuritasDirectError(
                    f"Disarm command failed: {raw.get('msg', 'unknown error')}"
                )

        if raw.get("protomResponse"):
            self.protom_response = raw["protomResponse"]
        return OperationStatus.model_validate(raw)

    async def check_alarm(self, installation: Installation) -> OperationStatus:
        """Check the current alarm status by querying the panel.

        Submits a CHECK_ALARM query, then polls until the panel responds.

        Returns:
            OperationStatus with the current alarm state.

        Raises:
            OperationTimeoutError: If polling times out.
        """
        # ── Submit check alarm request ──
        content = {
            "operationName": "CheckAlarm",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": CHECK_ALARM_QUERY,
        }
        envelope = await self._execute_graphql(
            content, "CheckAlarm", CheckAlarmEnvelope, installation=installation
        )
        reference_id = envelope.data.xSCheckAlarm.reference_id

        # ── Poll check alarm status ──
        async def _check() -> dict[str, Any]:
            poll_content = {
                "operationName": "CheckAlarmStatus",
                "variables": {
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "referenceId": reference_id,
                    "idService": ALARM_STATUS_SERVICE_ID,
                },
                "query": CHECK_ALARM_STATUS_QUERY,
            }
            response = await self._execute_raw(
                poll_content, "CheckAlarmStatus", installation=installation
            )
            return self._extract_response_data(response, "xSCheckAlarmStatus")

        raw = await self._poll_operation(_check)

        self.protom_response = raw["protomResponse"]
        return OperationStatus.model_validate(raw)

    async def get_general_status(self, installation: Installation) -> SStatus:
        """Get the general alarm status (single call, no polling).

        Returns:
            SStatus with current status, timestamp, and wifi connectivity.
        """
        content = {
            "operationName": "Status",
            "variables": {"numinst": installation.number},
            "query": GENERAL_STATUS_QUERY,
        }
        envelope = await self._execute_graphql(
            content, "Status", GeneralStatusEnvelope, installation=installation
        )
        raw_data = envelope.data.xSStatus
        return SStatus.model_validate(raw_data.model_dump(by_alias=True))

    async def _get_exceptions(
        self,
        installation: Installation,
        reference_id: str,
        suid: str,
    ) -> list[dict[str, Any]]:
        """Fetch arming exception details (e.g. open windows/doors).

        Polls until the exceptions list is non-empty or the result is not WAIT.
        """
        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            content = {
                "operationName": "xSGetExceptions",
                "variables": {
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "referenceId": reference_id,
                    "counter": counter,
                    "suid": suid,
                },
                "query": GET_EXCEPTIONS_QUERY,
            }
            response = await self._execute_raw(
                content, "xSGetExceptions", installation=installation
            )
            data = self._extract_response_data(response, "xSGetExceptions")
            return data

        raw = await self._poll_operation(_check)
        return raw.get("exceptions") or []

    # ── Lock operations ────────────────────────────────────────────────────

    async def get_lock_modes(self, installation: Installation) -> list[SmartLockMode]:
        """Get the current mode of all smart locks.

        Returns:
            A list of SmartLockMode instances, one per lock device.
        """
        content = {
            "operationName": "xSGetLockCurrentMode",
            "variables": {
                "numinst": installation.number,
            },
            "query": LOCK_CURRENT_MODE_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "xSGetLockCurrentMode",
            LockModeEnvelope,
            installation=installation,
        )
        smartlock_info = envelope.data.xSGetLockCurrentMode.smartlock_info
        if not smartlock_info:
            return []
        # Skip phantom entries with null lockStatus (e.g. SmartLock Tácito)
        return [
            SmartLockMode.model_validate(item)
            for item in smartlock_info
            if item.get("lockStatus") is not None
        ]

    async def get_lock_config(
        self,
        installation: Installation,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> SmartLock:
        """Fetch lock configuration, auto-detecting Smartlock vs Danalock API.

        Tries the fast xSGetSmartlockConfig query first.  If that returns a
        non-OK result or raises, falls back to the Danalock two-phase polling
        API.  Returns an empty SmartLock() if both paths fail.

        Args:
            installation: The installation to query.
            device_id: Lock device ID (defaults to SMARTLOCK_DEVICE_ID).

        Returns:
            SmartLock with lock configuration details, or empty SmartLock().
        """
        # ── Smartlock fast path ──
        try:
            smartlock_content = {
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
            envelope = await self._execute_graphql(
                smartlock_content,
                "xSGetSmartlockConfig",
                SmartlockConfigEnvelope,
                installation=installation,
            )
            config = envelope.data.xSGetSmartlockConfig
            if config.res == "OK":
                return config
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "Smartlock config fetch failed for %s device %s, trying Danalock",
                installation.number,
                device_id,
                exc_info=True,
            )

        # ── Danalock fallback (two-phase polling) ──
        try:
            return await self._get_danalock_config(installation, device_id)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _LOGGER.debug(
                "Danalock config fetch also failed for %s device %s",
                installation.number,
                device_id,
                exc_info=True,
            )

        return SmartLock()

    async def _get_danalock_config(
        self,
        installation: Installation,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> SmartLock:
        """Fetch Danalock config via submit + poll.

        Returns:
            SmartLock with lock configuration, or SmartLock() on failure.
        """
        # Submit danalock config request
        submit_content = {
            "operationName": "xSGetDanalockConfig",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "deviceType": SMARTLOCK_DEVICE_TYPE,
                "deviceId": device_id,
            },
            "query": DANALOCK_CONFIG_QUERY,
        }
        envelope = await self._execute_graphql(
            submit_content,
            "xSGetDanalockConfig",
            DanalockConfigEnvelope,
            installation=installation,
        )
        reference_id = envelope.data.xSGetDanalockConfig.reference_id

        # Poll for status
        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            poll_content = {
                "operationName": "xSGetDanalockConfigStatus",
                "variables": {
                    "numinst": installation.number,
                    "referenceId": reference_id,
                    "counter": counter,
                },
                "query": DANALOCK_CONFIG_STATUS_QUERY,
            }
            response = await self._execute_raw(
                poll_content,
                "xSGetDanalockConfigStatus",
                installation=installation,
            )
            return self._extract_response_data(response, "xSGetDanalockConfigStatus")

        raw = await self._poll_operation(_check)

        if raw.get("res") != "OK":
            return SmartLock()

        return SmartLock(
            res=raw.get("res"),
            device_id=raw.get("deviceNumber") or device_id,
            features=LockFeatures.model_validate(raw["features"])
            if raw.get("features")
            else None,
        )

    async def change_lock_mode(
        self,
        installation: Installation,
        lock: bool,
        device_id: str = SMARTLOCK_DEVICE_ID,
    ) -> SmartLockModeStatus:
        """Send lock/unlock command and poll until the backend responds.

        Args:
            installation: The installation containing the lock.
            lock: True to lock, False to unlock.
            device_id: Lock device ID (defaults to SMARTLOCK_DEVICE_ID).

        Returns:
            SmartLockModeStatus with the final operation result.

        Raises:
            OperationTimeoutError: If polling times out.
        """
        # ── Submit change lock mode request ──
        submit_content = {
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
        envelope = await self._execute_graphql(
            submit_content,
            "xSChangeSmartlockMode",
            ChangeLockModeEnvelope,
            installation=installation,
        )
        reference_id = envelope.data.xSChangeSmartlockMode.reference_id

        # ── Poll change lock mode status ──
        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            poll_content = {
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
            response = await self._execute_raw(
                poll_content,
                "xSChangeSmartlockModeStatus",
                installation=installation,
            )
            return self._extract_response_data(response, "xSChangeSmartlockModeStatus")

        raw = await self._poll_operation(_check)

        # ── Process result ──
        self.protom_response = raw["protomResponse"]
        return SmartLockModeStatus.model_validate(raw)

    # ── Camera operations ──────────────────────────────────────────────────

    async def get_camera_devices(
        self, installation: Installation
    ) -> list[CameraDevice]:
        """Get list of camera devices (QR, YR, YP, QP) for an installation.

        Returns:
            A list of CameraDevice instances for active camera devices.
        """
        content = {
            "operationName": "xSDeviceList",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": DEVICE_LIST_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "xSDeviceList",
            DeviceListEnvelope,
            installation=installation,
        )
        devices = envelope.data.xSDeviceList.devices or []
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

    async def capture_image(
        self,
        installation: Installation,
        device_code: int,
        device_type: str,
        zone_id: str,
        *,
        capture_timeout: float = 90.0,
    ) -> ThumbnailResponse:
        """Request a new image capture and poll until the thumbnail updates.

        Follows the flow: get baseline thumbnail -> submit capture request ->
        poll capture status until not processing -> poll thumbnail until
        idSignal changes from baseline.

        Args:
            installation: The installation containing the camera.
            device_code: Camera device code.
            device_type: Camera device type (e.g. "QR", "YR").
            zone_id: Camera zone ID.
            capture_timeout: Wall-clock timeout for the entire flow (default 30s).

        Returns:
            The new ThumbnailResponse (or baseline if timed out).
        """
        # Submit capture request
        submit_content = {
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
        submit_envelope = await self._execute_graphql(
            submit_content,
            "RequestImages",
            RequestImagesEnvelope,
            installation=installation,
        )
        reference_id = submit_envelope.data.xSRequestImages.reference_id

        thumbnail: ThumbnailResponse | None = None

        async def _poll_capture_result() -> None:
            nonlocal thumbnail
            counter = 0

            # Poll status at 10s intervals until it transitions from
            # "processing" to done (~40-60s for YR/PIR cameras).
            # Then fetch the thumbnail once.
            while True:
                counter += 1
                status_content = {
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
                status_envelope = await self._execute_graphql(
                    status_content,
                    "RequestImagesStatus",
                    RequestImagesStatusEnvelope,
                    installation=installation,
                )
                inner = status_envelope.data.xSRequestImagesStatus
                msg = inner.msg or ""
                if "processing" not in msg and inner.res != "WAIT":
                    break
                await asyncio.sleep(10)

            # Status done — fetch the updated thumbnail
            thumbnail = await self.get_thumbnail(installation, device_type, zone_id)

        try:
            await asyncio.wait_for(_poll_capture_result(), timeout=capture_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            _LOGGER.warning(
                "Image capture timed out after %.0f seconds for %s",
                capture_timeout,
                zone_id,
            )
            if thumbnail is None:
                # Status polling consumed the entire timeout — fetch one
                # final thumbnail as the CDN may have caught up.
                thumbnail = await self.get_thumbnail(installation, device_type, zone_id)

        return thumbnail  # type: ignore[return-value]

    async def get_thumbnail(
        self,
        installation: Installation,
        device_type: str,
        zone_id: str,
    ) -> ThumbnailResponse:
        """Fetch the latest thumbnail image for a camera device.

        Args:
            installation: The installation to query.
            device_type: Camera device type string (e.g. "QR").
            zone_id: Camera zone ID.

        Returns:
            ThumbnailResponse with image data and metadata.
        """
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
        envelope = await self._execute_graphql(
            content,
            "mkGetThumbnail",
            ThumbnailEnvelope,
            installation=installation,
        )
        return envelope.data.xSGetThumbnail

    async def get_full_image(
        self,
        installation: Installation,
        id_signal: str,
        signal_type: str,
    ) -> bytes | None:
        """Fetch full-resolution images for a completed capture.

        Selects the largest BINARY image, base64-decodes it, and validates
        JPEG magic bytes.

        Args:
            installation: The installation to query.
            id_signal: The idSignal from a ThumbnailResponse.
            signal_type: The signalType from a ThumbnailResponse.

        Returns:
            Decoded JPEG bytes, or None if no valid image found.
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
        envelope = await self._execute_graphql(
            content,
            "mkGetPhotoImages",
            PhotoImagesEnvelope,
            installation=installation,
        )
        devices = envelope.data.xSGetPhotoImages.devices or []
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
            decoded = base64.b64decode(best["image"])
        except (ValueError, TypeError):
            return None
        # Validate JPEG magic bytes
        if not decoded[:2] == b"\xff\xd8":
            return None
        return decoded

    # ── Sensor operations ────────────────────────────────────────────────────

    async def get_sentinel_data(
        self,
        installation: Installation,
        service: Service,
    ) -> Sentinel:
        """Get sentinel environmental sensor data.

        Args:
            installation: The installation to query.
            service: The sentinel service (uses first attribute for zone).

        Returns:
            Sentinel with temperature, humidity, and air quality.
        """
        content = {
            "operationName": "Sentinel",
            "variables": {
                "numinst": installation.number,
            },
            "query": SENTINEL_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "Sentinel",
            SentinelEnvelope,
            installation=installation,
        )
        comfort_data = envelope.data.xSComfort
        empty = Sentinel(alias="", air_quality="", humidity=0, temperature=0)

        if not service.attributes or not isinstance(service.attributes, list):
            _LOGGER.warning("No attributes found for sentinel service %s", service.id)
            return empty

        zone = service.attributes[0].value
        devices = comfort_data.devices or []
        target_device = None
        for device in devices:
            if device.get("zone") == zone:
                target_device = device
                break

        if target_device is None:
            return empty

        air_quality_code = target_device["status"].get("airQualityCode")
        return Sentinel(
            alias=target_device["alias"],
            air_quality=str(air_quality_code) if air_quality_code is not None else "",
            humidity=int(target_device["status"]["humidity"]),
            temperature=int(target_device["status"]["temperature"]),
            zone=target_device.get("zone", ""),
        )

    async def get_air_quality_data(
        self,
        installation: Installation,
        zone: str,
    ) -> AirQuality | None:
        """Get air quality data from xSAirQuality API.

        Args:
            installation: The installation to query.
            zone: Zone identifier string.

        Returns:
            AirQuality with latest reading, or None if no data available.
        """
        content = {
            "operationName": "AirQuality",
            "variables": {
                "numinst": installation.number,
                "zone": zone,
            },
            "query": AIR_QUALITY_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "AirQuality",
            AirQualityEnvelope,
            installation=installation,
        )
        aq_inner = envelope.data.xSAirQuality
        aq_data = aq_inner.data
        if aq_data is None:
            return None

        # hours may be null for some installations while status is still valid
        value: int | None = None
        hours = aq_data.get("hours") or []
        if hours:
            try:
                value = int(hours[-1].get("value", 0))
            except (ValueError, TypeError):
                pass

        status = aq_data.get("status", {})
        return AirQuality(
            value=value,
            status_current=int(status.get("current", 0)),
        )

    # ── Installation / Services operations ───────────────────────────────────

    async def list_installations(self) -> list[Installation]:
        """List all securitas direct installations.

        Returns:
            A list of Installation instances.
        """
        content = {
            "operationName": "mkInstallationList",
            "query": INSTALLATION_LIST_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "mkInstallationList",
            InstallationListEnvelope,
        )
        return list(envelope.data.xSInstallations.installations)

    async def get_services(self, installation: Installation) -> list[Service]:
        """Fetch services for an installation.

        Calls xSSrv, extracts the capabilities JWT token and stores it in
        ``self._capabilities[installation.number]``, extracts alarm partitions,
        and builds the Service list.

        Args:
            installation: The installation to query.

        Returns:
            A list of Service instances.
        """
        content = {
            "operationName": "Srv",
            "variables": {"numinst": installation.number, "uuid": self.uuid},
            "query": SERVICES_QUERY,
        }
        await self._check_authentication_token()
        self._register_installation(installation)
        response = await self._execute_raw(content, "Srv", installation=installation)

        installation_data = (response.get("data") or {}).get("xSSrv") or {}
        installation_data = installation_data.get("installation")
        if installation_data is None:
            _LOGGER.warning(
                "API returned no installation data for %s", installation.number
            )
            return []

        raw_data = installation_data.get("services")
        if raw_data is None:
            _LOGGER.warning("API returned no services for %s", installation.number)
            return []

        capabilities = installation_data.get("capabilities")
        if capabilities is None:
            _LOGGER.warning("API returned no capabilities for %s", installation.number)
            return []

        # Decode capabilities JWT and store in self._capabilities
        try:
            token = jwt.decode(
                capabilities,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
        except jwt.exceptions.DecodeError as err:
            raise SecuritasDirectError("Failed to decode capabilities token") from err

        expiry = datetime.min
        if "exp" in token:
            expiry = datetime.fromtimestamp(token["exp"])

        self._capabilities[installation.number] = (capabilities, expiry)

        # Build service list
        result: list[Service] = []
        for item in raw_data:
            attribute_list: list[Attribute] = []
            attributes = item.get("attributes")
            if attributes and attributes.get("attributes"):
                for attr_item in attributes["attributes"]:
                    attribute_list.append(
                        Attribute(
                            name=attr_item["name"],
                            value=attr_item["value"],
                            active=bool(attr_item["active"]),
                        )
                    )

            result.append(
                Service(
                    id=int(item["idService"]),
                    id_service=int(item["idService"]),
                    active=bool(item["active"]),
                    visible=bool(item["visible"]),
                    bde=bool(item["bde"]),
                    is_premium=bool(item["isPremium"]),
                    cod_oper=bool(item["codOper"]),
                    total_device=int(item.get("totalDevice", 0)),
                    request=item["request"],
                    multiple_req=False,
                    num_devices_mr=0,
                    secret_word=False,
                    min_wrapper_version=item["minWrapperVersion"],
                    description=item.get("description", ""),
                    attributes=attribute_list,
                    listdiy=[],
                    listprompt=[],
                    installation=installation,
                )
            )
        return result
