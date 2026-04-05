"""Securitas Direct API exceptions."""

from __future__ import annotations

from typing import Any


class SecuritasDirectError(Exception):
    """Base class for all Securitas Direct errors."""

    # http_status values that are well-understood and need no extra context.
    _KNOWN_STATUSES: frozenset[int] = frozenset({400, 403, 409})

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

        Known HTTP statuses (400, 403, 409) return just the message.
        Unknown errors append the response body so we can diagnose them.
        """
        if self.http_status in self._KNOWN_STATUSES:
            return self.message
        if self.response_body is None:
            return self.message
        return f"{self.message} | response: {self.response_body}"


class AuthenticationError(SecuritasDirectError):
    """Raised when credentials are rejected."""


class TwoFactorRequiredError(SecuritasDirectError):
    """Raised when the device requires 2FA authorisation."""


class SessionExpiredError(SecuritasDirectError):
    """Raised when the JWT has expired and must be refreshed."""


class APIResponseError(SecuritasDirectError):
    """Raised when the API returns a GraphQL-level error.

    Carries the HTTP status code so callers can make routing decisions
    without inspecting the response body.
    """

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message, http_status=http_status)


class AccountBlockedError(AuthenticationError):
    """Raised when the user account is blocked by Securitas."""


class WAFBlockedError(SecuritasDirectError):
    """Raised when the Incapsula WAF blocks the request."""


class APIConnectionError(SecuritasDirectError):
    """Raised on network-level failures (DNS, TCP, TLS)."""


class OperationTimeoutError(SecuritasDirectError):
    """Raised when a panel operation does not complete within the timeout."""


class OperationFailedError(SecuritasDirectError):
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


class ArmingExceptionError(SecuritasDirectError):
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


class ImageCaptureError(SecuritasDirectError):
    """Raised when a camera image capture request fails."""


class UnexpectedStateError(SecuritasDirectError):
    """Raised when the API returns an unrecognised protocol code."""

    def __init__(self, proto_code: str) -> None:
        self.proto_code = proto_code
        super().__init__(f"Unexpected protocol code: {proto_code!r}")
