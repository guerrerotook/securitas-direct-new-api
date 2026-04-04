"""Securitas Direct API exceptions."""

from __future__ import annotations

from typing import Any


class SecuritasDirectError(Exception):
    """Base class for Securitas Direct errors.

    Typically raised as ``SecuritasDirectError(message, response_dict,
    headers, graphql_content)``.  Only ``message`` is guaranteed; the
    remaining args are optional.
    """

    # http_status values that are well-understood and need no extra context.
    _KNOWN_STATUSES: frozenset[int] = frozenset({400, 403, 409})

    def __init__(self, *args, http_status: int | None = None) -> None:
        super().__init__(*args)
        self.http_status = http_status

    @property
    def message(self) -> str:
        """Short human-readable error description (args[0])."""
        return str(self.args[0]) if self.args else str(self)

    @property
    def response_body(self) -> Any | None:
        """Raw API response dict (args[1]), if available."""
        return self.args[1] if len(self.args) > 1 else None

    def log_detail(self) -> str:
        """Return a log string: concise for known errors, verbose otherwise.

        Known HTTP statuses (400, 403, 409) return just the message.
        Unknown errors append the response body so we can diagnose them.
        """
        if self.http_status in self._KNOWN_STATUSES:
            return self.message
        body = self.response_body
        if body is None:
            return self.message
        return f"{self.message} | response: {body}"


class APIError(SecuritasDirectError):
    """Exception raised when API fails."""


class LoginError(SecuritasDirectError):
    """Exception raised when login fails."""


class AuthError(LoginError):
    """Exception raised when API denies access."""


class TokenRefreshError(LoginError):
    """Exception raised when the token needs refreshing."""


class AccountBlockedError(LoginError):
    """Exception raised when the user account is blocked by Securitas."""


class Login2FAError(LoginError):
    """Exception raised when a 2FA authentication is needed."""


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
