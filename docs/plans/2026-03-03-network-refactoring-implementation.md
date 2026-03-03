# Network Code Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce code duplication in `apimanager.py` by extracting three helper methods, fix error handling issues, and improve token management.

**Architecture:** Add private helper methods directly to `ApiManager` — `_decode_auth_token()`, `_extract_response_data()`, and `_poll_operation()`. Then fix error handling in `_check_authentication_token()`, add token cleanup to `logout()`, and remove dead code.

**Tech Stack:** Python 3.13, aiohttp, PyJWT, pytest, asyncio

**Working directory:** `/workspaces/securitas-direct-new-api/.worktrees/refactor-network`

**Run tests with:** `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

---

### Task 1: Extract `_decode_auth_token()` helper

JWT token decoding is copy-pasted in 4 methods. Extract it into a single helper.

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py`
- Create: `tests/test_helpers.py`

**Step 1: Write the failing tests**

Create `tests/test_helpers.py`:

```python
"""Tests for ApiManager helper methods."""

from datetime import datetime
from unittest.mock import AsyncMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.apimanager import ApiManager

from .conftest import FAKE_JWT, make_jwt

pytestmark = pytest.mark.asyncio


# ── _decode_auth_token() ────────────────────────────────────────────────────


class TestDecodeAuthToken:
    def test_decodes_valid_jwt_and_sets_expiry(self, api):
        """Valid JWT should return decoded dict and set authentication_token_exp."""
        token = make_jwt(exp_minutes=30)
        result = api._decode_auth_token(token)

        assert result is not None
        assert "exp" in result
        assert isinstance(api.authentication_token_exp, datetime)
        assert api.authentication_token_exp > datetime.now()

    def test_returns_none_on_invalid_token(self, api):
        """Invalid JWT string should return None and not crash."""
        result = api._decode_auth_token("not-a-valid-jwt")
        assert result is None

    def test_handles_jwt_without_exp_claim(self, api):
        """JWT without 'exp' claim should return decoded dict but not update expiry."""
        # Create a JWT without exp
        token = jwt.encode({"sub": "test"}, "secret", algorithm="HS256")
        old_exp = api.authentication_token_exp
        result = api._decode_auth_token(token)

        assert result is not None
        assert "sub" in result
        assert api.authentication_token_exp == old_exp

    def test_returns_none_on_none_input(self, api):
        """None input should return None gracefully."""
        result = api._decode_auth_token(None)
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py -v --tb=short`

Expected: FAIL — `ApiManager` has no `_decode_auth_token` method.

**Step 3: Implement `_decode_auth_token()`**

Add this method to `ApiManager` class in `apimanager.py`, after `_generate_id()` (around line 321):

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py -v --tb=short`

Expected: 4 PASSED

**Step 5: Replace the 4 inline JWT decode blocks with calls to `_decode_auth_token()`**

Replace the JWT decode block in `validate_device()` (lines 381-394). The current code:
```python
        try:
            assert self.authentication_token is not None
            token = jwt.decode(
                self.authentication_token,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )
        except jwt.exceptions.DecodeError:
            _LOGGER.warning(
                "Failed to decode authentication token after device validation"
            )
        else:
            if "exp" in token:
                self.authentication_token_exp = datetime.fromtimestamp(token["exp"])
```

Replace with:
```python
        self._decode_auth_token(self.authentication_token)
```

Replace the JWT decode block in `refresh_token()` (lines 432-443). The current code:
```python
            try:
                assert self.authentication_token is not None
                token = jwt.decode(
                    self.authentication_token,
                    algorithms=["HS256"],
                    options={"verify_signature": False},
                )
            except jwt.exceptions.DecodeError:
                _LOGGER.warning("Failed to decode refreshed authentication token")
                return False
            if "exp" in token:
                self.authentication_token_exp = datetime.fromtimestamp(token["exp"])
```

Replace with:
```python
            if self._decode_auth_token(self.authentication_token) is None:
                return False
