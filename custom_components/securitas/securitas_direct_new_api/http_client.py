"""Securitas Direct HTTP transport layer.

Contains the base HTTP client with authentication, request execution,
response extraction, and polling logic. Business-logic methods live in
ApiManager, which inherits from this class.

Note: _check_authentication_token calls self.login() / self.refresh_token()
and _check_capabilities_token calls self.get_all_services() — these are
defined in the ApiManager subclass and resolved at runtime via Python's MRO.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from custom_components.securitas.log_filter import SensitiveDataFilter

from aiohttp import ClientConnectorError, ClientSession
import jwt

from .dataTypes import Installation
from .domains import ApiDomains
from .exceptions import SecuritasDirectError

_LOGGER = logging.getLogger(__name__)

# API protocol constants
API_CALLBY = "OWA_10"
API_ID_PREFIX = "OWA_______________"

# Keys whose values should be replaced with a placeholder in debug logs
_LOG_TRUNCATE_KEYS = {"hours", "image"}


def _sanitize_response_for_log(response_text: str) -> str:
    """Replace large fields in a JSON response with a placeholder for logging."""
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        return response_text

    def _truncate(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (["..."] if isinstance(v, list) else "...")
                if k in _LOG_TRUNCATE_KEYS
                else _truncate(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_truncate(item) for item in obj]
        return obj

    return json.dumps(_truncate(data))


class SecuritasHttpClient:
    """HTTP transport layer for the Securitas Direct API.

    Handles authentication tokens, HTTP request execution with retries,
    GraphQL response extraction, and generic polling.

    Subclasses must implement: login(), refresh_token(), get_all_services().
    """

    async def login(self) -> dict[str, Any] | None:
        """Login to the API. Implemented by ApiManager."""
        raise NotImplementedError

    async def refresh_token(self) -> bool:
        """Refresh the authentication token. Implemented by ApiManager."""
        raise NotImplementedError

    async def get_all_services(self, installation: Installation) -> Any:
        """Get all services for an installation. Implemented by ApiManager."""
        raise NotImplementedError

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
        """Create the HTTP client."""
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
        self,
        content,
        operation: str,
        installation: Optional[Installation] = None,
        _retried: bool = False,
    ) -> dict[str, Any]:
        """Send request to Securitas' API."""

        app: str = json.dumps({"appVersion": self.device_version, "origin": "native"})
        headers = {
            "app": app,
            "User-Agent": (
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                " AppleWebKit/537.36 (KHTML, like Gecko)"
                " Chrome/102.0.5005.124 Safari/537.36"
                " Edg/102.0.1245.41"
            ),
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

        log_prefix = (
            f"[{operation}:{installation.alias}]"
            if installation is not None
            else f"[{operation}]"
        )
        # Retry once on HTTP 403 (Incapsula WAF rate limiting)
        response_text = ""
        for attempt in range(2):
            try:
                async with self.http_client.post(
                    self.api_url, headers=headers, json=content
                ) as response:
                    http_status: int = response.status
                    response_text: str = await response.text()
            except ClientConnectorError as err:
                os_err = err.os_error or err.strerror or "unknown"
                # --- TEMPORARY DEBUG: full connection failure diagnostics ---
                _LOGGER.debug(
                    "%s ClientConnectorError DETAIL: host=%r port=%r ssl=%r"
                    " | err=%s"
                    " | os_error class=%s errno=%r strerror=%r"
                    " | cause=%r"
                    " | request_headers=%s",
                    log_prefix,
                    getattr(err, "host", "?"),
                    getattr(err, "port", "?"),
                    getattr(err, "ssl", "?"),
                    err,
                    type(err.os_error).__name__ if err.os_error else "None",
                    getattr(err.os_error, "errno", None) if err.os_error else None,
                    getattr(err.os_error, "strerror", None) if err.os_error else None,
                    repr(err.__cause__),
                    {
                        k: v
                        for k, v in headers.items()
                        if k not in ("auth", "X-Capabilities")
                    },
                    exc_info=True,
                )
                # --- END TEMPORARY DEBUG ---
                raise SecuritasDirectError(
                    f"Connection error with URL {self.api_url}: {os_err}",
                    None,
                    headers,
                    content,
                ) from err

            _LOGGER.debug(
                "%s response=%s",
                log_prefix,
                _sanitize_response_for_log(response_text),
            )

            if http_status == 403 and attempt == 0:
                # Incapsula WAF blocks return HTML — retrying immediately
                # just adds more requests that extend the block.  Only retry
                # for non-WAF 403s (e.g. server-side rate limit with
                # Retry-After header).
                if "_Incapsula_Resource" in response_text:
                    _LOGGER.warning(
                        "%s HTTP 403 WAF block (not retrying — WAF blocks require longer backoff)",
                        log_prefix,
                    )
                    raise SecuritasDirectError(
                        f"HTTP {http_status} from Securitas API ({operation})",
                        None,
                        headers,
                        content,
                        http_status=http_status,
                    )
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = int(retry_after) if retry_after else 2
                except (ValueError, TypeError):
                    delay = 2
                _LOGGER.warning(
                    "%s HTTP 403, retrying in %ds",
                    log_prefix,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if http_status >= 400:
                _LOGGER.debug(
                    "%s HTTP %d error: %s",
                    log_prefix,
                    http_status,
                    response_text[:500],
                )
                raise SecuritasDirectError(
                    f"HTTP {http_status} from Securitas API ({operation})",
                    None,
                    headers,
                    content,
                    http_status=http_status,
                )

            break  # Success

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
            if isinstance(errors, list) and errors:
                # GraphQL error response. When there's no "data" key at all, it's
                # a pure validation error (e.g. BAD_USER_INPUT). When there IS a
                # data key, only raise when all values are null/empty (partial
                # responses with valid data are handled by callers).
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
                    # Extract HTTP-like status from GraphQL error data
                    error_status = None
                    if isinstance(first, dict):
                        if isinstance(first.get("data"), dict):
                            error_status = first["data"].get("status")
                        # BAD_USER_INPUT = command not in panel's enum
                        if (
                            error_status is None
                            and isinstance(first.get("extensions"), dict)
                            and first["extensions"].get("code") == "BAD_USER_INPUT"
                        ):
                            error_status = 400
                        # Application-level rejection (e.g. "not valid for Central Unit")
                        if (
                            error_status is None
                            and isinstance(first.get("data"), dict)
                            and first["data"].get("res") == "ERROR"
                        ):
                            error_status = 400

                    # Session expired server-side: re-authenticate and retry once
                    if error_status == 403 and not _retried:
                        _LOGGER.debug(
                            "[auth] Session expired server-side, re-authenticating"
                        )
                        self.authentication_token_exp = datetime.min
                        await self._check_authentication_token()
                        if installation is not None:
                            await self._check_capabilities_token(installation)
                        return await self._execute_request(
                            content, operation, installation=installation, _retried=True
                        )

                    raise SecuritasDirectError(
                        message,
                        response_dict,
                        headers,
                        content,
                        http_status=error_status,
                    )

        return response_dict

    async def _ensure_auth(self, installation: Installation) -> None:
        """Ensure both authentication and capabilities tokens are valid."""
        await self._check_authentication_token()
        await self._check_capabilities_token(installation)

    async def _execute_graphql(
        self,
        content: dict[str, Any],
        operation_name: str,
        response_field: str,
        installation: Installation | None = None,
        *,
        check_ok: bool = True,
    ) -> dict[str, Any]:
        """Execute a GraphQL operation with auth, request, and response extraction.

        Args:
            content: The GraphQL request body (operationName, variables, query).
            operation_name: Operation name for logging/headers.
            response_field: The key under response["data"] to extract.
            installation: Installation for capabilities token (None skips cap check).
            check_ok: If True, raise SecuritasDirectError when res != "OK".

        Returns:
            The extracted response data dict.
        """
        if installation is not None:
            await self._ensure_auth(installation)
        else:
            await self._check_authentication_token()

        response = await self._execute_request(content, operation_name, installation)
        data = self._extract_response_data(response, response_field)

        if check_ok and data.get("res") != "OK":
            raise SecuritasDirectError(
                data.get("msg", f"{operation_name} failed"), response
            )

        return data

    async def _check_capabilities_token(self, installation: Installation) -> None:
        """Check the capabilities token and get a new one if needed."""

        if (installation.capabilities == "") or (
            datetime.now() + timedelta(minutes=1) > installation.capabilities_exp
        ):
            _LOGGER.debug("[auth] Capabilities token expired, refreshing")
            await self.get_all_services(installation)

    async def _check_authentication_token(self) -> None:
        """Check expiration of the authentication token and get a new one if needed."""

        if (self.authentication_token is None) or (
            datetime.now() + timedelta(minutes=1) > self.authentication_token_exp
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
                    ClientConnectorError,
                ) as err:
                    _LOGGER.warning(
                        "Refresh token error, falling back to login: %s", err
                    )
            _LOGGER.debug("[auth] Auth token expired, logging in again")
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
            raise SecuritasDirectError(f"{field_name}: no data in response", response)
        result = data.get(field_name)
        if result is None:
            raise SecuritasDirectError(f"{field_name} response is None", response)
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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        result: dict[str, Any] = {}
        first = True

        while True:
            if not first and loop.time() > deadline:
                raise TimeoutError(
                    f"Poll operation timed out after {timeout}s, "
                    f"last response: {result}"
                )
            if not first:
                await asyncio.sleep(self.delay_check_operation)
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
