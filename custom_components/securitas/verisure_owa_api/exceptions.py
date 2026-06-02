"""Verisure OWA API exceptions."""

from __future__ import annotations

from typing import Any


class VerisureOwaError(Exception):
    """Base class for all Verisure OWA errors."""

    # http_status values that are well-understood and need no extra context.
    # 400 = command not in panel's GraphQL enum (BAD_USER_INPUT).
    # 403 = session expired / WAF block.
    # 404 = panel-side rejection of a specific command (e.g. compound
    #       disarm not recognised by panel firmware); the message already
    #       carries the panel's error code so the body is duplicative.
    # 409 = server busy (transient).
    _KNOWN_STATUSES: frozenset[int] = frozenset({400, 403, 404, 409})

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        # May be set by callers after construction to attach the raw response.
        self.response_body: Any | None = None

    @property
    def message(self) -> str:
        """Short human-readable error description."""
        return str(self.args[0]) if self.args else str(self)

    def log_detail(self) -> str:
        """Return a log string: concise for known errors, verbose otherwise.

        Known HTTP statuses (400, 403, 404, 409) return just the message.
        Unknown errors append the response body so we can diagnose them.
        """
        if self.http_status in self._KNOWN_STATUSES:
            return self.message
        if self.response_body is None:
            return self.message
        return f"{self.message} | response: {self.response_body}"


class AuthenticationError(VerisureOwaError):
    """Raised when credentials are rejected."""


class TwoFactorRequiredError(VerisureOwaError):
    """Raised when the device requires 2FA authorisation."""


class SessionExpiredError(VerisureOwaError):
    """Raised when the JWT has expired and must be refreshed."""


class APIResponseError(VerisureOwaError):
    """Raised when the API returns a GraphQL-level error.

    Carries the HTTP status code so callers can make routing decisions
    without inspecting the response body.
    """


class AccountBlockedError(AuthenticationError):
    """Raised when the user account is blocked by Verisure."""


class WAFBlockedError(VerisureOwaError):
    """Raised when the Incapsula WAF blocks the request."""


class APIConnectionError(VerisureOwaError):
    """Raised on network-level failures (DNS, TCP, TLS)."""


class OperationTimeoutError(VerisureOwaError):
    """Raised when a panel operation does not complete within the timeout."""


class OperationFailedError(VerisureOwaError):
    """Raised when the panel explicitly rejects an operation.

    Carries the vendor error codes for diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_type = error_type


class ArmingExceptionError(VerisureOwaError):
    """Raised when arming fails due to non-blocking exceptions (e.g. open window).

    Carries force-arm context (reference_id, suid) so the caller can retry
    with forceArmingRemoteId to override the exception.
    """

    def __init__(
        self,
        reference_id: str,
        suid: str,
        exceptions: list[dict[str, Any]],
    ) -> None:
        self.reference_id = reference_id
        self.suid = suid
        self.exceptions = exceptions  # [{status, deviceType, alias}, ...]
        details = ", ".join(e.get("alias", "unknown") for e in exceptions)
        super().__init__(f"Arming blocked by exceptions: {details}")


class ImageCaptureError(VerisureOwaError):
    """Raised when a camera image capture request fails."""


class UnexpectedStateError(VerisureOwaError):
    """Raised when the API returns an unrecognised protocol code."""

    def __init__(self, proto_code: str) -> None:
        self.proto_code = proto_code
        super().__init__(f"Unexpected protocol code: {proto_code!r}")


# Vendor error codes that genuinely require re-authentication:
# 60052 = account blocked; 60067 = invalid/expired session on refresh.
_GENUINE_AUTH_ERROR_CODES: frozenset[str] = frozenset({"60052", "60067"})


def _error_code_from_body(body: object) -> str | None:
    """Extract the vendor ``err`` code from a GraphQL response-body dict.

    Walks ``body["errors"][0]["data"]["err"]`` defensively, returning the code
    as a string (the server sends strings) or ``None`` if absent/malformed.
    Shared by ``_error_code`` (error-object form) and the auth client's
    account-blocked check (raw-response form).
    """
    if not isinstance(body, dict):
        return None
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        data = errors[0].get("data")
        if isinstance(data, dict):
            code = data.get("err")
            return str(code) if code is not None else None
    return None


def _error_code(err: VerisureOwaError) -> str | None:
    """Best-effort extraction of the vendor ``err`` code from an error object."""
    return _error_code_from_body(err.response_body)


def is_genuine_auth_failure(err: VerisureOwaError) -> bool:
    """True only for failures that genuinely require re-authentication.

    Genuine (-> reauth): credential rejection, account blocked, 2FA required,
    or an explicitly invalid/revoked token (err 60052 / 60067).

    Everything else -- 5xx, 409, network/timeout, WAF blocks, a bare HTTP 403
    "try again later" session error, and unrecognised null-data GraphQL errors
    such as the xSRefreshLogin server crash -- is transient and must NOT trigger
    a reauth prompt. Unknown failures default to transient (retry forever).
    """
    if isinstance(err, (AuthenticationError, TwoFactorRequiredError)):
        return True
    return _error_code(err) in _GENUINE_AUTH_ERROR_CODES
