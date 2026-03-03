"""Centralized log sanitization filter for the Securitas Direct integration."""

from __future__ import annotations

import logging


# Map secret keys to their redaction labels
_REDACTION_LABELS: dict[str, str] = {
    "auth_token": "[AUTH_TOKEN]",
    "refresh_token": "[REFRESH_TOKEN]",
    "username": "[USERNAME]",
    "password": "[PASSWORD]",
    "otp_hash": "[OTP_DATA]",
    "otp_token": "[OTP_DATA]",
}


class SensitiveDataFilter(logging.Filter):
    """Logging filter that redacts known sensitive values from log records."""

    def __init__(self) -> None:
        super().__init__()
        # Maps raw secret value -> redaction label
        self._secrets: dict[str, str] = {}
        # Maps secret key -> current raw value (for replacement on update)
        self._keys: dict[str, str] = {}

    def add_installation(self, number: str) -> None:
        """Register an installation number for partial masking."""
        if not number:
            return
        if len(number) <= 4:
            masked = "***"
        else:
            masked = "***" + number[-4:]
        self._secrets[number] = masked

    def update_secret(self, key: str, value: str | None) -> None:
        """Register or update a sensitive value for redaction."""
        # Remove old value for this key if it exists
        old = self._keys.pop(key, None)
        if old and old in self._secrets:
            del self._secrets[old]

        if not value:
            return

        label = _REDACTION_LABELS.get(key, f"[{key.upper()}]")
        self._secrets[value] = label
        self._keys[key] = value

    def _redact(self, text: str) -> str:
        """Replace all known secret values in a string."""
        for secret, label in self._secrets.items():
            text = text.replace(secret, label)
        return text

    def _redact_value(self, value: object) -> object:
        """Redact secrets in a single value, recursing into dicts."""
        if isinstance(value, str):
            return self._redact(value)
        if isinstance(value, dict):
            return {k: self._redact_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            redacted = [self._redact_value(item) for item in value]
            return type(value)(redacted)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive values from the log record. Always returns True."""
        if not self._secrets:
            return True

        try:
            if isinstance(record.msg, str):
                record.msg = self._redact(record.msg)

            if isinstance(record.args, tuple):
                record.args = tuple(self._redact_value(a) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: self._redact_value(v) for k, v in record.args.items()}
        except Exception:  # noqa: BLE001
            pass  # Never break logging

        return True