```

Replace the JWT decode block in `login()` (lines 530-543). The current code:
```python
            try:
                assert self.authentication_token is not None
                token = jwt.decode(
                    self.authentication_token,
                    algorithms=["HS256"],
                    options={"verify_signature": False},
                )
            except jwt.exceptions.DecodeError as err:
                raise SecuritasDirectError(
                    f"Failed to decode authentication token {self.authentication_token}"
                ) from err

            if "exp" in token:
                self.authentication_token_exp = datetime.fromtimestamp(token["exp"])
```

Replace with:
```python
            if self._decode_auth_token(self.authentication_token) is None:
                raise SecuritasDirectError(
                    "Failed to decode authentication token"
                )
```

Note: the `get_all_services()` JWT decode (lines 630-642) decodes the **capabilities** token, not the auth token. It sets `installation.capabilities_exp`, not `self.authentication_token_exp`. Do NOT replace it with `_decode_auth_token()` — it has different behavior. Leave it as-is.

**Step 6: Run all tests**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

Expected: All tests pass (391 existing + 4 new = 395).

**Step 7: Commit**

```bash
git add tests/test_helpers.py custom_components/securitas/securitas_direct_new_api/apimanager.py
git commit -m "refactor: extract _decode_auth_token() helper to DRY up JWT decoding"
```

---

### Task 2: Extract `_extract_response_data()` helper

The pattern `response["data"]["xSFieldName"]` with a None check is repeated in 13+ methods. Extract it.

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py`
- Modify: `tests/test_helpers.py`

**Step 1: Write the failing tests**

Add to `tests/test_helpers.py`:

```python
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)


# ── _extract_response_data() ────────────────────────────────────────────────


class TestExtractResponseData:
    def test_extracts_nested_data(self, api):
        """Should return response['data'][field_name] when present."""
        response = {"data": {"xSFoo": {"res": "OK", "msg": ""}}}
        result = api._extract_response_data(response, "xSFoo")
        assert result == {"res": "OK", "msg": ""}

    def test_raises_when_data_key_missing(self, api):
        """Should raise SecuritasDirectError when 'data' key is absent."""
        response = {"errors": [{"message": "bad"}]}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")

    def test_raises_when_data_is_none(self, api):
        """Should raise SecuritasDirectError when response['data'] is None."""
        response = {"data": None}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")

    def test_raises_when_field_is_none(self, api):
        """Should raise SecuritasDirectError when the named field is None."""
        response = {"data": {"xSFoo": None}}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")

    def test_raises_when_field_missing(self, api):
        """Should raise SecuritasDirectError when the named field doesn't exist."""
        response = {"data": {"xSBar": {"res": "OK"}}}
        with pytest.raises(SecuritasDirectError, match="xSFoo"):
            api._extract_response_data(response, "xSFoo")
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py::TestExtractResponseData -v --tb=short`

Expected: FAIL — `ApiManager` has no `_extract_response_data` method.

**Step 3: Implement `_extract_response_data()`**

Add this method to `ApiManager` class, after `_decode_auth_token()`:

```python
def _extract_response_data(self, response: dict, field_name: str) -> dict:
    """Extract and validate response['data'][field_name].

    Raises SecuritasDirectError if the data is missing or None.
    """
    data = response.get("data")
    if data is None:
        raise SecuritasDirectError(
            f"{field_name}: no data in response", response
        )
    result = data.get(field_name)
    if result is None:
        raise SecuritasDirectError(
            f"{field_name} response is None", response
        )
    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py::TestExtractResponseData -v --tb=short`

Expected: 5 PASSED

**Step 5: Replace inline response extraction with `_extract_response_data()` calls**

Replace in these methods (each has a 2-3 line block of `response["data"]["xSFieldName"]` + None check):

| Method | Field name | Lines |
|--------|-----------|-------|
| `validate_device()` | `"xSValidateDevice"` | 377-379 |
| `refresh_token()` | `"xSRefreshLogin"` | 423-425 |
| `send_otp()` | `"xSSendOtp"` | 464-466 |
| `login()` | `"xSLoginToken"` | 516-518 |
| `list_installations()` | `"xSInstallations"` | 557-559 |
| `check_alarm()` | `"xSCheckAlarm"` | 595-597 |
| `_check_alarm_status()` | `"xSCheckAlarmStatus"` | 838-840 |
| `_check_arm_status()` | `"xSArmStatus"` | 993-995 |
| `_check_disarm_status()` | `"xSDisarmStatus"` | 1147-1149 |
| `change_lock_mode()` | `"xSChangeSmartlockMode"` | 1234-1238 |
| `_check_change_lock_mode()` | `"xSChangeSmartlockModeStatus"` | 1288-1292 |

