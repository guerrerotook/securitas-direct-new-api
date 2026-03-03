# Log Sanitization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a centralized `logging.Filter` that automatically redacts sensitive data (tokens, credentials, installation numbers) from all log output in the securitas integration.

**Architecture:** A `SensitiveDataFilter` class attached to the integration's root logger intercepts all log records and replaces known sensitive values with redaction labels. Sensitive values are registered dynamically as they become available (login, refresh, installation fetch). Separately, two exception messages that embed raw tokens are fixed.

**Tech Stack:** Python `logging.Filter`, pytest

---

### Task 1: Create `SensitiveDataFilter` with basic secret redaction

**Files:**
- Create: `custom_components/securitas/log_filter.py`
- Create: `tests/test_log_filter.py`

**Step 1: Write the failing tests**

```python
"""Tests for SensitiveDataFilter."""

import logging

from custom_components.securitas.log_filter import SensitiveDataFilter


def test_redacts_secret_in_message():
    """Filter replaces a registered secret in the log message."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "eyJhbGciOiJIUzI1NiJ9.secret")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="Token is eyJhbGciOiJIUzI1NiJ9.secret here",
        args=(), exc_info=None,
    )
    f.filter(record)
    assert "eyJhbGciOiJIUzI1NiJ9.secret" not in record.msg
    assert "[AUTH_TOKEN]" in record.msg


def test_redacts_secret_in_format_args():
    """Filter replaces a registered secret in %s format args."""
    f = SensitiveDataFilter()
    f.update_secret("password", "hunter2")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="Login with %s",
        args=("hunter2",), exc_info=None,
    )
    f.filter(record)
    assert "hunter2" not in str(record.args)
    assert "[PASSWORD]" in str(record.args)


def test_redacts_multiple_secrets():
    """Filter replaces multiple different secrets in the same message."""
    f = SensitiveDataFilter()
    f.update_secret("username", "user@example.com")
    f.update_secret("password", "hunter2")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="user@example.com logged in with hunter2",
        args=(), exc_info=None,
    )
    f.filter(record)
    assert "[USERNAME]" in record.msg
    assert "[PASSWORD]" in record.msg
    assert "user@example.com" not in record.msg
    assert "hunter2" not in record.msg


def test_update_secret_replaces_old_value():
    """Updating a secret key removes the old value and tracks the new one."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "old-token")
    f.update_secret("auth_token", "new-token")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="old-token and new-token",
        args=(), exc_info=None,
    )
    f.filter(record)
    # Old value should pass through (no longer tracked)
    assert "old-token" in record.msg
    # New value should be redacted
    assert "[AUTH_TOKEN]" in record.msg
    assert "new-token" not in record.msg


def test_filter_always_returns_true():
    """Filter never suppresses log records."""
    f = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="safe message", args=(), exc_info=None,
    )
    assert f.filter(record) is True


def test_empty_and_none_secrets_ignored():
    """Empty string and None values are not registered as secrets."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "")
    f.update_secret("password", None)

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="normal message",
        args=(), exc_info=None,
    )
    f.filter(record)
    assert record.msg == "normal message"


def test_non_string_args_handled():
    """Filter handles non-string args (int, dict, None) without raising."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "secret123")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="code %d data %s",
        args=(42, {"key": "secret123"}), exc_info=None,
    )
    f.filter(record)
    assert "secret123" not in str(record.args)


def test_filter_survives_malformed_record():
    """A malformed record doesn't crash the filter."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "secret123")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg=None, args=None, exc_info=None,
    )
    # Should not raise
    result = f.filter(record)
    assert result is True
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_log_filter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'custom_components.securitas.log_filter'`

**Step 3: Write minimal implementation**

```python
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
                record.args = {
                    k: self._redact_value(v) for k, v in record.args.items()
                }
        except Exception:  # noqa: BLE001
            pass  # Never break logging

        return True
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_log_filter.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add custom_components/securitas/log_filter.py tests/test_log_filter.py
git commit -m "feat: add SensitiveDataFilter with basic secret redaction"
```

---

### Task 2: Add installation number partial masking

**Files:**
- Modify: `custom_components/securitas/log_filter.py`
- Modify: `tests/test_log_filter.py`

**Step 1: Write the failing tests**

Add to `tests/test_log_filter.py`:

```python
def test_add_installation_masks_number():
    """Installation numbers are partially masked (last 4 visible)."""
    f = SensitiveDataFilter()
    f.add_installation("1234567")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="No services for 1234567",
        args=(), exc_info=None,
    )
    f.filter(record)
    assert "1234567" not in record.msg
    assert "***4567" in record.msg


def test_add_installation_short_number():
    """Installation numbers with 4 or fewer chars are fully masked."""
    f = SensitiveDataFilter()
    f.add_installation("1234")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="Installation 1234",
        args=(), exc_info=None,
    )
    f.filter(record)
    assert "1234" not in record.msg
    assert "***" in record.msg


def test_add_installation_in_format_args():
    """Installation numbers in %s args are masked."""
    f = SensitiveDataFilter()
    f.add_installation("9876543")

    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="No services for %s",
        args=("9876543",), exc_info=None,
    )
    f.filter(record)
    assert "9876543" not in str(record.args)
    assert "***6543" in str(record.args)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_log_filter.py::test_add_installation_masks_number tests/test_log_filter.py::test_add_installation_short_number tests/test_log_filter.py::test_add_installation_in_format_args -v`
Expected: FAIL — `AttributeError: 'SensitiveDataFilter' object has no attribute 'add_installation'`

**Step 3: Write minimal implementation**

Add to `SensitiveDataFilter` in `log_filter.py`:

```python
    def add_installation(self, number: str) -> None:
        """Register an installation number for partial masking."""
        if not number:
            return
        if len(number) <= 4:
            masked = "***"
        else:
            masked = "***" + number[-4:]
        self._secrets[number] = masked
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_log_filter.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add custom_components/securitas/log_filter.py tests/test_log_filter.py
git commit -m "feat: add installation number partial masking to log filter"
```

---

### Task 3: Attach filter in `__init__.py` and register credentials

**Files:**
- Modify: `custom_components/securitas/__init__.py:140-260` (async_setup_entry / SecuritasHub)
- Modify: `tests/test_log_filter.py`

**Step 1: Write the failing test**

Add to `tests/test_log_filter.py`:

```python
def test_filter_attached_to_logger():
    """Verify the filter can be attached to a logger and intercepts records."""
    import io

    f = SensitiveDataFilter()
    f.update_secret("password", "hunter2")

    logger = logging.getLogger("test.securitas.filter_attach")
    logger.addFilter(f)
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(io.StringIO())
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    try:
        logger.debug("Password is hunter2")
        output = handler.stream.getvalue()
        assert "hunter2" not in output
        assert "[PASSWORD]" in output
    finally:
        logger.removeFilter(f)
        logger.removeHandler(handler)
```

**Step 2: Run test to verify it fails (or passes — this validates the approach)**

Run: `python -m pytest tests/test_log_filter.py::test_filter_attached_to_logger -v`
Expected: PASS (this validates the logging.Filter mechanism works end-to-end)

**Step 3: Wire the filter into `__init__.py`**

In `custom_components/securitas/__init__.py`:

1. Add import at top (after existing imports, around line 27):
```python
from .log_filter import SensitiveDataFilter
```

2. In `async_setup_entry` (line ~205, after `hass.data[DOMAIN] = {}`), create and attach the filter:
```python
    # Set up log sanitization filter
    log_filter = SensitiveDataFilter()
    logging.getLogger("custom_components.securitas").addFilter(log_filter)
    hass.data[DOMAIN]["log_filter"] = log_filter

    # Register credentials immediately
    log_filter.update_secret("username", config[CONF_USERNAME])
    log_filter.update_secret("password", config[CONF_PASSWORD])
```

3. In `SecuritasHub.__init__` (line ~358), store the filter reference:
```python
        self.log_filter: SensitiveDataFilter | None = hass.data.get(DOMAIN, {}).get("log_filter")
```

4. In `async_unload_entry` (line ~274), remove the filter:
```python
    log_filter = hass.data[DOMAIN].get("log_filter")
    if log_filter:
        logging.getLogger("custom_components.securitas").removeFilter(log_filter)
```

**Step 4: Run full test suite to verify nothing breaks**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add custom_components/securitas/__init__.py custom_components/securitas/log_filter.py tests/test_log_filter.py
git commit -m "feat: attach SensitiveDataFilter in async_setup_entry, register credentials"
```

---

### Task 4: Register tokens in `ApiManager` after login/refresh/validate

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py:68-110` (constructor), `:380-397` (validate_device), `:430-448` (refresh_token), `:523-540` (login)
- Modify: `custom_components/securitas/__init__.py:368-377` (SecuritasHub constructor — pass filter to ApiManager)

**Step 1: Add `log_filter` parameter to `ApiManager.__init__`**

In `apimanager.py`, add an optional `log_filter` parameter to `__init__` (after `delay_check_operation`):

```python
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
```

Add at top of `apimanager.py` (conditional import to avoid circular):
```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.securitas.log_filter import SensitiveDataFilter
```

Store it in `__init__`:
```python
        self._log_filter = log_filter
```

Add a helper method:
```python
    def _register_secret(self, key: str, value: str | None) -> None:
        """Register a secret with the log filter if available."""
        if self._log_filter and value:
            self._log_filter.update_secret(key, value)
```

