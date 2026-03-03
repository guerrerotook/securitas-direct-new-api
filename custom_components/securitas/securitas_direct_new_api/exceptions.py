"""Securitas Direct API exceptions."""

from __future__ import annotations

from typing import Any


class SecuritasDirectError(Exception):
    """Base class for Securitas Direct errors."""

    def __init__(self, *args, http_status: int | None = None) -> None:
        super().__init__(*args)
        self.http_status = http_status


class APIError(SecuritasDirectError):
    """Exception raised when API fails."""


class LoginError(SecuritasDirectError):
    """Exception raised when login fails."""


class AuthError(LoginError):
    """Exception raised when API denies access."""


class TokenRefreshError(LoginError):
    """Exception raised when the token needs refreshing."""


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