For each, replace the old pattern:
```python
field_data = response["data"]["xSFieldName"]
if field_data is None:
    raise SecuritasDirectError("xSFieldName response is None", response)
```

With:
```python
field_data = self._extract_response_data(response, "xSFieldName")
```

**Special cases — do NOT replace:**
- `arm_alarm()` (lines 885-898) — has extra `"data" not in response` check + custom error message extraction. Replace the `"data" not in response` check and the None check separately:
  ```python
  # Replace lines 885-898 with:
  arm_data = self._extract_response_data(response, "xSArmPanel")
  ```
  This works because `_extract_response_data` already handles both missing "data" and None field.
- `disarm_alarm()` (lines 1067-1080) — same pattern as arm_alarm. Replace with:
  ```python
  disarm_data = self._extract_response_data(response, "xSDisarmPanel")
  ```

**Do NOT replace** these methods (they use a different pattern — returning defaults instead of raising):
- `get_sentinel_data()` — returns `Sentinel("", "", 0, 0)` on error
- `get_air_quality_data()` — returns `AirQuality(0, "")` on error
- `check_general_status()` — returns `SStatus(None, None)` on error
- `get_all_services()` — returns `[]` on error
- `get_smart_lock_config()` — returns `SmartLock(None, None, None)` on error
- `get_lock_current_mode()` — returns `SmartLockMode(None, "0")` on error

These keep their current behavior as agreed in the design.

**Step 6: Run all tests**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

Expected: All tests pass.

**Step 7: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py tests/test_helpers.py
git commit -m "refactor: extract _extract_response_data() helper for consistent response validation"
```

---

### Task 3: Extract `_poll_operation()` helper

The arm/disarm/lock-change polling loops are nearly identical. Extract a generic polling helper with transient error retry and wall-clock timeout.

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py`
- Modify: `tests/test_helpers.py`

**Step 1: Write the failing tests**

Add to `tests/test_helpers.py`:

```python
import asyncio
import time


# ── _poll_operation() ────────────────────────────────────────────────────────


class TestPollOperation:
    async def test_returns_result_on_first_non_wait(self, api):
        """Should return immediately when check_fn returns non-WAIT result."""
        check_fn = AsyncMock(return_value={"res": "OK", "msg": "done"})
        api.delay_check_operation = 0  # no sleep for tests

        result = await api._poll_operation(check_fn)
        assert result == {"res": "OK", "msg": "done"}
        assert check_fn.call_count == 1

    async def test_polls_until_non_wait(self, api):
        """Should keep polling while result is WAIT, then return final result."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "WAIT", "msg": ""},
                {"res": "WAIT", "msg": ""},
                {"res": "OK", "msg": "done"},
            ]
        )
        api.delay_check_operation = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 3

    async def test_retries_on_transient_error(self, api):
        """Should catch transient errors and continue polling."""
        from aiohttp import ClientConnectorError
        from unittest.mock import MagicMock

        conn_err = ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("connection reset")
        )
        check_fn = AsyncMock(
            side_effect=[
                conn_err,
                {"res": "OK", "msg": "done"},
            ]
        )
        api.delay_check_operation = 0

        result = await api._poll_operation(check_fn)
        assert result["res"] == "OK"
        assert check_fn.call_count == 2

    async def test_raises_on_non_transient_error(self, api):
        """Should immediately raise non-transient errors."""
        check_fn = AsyncMock(
            side_effect=SecuritasDirectError("bad request", None)
        )
        api.delay_check_operation = 0

        with pytest.raises(SecuritasDirectError, match="bad request"):
            await api._poll_operation(check_fn)

    async def test_timeout_raises(self, api):
        """Should raise TimeoutError when wall-clock timeout is exceeded."""
        check_fn = AsyncMock(return_value={"res": "WAIT", "msg": ""})
        api.delay_check_operation = 0

        with pytest.raises(TimeoutError, match="timed out"):
            await api._poll_operation(check_fn, timeout=0.05)

    async def test_also_polls_on_specific_message(self, api):
        """Should continue polling when continue_on_msg matches response msg."""
        check_fn = AsyncMock(
            side_effect=[
                {"res": "ERROR", "msg": "alarm-manager.error_no_response_to_request"},
                {"res": "OK", "msg": "done"},
            ]
        )
        api.delay_check_operation = 0

        result = await api._poll_operation(
            check_fn,
            continue_on_msg="alarm-manager.error_no_response_to_request",
        )
        assert result["res"] == "OK"
        assert check_fn.call_count == 2
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py::TestPollOperation -v --tb=short`