**Step 2: Register tokens after login (line ~527)**

After `self.authentication_token = login_data["hash"]` (line 527):
```python
            self._register_secret("auth_token", self.authentication_token)
```

After `self.refresh_token_value = login_data["refreshToken"]` (line 524):
```python
            self._register_secret("refresh_token", self.refresh_token_value)
```

**Step 3: Register tokens after refresh (line ~431)**

After `self.authentication_token = refresh_data["hash"]` (line 431):
```python
            self._register_secret("auth_token", self.authentication_token)
```

After `self.refresh_token_value = refresh_data["refreshToken"]` (line 448):
```python
            self._register_secret("refresh_token", self.refresh_token_value)
```

**Step 4: Register tokens after validate_device (line ~380)**

After `self.authentication_token = validate_data["hash"]` (line 380):
```python
        self._register_secret("auth_token", self.authentication_token)
```

After `self.refresh_token_value = validate_data["refreshToken"]` (line 396):
```python
            self._register_secret("refresh_token", self.refresh_token_value)
```

**Step 5: Register OTP data (line ~360)**

After `self.authentication_otp_challenge_value = (auth_otp_hash, sms_code)` (line 360):
```python
            self._register_secret("otp_hash", auth_otp_hash)
            self._register_secret("otp_token", sms_code)
```

**Step 6: Register installation numbers in `get_all_services` (after line ~579)**

After the `for item in raw_installations:` loop builds installations in `list_installations`, the caller (`get_services` in `__init__.py`) iterates installations. Instead, register in `get_all_services` where we have the installation object — after line 612 where `installation_data` is confirmed not None:

```python
        self._register_installation(installation)
```

Add helper:
```python
    def _register_installation(self, installation: Installation) -> None:
        """Register an installation number with the log filter."""
        if self._log_filter and installation.number:
            self._log_filter.add_installation(installation.number)
```

**Step 7: Pass the filter from SecuritasHub to ApiManager**

In `__init__.py`, update `SecuritasHub.__init__` to pass `log_filter`:
```python
        self.session: ApiManager = ApiManager(
            domain_config[CONF_USERNAME],
            domain_config[CONF_PASSWORD],
            self.country,
            http_client,
            domain_config[CONF_DEVICE_ID],
            domain_config[CONF_UNIQUE_ID],
            domain_config[CONF_DEVICE_INDIGITALL],
            domain_config[CONF_DELAY_CHECK_OPERATION],
            log_filter=self.log_filter,
        )
```

**Step 8: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS (existing tests use the `api` fixture which doesn't pass `log_filter`, so it defaults to `None` — no behavior change)

**Step 9: Commit**

```bash
git add custom_components/securitas/__init__.py custom_components/securitas/securitas_direct_new_api/apimanager.py
git commit -m "feat: register tokens and installation numbers with log filter"
```

---

### Task 5: Fix exception messages that embed raw tokens

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py:537-540, 636-639`
- Modify: `tests/test_auth.py` (if existing tests assert on the old message)

**Step 1: Check existing tests for these error messages**

Run: `grep -n "Failed to decode" tests/`
Check if any tests assert on the old error message text.

**Step 2: Fix login token decode error (line 538-539)**

Change:
```python
                raise SecuritasDirectError(
                    f"Failed to decode authentication token {self.authentication_token}"
                ) from err
```
To:
```python
                raise SecuritasDirectError(
                    "Failed to decode authentication token"
                ) from err
```

**Step 3: Fix capabilities token decode error (line 637-638)**

Change:
```python
            raise SecuritasDirectError(
                f"Failed to decode capabilities token {installation.capabilities}"
            ) from err
```
To:
```python
            raise SecuritasDirectError(
                "Failed to decode capabilities token"
            ) from err
```

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py
git commit -m "fix: remove raw tokens from exception messages"
```

---

### Task 6: Delete commented-out debug logging

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py:169-172`

**Step 1: Remove the commented-out lines**

Delete these four lines (169-172):
```python
        # _LOGGER.debug("--------------Content---------------")
        # _LOGGER.debug(content)
        # _LOGGER.debug("--------------Headers---------------")
        # _LOGGER.debug(headers)
```

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py
git commit -m "chore: remove commented-out debug logging of headers and content"
```

---

### Task 7: Run linting and type checking

**Step 1: Run ruff**

```bash
ruff check . && ruff format .
```

Fix any issues.

**Step 2: Run pyright**

```bash
npx pyright
```

Fix any type errors in changed files.

**Step 3: Run full test suite one final time**

```bash
python -m pytest tests/ -v
```

**Step 4: Commit any fixes**

```bash
git add -u
git commit -m "chore: fix linting and type errors"
```
