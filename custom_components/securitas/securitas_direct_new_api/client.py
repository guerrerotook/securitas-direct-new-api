"""SecuritasClient — unified API client with auth lifecycle and typed execute.

Composes an HttpTransport for the raw HTTP layer.  Business methods (arm,
disarm, lock, camera, etc.) will be added in later tasks.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError
import jwt

from .exceptions import (
    AccountBlockedError,
    AuthenticationError,
    OperationTimeoutError,
    SecuritasDirectError,
    TwoFactorRequiredError,
)
from .graphql_queries import (
    LOGIN_TOKEN_MUTATION,
    REFRESH_LOGIN_MUTATION,
    SEND_OTP_MUTATION,
    VALIDATE_DEVICE_MUTATION,
)
from .http_transport import HttpTransport
from .models import Installation, OtpPhone

if TYPE_CHECKING:
    from custom_components.securitas.log_filter import SensitiveDataFilter

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# API protocol constants
API_CALLBY = "OWA_10"
API_ID_PREFIX = "OWA_______________"

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
        self.device_brand: str = "Samsung"
        self.device_name: str = "S22"
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
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
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
            self._authentication_token_exp = datetime.fromtimestamp(decoded["exp"])
        return decoded

    # ── Response extraction ──────────────────────────────────────────────

    def _extract_response_data(self, response: dict, field_name: str) -> dict:
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
    def _is_account_blocked(result_json: dict) -> bool:
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
        operation: str,
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

        # Check for GraphQL errors
        self._check_graphql_errors(response_dict, operation)

        # Session expired (403): re-auth and retry once
        if "errors" in response_dict and not _retried:
            errors = response_dict.get("errors", [])
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    error_status = None
                    if isinstance(first.get("data"), dict):
                        error_status = first["data"].get("status")
                    if error_status == 403 and operation not in _AUTH_OPERATIONS:
                        _LOGGER.debug(
                            "[auth] Session expired server-side, re-authenticating"
                        )
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
            result_json: dict | None = err.response_body
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
            except asyncio.TimeoutError as err:
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

    # ── Stub: get_services (full implementation in Task 5) ───────────────

    async def get_services(self, installation: Any) -> list[Any]:
        """Fetch services for an installation. Stub -- full implementation in Task 5."""
        raise NotImplementedError("get_services will be implemented in Task 5")