Expected: FAIL — `ApiManager` has no `_poll_operation` method.

**Step 3: Implement `_poll_operation()`**

Add this method to `ApiManager` class, after `_extract_response_data()`:

```python
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
    deadline = asyncio.get_event_loop().time() + timeout
    result: dict[str, Any] = {}
    first = True

    while True:
        if not first and asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(
                f"Poll operation timed out after {timeout}s, "
                f"last response: {result}"
            )
        await asyncio.sleep(self.delay_check_operation)
        try:
            result = await check_fn()
        except (ClientConnectorError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Transient error during poll, retrying: %s", err)
            first = False
            continue

        first = False

        if result.get("res") == "WAIT":
            continue
        if continue_on_msg and result.get("msg") == continue_on_msg:
            continue
        break

    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py::TestPollOperation -v --tb=short`

Expected: 6 PASSED

**Step 5: Replace the polling loops in `arm_alarm()`, `disarm_alarm()`, and `change_lock_mode()`**

**In `arm_alarm()`** — replace the polling loop (lines 904-939). Current code:
```python
        count = 1
        raw_data: dict[str, Any] = {}
        max_retries = max(10, round(30 / max(1, self.delay_check_operation)))
        while (count == 1) or (raw_data.get("res") == "WAIT"):
            if count > max_retries:
                _LOGGER.warning(...)
                break
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_arm_status(...)
            # Detect non-blocking exception...
            count += 1
```

Replace with:
```python
        async def _check():
            nonlocal count
            count += 1
            data = await self._check_arm_status(
                installation, reference_id, command, count, force_arming_remote_id,
            )
            # Detect non-blocking exception that allows forcing
            error = data.get("error")
            if (
                data.get("res") == "ERROR"
                and error
                and error.get("type") == "NON_BLOCKING"
                and error.get("allowForcing")
            ):
                error_ref = error.get("referenceId", reference_id)
                error_suid = error.get("suid", "")
                exceptions = await self._get_exceptions(
                    installation, error_ref, error_suid
                )
                raise ArmingExceptionError(error_ref, error_suid, exceptions)
            return data

        count = 0
        raw_data = await self._poll_operation(_check)
```

Note: `ArmingExceptionError` is a non-transient error, so `_poll_operation` will let it propagate immediately.

**In `disarm_alarm()`** — replace the polling loop (lines 1089-1110). Current code:
```python
        count = 1
        raw_data: dict[str, Any] = {}
        max_retries = max(10, round(30 / max(1, self.delay_check_operation)))
        while (count == 1) or (
            raw_data.get("res") == "WAIT"
            or raw_data.get("msg") == "alarm-manager.error_no_response_to_request"
        ):
            if count > max_retries:
                ...
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_disarm_status(...)
            count = count + 1
```

Replace with:
```python
        count = 0

        async def _check():
            nonlocal count
            count += 1
            return await self._check_disarm_status(
                installation, reference_id, command, count,
            )

        raw_data = await self._poll_operation(
            _check,
            continue_on_msg="alarm-manager.error_no_response_to_request",
        )
```

**In `change_lock_mode()`** — replace the polling loop (lines 1247-1256). Current code:
```python
        count = 1
        raw_data: dict[str, Any] = {}
        while (count == 1) or raw_data.get("res") == "WAIT":
            await asyncio.sleep(self.delay_check_operation)
            raw_data = await self._check_change_lock_mode(...)
            count = count + 1
```

