"""Shared client base: auth lifecycle, headers, GraphQL execute, polling.

Domain mixins (auth, alarm, lock, camera, sentinel, activity, installation)
each extend ``_ClientBase`` so they have access to ``self._execute_graphql``,
``self._build_headers`` and the rest of the shared infrastructure.
``VerisureOwaClient`` in ``__init__.py`` then composes all the mixins.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

from aiohttp import ClientConnectorError
from pydantic import BaseModel, ValidationError
import jwt

from ..exceptions import (
    OperationTimeoutError,
    SessionExpiredError,
    VerisureOwaError,
    _error_code_from_body,
    is_genuine_auth_failure,
)
from ..http_transport import HttpTransport
from ..models import Installation, OtpPhone

if TYPE_CHECKING:
    from custom_components.securitas.log_filter import SensitiveDataFilter

_LOGGER = logging.getLogger(__name__)


def _format_graphql_error(
    field_name: str, response: dict[str, Any], fallback: str
) -> str:
    """Build a human-readable error string from a GraphQL response.

    Prefers the first entry of the response's ``errors`` array (message
    + err code), falling back to ``fallback`` when no errors array is
    present.  Used by ``_extract_response_data`` so logs surface
    server-side reasons like ``Invalid Session (err=60067)`` rather
    than the misleading ``response is None``.
    """
    errors = response.get("errors") if isinstance(response, dict) else None
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = first.get("message")
        data = first.get("data") if isinstance(first.get("data"), dict) else {}
        code = data.get("err") if isinstance(data, dict) else None
        if message and code:
            return f"{field_name} failed: {message} (err={code})"
        if message:
            return f"{field_name} failed: {message}"
    return fallback


T = TypeVar("T", bound=BaseModel)

# API protocol constants
API_CALLBY = "OWA_10"
API_ID_PREFIX = "OWA_______________"
ALARM_STATUS_SERVICE_ID = "11"

# Auth-recovery observability. A transient failure on the refresh/login path
# increments a streak counter; once it reaches the threshold we emit a louder,
# throttled WARNING so a misclassified dead session stays visible despite HA's
# UpdateFailed repeat-suppression.
_AUTH_ESCALATION_THRESHOLD = 3
_AUTH_ESCALATION_INTERVAL = timedelta(minutes=30)
_ISSUES_URL = "https://github.com/guerrerotook/securitas-direct-new-api/issues"

# Operations that ARE the authentication — never require auth before calling
_AUTH_OPERATIONS = frozenset(
    {
        "mkLoginToken",
        "RefreshLogin",
        "mkSendOTP",
        "mkValidateDevice",
    }
)


class _ClientBase:
    """Shared state, header building, GraphQL execute and polling.

    Subclassed by every domain mixin and by ``VerisureOwaClient`` itself.
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
        refresh_token: str | None = None,
        on_refresh_token_changed: Callable[[str], None] | None = None,
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
        self.refresh_token_value: str = refresh_token or ""
        self._on_refresh_token_changed: Callable[[str], None] | None = (
            on_refresh_token_changed
        )
        self.login_timestamp: int = 0
        self.protom_response: str = ""
        self.authentication_otp_challenge_value: tuple[str, str] | None = None

        # Serializes token renewal. All coordinators share one client, so when
        # the short-lived auth JWT expires their polls would otherwise fire
        # concurrent RefreshLogin calls with the same one-time-use refresh
        # token — the server rotates on the first and rejects the rest. See #499.
        self._auth_lock = asyncio.Lock()

        # Auth-recovery streak: consecutive transient failures on the auth
        # path (refresh/login). Reset on any successful auth. Shared across all
        # coordinators because they share one client.
        self.consecutive_auth_recovery_failures: int = 0
        self._auth_streak_started: datetime | None = None
        self._last_auth_escalation: datetime | None = None

        # Device configuration
        self.device_id: str = device_id
        self.uuid: str = uuid
        self.id_device_indigitall: str = id_device_indigitall
        self.device_brand: str = "samsung"
        self.device_name: str = "SM-S901U"
        self.device_os_version: str = "12"
        self.device_version: str = "10.102.0"

        # Polling configuration
        self.poll_delay: float = poll_delay
        self.poll_timeout: float = poll_timeout

        # Capabilities tokens per installation (key: installation number)
        self._capabilities: dict[str, tuple[str, datetime, frozenset[str]]] = {}

        # Internal state
        self._apollo_operation_id: str = secrets.token_hex(64)
        self._log_filter: SensitiveDataFilter | None = log_filter

        # Persisted refresh tokens load before any rotation, so any log emitted
        # before the first refresh would otherwise leak the value in plaintext.
        self._register_secret("refresh_token", self.refresh_token_value)

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

    def _update_refresh_token(self, value: str) -> None:
        """Store a refresh token and notify the host integration.

        Persistence failures must not break the auth flow: the in-memory
        token still works for the current session, and the next rotation
        will retry the host write.
        """
        self.refresh_token_value = value
        self._register_secret("refresh_token", value)
        if self._on_refresh_token_changed is not None:
            try:
                self._on_refresh_token_changed(value)
            except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
                _LOGGER.warning(
                    "on_refresh_token_changed callback raised; refresh token "
                    "stored in memory but host persistence may have failed",
                    exc_info=True,
                )

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
            # Tokens come from a trusted HTTPS endpoint, so we don't verify
            # signatures here. The Verisure API signs with EdDSA, not HS256 —
            # passing a constraining `algorithms=` would be misleading and
            # would break if signature verification were ever turned on.
            decoded = jwt.decode(token_str, options={"verify_signature": False})
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

        Raises VerisureOwaError if the data is missing or None.  When the
        response carries a GraphQL `errors` array, the exception message
        surfaces the first error's message + err code so callers (and
        logs) see the actual server-side reason instead of "response is
        None" — important for reauth signals like err=60067 "Invalid
        Session" on xSRefreshLogin.
        """
        data = response.get("data")
        if data is None:
            _err = VerisureOwaError(
                _format_graphql_error(
                    field_name, response, f"{field_name}: no data in response"
                )
            )
            _err.response_body = response
            raise _err
        result = data.get(field_name)
        if result is None:
            _err = VerisureOwaError(
                _format_graphql_error(
                    field_name, response, f"{field_name} response is None"
                )
            )
            _err.response_body = response
            raise _err
        return result

    # ── Error checking helpers ───────────────────────────────────────────

    @staticmethod
    def _is_account_blocked(result_json: dict[str, Any]) -> bool:
        """Check if a login response indicates the account is blocked (error 60052)."""
        return _error_code_from_body(result_json) == "60052"

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
    ) -> None:
        """Check for GraphQL-level errors in the response and raise if needed."""
        if "errors" not in response_dict:
            return

        errors = response_dict["errors"]

        # Dict-style error with data.reason
        if isinstance(errors, dict) and "data" in errors and "reason" in errors["data"]:
            _err = VerisureOwaError(errors["data"]["reason"])
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
                _err = VerisureOwaError(message, http_status=error_status)
                _err.response_body = response_dict
                raise _err

    # ── Auth lifecycle ───────────────────────────────────────────────────

    async def _ensure_auth(self, installation: Installation | None = None) -> None:
        """Ensure the authentication token is valid, refreshing or logging in as needed."""
        await self._check_authentication_token()
        if installation is not None:
            await self._ensure_capabilities(installation)

    def _token_needs_renewal(self) -> bool:
        """True when the auth token is missing or within a minute of expiry."""
        return (self.authentication_token is None) or (
            datetime.now() + timedelta(minutes=1) > self._authentication_token_exp
        )

    async def _check_authentication_token(self) -> None:
        """Check expiration of the authentication token and get a new one if needed.

        Renewal is serialized behind ``_auth_lock`` with a double-check inside:
        when several coordinators hit an expired token at once, the first
        renews and the rest reuse that result instead of racing concurrent
        RefreshLogin calls against a one-time-use refresh token (issue #499).
        """
        if not self._token_needs_renewal():
            return
        async with self._auth_lock:
            # Re-check under the lock: a coroutine we queued behind may have
            # already minted a fresh token while we were waiting.
            if not self._token_needs_renewal():
                return
            if self.refresh_token_value:
                _LOGGER.debug("[auth] Auth token expired, refreshing")
                try:
                    # pylint: disable=no-member  # provided by _AuthMixin
                    if await self.refresh_token():  # type: ignore[attr-defined]
                        return
                    _LOGGER.warning("Refresh token failed, falling back to login")
                except (
                    VerisureOwaError,
                    asyncio.TimeoutError,
                ) as err:
                    owa_err = (
                        err
                        if isinstance(err, VerisureOwaError)
                        else VerisureOwaError(str(err))
                    )
                    # Genuine token rejection (e.g. err 60067): the refresh
                    # token is dead -> fall through to login() so a missing
                    # password surfaces as a clean reauth signal. Transient
                    # server error (5xx, the xSRefreshLogin crash, a timeout):
                    # the token is probably fine -> do NOT burn a login attempt;
                    # record it and propagate so the coordinator retries.
                    if not is_genuine_auth_failure(owa_err):
                        self.record_auth_recovery_failure(owa_err)
                        if isinstance(err, VerisureOwaError):
                            raise
                        raise owa_err from err
                    _LOGGER.warning(
                        "Refresh token genuinely rejected, falling back to login: %s",
                        err,
                    )
            _LOGGER.debug("[auth] Auth token expired, logging in again")
            # pylint: disable=no-member  # provided by _AuthMixin
            await self.login()  # type: ignore[attr-defined]

    def note_auth_success(self) -> None:
        """Reset the auth-recovery streak after a successful authentication."""
        if self.consecutive_auth_recovery_failures:
            _LOGGER.info(
                "Verisure authentication recovered after %d transient failure(s)",
                self.consecutive_auth_recovery_failures,
            )
        self.consecutive_auth_recovery_failures = 0
        self._auth_streak_started = None
        self._last_auth_escalation = None

    def record_auth_recovery_failure(self, err: VerisureOwaError) -> None:
        """Record a transient auth-recovery failure and log it.

        The first failure in a streak logs a WARNING. Once the streak reaches
        ``_AUTH_ESCALATION_THRESHOLD`` a louder, throttled WARNING explains that
        reauth is being deliberately withheld and how to report a wrong call.
        """
        now = datetime.now()
        is_first = self.consecutive_auth_recovery_failures == 0
        if is_first:
            self._auth_streak_started = now
        self.consecutive_auth_recovery_failures += 1
        count = self.consecutive_auth_recovery_failures

        if is_first:
            _LOGGER.warning(
                "Verisure auth recovery failed with a transient server error "
                "(%s); credentials look valid, will retry next poll. NOT forcing "
                "reauthentication.",
                err.log_detail(),
            )
        elif count >= _AUTH_ESCALATION_THRESHOLD:
            last = self._last_auth_escalation
            if last is None or now - last >= _AUTH_ESCALATION_INTERVAL:
                self._last_auth_escalation = now
                # _auth_streak_started is always set on the first failure above,
                # so it is non-None here; `or now` only narrows the Optional type.
                started = self._auth_streak_started or now
                minutes = int((now - started).total_seconds() // 60)
                _LOGGER.warning(
                    "Verisure session has failed to recover %d times over %d "
                    "minutes. The errors look transient/server-side so we are "
                    "deliberately NOT forcing reauthentication. If your Verisure "
                    "devices remain unavailable, please report this at %s and "
                    "include this line. Last response: %s",
                    count,
                    minutes,
                    _ISSUES_URL,
                    err.log_detail(),
                )

    async def _ensure_capabilities(self, installation: Installation) -> None:
        """Check the capabilities token and get a new one if needed."""
        entry = self._capabilities.get(installation.number)
        if entry is None or datetime.now() + timedelta(minutes=1) > entry[1]:
            _LOGGER.debug("[auth] Capabilities token expired, refreshing")
            # pylint: disable=no-member  # provided by _InstallationMixin
            await self.get_services(installation)  # type: ignore[attr-defined]

    def get_supported_commands(self, installation_number: str) -> frozenset[str]:
        """Return the capability set for an installation, or empty frozenset if unknown.

        Reads the cap claim from the decoded capability JWT, populated during
        the most recent _ensure_capabilities call for this installation.
        """
        entry = self._capabilities.get(installation_number)
        if entry is None or len(entry) < 3:
            return frozenset()
        return entry[2]

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
            self._check_graphql_errors(response_dict)
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
            _err = VerisureOwaError(f"Invalid response for {operation}")
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

    # ── Poll operation ───────────────────────────────────────────────────

    async def _poll_operation(
        self,
        check_fn: Any,
        *,
        timeout: float | None = None,
        delay: float | None = None,
        continue_on_msg: str | None = None,
    ) -> dict[str, Any]:
        """Poll check_fn until result is no longer WAIT.

        Args:
            check_fn: Async callable that returns a dict with at least 'res' key.
            timeout: Wall-clock timeout in seconds (defaults to poll_timeout).
            delay: Sleep between polls in seconds (defaults to poll_delay).
                Operations with known long latency (e.g. image capture, which
                routinely takes 30-90s on the server) can pass a larger value
                to reduce API call volume and avoid rate-limiting.
            continue_on_msg: If set, also continue polling when response 'msg'
                matches this value.

        Returns:
            The final poll result dict.

        Raises:
            OperationTimeoutError: If wall-clock timeout is exceeded.
            VerisureOwaError: If a non-transient error occurs.
        """
        if timeout is None:
            timeout = self.poll_timeout
        if delay is None:
            delay = self.poll_delay

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
                await asyncio.sleep(delay)
            try:
                result = await check_fn()
            except (ClientConnectorError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Transient error during poll, retrying: %s", err)
                first = False
                continue
            except VerisureOwaError as err:
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

    async def _submit_and_poll(
        self,
        *,
        installation: Installation,
        submit_op: str,
        submit_query: str,
        submit_vars: dict[str, Any],
        submit_envelope_cls: type,
        submit_data_field: str,
        status_op: str,
        status_query: str,
        status_data_field: str,
        status_vars_builder: Callable[[str, int], dict[str, Any]],
    ) -> dict[str, Any]:
        """Submit a mutation, extract its referenceId, then poll status until done.

        Common scaffold for arm/disarm/check_alarm/change_lock_mode. Returns
        the raw status dict from the final poll response — callers handle
        operation-specific error semantics and result-model validation.
        """
        submit_content = {
            "operationName": submit_op,
            "variables": submit_vars,
            "query": submit_query,
        }
        envelope = await self._execute_graphql(
            submit_content,
            submit_op,
            submit_envelope_cls,
            installation=installation,
        )
        inner = getattr(envelope.data, submit_data_field)
        reference_id: str = inner.reference_id

        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            poll_content = {
                "operationName": status_op,
                "variables": status_vars_builder(reference_id, counter),
                "query": status_query,
            }
            response = await self._execute_raw(
                poll_content, status_op, installation=installation
            )
            return self._extract_response_data(response, status_data_field)

        return await self._poll_operation(_check)
