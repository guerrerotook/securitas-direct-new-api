# Centralized Log Sanitization

## Problem

Debug logging exposes private information: authentication tokens, refresh tokens, usernames, passwords, installation numbers, and OTP data. There is no sanitization anywhere in the codebase. Full API response bodies are logged at DEBUG level, and `SecuritasDirectError` exceptions embed tokens and auth headers in their args, which are then logged by callers.

## Approach: `logging.Filter`

Python's `logging.Filter` intercepts every log record before it reaches a handler. A custom `SensitiveDataFilter` attached to the integration's root logger (`custom_components.securitas`) automatically redacts known sensitive values from all log output — including from sub-loggers in `apimanager`, `alarm_control_panel`, `lock`, etc.

This was chosen over a manual `redact()` utility because:
- New log statements are covered automatically without developer action
- Existing log statements need no changes
- All sub-modules are covered via logger hierarchy

## Design

### New file: `custom_components/securitas/log_filter.py`

`SensitiveDataFilter(logging.Filter)` with:

- `secrets: dict[str, str]` — maps raw sensitive values to redaction labels
- `installation_numbers: dict[str, str]` — maps full numbers to partial masks
- `update_secret(key: str, value: str)` — add/update a secret value; called when tokens change
- `add_installation(number: str)` — register an installation number for partial masking
- `filter(record: LogRecord) -> bool` — replaces occurrences of known secrets in `record.msg` and `record.args`, always returns `True`

The `filter()` method wraps replacement logic in try/except so a bug in redaction never breaks logging — it falls through to the original unredacted message.

### Redaction table

| Value | Source | Replacement |
|-------|--------|-------------|
| `authentication_token` | Login/refresh response | `[AUTH_TOKEN]` |
| `refresh_token_value` | Login/refresh response | `[REFRESH_TOKEN]` |
| `username` | Config entry | `[USERNAME]` |
| `password` | Config entry | `[PASSWORD]` |
| Installation numbers | Per-installation | Partial mask: `***5678` |
| OTP hash/token | 2FA flow | `[OTP_DATA]` |

Replacement is exact string matching against known values, not regex patterns. This avoids false positives.

### Registration points in `ApiManager`

- After login/refresh: register `authentication_token`, `refresh_token_value`
- After config load: register `username`, `password`
- After 2FA: register OTP hash and token values
- After installation fetch: register each installation number

### Filter attachment in `__init__.py`

During `async_setup_entry`:
1. Create the `SensitiveDataFilter` instance
2. Attach it to `logging.getLogger("custom_components.securitas")`
3. Store it on the hub so `ApiManager` can access it
4. Register `username` and `password` immediately

### Separate fix: exception messages

Two exception messages embed raw tokens in their string:
- `apimanager.py:539`: `f"Failed to decode authentication token {self.authentication_token}"` — remove the token value
- `apimanager.py:637-638`: `f"Failed to decode capabilities token {installation.capabilities}"` — remove the JWT value

These are fixed by removing the raw values from the format strings (just say "Failed to decode authentication token" / "Failed to decode capabilities token").

## Testing

- Unit test the filter directly: register secrets, pass log records through, assert redacted output
- Test dynamic updates: change a token value, verify new value is redacted, old value no longer matched
- Test partial masking of installation numbers (various lengths)
- Test non-string args (dicts, ints, None) handled gracefully
- Test that filter never raises — malformed input falls through to original message