Replace with:
```python
        count = 0

        async def _check():
            nonlocal count
            count += 1
            return await self._check_change_lock_mode(
                installation, reference_id, count,
            )

        raw_data = await self._poll_operation(_check)
```

**Step 6: Run all tests**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

Expected: All tests pass.

**Step 7: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py tests/test_helpers.py
git commit -m "refactor: extract _poll_operation() helper with transient error retry and timeout"
```

---

### Task 4: Fix error handling in `_check_authentication_token()`

Replace the bare `except Exception` with specific exception types. Upgrade logging from debug to warning.

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py`
- Modify: `tests/test_helpers.py`

**Step 1: Write the failing tests**

Add to `tests/test_helpers.py`:

```python
from aiohttp import ClientConnectorError


# ── _check_authentication_token() error handling ────────────────────────────


class TestCheckAuthenticationTokenErrorHandling:
    async def test_falls_back_to_login_on_securitas_error(self, api):
        """Should fall back to login() when refresh raises SecuritasDirectError."""
        api.authentication_token = None  # trigger refresh path
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(
            side_effect=SecuritasDirectError("refresh failed", None)
        )
        api.login = AsyncMock()

        await api._check_authentication_token()
        api.login.assert_called_once()

    async def test_falls_back_to_login_on_timeout(self, api):
        """Should fall back to login() when refresh raises asyncio.TimeoutError."""
        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(side_effect=asyncio.TimeoutError())
        api.login = AsyncMock()

        await api._check_authentication_token()
        api.login.assert_called_once()

    async def test_falls_back_to_login_on_connection_error(self, api):
        """Should fall back to login() when refresh raises ClientConnectorError."""
        from unittest.mock import MagicMock

        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        conn_err = ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("fail")
        )
        api.refresh_token = AsyncMock(side_effect=conn_err)
        api.login = AsyncMock()

        await api._check_authentication_token()
        api.login.assert_called_once()

    async def test_does_not_catch_unexpected_exceptions(self, api):
        """Should NOT catch unexpected exceptions like ValueError."""
        api.authentication_token = None
        api.refresh_token_value = "some-refresh-token"
        api.refresh_token = AsyncMock(side_effect=ValueError("unexpected"))
        api.login = AsyncMock()

        with pytest.raises(ValueError, match="unexpected"):
            await api._check_authentication_token()
```

**Step 2: Run tests to verify behavior**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py::TestCheckAuthenticationTokenErrorHandling -v --tb=short`

Expected: The last test (`test_does_not_catch_unexpected_exceptions`) should FAIL because the current bare `except Exception` catches everything.

**Step 3: Fix the error handling**

In `apimanager.py`, find `_check_authentication_token()` (around line 286). Replace:

```python
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Refresh token error, falling back to login")
```

With:
```python
                except (
                    SecuritasDirectError,
                    asyncio.TimeoutError,
                    ClientConnectorError,
                ) as err:
                    _LOGGER.warning("Refresh token error, falling back to login: %s", err)
```

Also change the line above it from:
```python
                    _LOGGER.debug("Refresh token failed, falling back to login")
```
To:
```python
                    _LOGGER.warning("Refresh token failed, falling back to login")
```

**Step 4: Run all tests**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

Expected: All tests pass, including the new test that verifies `ValueError` is NOT caught.

**Step 5: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py tests/test_helpers.py
git commit -m "fix: replace bare except in _check_authentication_token with specific exceptions"
```

---

### Task 5: Add token cleanup to `logout()` and upgrade refresh failure logging

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py`
- Modify: `tests/test_helpers.py`

**Step 1: Write the failing tests**

Add to `tests/test_helpers.py`:

```python
# ── logout() token cleanup ──────────────────────────────────────────────────


