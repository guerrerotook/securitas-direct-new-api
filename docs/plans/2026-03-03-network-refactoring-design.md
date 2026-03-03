# Network Code Refactoring Design

**Goal:** Reduce code duplication in `apimanager.py` by extracting shared helpers, fix inconsistent error handling, and improve token management.

**Approach:** Add private helper methods directly to `ApiManager`. Minimal structural change, easy to review, low risk.

**Scope:** Full cleanup — DRY extraction, error handling fixes, token management, response validation standardization.

---

## Current Problems

### Code Duplication

1. **JWT token decoding** — same ~10 lines copy-pasted in `validate_device()`, `refresh_token()`, `login()`, `get_all_services()` (4 instances)
2. **Response data extraction + None check** — `response["data"][field_name]` with None guard repeated in 13+ methods
3. **Polling loops** — nearly identical retry logic in `arm_alarm()`, `disarm_alarm()`, `change_lock_mode()` (3 instances)

### Error Handling Issues

1. **Bare `except Exception`** in `_check_authentication_token()` catches everything including `SystemExit`
2. **Inconsistent response validation** — some methods check `"data"` key exists, others don't
3. **No per-iteration error handling in poll loops** — one network blip fails the entire arm/disarm/lock operation
4. **No wall-clock timeout on polling** — loops are count-bounded but not time-bounded
5. **Silent error masking** — `get_sentinel_data()`, `get_air_quality_data()`, `get_smart_lock_config()`, `get_lock_current_mode()` return empty defaults on API errors (keep current behavior, flag in PR)

### Token Management

1. **No token cleanup on logout** — `logout()` sends the request but doesn't clear stored tokens
2. **Refresh failure logged at debug** — should be warning level

---

## Design

### New Helper Methods

#### `_decode_auth_token(token_str: str) -> dict | None`

Decodes a JWT auth token, extracts expiration, sets `self.authentication_token_exp`. Returns the decoded token dict or None on decode failure. Logs warning on failure.

Replaces 4 identical blocks in `validate_device()`, `refresh_token()`, `login()`, `get_all_services()`.

#### `_extract_response_data(response: dict, field_name: str) -> dict`

Validates that `response["data"][field_name]` exists and is not None. Raises `SecuritasDirectError` with an informative message if missing. Returns the extracted data.

Replaces 13+ inline None checks with consistent validation.

#### `_poll_operation(check_fn, installation, reference_id, ...) -> result`

Generic polling loop that:
- Calls `check_fn(installation, reference_id)` repeatedly
- Sleeps `delay_check_operation` seconds between polls
- Retries on transient errors (`ClientConnectorError`, `asyncio.TimeoutError`, `SecuritasDirectError` with HTTP status >= 500)
- Fails immediately on non-transient errors
- Enforces a wall-clock timeout (default 60 seconds)
- Logs transient errors at warning level

Replaces 3 nearly identical polling loops in `arm_alarm()`, `disarm_alarm()`, `change_lock_mode()`.

### Error Handling Fixes

- **`_check_authentication_token()`**: Replace `except Exception` with `except (SecuritasDirectError, asyncio.TimeoutError, ClientConnectorError)`. Log at warning level.
- **Response validation**: All methods use `_extract_response_data()` for consistent KeyError handling.
- **Poll loops**: Transient errors caught per iteration, logged, and retried. Non-transient errors fail immediately.

### Token Management

- **Logout cleanup**: After logout request, clear `authentication_token`, `refresh_token_value`, `authentication_token_exp`, `login_timestamp`.
- **Refresh failure logging**: Log at warning level with failure reason.

### Testing

- TDD approach: write failing tests first for each helper
- New tests for `_decode_auth_token()`, `_extract_response_data()`, `_poll_operation()`
- All 391 existing tests must remain green

### PR Notes

Flag for future discussion:
- Silent-return methods (`get_sentinel_data`, etc.) — should these raise instead of returning empty defaults?
- `logout()` is never called during normal HA operation — should it be wired into `async_unload_entry`?
