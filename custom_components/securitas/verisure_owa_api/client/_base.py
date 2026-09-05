"""Shared client base: auth lifecycle, headers, GraphQL execute, polling.

Domain mixins (auth, alarm, lock, camera, sentinel, activity, installation)
each extend ``_ClientBase`` so they have access to ``self._execute_graphql``,
``self._build_headers`` and the rest of the shared infrastructure.
``VerisureOwaClient`` in ``__init__.py`` then composes all the mixins.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

import jwt
from aiohttp import ClientConnectorError
from pydantic import BaseModel, ValidationError

from ..exceptions import (
    APIConnectionError,
    OperationTimeoutError,
    RefreshTokenDeadError,
    SessionExpiredError,
    VerisureOwaError,
    _error_code_from_body,
    is_genuine_auth_failure,
    is_refresh_login_crash,
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


def _token_fingerprint(token: str | None) -> str:
    """Return a short, stable, non-reversible fingerprint of a token.

    The refresh/auth tokens are redacted wholesale by ``SensitiveDataFilter``
    (raw value -> ``[REFRESH_TOKEN]``), so logging them directly makes every
    generation look identical. A truncated *unsalted* sha256 gives each token
    a distinct id that survives the redaction filter, never leaks the value,
    and — crucially for issue #557 — is stable across process restarts, so the
    fingerprint persisted before a reboot can be compared with the one loaded
    from disk afterwards. Falsy tokens map to ``<none>``.
    """
    if not token:
        return "<none>"
    return hashlib.sha256(token.encode()).hexdigest()[:12]


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
# Counted xSRefreshLogin crashes, with no successful renewal in between, after
# which the stored refresh token is treated as dead and reauth is requested
# (#568). One crash can be a server wobble; a token that keeps crashing across
# polls has never been seen to recover. Crashes closer together than the
# spacing are one renewal window — the coordinators sharing this client each
# take a turn behind the auth lock seconds apart — and count once.
_REFRESH_CRASH_REAUTH_THRESHOLD = 3
_REFRESH_CRASH_MIN_SPACING = timedelta(seconds=60)
_ISSUES_URL = "https://github.com/guerrerotook/securitas-direct-new-api/issues"
# The open issue tracking the xSRefreshLogin server crash; the recruitment
# WARNING points affected users straight at it.
_ISSUE_568_URL = "https://github.com/guerrerotook/securitas-direct-new-api/issues/568"

# Operations that ARE the authentication: they never require auth before
# calling, and the transport never re-sends them after a 403 (see _send).
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
        self._last_auth_failure: datetime | None = None

        # The #568 recruitment WARNING fires at most once per client instance
        # (so once per account — each account is a separate report): a persistent
        # crash re-presents the same token every poll, and repeating the recruit
        # line on each retry would become the log spam it avoids.
        self._refresh_crash_reported: bool = False
        # Consecutive xSRefreshLogin crashes on the current refresh token; reset
        # only by a successful renewal. See _REFRESH_CRASH_REAUTH_THRESHOLD.
        self._refresh_crash_streak: int = 0
        self._last_counted_refresh_crash: datetime | None = None
        # Latched once the streak trips: the client is shared by every
        # coordinator (and user command) on the account, and each would
        # otherwise spend a doomed RefreshLogin round-trip against the
        # rate-limited endpoint before hitting the same conclusion.
        self._refresh_token_dead: bool = False

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
        # Diagnostic for issue #557: the fingerprint of the newly-rotated token.
        # This fires at the *in-memory* rotation, BEFORE the persist callback
        # below — so rotated_fp marks a rotation, not a completed disk write
        # (hub._persist_refresh_token's persist_fp/outcome line confirms the
        # write reached the config entry). Comparing the next boot's
        # RefreshLogin token_fp against the last rotated_fp/persist_fp reveals a
        # stale on-disk token (mismatch, e.g. a rotation that never reached
        # storage before an ungraceful stop) vs a genuinely broken refresh
        # (match — the token loaded is the last valid one and still crashes).
        _LOGGER.debug(
            "[refresh] refresh token rotated: rotated_fp=%s",
            _token_fingerprint(value),
        )
        if self._on_refresh_token_changed is not None:
            try:
                self._on_refresh_token_changed(value)
            except Exception:  # pylint: disable=broad-exception-caught
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
            # Diagnostic for issue #557: measure the real auth-token lifetime on
            # the account rather than relying on the ~15-minute value inferred
            # from fixtures — it underpins the "reboot forces a refresh we'd
            # otherwise rarely hit" reasoning.
            ttl_s = int(
                (self._authentication_token_exp - datetime.now()).total_seconds()
            )
            _LOGGER.debug("[auth] auth token accepted: auth_token_ttl_s=%d", ttl_s)
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
            if self.refresh_token_value and not self._refresh_token_dead:
                _LOGGER.debug("[auth] Auth token expired, refreshing")
                try:
                    # pylint: disable=no-member  # provided by _AuthMixin
                    if await self.refresh_token():  # type: ignore[attr-defined]
                        return
                    _LOGGER.warning("Refresh token failed, falling back to login")
                except (TimeoutError, VerisureOwaError) as err:
                    owa_err = (
                        err
                        if isinstance(err, VerisureOwaError)
                        else VerisureOwaError(f"Token refresh failed: {err!r}")
                    )
                    # Genuine token rejection (e.g. err 60067): the refresh
                    # token is dead -> fall through to login() so a missing
                    # password surfaces as a clean reauth signal. Transient
                    # server error (5xx, the xSRefreshLogin crash, a timeout):
                    # the token is probably fine -> do NOT burn a login attempt;
                    # record it and propagate so the coordinator retries.
                    if is_genuine_auth_failure(owa_err):
                        _LOGGER.warning(
                            "Refresh token genuinely rejected, falling back to "
                            "login: %s",
                            err,
                        )
                    elif not self._note_refresh_crash(owa_err):
                        self.record_auth_recovery_failure(owa_err)
                        if isinstance(err, VerisureOwaError):
                            raise
                        raise owa_err from err
                    elif not self.password:
                        # Not recorded as a transient failure: that WARNING says
                        # reauth is being withheld, which this raise contradicts.
                        raise RefreshTokenDeadError(
                            f"Stored refresh token rejected {self._refresh_crash_streak} "
                            "times by the Verisure refresh-login crash; "
                            "re-authentication required"
                        ) from err
                    else:
                        _LOGGER.warning(
                            "Refresh token found dead after %d refresh-login "
                            "crashes, falling back to login",
                            self._refresh_crash_streak,
                        )
            elif self._refresh_token_dead and not self.password:
                raise RefreshTokenDeadError(
                    "Stored refresh token already found dead; "
                    "re-authentication required"
                )
            _LOGGER.debug("[auth] Auth token expired, logging in again")
            # pylint: disable=no-member  # provided by _AuthMixin
            await self.login()  # type: ignore[attr-defined]

    def _note_refresh_crash(self, err: VerisureOwaError) -> bool:
        """Count a refresh-login crash; True once the stored token is dead.

        Only the crash signature counts, other transient failures neither count
        nor reset (a successful renewal does, via note_auth_success). Crashes
        within ``_REFRESH_CRASH_MIN_SPACING`` of the last counted one are the
        same renewal window and count once. Reaching
        ``_REFRESH_CRASH_REAUTH_THRESHOLD`` latches ``refresh_token_is_dead``
        so every later renewal on this shared client concludes the same
        without another round-trip.
        """
        if self._refresh_token_dead:
            return True
        if not is_refresh_login_crash(err):
            return False
        now = datetime.now()
        last = self._last_counted_refresh_crash
        if last is not None and now - last < _REFRESH_CRASH_MIN_SPACING:
            return False
        self._last_counted_refresh_crash = now
        self._refresh_crash_streak += 1
        if self._refresh_crash_streak < _REFRESH_CRASH_REAUTH_THRESHOLD:
            return False
        self._refresh_token_dead = True
        return True

    @property
    def refresh_token_is_dead(self) -> bool:
        """True once a crash streak has condemned the stored refresh token."""
        return self._refresh_token_dead

    def adopt_refresh_token(self, value: str) -> None:
        """Replace the refresh token with one obtained elsewhere (e.g. reauth).

        Clears the dead-token verdict so the next renewal actually tries it.
        The token is not persisted here: it came from the caller's own entry.
        """
        self.refresh_token_value = value
        self._register_secret("refresh_token", value)
        self._refresh_crash_streak = 0
        self._last_counted_refresh_crash = None
        self._refresh_token_dead = False

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
        self._last_auth_failure = None
        self._refresh_crash_streak = 0
        self._last_counted_refresh_crash = None
        self._refresh_token_dead = False

    def record_auth_recovery_failure(self, err: VerisureOwaError) -> None:
        """Record a transient auth-recovery failure and log it.

        The first failure in a streak logs a WARNING. Once the streak reaches
        ``_AUTH_ESCALATION_THRESHOLD`` a louder, throttled WARNING explains that
        reauth is being deliberately withheld and how to report a wrong call.
        """
        now = datetime.now()
        # A streak represents *continuous* failures. If the previous failure was
        # longer ago than the escalation interval, the problem cleared in between
        # (e.g. polls succeeded on a still-valid token), so start a fresh streak
        # rather than reporting a count that spans a long idle gap.
        last_failure = self._last_auth_failure
        if last_failure is not None and now - last_failure >= _AUTH_ESCALATION_INTERVAL:
            self.consecutive_auth_recovery_failures = 0
            self._auth_streak_started = None
            self._last_auth_escalation = None
        self._last_auth_failure = now

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

    def warn_once_on_refresh_login_crash(self, err: VerisureOwaError) -> None:
        """Emit a one-time WARNING recruiting reporters for the #568 crash.

        The ``[refresh]`` fingerprint diagnostics are DEBUG and off by default,
        so only users who already know to enable them ever surface in the issue.
        The crash otherwise reaches the log as a generic transient-recovery
        WARNING (``record_auth_recovery_failure``) that names neither the issue
        nor the data we need. This adds a targeted, once-per-client WARNING —
        only for the specific server crash — that both confirms the diagnosis
        and tells the user exactly how to capture the DEBUG timeline. Keeping it
        to the crash signature (not every transient failure) and to once per
        client instance (not every retry) is what lets it stay at WARNING
        without spamming healthy installations, where the noisy per-rotation
        lines stay on DEBUG.
        """
        if self._refresh_crash_reported or not is_refresh_login_crash(err):
            return
        self._refresh_crash_reported = True
        _LOGGER.warning(
            "Verisure rejected the stored refresh token with the known "
            "refresh-login server crash (issue #568): %s. The integration retries "
            "briefly and, if it persists, asks you to re-authenticate — enter "
            "your password once and a fresh token is issued. If you can help pin "
            "down how the token went stale: enable debug logging for "
            "'custom_components.securitas' (a logs: entry under logger: in "
            "configuration.yaml), restart Home Assistant, let it run ~30 minutes, "
            "then share the log at %s.",
            err.message,
            _ISSUE_568_URL,
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

        response_dict = await self._send(content, operation, installation=installation)

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
        return await self._send(content, operation, installation=installation)

    async def _send(
        self,
        content: dict[str, Any],
        operation: str,
        *,
        installation: Installation | None = None,
    ) -> dict[str, Any]:
        """Build headers and hand the request to the transport.

        The single place the transport's retry policy is decided, so both the
        typed and raw paths agree: an auth mutation is never re-sent blindly.
        RefreshLogin rotates a one-time refresh token and the OTP calls consume
        a one-time code on the first send; the password login is kept with
        them so no credential-bearing request is ever repeated by the transport.
        """
        headers = self._build_headers(operation, installation=installation)
        return await self._transport.execute(
            content, headers, retry_on_403=operation not in _AUTH_OPERATIONS
        )

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
            except (TimeoutError, ClientConnectorError, APIConnectionError) as err:
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