class TestLogoutTokenCleanup:
    async def test_clears_tokens_on_successful_logout(self, api, mock_execute):
        """Logout should clear all stored tokens."""
        api.authentication_token = "some-token"
        api.refresh_token_value = "some-refresh"
        api.authentication_token_exp = datetime.now()
        api.login_timestamp = 12345

        mock_execute.return_value = {"data": {"xSLogout": True}}
        await api.logout()

        assert api.authentication_token is None
        assert api.refresh_token_value == ""
        assert api.authentication_token_exp == datetime.min
        assert api.login_timestamp == 0

    async def test_clears_tokens_even_on_failed_logout(self, api, mock_execute):
        """Tokens should be cleared even if the logout API call fails."""
        api.authentication_token = "some-token"
        api.refresh_token_value = "some-refresh"
        api.authentication_token_exp = datetime.now()
        api.login_timestamp = 12345

        mock_execute.side_effect = SecuritasDirectError("logout failed", None)

        with pytest.raises(SecuritasDirectError):
            await api.logout()

        assert api.authentication_token is None
        assert api.refresh_token_value == ""
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/test_helpers.py::TestLogoutTokenCleanup -v --tb=short`

Expected: FAIL — logout doesn't clear tokens.

**Step 3: Add token cleanup to `logout()`**

In `apimanager.py`, find `logout()` (around line 323). Replace:

```python
    async def logout(self):
        """Logout."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        await self._execute_request(content, "Logout")
```

With:
```python
    async def logout(self):
        """Logout."""
        content = {
            "operationName": "Logout",
            "variables": {},
            "query": "mutation Logout {\n  xSLogout\n}\n",
        }
        try:
            await self._execute_request(content, "Logout")
        finally:
            self.authentication_token = None
            self.refresh_token_value = ""
            self.authentication_token_exp = datetime.min
            self.login_timestamp = 0
```

**Step 4: Run all tests**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

Expected: All tests pass.

**Step 5: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py tests/test_helpers.py
git commit -m "fix: clear tokens on logout and upgrade refresh failure logging"
```

---

### Task 6: Remove dead code

The `_check_errors()` method (lines 250-269) and commented-out code blocks are dead code. Clean them up.

**Files:**
- Modify: `custom_components/securitas/securitas_direct_new_api/apimanager.py`

**Step 1: Verify `_check_errors()` is not called**

Search the codebase for any calls to `_check_errors`:
```bash
cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && grep -rn "_check_errors" custom_components/ tests/
```

It should only show the method definition and the commented-out call in `_execute_request()`.

**Step 2: Remove `_check_errors()` method and commented-out code**

Delete the `_check_errors()` method entirely (lines 250-269).

Delete the commented-out block in `_execute_request()` (lines 202-206):
```python
            # error_login: bool = await self._check_errors(response_text)
            # if error_login:
            # response_text: str = await self._execute_request(
            #     content, operation, installation
            # )
```

Delete the commented-out debug lines in `_execute_request()` (lines 169-172):
```python
        # _LOGGER.debug("--------------Content---------------")
        # _LOGGER.debug(content)
        # _LOGGER.debug("--------------Headers---------------")
        # _LOGGER.debug(headers)
```

Delete the commented-out lines in `get_all_services()` (lines 644-645):
```python
        # json_services = json.dumps(raw_data)
        # result = json.loads(json_services)
```

**Step 3: Run all tests**

Run: `cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py`

Expected: All tests pass.

**Step 4: Commit**

```bash
git add custom_components/securitas/securitas_direct_new_api/apimanager.py
git commit -m "chore: remove dead _check_errors() method and commented-out code"
```

---

### Task 7: Lint, format, type-check, and final verification

**Files:**
- Any files modified in previous tasks

**Step 1: Run ruff check and format**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && ruff check . && ruff format .
```

Fix any issues found.

**Step 2: Run pyright**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && npx pyright
```

Only pre-existing errors expected (homeassistant module imports). No new errors from our changes.

**Step 3: Run full test suite**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/refactor-network && python -m pytest tests/ -v --tb=short --ignore=tests/test_config_flow.py --ignore=tests/test_init.py --ignore=tests/test_integration.py
```

Expected: All tests pass.

**Step 4: Commit any formatting fixes**

```bash
git add -A && git commit -m "style: apply ruff formatting"
```

(Only if there are changes to commit.)
