# Architecture Guide

This document explains how the Verisure OWA integration works, aimed at developers who want to contribute.

## System overview

The integration has three layers:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Home Assistant Platform Layer                                       │
│  alarm_control_panel/  sensor.py  binary_sensor.py                   │
│  lock.py  button.py  camera.py                                       │
│  entity.py  (VerisureEntity base class)                              │
│  coordinators.py  (DataUpdateCoordinators)                           │
│  events.py  (Activity log → bus event injection + dedup)             │
│  discovery.py  (Background camera + lock discovery)                  │
│  card_resources.py  (Lovelace static-path + resource registration    │
│    + the verisure_owa/deprecated_element websocket command           │
│    + the More Info module loaded on every page)                      │
├──────────────────────────────────────────────────────────────────────┤
│  Integration Hub Layer                                               │
│  __init__.py  (setup functions)                                      │
│  hub.py  (VerisureHub + VerisureDevice)                              │
│  config_flow.py  (ConfigFlow + OptionsFlow + Reauth/Reconfigure)     │
│  api_queue.py  (Priority-based rate limiting)                        │
│  log_filter.py  (SensitiveDataFilter + TransientCoordinatorErrorFilter)│
│  pin_crypto.py  (hash_pin/verify_pin — PIN stored hashed, never plain)│
│  migrate.py  (v3→v5 + securitas→verisure_owa rebrand migration)      │
├──────────────────────────────────────────────────────────────────────┤
│  API Client Layer                                                    │
│  verisure_owa_api/                                                   │
│  client/  (VerisureOwaClient — per-domain mixins on a base)          │
│  http_transport.py  (HttpTransport — raw HTTP with retries)          │
│  graphql_queries.py  command_resolver.py  domains.py  capabilities.py│
│  models/  responses/  const.py  exceptions.py                        │
└──────────────────────────────────────────────────────────────────────┘
```

Every API call goes through `HttpTransport.execute()` (in `http_transport.py`), which sends POST requests over HTTP to Verisure's cloud. `VerisureOwaClient` (in `client/`) composes an `HttpTransport` instance and adds authentication lifecycle, typed GraphQL execution via Pydantic response envelopes, and all business-level operations (login, arm/disarm, status checks, etc.). Operations are grouped into per-domain mixins (`_auth`, `_alarm`, `_lock`, `_camera`, `_sentinel`, `_installation`) that the public `VerisureOwaClient` class composes. The integration hub (`VerisureHub` in `hub.py`) wraps the API client and is shared by all entity platforms. Four `DataUpdateCoordinator` subclasses (in `coordinators.py`) handle periodic polling for alarm status, sentinel sensors, locks, and cameras. All entity platforms use the `CoordinatorEntity` pattern. Each platform creates entities for the installations discovered at startup.

## API client layer

**Location:** `custom_components/verisure_owa/verisure_owa_api/`

### HttpTransport (`http_transport.py`)

The bottom transport layer. It has no knowledge of auth tokens, GraphQL structure, or Verisure API semantics. All it does is POST JSON to a base URL and return the parsed response.

**Request execution:** `execute(content, headers)`:
1. Merges caller-provided headers on top of defaults (`User-Agent`, `content-type`)
2. POSTs the JSON body via `aiohttp.ClientSession.post()`
3. Retries once on DNS errors (`ClientConnectorDNSError`)
4. Retries once on HTTP 403 with `Retry-After` header (rate limiting) — unless the caller passes `retry_on_403=False`, which the client's single `_send()` does for the auth mutations (`RefreshLogin`, `mkLoginToken`, `mkValidateDevice`, `mkSendOTP`): `RefreshLogin` rotates a one-time refresh token and the OTP calls consume a one-time code on the first send, so a blind re-send would present already-used material; the password login is kept with them so no credential-bearing request is ever repeated by the transport
5. Raises `WAFBlockedError` immediately if 403 response contains `_Incapsula_Resource` (WAF blocks require longer backoff — retrying would extend the block)
6. Raises `VerisureOwaError` on HTTP >= 400
7. Parses JSON and returns the dict

**Response log sanitization:** Before logging API responses at DEBUG level, `_sanitize_response_for_log()` replaces large fields (`hours`, `image`) with placeholder values (`["..."]` for lists, `"..."` for strings). This prevents base64-encoded camera images and hourly sensor arrays from flooding the debug log.

### VerisureOwaClient (`client/`)

A composed class implementing all business-level API operations: login, refresh, 2FA validation, arm/disarm, status checks, sentinel data, lock operations, camera operations, and service discovery. All GraphQL query and mutation strings are defined in `graphql_queries.py` and imported here.

The class is split across per-domain mixins under the `client/` package — `_base.py` carries the transport composition, GraphQL execution, auth lifecycle, polling, and sanitization; `_auth.py`, `_alarm.py`, `_lock.py`, `_camera.py`, `_sentinel.py`, `_installation.py` each contribute their domain's operations as mixins. `VerisureOwaClient` itself lives in `client/__init__.py` and inherits from the mixins. The split is purely organisational; consumers import `VerisureOwaClient` exactly as before.

**Architecture:** `VerisureOwaClient` takes an `HttpTransport` via its constructor (composition, not inheritance, despite the mixin layout — the transport is held as `self._transport`). This separation means the transport layer can be mocked independently of business logic in tests.

**Typed GraphQL execution:** `_execute_graphql()` is the central entry point for all installation-scoped operations. It:
1. Calls `_ensure_auth()` (skipped for auth operations like `mkLoginToken`, `RefreshLogin`, `mkSendOTP`, `mkValidateDevice`)
2. Builds headers and posts via `_send()`, which also decides the transport's 403-retry policy (auth mutations are never re-sent)
3. Checks for GraphQL-level errors via `_check_graphql_errors()`
4. Validates the JSON response into a typed Pydantic envelope via `response_type.model_validate(response_dict)`
6. Returns the typed Pydantic model

Auth operations that need to inspect the raw response structure use `_execute_raw()` instead, which skips Pydantic validation and returns the raw dict.

**403 session-expired retry:** When the Verisure server returns a GraphQL error with `data.status == 403` (indicating a server-side session expiry), `_check_graphql_errors()` raises `SessionExpiredError`. The `_execute_graphql()` method catches this, forces token re-authentication, and retries the operation once. A `_retried` flag prevents infinite retry loops.

**Authentication** is JWT-based with three mechanisms:

1. **Login** (`login()`) — Sends credentials, receives a JWT hash token. The JWT's `exp` claim sets `authentication_token_exp`. If the account needs 2FA, raises `TwoFactorRequiredError`. If the account is blocked, raises `AccountBlockedError`.

2. **Token refresh** (`refresh_token()`) — Uses a long-lived refresh token to get a new JWT without re-entering credentials. Returns `True` on success, `False` on failure.

3. **2FA device validation** (`validate_device()`) — For new devices: calls `validate_device()` which returns a list of phone numbers. The user picks one, `send_otp()` sends the SMS, then `validate_device()` is called again with the OTP code to complete registration.

**Token lifecycle:** Before every API operation, `_ensure_auth()` checks whether the JWT expires within the next minute. If so, it tries `refresh_token()` first, falling back to `login()`. A single `xSRefreshLogin` crash, or a single refusal of the stored token with error code 4 (sent with status 404), is transient, but the client counts both the same way (`dead_refresh_token_signal`, `_note_refresh_crash`, at most one per renewal window) and on the third with no successful renewal in between condemns the token: `refresh_token_is_dead` is latched, every later renewal on the shared client raises `RefreshTokenDeadError` without a round-trip (or falls back to `login()` if a password is stored), and only `note_auth_success()` or `adopt_refresh_token()` clears it. Errors during refresh are caught with specific exception types (`VerisureOwaError`, `asyncio.TimeoutError`) rather than bare `except`. Similarly, `_ensure_capabilities()` checks a per-installation capabilities JWT that's obtained from `get_services()`. On `logout()`, all tokens are cleared (`authentication_token`, `refresh_token_value`, `authentication_token_exp`, `login_timestamp`) to prevent stale credentials from being reused.

**Refresh-token persistence:** The auth token (~15 min TTL) is in-memory only, but the long-lived refresh token (~180 day TTL) is persisted to `entry.data[CONF_REFRESH_TOKEN]` so reloads don't need a password. The client accepts an `on_refresh_token_changed(new_token)` callback that fires whenever `login()`, `refresh_token()`, or `validate_device()` updates `refresh_token_value`. The hub registers `_persist_refresh_token` as that callback, which writes the new value to `entry.data` via `hass.config_entries.async_update_entry` and atomically scrubs any legacy `CONF_PASSWORD`. Same-token rotations on a clean entry are a no-op to avoid redundant store writes. It writes nothing into an entry whose saved username is not the session's account (`outcome=other-account`; see Session sharing).

**DRY helpers:** Internal helpers reduce code duplication:

- `_decode_auth_token(token_str)` — Decodes a JWT (signature not verified — Verisure's tokens are EdDSA-signed but we only need the `exp` claim for client-side expiry tracking), updates `authentication_token_exp` from the `exp` claim. Returns the decoded claims dict or `None` on failure. Used by `login()`, `refresh_token()`, and `validate_device()`.

- `_extract_response_data(response, field_name)` — Extracts `response["data"][field_name]`, raising `VerisureOwaError` if the data is missing or `None`. Used by poll-status callbacks that work with raw dicts.

- `_poll_operation(check_fn, *, timeout, delay, continue_on_msg)` — Polls `check_fn()` in a loop until the result is no longer `"WAIT"`. Handles transient errors (connection errors, timeouts, 409 "server busy") by retrying. Raises `OperationTimeoutError` after `timeout` seconds (default `poll_timeout`). The `delay` parameter overrides the integration-wide `poll_delay` for callers with known long latency — image capture passes `delay=5.0` to avoid hammering the API on captures that routinely take 30-90 s server-side. Used by arm, disarm, status check, exception fetch, lock, and camera operations.

- `_ensure_auth(installation)` — Checks both the authentication token and the per-installation capabilities token, refreshing them as needed before executing a request.

- `_build_headers(operation, *, installation)` — Builds request headers including `app`, `auth` (JSON with JWT hash, user, country), `X-APOLLO-OPERATION-ID`, `X-APOLLO-OPERATION-NAME`, and optionally `numinst`/`panel`/`X-Capabilities` for installation-scoped requests. Auth operations (`mkValidateDevice`, `RefreshLogin`, `mkSendOTP`) use special headers with empty hash/refreshToken.

**Polling pattern:** Arm, disarm, status-check, exception-fetch, lock, and camera operations are asynchronous on the server side. The client sends the initial request, receives a `referenceId`, then polls a status endpoint via `_poll_operation()` (sleeping `poll_delay` seconds between attempts) until the response changes from `"WAIT"` to a final state or a wall-clock timeout is reached. Transient errors during polling — connection failures, timeouts, and 409 "server busy" responses — are automatically retried rather than failing the operation. After polling completes, `arm()` and `disarm()` check for `res: "ERROR"` with non-`NON_BLOCKING` error types (e.g. `TECHNICAL_ERROR`) and raise `VerisureOwaError`, enabling the command resolver's fallback chain.

**Camera capture:** `capture_image()` (in the client) submits the capture request, then polls `RequestImagesStatus` at 5-second intervals (kept distinct from the integration-wide `poll_delay` to avoid hammering the API on long captures) until the status transitions from "processing" to done. When called with `wait_for_fresh=True` (the default from the hub), it also pre-fetches a baseline thumbnail at request time, then after status-success polls `xSGetThumbnail` every 5 s for up to 30 s until a frame strictly newer than the baseline appears — lexicographic compare on the server's ISO timestamp, no timezone math needed since both sides come from the same server clock. Without that loop the CDN's tens-of-seconds lag after capture-acknowledge returns the previous frame. The whole status-poll has a 90-second deadline; if it fires, the freshness-poll still runs against whatever the CDN has caught up to. `get_full_image()` fetches full-resolution photos via `xSGetPhotoImages`, selects the largest BINARY image, base64-decodes it, and validates JPEG magic bytes.

**Device spoofing:** The client identifies itself as a Samsung Galaxy S22 running the Verisure mobile app v10.102.0. Device identity consists of three IDs generated at setup time: `device_id` (FCM-format token), `uuid` (16-char hex), and `id_device_indigitall` (UUID v4).

### Response envelopes (`responses/`)

Every GraphQL operation has a typed Pydantic `BaseModel` envelope under the `responses/` package that mirrors the exact shape of the API response. For example, `ArmPanelEnvelope` wraps `{"data": {"xSArmPanel": {res, msg, referenceId}}}`. This provides compile-time type safety and runtime validation — if the API response shape changes unexpectedly, `model_validate()` raises `ValidationError` which `_execute_graphql()` converts to `VerisureOwaError`.

The package is split per domain (`alarm.py`, `lock.py`, `camera.py`, `sentinel.py`, `auth.py`, `installation.py`, plus shared `_common.py` for `_ResMsg`, `_ResMsgRef`, `_OperationResult`, `_GeneralStatus`). All envelopes are re-exported from `responses/__init__.py`.

Envelopes use a `_NullSafeBase` base class that coerces `None` to `""` for any `str` field with a default. This is necessary because the Verisure API returns `null` for string fields during polling or when fields are not applicable, and Pydantic rejects `None` for `str` fields even with a default.

Shared inner models (`_ResMsg`, `_ResMsgRef`, `_OperationResult`, `_GeneralStatus`) are used across multiple envelopes to avoid duplication. `PanelError` carries force-arm context (allowForcing, referenceId, suid).

### Domain models (`models/`)

Pydantic models for API domain objects, split per domain (`alarm.py`, `lock.py`, `camera.py`, `sentinel.py`, `installation.py`, `services.py`) and re-exported from `models/__init__.py`. All domain models inherit from `_NullSafeBase` (same null-coercion logic as response envelopes). The most important ones:

- `Installation` — Represents a physical Verisure installation (number, alias, panel type, address, capabilities JWT, `alarm_partitions` list from services response). Uses `validation_alias` for API field name mapping (e.g. `numinst` -> `number`).
- `OperationStatus` — Result of an alarm or lock operation (arm, disarm, check) with `protomResponse` (the single-letter state code) and `protomResponseData`
- `SStatus` — General status with `wifi_connected` boolean (diagnostic) and `timestampUpdate`
- `OtpPhone` — Phone number option during 2FA setup
- `SmartLock` — Smart lock discovery response with device metadata (serialNumber, features)
- `SmartLockMode` — Lock mode with `deviceId` field for multi-lock support
- `SmartLockModeStatus` — Lock mode change operation status
- `CameraDevice` — Camera device (id, code, zone_id, name, serial_number, device_type)
- `ThumbnailResponse` — Thumbnail data (id_signal, device_code, device_alias, timestamp, signal_type, image as base64)
- `Sentinel` — Temperature, humidity, and air quality from a Sentinel device
- `AirQuality` — Air quality reading with value and status_current
- `Service` — A discovered service with attributes list
- `LockFeatures` — Lock features (holdBackLatchTime, calibrationType, autolock)
- `LockAutolock` — Autolock settings (active, timeout)

**Alarm state types** (also in `models.py`):

- `InteriorMode` — StrEnum: off, day, night, total
- `PerimeterMode` — StrEnum: off, on
- `AnnexMode` — StrEnum: off, on
- `ProtoCode` — StrEnum for single-letter protocol response codes (D, E, P, Q, B, C, T, A, X, R, S, O)
- `ArmCommand` — StrEnum for arm/disarm command strings (DARM1, ARM1, ARMDAY1, ARMANNEX1, DARMANNEX1, etc.)
- `AlarmState` — Frozen `BaseModel` combining `InteriorMode` + `PerimeterMode` + `AnnexMode`
- `parse_proto_code()` — Parses raw code to `ProtoCode`, raises `UnexpectedStateError` for unknown codes
- `PROTO_TO_STATE` — Maps `ProtoCode` to `AlarmState`
- `STATE_TO_PROTO` — Reverse mapping
- `STATE_TO_COMMAND` — Maps `AlarmState` to `ArmCommand`

### GraphQL queries (`graphql_queries.py`)

All GraphQL query and mutation strings are extracted into `graphql_queries.py`, keeping `client.py` focused on business logic. This module contains named constants for each operation (e.g. `VALIDATE_DEVICE_MUTATION`, `REFRESH_LOGIN_MUTATION`, `ARM_PANEL_MUTATION`, etc.) that `VerisureOwaClient` imports and passes to `_execute_graphql()`.

### Log sanitization (`log_filter.py`)

`SensitiveDataFilter` is a `logging.Filter` attached to all root logger handlers during integration setup. It redacts sensitive values (auth tokens, refresh tokens, usernames, passwords, OTP data) from log messages and arguments before they reach any handler (console, file, remote).

**How it works:**
- `update_secret(key, value)` registers a raw secret value with its redaction label (e.g. `"auth_token"` -> `[AUTH_TOKEN]`). Updating a key replaces the old value.
- `add_installation(number)` registers an installation number for partial masking (last 4 digits visible, e.g. `123456` -> `***3456`).
- The `filter()` method scans `record.msg` and `record.args` (including nested dicts/lists/tuples), replacing any known secret with its label.
- Registration happens in `VerisureOwaClient` via `_register_secret()` — called whenever tokens are obtained or refreshed (login, refresh, validate_device).
- The username is registered at setup time in `async_setup_entry()`. The password is registered there only if present (legacy v3 entries on first reload); refresh-token-shape entries skip it because no password is in scope.
- The filter is removed from handlers by the integration-wide clean-up (`_async_teardown_domain`), which runs once nothing uses the integration any more — see Session sharing.

**Error notifications:** When operations fail, error notifications shown to the user use only the short error message (`err.message`), never the full error tuple which could contain headers, tokens, or response bodies. The `log_detail()` method on exceptions provides verbose output only for unknown error types.

### Debug logging conventions

All debug log messages use context prefixes for easy filtering:

| Prefix | Layer | Example |
|--------|-------|---------|
| `response=` | HTTP (`http_transport.py`) | Sanitized JSON response |
| `[auth]` | Client (`client.py`) | Token refresh, re-authentication, capabilities checks |
| `[queue]` | Queue (`api_queue.py`) | Throttle delays and priority preemption |
| `[setup]` | Setup (`__init__.py`) | Card resource registration, entry migration |
| `[camera_discovery]` | Setup (`__init__.py`) | Camera device discovery and entity creation |
| `[hub]` | Hub (`hub.py`) | Thumbnail fetch, image storage |

### Country routing (`domains.py`)

`ApiDomains` maps country codes to API URLs and language codes. Supported countries: ES, FR, GB, IE, IT, BR, CL, AR, PT. Countries without an explicit entry fall back to a URL template using the country code as a subdomain.

### Alarm states and commands (`const.py`, `models.py`)

Verisure alarms have up to three independent axes: **interior mode** (disarmed, partial day, partial night, total), **perimeter** (on or off), and **annex** (on or off). Most installations only use the interior axis ± perimeter; the annex axis is used by some UK Vatrinus installations. The combination of interior × perimeter alone produces these 8 states:

| State | Interior | Perimeter | API Command | Proto Code |
|-------|----------|-----------|-------------|------------|
| `DISARMED` | off | off | `DARM1` | `D` |
| `PARTIAL_DAY` | day | off | `ARMDAY1` | `P` |
| `PARTIAL_NIGHT` | night | off | `ARMNIGHT1` | `Q` |
| `TOTAL` | full | off | `ARM1` | `T` |
| `PERI_ONLY` | off | on | `PERI1` | `E` |
| `PARTIAL_DAY_PERI` | day | on | `ARMDAY1PERI1` | `B` |
| `PARTIAL_NIGHT_PERI` | night | on | `ARMNIGHT1PERI1` | `C` |
| `TOTAL_PERI` | full | on | `ARM1PERI1` | `A` |

Most compound commands (`ARMDAY1PERI1`, `ARM1PERI1`) are accepted by all known panels. However, `ARMNIGHT1PERI1` and `DARM1DARMPERI` are rejected by some panels (e.g. SDVFAST in Spain). The integration auto-detects which commands the panel supports at runtime (see [Command resolver](#command-resolver) below).

**Panel-specific `DARM1` behavior:** On SDVFAST (Spain), `DARM1` disarms everything (interior + perimeter). On SDVECU (Italy), `DARM1` only disarms the interior — `DARMPERI` disarms only the perimeter, and `DARM1DARMPERI` disarms both. This difference is safe because the `DARM1` fallback only triggers on panels that reject `DARM1DARMPERI` (i.e. SDVFAST, where `DARM1` disarms everything).

Two mapping tables in `models.py` connect these:
- `PROTO_TO_STATE` — `ProtoCode` to `AlarmState` (e.g. `ProtoCode.TOTAL` -> `AlarmState(TOTAL, OFF)`)
- `STATE_TO_COMMAND` — `AlarmState` to `ArmCommand` (e.g. `AlarmState(TOTAL, OFF)` -> `ArmCommand.ARM_TOTAL`)

#### Command resolver

**Location:** `verisure_owa_api/command_resolver.py`

The `CommandResolver` class models the alarm as three independent axes — `InteriorMode` (off, day, night, total), `PerimeterMode` (off, on), and `AnnexMode` (off, on) — combined into an `AlarmState`. It replaces the old `_use_multi_step` flag, `_send_arm_command()` / `_send_disarm_command()` methods, `COMPOUND_COMMAND_STEPS` constant, and `PERI_ARMED_PROTO_CODES` set.

**How it works:**

1. `resolve(current, target)` computes the state transition and returns an ordered list of `CommandStep` objects. Each step contains a list of command alternatives to try in order.

2. Combined commands are tried first (e.g. `ARMINTEXT1`, `ARM1PERI1`), with multi-step fallbacks using `+` separator (e.g. `ARM1+PERI1` means send `ARM1` then `PERI1` as separate sequential API calls).

3. For Total+Perimeter arm, `ARMINTEXT1` is ordered before `ARM1PERI1` — `ARMINTEXT1` arms interior+perimeter in one step without triggering the siren delay, which is important for Spanish WAF (Wife Acceptance Factor) safety.

4. **Runtime discovery of unsupported commands:** When a command fails with a non-409 `VerisureOwaError`, `_execute_step()` calls `resolver.mark_unsupported(command)`, and the resolver skips it in all future resolutions. This is per-command granularity (not a global flag), so a disarm-specific failure (e.g. `DARM1DARMPERI`) does not disable unrelated compound arm commands. The unsupported set is in-memory and resets on HA restart.

5. **Disarm uses current state:** The resolver determines the disarm command from the current `AlarmState` (derived from `_planning_proto_code()`, see *Installation-wide confirmed state*), not from configuration flags. If both interior and perimeter are armed, it tries `DARM1DARMPERI` first, falling back to `DARM1`. If only perimeter is armed, it tries `DARMPERI` first, falling back to `DARM1`.

6. **409 errors** (server busy) are re-raised immediately and do not trigger the fallback chain.

Home Assistant has five alarm buttons (Home, Away, Night, Vacation, Custom Bypass). The user maps each button to a Verisure OWA state through the options flow. Standard installations get defaults without perimeter; perimeter installations get defaults that use perimeter states for Away (Total + Perimeter) and Custom (Perimeter Only). Both standard and perimeter installations default Night to Partial Night. Perimeter variants (e.g. Partial Night + Perimeter) are available in the options for perimeter installations and can be assigned to any button. The `Vacation` and `Custom Bypass` buttons are hidden unless a mapping is configured for them.

If the alarm is put into a state that is not mapped to any HA button (e.g. the perimeter is armed via a physical panel but perimeter support is not enabled in the integration), the entity reports `ARMED_CUSTOM_BYPASS` and logs the unmapped proto code as a warning, once per code. This is not an error — it simply means the alarm is in a valid Verisure OWA state that the user has not assigned to an HA button. To resolve it, enable perimeter support or map the relevant state in the integration options.

**Unknown proto codes: arm refuses, disarm proceeds** (issues [#441](https://github.com/guerrerotook/securitas-direct-new-api/issues/441), [#550](https://github.com/guerrerotook/securitas-direct-new-api/issues/550)). `_last_proto_code` and `AlarmCoordinator.confirmed_proto_code` admit any single uppercase ASCII letter — including codes we don't yet model (e.g. `N`, which Verisure reports after a central-station reset). The two operations are handled differently because a disarm command is *unconditional* while an arm is not:

- **Arm** needs a known current state to plan the transition, so `_execute_transition()` refuses it. With no code at all yet it raises a plain `VerisureOwaError` ("Alarm state not yet known"), handled like any arm failure with the `arm_failed` notification. With an unmodelled code it raises `_UnrecognisedStateError` (a `VerisureOwaError` carrying the code), which `set_arm_state` turns into a translated `HomeAssistantError`, `arm_refused_unknown_state`, naming the installation and the code and pointing at Settings → Repairs. Like the other translated refusals it is shown to whoever pressed Arm, puts the display back and sends no notification (except after Force Arm tapped in the phone notification, where no screen shows it: `_async_force_arm_from_notification()` sends any refused force arm as the `arm_failed` notification with the error's English text). Like `operation_in_progress` it logs a warning; unlike the other refusals it adds an `ARMING_FAILED` "Arm failed: …" activity-log entry attributed to the caller's context, as the `arm_failed` branch does. Other callers of `_execute_transition()` (a disarm, the lock's partial disarm) still see it as a `VerisureOwaError`. Sending incorrect transitions off an unknown state was one half of #441. The refusal clears automatically on the next poll once the alarm returns to a state we model.
- **Repairs issue.** While the latest code the alarm reported is a well-formed letter not in `PROTO_TO_ALARM_STATE`, `AlarmCoordinator` keeps a Repairs issue, `unknown_alarm_state_<installation number>` (translation key `unknown_alarm_state`, placeholders `code`, `installation` — the alias — and `url`), asking the user to report the code. `track_unrecognised_code()` runs from `record_confirmed_proto_code()` unless it is given `optimistic=True` (command answers, the pre-arm status check, a manual Refresh, a poll), and directly for a poll or Refresh answer held back from `confirmed_proto_code` while a command runs, so the issue follows the latest code the alarm reported. A timed-out command's optimistic code is recorded with `optimistic=True` and leaves the issue alone: it is a guess, not a code the alarm reported. A modelled code deletes the issue; anything that is not a proto letter leaves it alone. It is neither persistent (the first poll after a restart raises it again) nor fixable. `AlarmCoordinator.async_shutdown()`, which Home Assistant runs when the entry unloads (also before a removal or a reload), deletes it unless another loaded entry runs the installation's alarm panels (`main_panel_for()`; an installation added twice), so it does not outlive the last coordinator polling the installation: the entry that runs no panels owns no entities, so nothing listens to its coordinator and Home Assistant schedules no polls for it; after a reload the first poll raises it again if the code is still unknown. A code the integration models but no Main-panel button is mapped to is not this issue: `_log_unmapped_proto_code()` only logs a warning for it, once per code, as it also does for an unmodelled one.
- **Disarm** proceeds unconditionally. `_execute_transition()` routes a full disarm to `_disarm_circuits_unconditional()`, which asks the resolver for disarm-only steps (`resolve_disarm_only()`) — `DARM1` / `DARM1DARMPERI` / `DARMANNEX1` clear their axis regardless of the current state, so no read is needed. This is *not* the #441 silent no-op (resolver computing `current==target` off a stale `D` and skipping `DARM1`): the command is actually sent. A partial disarm (`execute_partial_disarm`, which the lock's auto-disarm calls with its circuits) takes the same path when the installation's latest known state (`AlarmCoordinator.confirmed_proto_code`, read through `_confirmed_alarm_state()`) is missing, unmodelled or provisional — otherwise an unmodeled code would read as nothing armed and the disarm would silently skip, leaving the door open over an armed alarm.

### Exceptions (`exceptions.py`)

```
VerisureOwaError                  Base class (http_status, message, response_body, log_detail())
├── AuthenticationError           Credentials rejected
│   ├── AccountBlockedError       Account blocked by Verisure
│   └── RefreshTokenDeadError     Refresh token condemned by a dead-token streak (crash or err 4) → reauth
├── TwoFactorRequiredError        2FA required
├── SessionExpiredError           JWT expired server-side (triggers re-auth in _execute_graphql)
├── APIResponseError              GraphQL-level error
├── WAFBlockedError               Incapsula WAF block (no retry)
├── APIConnectionError            Network-level failures (DNS, TCP, TLS)
├── OperationTimeoutError         Panel operation timeout
├── OperationFailedError          Panel rejection (carries error_code, error_type)
├── ArmingExceptionError          Open sensors blocking arm (carries force-arm context)
├── ImageCaptureError             Camera capture failure
├── UnexpectedStateError          Unrecognised protocol code (carries proto_code)
└── _UnrecognisedStateError       Transition refused: current state code not modelled (carries proto_code; private, in alarm_control_panel/_base.py)
```

`VerisureOwaError` takes `(message, *, http_status)` and has a `response_body` attribute that callers can set after construction. The `message` property returns the short human-readable description. The `log_detail()` method returns just the message for well-known HTTP statuses (400, 403, 409) and appends the response body for unknown errors to aid diagnosis.

`ArmingExceptionError` is raised when arming fails due to non-blocking exceptions (e.g. open window/door). It carries `reference_id`, `suid`, and the list of exceptions, providing the context needed to retry with `forceArmingRemoteId`.

## Integration hub layer

**Location:** `custom_components/verisure_owa/hub.py` (`VerisureHub`, `VerisureDevice`) and `custom_components/verisure_owa/__init__.py` (setup functions only)

### VerisureHub

The central coordinator between the HA layer and the API client. It owns a `VerisureOwaClient` session and is shared by all entity platforms via `hass.data[DOMAIN][entry.entry_id]["hub"]`.

**Key responsibilities:**
- **Auth delegation** — `login()` prefers the persisted refresh token (`CONF_REFRESH_TOKEN`, ~180-day TTL) and only falls back to a password login when no refresh token is available. If refresh fails and no password is on hand, `AuthenticationError` propagates up so the caller can map it to `ConfigEntryAuthFailed` and trigger reauth — no point sending an empty password to the API. The hub also registers `_persist_refresh_token` on the client, so server-rotated refresh tokens are written back to `entry.data` and any legacy `CONF_PASSWORD` is scrubbed on first capture.
- **Service discovery** — `get_services()` calls `VerisureOwaClient.get_services()` and caches the results per installation
- **API call serialization** — All API calls are submitted via `ApiQueue`, which enforces a minimum gap between calls to avoid triggering the Incapsula WAF rate limiter. See [ApiQueue](#apiqueue) below.
- **Camera management** — `get_camera_devices()` discovers cameras (cached), `capture_image()` requests new captures via the client and stores results. The hub handles HA-specific concerns: dispatcher signals (`SIGNAL_CAMERA_STATE`), image validation/storage, full-image background fetch, and coordinator data updates. After a capture completes, it pushes the new thumbnail and full image into the `CameraCoordinator` via `async_set_updated_data()`.
- **Lock management** — `get_lock_modes()` discovers locks (thin pass-through to the client), `change_lock_mode()` performs lock/unlock via queue, `get_lock_config()` fetches per-lock configuration (auto-detects Smartlock vs Danalock API).
- **Alarm operations** — `arm_alarm()`, `disarm_alarm()`, `refresh_alarm_status()` submit commands through the queue. `refresh_alarm_status()` uses the authoritative `CheckAlarm` round-trip (not just `xSStatus`).
- **Session sharing** — Multiple config entries for the same username share a single `VerisureHub` instance, tracked in `hass.data[DOMAIN]["sessions"]`. This prevents duplicate logins and reduces WAF pressure. Each record carries `holders`, the set of everyone using the hub: the ids of the config entries set up on it, plus one key per open config flow that signed in with it or borrowed it (`config_flow:<flow id>`). The hub is dropped once `holders` empties. An entry releases its hold when it unloads (`_release_shared_session`), or, if its setup failed after taking it, when it is deleted (`async_remove_entry`, since HA calls `async_unload_entry` only for a loaded entry). Each of these finds the session by the entry's hold, not by the username in its data (`_held_session_username`), because reauth or Reconfigure can sign the entry in to a different account and write that account into its data before reloading it; for the same reason entry setup (`_get_or_create_session`) first releases a hold the entry still has on another account's session. A config flow releases its hold in its `async_remove`, which HA runs on every way out of a flow — a returned or raised abort, the user closing the dialog, or a created entry, which HA has already set up (so the entry holds the hub) by then. A flow the user sends back to sign in to a different account lets go of the first account's session once it has signed in to the other account, or borrowed that account's running session. Holding ids rather than keeping a count makes a hold idempotent per holder, so a setup Home Assistant retries after `ConfigEntryNotReady` — which it does without unloading first — still counts once, and an entry holding nothing cannot take a co-tenant's hold away. Setup that reuses an existing session, and a config flow that borrows one, take their hold before awaiting anything, so a flow closing or the last entry unloading meanwhile cannot unregister it. A session never saves its refresh token into an entry whose stored username is not its own account (`_persist_refresh_token` logs `outcome=other-account` instead): reauth or Reconfigure can move the entry a session saves to onto another account before the session lets go of it. When the entry that saves the account's refresh tokens lets go, token saving is handed to another entry that holds the session — a loaded one first, otherwise one still setting up or retrying, or one whose setup failed while holding it. Only when nothing but config flows hold the session is the hub detached from that entry, and the entry a flow creates attaches itself during setup. An entry and a setup dialog signing in to the same account never both sign in from scratch: entry setup (`_get_or_create_session`) and a dialog that built its own hub (`_sign_in_and_hold_session`) each look for the account's session, and sign in and register one if there is none, under the same per-account lock (`_account_lock`), so whichever comes second uses the session the first registered. A reauth or Reconfigure dialog that has signed in takes the same lock before reloading (`_finish_reauth`). It never changes the login of a session already running: a running session for the account is taken out of `sessions` and stops saving tokens (`config_entry` set to `None`), so a renewal of the old login still in flight cannot save over the new one. The dialog registers its own signed-in hub as the account's session in its place and holds it (`config_flow:<flow id>`) until its reloads return (not until the dialog closes: Home Assistant 2025.5 and later close a reauth dialog as its entry's reload starts). It saves the new refresh token to its entry and to every other entry on the account, with no await in between, then reloads all of them, so each drops the old session and joins the new login. The entries of the old session keep using it until their own reload, which finds no hold on it in `sessions` and so releases nothing. A setup dialog still holding the old session moves its hold to the new one before it creates its entry (`_follow_replaced_session`), so the entry stores the login of the session it joins. A dialog that borrowed a running session is already holding it and signs it in again, when needed, without that lock, so an entry unloading meanwhile never waits on the dialog. Home Assistant unloads an entry that is retrying or whose setup failed without calling `async_unload_entry`; the integration listens for `SIGNAL_CONFIG_ENTRY_CHANGED` and, when one of its entries becomes `NOT_LOADED`, waits for that entry's own setup lock (which Home Assistant holds across a reload, so a reloaded entry is set up again first and keeps its session, unless reauth or Reconfigure switched its account, in which case setup releases the old one) and then releases the entry's hold if it is still not loaded (`_async_entry_unloaded`). The integration-wide clean-up (`_async_teardown_domain`) is checked whenever an entry unloads, however it was unloaded, an entry is deleted, or any config flow closes, and runs when that leaves no session held, no other entry loaded, setting up, waiting to retry, unloading or failed to set up, and no setup dialog open, where a Reconfigure dialog counts and a reauth one does not (`_async_teardown_domain_if_unused`), a check it repeats after removing the dashboard cards and before it drops the shared data. The entry states count as well as the sessions because an entry still signing in, or one that failed before taking a hold and is waiting to retry, holds no session yet but still needs the integration; so does an entry whose setup failed, usually one waiting for the user to sign in again, so the cards it registered before signing in stay registered until it is reloaded, switched off or deleted, each of which passes through `NOT_LOADED` and runs the check again. Reauth dialogs need not count: their entry does while it waits for them, and closing one runs the check again. The entry is not loaded while it reloads or is disabled, so the clean-up can run while a reauth submission is still waiting on Verisure; the list of running sign-ins that submission is checked against is kept outside `hass.data[DOMAIN]` for that reason. The clean-up and the cards' registration in entry setup share one lock (`_card_lock`, kept outside `hass.data[DOMAIN]`), so an entry setting up while the cards are being removed waits, then registers all of them again.
- **Address family** — Every HTTP client this integration uses is one Home Assistant owns: the code calls `async_get_clientsession(hass, family=...)`, which caches one session *and one connector* per address family and closes them at shutdown. Nothing here is ever detached or closed.

  `_login_ipv4_first` (setup) and `FlowHandler._login_with_family_fallback` (config flow) both delegate to `_login_ipv4_then_any`, which attempts the login on the `AF_INET` client first. Verisure's customer endpoint publishes no AAAA record in any supported country — all ten are CNAMEs into the same Imperva edge — so the IPv6 half of the default combined lookup can only ever come back empty, and on some resolvers that empty answer fails the whole lookup instead of falling back to the IPv4 address that resolved (#606).

  The fallback serves the opposite network: a host with no IPv4 route of its own, reaching IPv4-only servers through NAT64/DNS64. A host with no IPv4 address at all fails instantly (the OS has no route), so the fallback is immediate; a host whose IPv4 packets are silently dropped instead waits out aiohttp's 30-second `sock_connect` first, because HA's session passes no timeout of its own. That is once per setup or reload, not per request. It fires only when `APIConnectionError.connection_never_established` is true. That flag is set in one place — `http_transport`, the only layer that still holds aiohttp's own exception: true for a `ClientConnectorError` (the name did not resolve, or the connection was refused or unreachable) or a `ConnectionTimeoutError` (the connection never opened, so nothing was written to it — the host whose IPv4 packets are dropped rather than refused). A **read timeout is deliberately excluded**: `SocketTimeoutError` means the request was sent and the reply is late, so it may have arrived and been acted on, and this integration does not resend a sign-in to a busy server, because resending can end the session rather than recover it. Both timeout classes subclass `ServerTimeoutError` and neither subclasses the other, so they are genuinely separable. Callers only read the flag; they never re-derive it from `__cause__`. On the setup path `_login_or_raise(..., retry_other_family=True)` leaves that narrow case unmapped so `_login_ipv4_then_any` can read the flag, and a first attempt about to be retried neither logs an error nor counts towards the dead-token streak; every other failure takes the unchanged path. The config-flow fallback additionally rebuilds only a hub the flow owns — a hub borrowed from a running shared session is signed in on its existing family and never swapped out.

  **Known limitation:** the family is chosen once, at login, and pinned for the hub's life (the session and its connector are fixed). A host that had a working IPv4 route at setup but later loses it — and must then reach Verisure over IPv6/NAT64 — stays pinned to `AF_INET` and cannot recover until the entry is reloaded. This is the price of the `AF_INET`-only pin that #606 needs; a single static choice cannot satisfy both "IPv4-only forever" (the #606 network) and "follow the network" (this one).


### Coordinators (`coordinators.py`)

Four `DataUpdateCoordinator` subclasses replace per-entity independent polling. Each coordinator owns a reference to the `VerisureOwaClient` and `ApiQueue`, fetches data on its configured interval, and handles `SessionExpiredError` (re-login + retry), `WAFBlockedError`, and general `VerisureOwaError` by raising `UpdateFailed`.

**`AlarmCoordinator`** — Polls alarm status via `get_general_status()` (lightweight `xSStatus`, no panel wake). Returns `AlarmStatusData` with `SStatus` and `protom_response`. Update interval is the user-configured `scan_interval`.

**`SentinelCoordinator`** — Fetches sentinel data and air quality sequentially via `get_sentinel_data()` + `get_air_quality_data()`. Returns `SentinelData`. Fixed 30-minute interval (environmental data changes slowly).

**`LockCoordinator`** — Fetches lock modes via `get_lock_modes()`. Returns `LockData`. Update interval is the user-configured `scan_interval`.

**`CameraCoordinator`** — Fetches thumbnails for all cameras. Returns `CameraData` with `thumbnails` (per zone_id) and `full_images` (per zone_id). Fixed 30-minute interval. Individual camera failures are logged but don't fail the whole update — previous thumbnails are preserved. When a thumbnail's `id_signal` changes from the previous refresh, the coordinator automatically fetches the full-resolution image via `get_full_image()`. Thumbnails older than 1 hour are skipped for full-image fetch (they likely have no full image available on the CDN).

All coordinators share the same error-handling pattern: catch `SessionExpiredError` -> re-login -> retry once; catch `WAFBlockedError` or `VerisureOwaError` -> raise `UpdateFailed`.

### ApiQueue (`api_queue.py`)

Serializes API calls with priority-based rate limiting to avoid WAF blocks. One queue is shared per API domain (country).

**Design:**
- Two priority levels: `FOREGROUND` (arm/disarm, user actions, setup) and `BACKGROUND` (polling)
- Both share the same minimum interval (`delay_check_operation`, default 2 seconds)
- Foreground requests preempt queued background work — background waits while any foreground request is waiting
- Within a level, requests run in the order they arrived, so a caller submitting back to back (camera thumbnails) can't starve one that queued earlier (the first alarm status after a reload)
- In-flight API calls are not cancelled; preemption happens between calls

**Algorithm:**
1. `submit(coro_fn, *args, priority, label)` accepts an async callable + args. The optional `label` overrides the function name in throttle log messages.
2. The call joins the end of its level's line (`_waiting[priority]`) with its own wake-up event
3. Only the call that goes next is woken (`_wake_next`): the first in the foreground line, else the first in the background line, and only while no call is running. A woken call that is no longer next (foreground arrived meanwhile) goes back to waiting
4. If the minimum gap (`interval - elapsed_since_last_api_time`) hasn't passed, it sleeps it out and checks again
5. It leaves the line, runs the coroutine, updates `_last_api_time` and wakes the next call; a caller cancelled while waiting leaves the line and wakes the next one too

### Setup flow (`async_setup_entry`)

**Critical rule:** Platform `async_setup_entry` functions must **never** make API calls. All API-based discovery is deferred to a background task that runs after setup completes. This avoids blocking HA startup.

**Config-entry migration (`async_migrate_entry`):** runs before `async_setup_entry` whenever `entry.version` is below the current `VERSION` (5), or `entry.minor_version` below `MINOR_VERSION` (2). Pre-v3 entries are rejected with a user notification. v3 → v4 strips the obsolete `CONF_TOKEN` dead-write key and bumps the version. `CONF_PASSWORD` is intentionally preserved so the next successful login can still happen on legacy entries; it is scrubbed lazily by `VerisureHub._persist_refresh_token` on first capture. v4 → v5 hashes any plain-text `CONF_CODE` still present in `entry.data`/`entry.options` (via `pin_crypto.hash_pin`) into `CONF_CODE_HASH` + `CONF_CODE_IS_NUMERIC`, then drops the plain-text key — see "PIN code validation" below. It rewrites the key wherever it was *present*, not just where it was non-empty: an empty `options["code"]` means "the user removed the PIN" and has to keep shadowing a stale `data["code"]` (`_opt` reads options first), so it becomes `CONF_CODE_HASH: None` rather than an absent key, which would stop shadowing and resurrect the old PIN. 5.1 → 5.2 (`_migrate_entry_unique_id`) rebuilds the entry's unique ID as `<username>_<installation>`, which corrects an ID still carrying the email from before a reauth account switch; an entry with no installation number keeps its ID. `CONF_USERNAME` is never rewritten: the login is used exactly as typed everywhere (sign-in, reauth, unique ID, the stores keyed by username), because Verisure Italy rejects a registered email typed in other capitals (`xSLoginToken` error 60091, tested 2026-09-29). It is a minor bump so an older release still loads the entry. When another entry of the domain works out to the same ID (two entries switched to the same account for one installation), neither entry is removed — which of the two owns the installation's entities is decided by which sets up first, so it can change on any restart — and the entry only takes the new ID when no other entry holds it. The user is asked to delete one by a Repairs issue, `duplicate_entry`, which `_async_update_duplicate_entry_issues` keeps in step with the entries: it runs at the start of every `async_setup_entry`, in `async_remove_entry`, and in the reauth or Reconfigure step once it has saved the entry's new account (the reload that follows runs no setup when the entry is disabled), groups the domain's entries by `_entry_unique_id` (entries with none are skipped), raises one issue per ID held by two or more, and deletes any `duplicate_entry_*` issue whose clash has gone — so it clears as soon as the user removes the duplicate, without a restart. Home Assistant drops an entry from `hass.config_entries` before it calls `async_remove_entry`; the entry being removed is still excluded explicitly. The issue is not persistent: Home Assistant forgets it on restart, and the next setup raises it again if the clash remains. Its ID is `duplicate_entry_` plus a hash of the shared unique ID, because Home Assistant saves issue IDs and the email must not be saved; its placeholder is the installation's name (the entry title).

```
1. Read config entry data into OrderedDict (CONF_PASSWORD optional, CONF_REFRESH_TOKEN preferred)
2. Migrate old config: if no per-button mappings exist, derive from PERI_alarm checkbox
3. Check for device IDs (device_id, unique_id, id_device_indigitall)
   └── Missing? → raise ConfigEntryNotReady
4. Create VerisureHub on HA's IPv4-only client — see "Address family" below
   └── Refresh token (if any) is plumbed into the client; persist callback wired up
5. Login via `_login_ipv4_first` (refresh-first; falls back to password if available, else AuthenticationError)
   ├── Connection never established → rebuild on HA's default client (both families) and log in again (#606)
   ├── TwoFactorRequiredError → raise ConfigEntryAuthFailed (triggers reauth flow)
   ├── AuthenticationError → raise ConfigEntryAuthFailed (triggers reauth flow)
   ├── VerisureOwaError → raise ConfigEntryNotReady (HA retries)
   └── …except an xSRefreshLogin crash or err 4 refusal on the 2nd consecutive attempt → ConfigEntryAuthFailed (the stored token is dead; #568)
6. Assign shared ApiQueue (per domain/country)
7. List installations, get_services() per installation
   └── VerisureOwaError → raise ConfigEntryNotReady (HA retries)
8. Create coordinators:
   ├── AlarmCoordinator (always)
   ├── SentinelCoordinator (if sentinel service found)
   └── LockCoordinator (if DOORLOCK/DANALOCK service found)
9. Store per-entry data in hass.data[DOMAIN][entry.entry_id]:
   {hub, devices, alarm_coordinator, sentinel_coordinator, lock_coordinator}
10. Schedule non-blocking first refresh for each coordinator
11. Forward to platforms: alarm_control_panel, binary_sensor, sensor, button, camera, lock
    └── Each platform stores its async_add_entities callback in entry_data
        and creates only entities it can build without API calls
12. Launch background task (_async_discover_devices) to:
    ├── Discover camera devices → create CameraCoordinator → add Camera + CaptureButton entities
    └── Discover lock devices → add Lock entities
```

**What each platform does at setup (synchronous):**

| Platform | Creates | API calls |
|----------|---------|-----------|
| alarm_control_panel | `CombinedVerisureOwaAlarmPanel` entities (CoordinatorEntity) | None (coordinator-driven) |
| binary_sensor | WifiConnectedSensor entities (CoordinatorEntity) | None (coordinator-driven) |
| button | `VerisureRefreshButton` entities (deprecated wrappers around `async_manual_refresh`) | None (stores callback for capture buttons) |
| camera | Nothing | None (stores callback) |
| sensor | Sentinel sensors (CoordinatorEntity) | None (coordinator-driven) |
| lock | Nothing | None (stores callback) |

**Background discovery (`_async_discover_devices`):**

After all platforms are registered, a single background task discovers cameras and locks via API calls, then adds entities using the stored `async_add_entities` callbacks. This runs concurrently with HA startup, so the integration is immediately available (alarm panel, refresh buttons, sensors) while cameras and locks appear shortly after.

Camera discovery creates a `CameraCoordinator` (stored in entry data as `"camera_coordinator"`) and schedules its initial refresh. For each camera, both a `VerisureCamera` (thumbnail) and `VerisureCameraFull` (full-resolution) entity are created.

Lock discovery uses the `LockCoordinator` created during setup. For locks whose initial config fetch fails, a deferred retry is scheduled at exponentially increasing intervals (60s, 120s, 300s).

### Options update (`async_update_options`)

When the user changes options (PIN code, scan interval, alarm mappings, etc.), the listener syncs the new options into the config entry data and reloads the integration. This triggers a full teardown and re-setup.

The sync (`_synced_entry_data`) **replaces** the `_OPTIONS_MANAGED_FIELDS` in `entry.data` from `entry.options` rather than merging them, so a field the user cleared can't linger in data and get resurrected by `_opt()` (which reads options first, then data). Two things make that sound, and both matter if you touch this:

1. **Clearing is recorded explicitly, so absence means "never written".** HA's frontend omits a cleared select from `user_input` entirely, so `_normalize_mapping_input` turns each cleared mapping back into an explicit `""`, and `_resolve_code_submission` always returns both PIN keys. **Exception:** the three `PANEL_OPTION_KEYS` toggles are only added to the schema when `_build_panel_extra_fields` sees the capability, and `_resolve_flow_capabilities` falls back to `(False, False)` until detection runs after a restart — so an options save in that window legitimately omits them. They are the one set for which "absent" is ambiguous.
2. **The sync only runs once `entry.options` is authoritative** (`_options_are_authoritative`). `_create_entry_for_installation` seeds options with `PANEL_OPTION_KEYS` alone, leaving the PIN, mappings, scan interval and the rest in `entry.data`, so a non-empty options dict does *not* imply the options flow has run.

Point 2 is not cosmetic. HA dispatches update listeners on **data-only** writes, and `VerisureHub._persist_refresh_token` writes `entry.data` on the first successful login — so treating a fresh install's toggles-only options dict as authoritative deleted the PIN hash and every mapping within minutes of setup, silently disabling the gate (`_check_code` accepts any code once `CONF_CODE_HASH` is gone). Note the two sets above coincide: the keys the config flow seeds are the keys the options flow may legitimately omit, both because the toggles are capability-gated rather than always present.

Because this design *writes* `entry.data`, a wrong authoritative-ness answer is destructive and unrecoverable. Resolving options-vs-data at read time instead — leaving `entry.data` untouched — would turn that into a transient wrong read; worth considering if this machinery causes trouble again.

### VerisureDevice (`hub.py`)

A thin wrapper around `Installation` that provides `device_info` for the HA device registry. Each physical installation becomes one device.

### VerisureEntity (`entity.py`)

Base class for non-coordinator entities. Inherits from `homeassistant.helpers.entity.Entity` and provides:

- **Common attributes** — `_installation`, `_client` (the `VerisureHub`), `_state`, `_last_state`, and `device_info` (via the `verisure_device_info()` helper that groups entities under the installation device).
- **State management** — `_force_state(state)` sets a transitional state and schedules an HA state write. Used during lock operations and similar.
- **Error notifications** — `_notify_error(title, message)` creates a persistent notification with an auto-generated ID scoped to the installation number.

The `VerisureRefreshButton` and `VerisureCaptureButton` inherit from `VerisureEntity`. The alarm, sensor, binary sensor, lock, and camera entities use `CoordinatorEntity` instead and duplicate the relevant helper methods directly (to avoid diamond inheritance).

The module also provides `verisure_device_info()` and `camera_device_info()` helpers for building `DeviceInfo` objects.

## Entity platforms

### Alarm control panel (`alarm_control_panel/`)

The alarm-panel platform is split into a package: `_base.py` carries `BaseVerisureOwaAlarmPanel` (state mapping, transition orchestration, force-arm context, PIN, WAF tracking) and the shared `build_partial_disarm_target` and `armed_circuits` helpers, which the package root re-exports for the lock; `_panels.py` defines the four concrete entity classes (`CombinedVerisureOwaAlarmPanel` and the three axis sub-panels via `_AxisSubPanelMixin`); `alarm_control_panel/__init__.py` is the platform's `async_setup_entry` plus the entity-service registrations. All four classes are re-exported from the package root for backwards compatibility.

The main entity is `CombinedVerisureOwaAlarmPanel` — one per installation. Inherits from `CoordinatorEntity[AlarmCoordinator]` and `AlarmControlPanelEntity`. The entity starts with `_state = None` (renders as "unknown" in HA) until the first successful coordinator update populates the real alarm state. This avoids showing a false "disarmed" state at startup.

On `async_setup_entry`, the combined panel is stored in `entry_data["combined_alarm_panels"][installation_number]` and each enabled sub-panel is stored in `entry_data["axis_alarm_panels"][installation_number][axis]`. The lock platform reads these to drive `execute_partial_disarm` (auto-disarm before unlock).

**One entry runs an installation's panels:** each config entry has its own `AlarmCoordinator`, and so its own `InstallationOperation` (see "One command at a time" below). When two entries serve the same installation (the duplicate the `duplicate_entry` Repairs issue reports), whichever sets up its alarm platform first creates the panels, and the other creates none for that installation — not the Main panel, and not an Interior, Perimeter or Annex panel switched on only in its options — registers nothing in its `combined_alarm_panels` / `axis_alarm_panels`, and logs a warning naming the installation's number and alias. Otherwise a sub-panel only the second entry switched on would run on that entry's coordinator and could arm while the first entry's Main panel disarms. `main_panel_for(hass, installation_number)` finds the Main panel whichever entry runs it; the check between the entries uses it too, with no await between it and the registration, so two entries setting up at once cannot both claim the installation. The deprecated Refresh button looks its panel up with it on each press (a no-op, logged at debug level, when no entry runs one), and so does the lock's auto-disarm when its own entry has no panel — both usually belong to the entry that runs the panels anyway, since that entry also won their unique IDs. When the entry running the panels is removed or unloaded, the other entry does not take them over until it is itself reloaded (or Home Assistant restarts).

**Coordinator integration:** The `_handle_coordinator_update()` callback skips updates while `_operation_in_progress` is True (while the panel takes part in the installation's running command, see "One command at a time" below) to prevent stale API responses from overwriting the transitional state. On each coordinator update, `_clear_force_context()` is called and `_update_from_coordinator()` maps the `SStatus.status` proto code to an HA state.

**Installation-wide confirmed state:** `AlarmCoordinator.confirmed_proto_code` holds the latest known proto code for the installation. Each command's own answer records it through `record_confirmed_proto_code()` as soon as that command returns (`_send_single_command`), so a transition of several commands cut short between them leaves behind the state its last answered command reached; that includes the answer `_execute_transition` retries from after a mismatch. The only other writers are `_handle_operation_timeout` (the optimistic code after a confirmation timeout, then marked provisional), `_confirm_state_with_panel` (below), `async_manual_refresh` (a successful Refresh, skipped while a command runs) and the coordinator's poll. Showing a result (`update_status_alarm`) only updates the entity, so a transition that sends no command records nothing. Every poll writes it unless the installation is running a command (`AlarmCoordinator.operation.running`), because a poll landing then may predate the command's result. Right after a command the confirmed code is therefore newer than the coordinator's `data`; and because the coordinator's own first poll writes it, it is known even before the panels are added to Home Assistant. `execute_partial_disarm` decides from it which of the circuits it is given (the lock's auto-disarm passes its own) are armed, and every panel plans its commands from it (`_planning_proto_code()`, which falls back to the panel's own `_last_proto_code` only while nothing is confirmed); sub-panels also keep the other axes from it when building a target. So a panel whose own polls lag behind a command sent from another panel still plans from what that command confirmed.

The recorded code becomes unconfirmed (`mark_confirmed_provisional()`) after a confirmation timeout, and when an arm or disarm is cancelled after its command left the API queue to be sent (the hub's `on_start` callback ran; a command cancelled while still queued was never sent and changes nothing). While it is, `possible_proto_codes` holds the last confirmed code, each later timed-out command's optimistic code, and None (not known) after such a cancellation or a timeout whose target has no proto code. A multi-step transition that timed out part-way may also have stopped between those (for example fully disarmed on the way from A to E), which the set does not list; that is harmless for the disarm check below, since no plan switches an axis on only part-way. `confirmed_is_provisional` stays True until a real command result, the pre-arm check, a manual Refresh or a poll allowed to record replaces the code, and while it does `_confirmed_alarm_state()` returns None, so `execute_partial_disarm` disarms the circuits it is given unconditionally rather than trust an unconfirmed disarm. Panels keep planning from the recorded code, with two exceptions for a disarm: `_execute_transition()` sends a full disarm unconditionally, and an axis sub-panel's disarm (`_unconfirmed_planning_state`) plans as if its axis were armed when any possible state has that axis armed or is None — so pressing Disarm again after a disarm that timed out is not a silent no-op — while sending nothing when every possible state has the axis off. An arm does not plan from an unconfirmed code at all: `set_arm_state` first calls `_confirm_state_with_panel()`, which asks the panel for its state through `refresh_alarm_status()` (the Refresh button's `CheckAlarm` round trip), records the answer as confirmed, clears the provisional flag, shows the answer and forces Arming again, so a later rollback lands on the answer rather than the old guess. The arm then plans from that answer; if the first arm did land, it sends nothing. A timeout or a non-letter answer raises `VerisureOwaError`, handled as an arm failure with nothing sent; an unmodelled letter (e.g. `N`) is recorded and the arm refused by `_execute_transition` as above. `_confirm_state_with_panel` first puts back the state from before "Arming", then applies the answer; an axis sub-panel cannot project an unmodelled answer onto its axis, so its `_show_state_check_answer` leaves its display alone then instead of falling back to the last poll.

**One command at a time per installation:** all panels of an installation share one `InstallationOperation` (`AlarmCoordinator.operation`, in `coordinators.py`), recording the running command's kind (`arm`, `disarm` or `partial_disarm`), the panels taking part and, for an arm, its mode. A user arm, a user disarm and `execute_partial_disarm` (the lock's auto-disarm) each wait (`_wait_until_idle`, bounded by `_operation_wait_limit()`, then the translated `operation_in_progress` error, which `execute_partial_disarm` turns into a False return) until the installation is idle, then call `begin()` with no await in between, and `end()` in the `finally` of the `try` that starts right after it, so no exit leaves the installation busy and no command can end another's. Each command plans from the state the previous one left. Repeat presses are quiet no-ops, decided by `_repeats_running()`: a full disarm while a full disarm runs on the same panel (checked each time the wait wakes, so two queued disarms send one), and an arm to the mode an arm is already running to on the same panel (checked at press time, before a user arm dismisses the pending Force Arm prompt, so an ignored repeat leaves the running arm's prompt in place). A force-arm is never a repeat: it may arrive while the blocked arm it completes is still finishing, and then queues behind it. Among arms waiting on one panel only the latest press runs (`_arm_presses`, a per-panel counter taken after the repeat check, so an ignored repeat cancels nothing); arms waiting on different panels all run, in turn. `_force_state(ARMING)` happens only after the arm has begun, so a waiting arm does not show Arming.

**State mapping system:** During `__init__`, two dictionaries are built from the user's configuration:

- `_command_map`: HA state -> API command string. E.g. `ARMED_AWAY` -> `"ARM1"`. Only includes states the user has mapped (cleared/blank fields are skipped, as is the legacy `NOT_USED` value still found on pre-v5 saved configs). Annex-bearing target states get an empty placeholder — actual transitions go through `CommandResolver` (`ARMANNEX1` / `DARMANNEX1`), and `_command_map` is only consulted for `supported_features` membership.
- `_status_map`: Protocol response code -> HA state. E.g. `"T"` -> `ARMED_AWAY`. Built by reverse-looking up `PROTO_TO_STATE` for each configured Verisure OWA state.

**`supported_features`** is derived from `_command_map` — only buttons with a configured mapping are exposed.

**Arm flow** (`async_alarm_arm_away` and friends):
```
1. _check_code_for_arm_if_required(code) — if PIN required for arming
2. Same mode already arming on this panel? return, sending nothing and
   leaving that arm's Force Arm prompt in place
3. Dismiss any pending force-arm context on this panel and its siblings
4. set_arm_state(target_mode):
   a. Same mode already arming on this panel (and not a force-arm)? return
      (checked again for direct callers of `set_arm_state`;
      `async_force_arm`, the only other caller in the integration, is never
      a repeat)
   b. Take a press number, _wait_until_idle(); a later arm pressed on this
      panel meanwhile? return (the latest press runs)
   c. operation.begin("arm", [self], mode)
   d. _force_state(ARMING) — set transitional state, save previous in _last_state
   e. Confirmed state provisional? _confirm_state_with_panel() first
   f. Convert target HA mode to AlarmState via _mode_to_alarm_state()
   g. _execute_transition(target_alarm_state, **force_params):
      - Derives current AlarmState from _planning_proto_code() (the installation's confirmed code)
      - resolver.resolve(current, target) returns list of CommandSteps
      - If mode change (e.g. Partial→Total): resolver inserts disarm first
      - For each step, _execute_step() tries command alternatives in order
      - BAD_USER_INPUT/404? mark_unsupported(), try next alternative
      - 403 (WAF) or 409 (busy)? re-raise immediately
      - TECHNICAL_ERROR (panel comms failure)? re-raise immediately
      - Multi-step commands ("+") executed as sequential API calls
      - Force params passed to all commands (both interior and perimeter
        sensors can trigger ArmingExceptionError)
      - _last_arm_result tracks the most recent successful step for partial state
   h. On error:
      - Notify user via persistent notification (short message only, never
        full error tuples with headers/tokens)
      - If a prior step succeeded (_last_arm_result), reflect that partial state
      - If no steps succeeded, revert to _last_state
   i. update_status_alarm() with the final response
   j. finally: operation.end()
```

**Disarm flow** (`async_alarm_disarm`):
```
1. _check_code(code) — raises ServiceValidationError if wrong
2. _wait_until_idle(duplicate_of="disarm") — waits until no panel of the
   installation runs a command; returns at once, sending nothing, when a
   disarm is already running on this same panel (checked each time the wait
   wakes, so two disarms queued behind one command send one)
3. operation.begin("disarm", [self])
4. Dismiss any pending force-arm context on this panel and its siblings
5. _force_state(DISARMING)
6. target = _resolve_target_state("disarmed"): all axes off on the Main
   panel; a sub-panel turns off its own axis and keeps the others as the
   installation's planning state has them (when that is unreadable, as the
   last poll has them, or all off)
7. _execute_transition(target):
   a. Planning state (_planning_proto_code()) unreadable (never polled, or an
      unmodelled code like N), or the confirmed state provisional, and the
      target is all off? → _disarm_circuits_unconditional(_full_disarm_circuits()):
      resolver.resolve_disarm_only() emits only DARM commands (DARM1 /
      DARM1DARMPERI / DARMANNEX1) for every axis the Main panel owns, or just
      a sub-panel's own axis, whatever the current state (#550)
   b. Otherwise, provisional? a sub-panel plans from _unconfirmed_planning_state():
      its axis counts as armed when any possible state has it armed or is
      unknown, so a disarm that timed out is sent again
   c. resolver.resolve(current, target) returns steps with ordered
      alternatives based on what is armed:
      - Interior and perimeter? → [DARM1DARMPERI, DARM1]
      - Only perimeter? → [DARMPERI, DARM1]
      - Only interior? → [DARM1]
      - Annex armed? → DARMANNEX1 appended
      - Nothing armed? → no steps, nothing sent
   d. _execute_step() tries alternatives, marks failed ones unsupported;
      409 errors re-raised (server busy, not unsupported)
   e. Answer differs from the target? replan once from the answer
8. Success → update_status_alarm(result), coordinator refresh, activity event
   Timeout → _handle_operation_timeout(): show the target, state provisional
   Error → restore _last_state, _handle_arm_disarm_error() notifies
9. finally: operation.end()
```

**Arming exception flow** (open sensors blocking arm):
```
1. set_arm_state() catches ArmingExceptionError from _send_arm_command()
2. _set_force_context(exc, mode) — stores reference_id, suid, mode, exceptions
3. _fire_arming_exception_event(exc, mode) — fires verisure_owa_arming_exception event
4. (if force_arm_notifications enabled) built-in handler listens for event:
   a. Persistent notification: lists each open sensor by name, explains how to force-arm
   b. Mobile notification (if notify_group configured): short message with
      Force Arm / Cancel action buttons
   c. Exception: if an auto-force asked for the prompt to be held back (and
      the panel allows forcing), a and b are NOT sent now. Instead
      _schedule_suppressed_prompt_fallback() sends them 15 s later, unless
      the force has resolved by then (_wipe_force_arm_state() and entity
      removal cancel the timer), and only if force_arm_notifications is
      still enabled when it fires
5. If an earlier command of this arm was answered (_last_arm_result), show
   that answer and request a coordinator refresh so the other panels catch
   up; otherwise the state reverts to _last_state
```

**Force arm flow** (`verisure_owa.force_arm` / `verisure_owa.force_arm_cancel` services):
```
force_arm:
  1. Read stored reference_id, suid, mode from _force_context
  2. _clear_force_context()  — cancels TTL timer + wipes context dict + attrs
  3. _dismiss_arming_exception_notification() (if notifications enabled)
  4. set_arm_state(mode, force_arming_remote_id=ref_id, suid=suid)
     → API accepts force params and overrides the open-sensor exceptions

force_arm_cancel:
  1. _clear_force_context()
  2. _dismiss_arming_exception_notification() (if notifications enabled)
  3. async_write_ha_state()

Mobile notification actions (when built-in handler enabled):
  - SECURITAS_FORCE_ARM_<num> → _async_force_arm_from_notification() (async_force_arm(); a refusal → arm_failed notification)
  - SECURITAS_CANCEL_FORCE_ARM_<num> → _clear_force_context() + write state
```

**Force-arm context expiry:** The force-arm context has a 180-second TTL (`_FORCE_ARM_TTL`). Expiry is driven by an independent `async_call_later` timer scheduled in `_set_force_context` (`_base.py:_schedule_force_arm_expiry`); when it fires, `_async_handle_force_arm_expiry` fires the public `verisure_owa_force_arm_expired` event, runs the built-in notification side effects (if enabled), and wipes the context. The timer runs independent of coordinator state — this matters because HA's `DataUpdateCoordinator` does NOT call its listeners on consecutive failed refreshes, so the previous coordinator-driven check would silently skip the expiry during a sustained API outage that started before the TTL boundary. `_clear_force_context()` is now a pure wipe (cancels the timer + drops the context dict + drops the entity attributes); it does no TTL bookkeeping itself and is used by the canonical resolution paths (force_arm, force_arm_cancel, sibling dismissal).

The `_get_exceptions()` API call uses the same polling pattern as arm/disarm — the server returns `WAIT` on the first poll while the panel reports the open sensors, then `OK` with the full exception list on a subsequent poll.

**Why disarm-before-rearm?** The Verisure API treats interior and perimeter as independent axes. Sending `ARMDAY1` while the perimeter is armed leaves the perimeter armed. Transitioning from `Partial+Perimeter` to `Partial` (no perimeter) would silently fail without disarming first. The `CommandResolver` handles this automatically: when the interior mode changes and the current interior is not off, it inserts a disarm step before the arm step.

**WAF rate-limit handling:** When the Verisure Incapsula WAF blocks requests with 403, the integration tracks this via a `waf_blocked` attribute on the alarm entity's `extra_state_attributes`. The custom Lovelace card reads this attribute to show an orange warning banner. A `_set_waf_blocked(blocked)` helper method manages the attribute and auto-dismisses the "Rate limited" persistent notification when the block clears. The attribute is:
- **Set** on 403 errors from status polls, arm/disarm operations, and button presses
- **Cleared** on successful arm/disarm operations and successful status polls
- 403 on arm/disarm shows only the rate-limited notification (the generic "Error arming/disarming" notification is suppressed to avoid duplicates)

**PIN code validation:** the PIN is never sent to the Verisure API — it only gates local HA actions — and is never stored in plain text. `entry.data`/`entry.options` carry `CONF_CODE_HASH` (a PBKDF2-HMAC-SHA256 hash, see `pin_crypto.py`) and `CONF_CODE_IS_NUMERIC` (captured at hash time, since digit-ness can't be recovered from the hash afterwards).
- `_check_code(code)` — Always checked for disarm. Verifies `code` against `CONF_CODE_HASH` via `pin_crypto.verify_pin`; raises `ServiceValidationError` on mismatch. No PIN configured = any code accepted.
- `_check_code_for_arm_if_required(code)` — Only checked for arm operations if `code_arm_required` is True AND a PIN is configured.
- `code_format` — `None` if no PIN configured, `NUMBER` if `CONF_CODE_IS_NUMERIC` is True, `TEXT` otherwise.
- `lock.py._check_code(code)` — the same PIN, same hash, gating lock/unlock/open when `CONF_LOCK_CODE_REQUIRED` is on. Publishing `code_format` is what turns the gate on, so it reads `CONF_CODE_HASH`/`CONF_CODE_IS_NUMERIC` too. Anything reading the PIN must go through `verify_pin` — there is no plain-text copy left to compare against.
- Options-flow UX: the PIN field can't be pre-filled with the real value, so `config_flow._build_settings_schema` shows a fixed mask sentinel (`●●●●●●●●`) when a PIN is already configured. Resubmitting it unchanged keeps the existing hash; clearing the field removes the PIN; typing anything else hashes it as the new PIN (see `_resolve_code_submission`). The field is a password selector, so a newly typed PIN isn't left on screen in the clear.

### Event-driven force-arm architecture

When arming is blocked by open sensors (the API returns a `NON_BLOCKING` error), the alarm panel raises an `ArmingExceptionError` and immediately does three things:

1. Stores force-arm context (`reference_id`, `suid`, `mode`, `exceptions`) with a 180-second TTL (`_FORCE_ARM_TTL`).
2. Sets entity attributes `force_arm_available: true` and `arm_exceptions` (list of open zone names) on `extra_state_attributes`.
3. Fires a `verisure_owa_arming_exception` event on the HA event bus.

**Event payload:**
```python
# verisure_owa_arming_exception
{
    "entity_id": "alarm_control_panel.verisure_owa_my_home",
    "mode": "armed_away",
    "zones": ["Kitchen window", "Bedroom sensor"],
    "details": {
        "installation": "12345",
        "exceptions": [
            {"alias": "Kitchen window", "zone_id": "3", "device_type": "MAG"},
        ],
    },
    "_event_id": "<uuid4>",
}
```

**Lifecycle events** (`events.py:33,39`):

Two follow-on events fire for every active force-arm context, regardless of the
`force_arm_notifications` toggle. The toggle gates the built-in side effects only —
the events themselves are the public contract for user automations.

```python
# verisure_owa_force_arm_expired — fires when the 180 s TTL elapses without
# the user pressing Force Arm or Cancel.
{
    "entity_id": "alarm_control_panel.verisure_owa_my_home",
    "mode": "armed_away",
    "zones": ["Front door", "Garage"],
    "details": {
        "installation": "12345",
        "exceptions": [{"alias": "Front door", "zone_id": "1", ...}],
    },
    "_event_id": "<uuid4>",
}

# verisure_owa_arming_exception_dismissed — fires when an active force-arm
# context is cleared by something OTHER than force_arm / force_arm_cancel
# (those are the canonical resolutions and do not fire dismissed).
{
    "entity_id": "alarm_control_panel.verisure_owa_my_home",
    "reason": "user_arm" | "user_disarm" | "integration_reload",
    "new_mode": "armed_home" | "armed_away" | "disarmed" | None,
    "details": {"installation": "12345"},
    "_event_id": "<uuid4>",
}
```

`reason` is one of the constants in `events.py:43-46` (`DISMISSAL_REASON_USER_ARM`,
`DISMISSAL_REASON_USER_DISARM`, `DISMISSAL_REASON_INTEGRATION_RELOAD`); `new_mode`
is `None` only when `reason="integration_reload"` (entity teardown — there is no
new mode being targeted).

**Cross-panel coordination:** the Combined and per-axis sub-panels (Interior /
Perimeter / Annex) for an installation share notification state. `_async_arm`
and `async_alarm_disarm` call `_dismiss_pending_force_context_on_siblings`
BEFORE dispatching the new operation: it walks every panel returned by
`_siblings_on_installation` (which reads `entry_data["combined_alarm_panels"]`
and `entry_data["axis_alarm_panels"]`), fires the dismissed event attributed to
the panel that HELD the context (its own `entity_id`), then clears that panel's
context. So if the user triggers an arming exception on Combined and then arms
via the Interior sub-panel, Combined's persistent + mobile notifications vanish
immediately even if the new arm operation later fails.

**Reload safety net:** `async_will_remove_from_hass` checks for a still-live
`_force_context` at teardown and fires the dismissed event with
`reason="integration_reload"` and `new_mode=None`. This covers options-flow
edits, reauth, and any other path that re-creates the entity, so user
automations see the loss instead of silently inheriting a fresh entity with no
context.

**Built-in handler (enabled by default):**

When the built-in handler is active it:
- Creates a persistent notification listing open zones with instructions for how to force-arm.
- Sends a mobile notification (if `notify_group` is configured) with **Force Arm** / **Cancel** action buttons.
- Listens for `mobile_app_notification_action` events to handle button taps (`SECURITAS_FORCE_ARM_<num>` → `_async_force_arm_from_notification()`, which runs `async_force_arm()` and sends a refused force arm as the `arm_failed` notification, `SECURITAS_CANCEL_FORCE_ARM_<num>` → cancel). The action names retain the `SECURITAS_` prefix through the v5 deprecation window: the integration both sends the action (in the mobile notification payload) and listens for the resulting press event, so renaming would silently break any user automation hooked to `mobile_app_notification_action` events that match the action string. Renamed in v6 with explicit release-note guidance.
- When the force-arm context expires (180 s), fires `verisure_owa_force_arm_expired` (regardless of toggle) and — when notifications are enabled — updates the persistent notification, then replaces the mobile notification *in place* with a button-less informational card (same `tag` as the original so iOS/Android updates the existing card rather than stacking a new one; `actions` array omitted so no buttons render).
- Listens for `verisure_owa_arming_exception_dismissed` and clears the shared persistent + mobile notifications when fired (so a sibling-panel arm/disarm or an integration reload cleans up the user-visible state).

**Disabling the built-in handler:**

Set **Built-in force-arm notifications** to off in the integration options (Settings → Devices & services → Verisure OWA → Configure). The `verisure_owa_arming_exception` event still fires, `force_arm_available` / `arm_exceptions` attributes are still set, and the `verisure_owa.force_arm` / `verisure_owa.force_arm_cancel` services still work — only the notifications are suppressed. This lets you replace the built-in notifications with custom automations.

**Custom automation examples:**

#### Auto force-arm when leaving home
```yaml
- id: verisure_owa_auto_force_arm
  alias: "Alarm: auto force-arm when leaving"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  conditions:
    - condition: template
      value_template: "{{ trigger.event.data.mode == 'armed_away' }}"
  actions:
    - action: verisure_owa.force_arm
      target:
        entity_id: "{{ trigger.event.data.entity_id }}"
  mode: single
```

#### Notify with open zone details
```yaml
- id: verisure_owa_notify_open_zones
  alias: "Alarm: notify about open zones"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  actions:
    - action: notify.mobile_app_phone
      data:
        title: "Alarm blocked"
        message: >
          Cannot arm {{ trigger.event.data.mode }}.
          Open zones: {{ trigger.event.data.zones | join(', ') }}
  mode: single
```

#### Different behaviour per mode
```yaml
- id: verisure_owa_smart_force_arm
  alias: "Alarm: smart force-arm by mode"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  actions:
    - choose:
        - conditions:
            - condition: template
              value_template: "{{ trigger.event.data.mode == 'armed_away' }}"
          sequence:
            - action: notify.mobile_app_phone
              data:
                message: >
                  Open zones: {{ trigger.event.data.zones | join(', ') }}
                  — force-arming...
            - action: verisure_owa.force_arm
              target:
                entity_id: "{{ trigger.event.data.entity_id }}"
        - conditions:
            - condition: template
              value_template: "{{ trigger.event.data.mode == 'armed_night' }}"
          sequence:
            - action: notify.mobile_app_phone
              data:
                title: "Cannot arm night mode"
                message: >
                  Please close: {{ trigger.event.data.zones | join(', ') }}
  mode: single
```

#### Notify then auto force-arm after delay
```yaml
- id: verisure_owa_delayed_force_arm
  alias: "Alarm: notify then force-arm after 30s"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  actions:
    - action: notify.mobile_app_phone
      data:
        title: "Alarm blocked"
        message: >
          Open zones: {{ trigger.event.data.zones | join(', ') }}.
          Force-arming in 30 seconds...
    - delay: "00:00:30"
    - action: verisure_owa.force_arm
      target:
        entity_id: "{{ trigger.event.data.entity_id }}"
  mode: single
```

#### TTS announcement of open zones
```yaml
- id: verisure_owa_tts_open_zones
  alias: "Alarm: announce open zones on speaker"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  actions:
    - action: tts.speak
      target:
        entity_id: tts.google_en_com
      data:
        media_player_entity_id: media_player.living_room
        message: >
          Alarm cannot arm. The following zones are open:
          {{ trigger.event.data.zones | join(', ') }}
  mode: single
```

### Sensors (`sensor.py`)

Four sensor types, all using `CoordinatorEntity[SentinelCoordinator]`:

- **SentinelTemperature** — Temperature in Celsius
- **SentinelHumidity** — Humidity as percentage
- **SentinelAirQuality** — Numeric air quality index (may remain unknown if the installation only provides status data)
- **SentinelAirQualityStatus** — Categorical air quality label (Good, Fair, Poor)

Sentinel sensors are discovered during setup by scanning services for ones whose `request` field matches any name in `SENTINEL_SERVICE_NAMES` (currently "CONFORT", "COMFORTO", "COMFORT"). No API calls are made during setup — entities start with unknown state. Data is populated by the `SentinelCoordinator` at a 30-minute interval. Each sensor reads its value from `self.coordinator.data` in its `native_value` property.

**Air quality data model:** The `xSAirQuality` API may return hourly readings (`hours` array) and/or a categorical status code. Some installations provide both; others return `hours: null` with only the status. `AirQuality.value` is `int | None` to handle this — the status sensor works regardless, while the numeric sensor only updates when hourly data is available.

### Binary sensors (`binary_sensor.py`)

- **WifiConnectedSensor** — Diagnostic binary sensor showing the panel's WiFi connection status from `SStatus.wifi_connected`. One per installation. Uses `CoordinatorEntity[AlarmCoordinator]` — updated whenever the alarm coordinator refreshes. Uses `BinarySensorDeviceClass.CONNECTIVITY` and `EntityCategory.DIAGNOSTIC`. `should_poll = False`.

### Smart lock (`lock.py`)

`VerisureLock` controls DOORLOCK services. Uses `CoordinatorEntity[LockCoordinator]`. Supports multiple locks per installation — each lock is identified by a `device_id` (extracted from the API response, defaults to `"01"`).

**Discovery:** Locks are discovered in the background task (`_async_discover_devices`). When a DOORLOCK service is found, `get_lock_modes()` returns all known lock devices. For each lock, `get_lock_config(device_id)` is called to fetch metadata from the `xSGetSmartlockConfig` API response (location name, serial number, device family). Each lock creates a separate HA device with `via_device` linking to the installation device as parent; name, model, and serial number in the `DeviceInfo` come from the config response. If the config fetch fails, the lock still works but falls back to using the installation alias as the device name with no serial number or model. A deferred retry schedule (60s, 120s, 300s) attempts to fetch config later. One `VerisureLock` entity is created per device. Unique IDs follow the format `v4_securitas_direct.{number}_lock_{device_id}`.

**Lock states** (string codes from the API):
- `"1"` = unlocked
- `"2"` = locked
- `"3"` = unlocking (transitional)
- `"4"` = locking (transitional)

Lock and unlock operations use `change_lock_mode(lock=True/False)` which follows the same polling pattern as arm/disarm. After the command is acknowledged, the entity verifies the real outcome via `_poll_lock_until` (see below). While a lock command is in flight, `_operation_in_progress` suppresses coordinator updates to prevent stale API responses from briefly overwriting the transitional state. Periodic background polling via `LockCoordinator` resumes on the scan interval once the command completes.

**Phantom entries:** Some lock models (e.g. SmartLock Tácito) return duplicate `smartlockInfo` entries in the `xSGetLockCurrentMode` response — a phantom entry with `lockStatus: null` and `statusTimestamp: "0"` alongside the real entry (see `docs/graphql_locks/smartlocktacito.json`). `get_lock_current_mode()` skips entries with `lockStatus: null` to prevent phantom lock entities and broken status detection.

**Lock automations** (`CONF_LOCK_AUTOMATIONS`): per-lock, per-circuit booleans persisted as `entry.options[CONF_LOCK_AUTOMATIONS] = {device_id: {"lock_on_arm": [circuits...], "unlock_disarms": [circuits...]}}`. Each `VerisureLock` reads its own slice in `async_added_to_hass` into `_lock_on_arm_circuits` / `_unlock_disarms_circuits`.

- **Auto-lock on arm**: the lock subscribes to the `AlarmCoordinator` via `async_add_listener`. On the first listener call it captures the currently-armed circuit set as a baseline (no firing). On each subsequent call it diffs the new armed set against the baseline; if any circuit in `_lock_on_arm_circuits` newly transitioned `disarmed → armed`, the lock fires `_auto_lock()` as a background task. It skips **only** when a lock operation is already in flight (`_operation_in_progress` or state `LOCKING`) — deliberately **not** when the cached state merely reads LOCKED, because that cache is eventually-consistent and can be stale; a redundant lock on an already-locked door is harmless, whereas trusting a stale "locked" could leave the door silently unlocked while armed. Confirmation and the failure notification are handled by the verification poll (below); a notification fires only when the settled state is definitively unlocked, with a stable per-lock ID so consecutive failures replace rather than stack.

- **Lock command verification** (`_change_lock_mode` → `_poll_lock_until`): the backend acks a lock/unlock before the device physically actuates (~6s to start + ~4.5s to complete; see PR #413), so a single immediate read races ahead of the lock. Before sending the command we take a **fresh baseline** `statusTimestamp` via a direct `get_lock_modes` call (foreground priority) — not from coordinator data, which can be older than the actual current backend state if the lock was physically moved since the last coordinator refresh. We then re-read the status up to `LOCK_VERIFY_ATTEMPTS` times (`LOCK_VERIFY_DELAY` apart) and treat any read with `statusTimestamp > pre_ts` as authoritative: matches target → confirmed success; doesn't match → confirmed failure (lock blocked / snapped back). Stale reads (`statusTimestamp <= pre_ts`) keep polling — they may be pre-command state still propagating. The window covers the worst-case actuation (currently ~18s, past #413's validated 15s; tune from the per-attempt `statusTimestamp` debug logs). On window exhaust with `status == target` but no fresh timestamp, we treat it as a quiet success — defensively handling the case where the device does not re-stamp `statusTimestamp` on a no-op command.

- **Auto-disarm before unlock**: HA-initiated `async_unlock` / `async_open` runs `_dispatch_unlock_disarm()` and `_change_lock_mode(unlock)` concurrently via `asyncio.gather`. The lock hands every circuit in `_unlock_disarms_circuits` to `combined_alarm_panel.execute_partial_disarm(circuits)`, which decides what to send: an empty list returns None at once without waiting; otherwise it waits for any command already running on any alarm panel of the installation (main or sub-panel), then keeps only the circuits armed in the installation's latest known state (`armed_circuits()`), or all of them when that state is unreadable or unconfirmed (#550). It returns None when nothing was armed (no command sent), True when it disarmed, and False when the disarm failed or the wait gave up — only False fires the lock's "Auto-disarm failed" notification. While it runs it holds the installation's operation (`partial_disarm`), so any arm, from any panel (e.g. Perimeter), waits for it rather than running alongside and re-arming the circuits it just disarmed. It drives the same optimistic-state lifecycle as a user-initiated disarm on the combined panel **and on every registered axis sub-panel** for the circuits it disarms (DISARMING during the transition, post-result state on success, rollback on failure), then triggers a coordinator refresh. Both the lock and any affected sub-panels animate immediately. After both branches complete, an "Unlock failed" notification fires only if the disarm succeeded but the lock state stayed LOCKED.

The `axis_alarm_panels` registration in `entry_data` is what lets `execute_partial_disarm` find the affected sub-panels without leaking lock-platform knowledge into the alarm package. Only HA-initiated unlocks reach into the alarm — Verisure-app or physical-lock unlocks never trigger auto-disarm because they don't go through the entity.

**Direction differs from the Verisure app (deliberate):** the Verisure app *unlocks the door when you disarm*. This integration has **no** unlock-on-disarm listener. "Auto-disarm before unlock" is the inverse coupling — unlocking the door (from HA) disarms the alarm. Users wanting unlock-on-disarm should write an HA automation (`alarm → disarmed` ⇒ `lock.unlock`). Separately, the integration's arm-driven auto-lock conflicts with Verisure's own timer-based autolock (the `LockAutolock` config); users are told (README + options-flow description) to disable autolock in the app so this integration is the only thing driving the lock.

`async_update_options` reloads the config entry when `CONF_LOCK_AUTOMATIONS` changes (alongside the other listed keys) so each lock entity re-reads its slice in `async_added_to_hass`.

**Lock features:** Lock features are fetched via `xSGetSmartlockConfig` and exposed as `extra_state_attributes`, including `holdBackLatchTime` (latch hold-back for door opening). When `holdBackLatchTime > 0`, the entity advertises `LockEntityFeature.OPEN` so users can trigger door unlatching from the UI even when the lock is already unlocked. The `async_open()` method sends the same `change_lock_mode(lock=False)` command — there is no separate API mutation for opening. Note: `is_open` always returns `False` because the API does not distinguish between "unlocked" and "open" (latch held back) — status `"1"` means unlocked. Reporting `is_open=True` would cause HA to grey out the "Open" button indefinitely since the API never transitions away from `"1"` after an unlock.

### Camera (`camera.py`)

Two camera entity types per discovered camera, both using `CoordinatorEntity[CameraCoordinator]`:

- **`VerisureCamera`** — Shows the last captured thumbnail image. `async_camera_image()` returns the decoded thumbnail from `self.coordinator.data.thumbnails[zone_id]`, or a placeholder JPEG if none exists. On `_handle_coordinator_update()`, rotates the access token so the frontend re-fetches.

- **`VerisureCameraFull`** — Shows the last full-resolution image. `async_camera_image()` returns `self.coordinator.data.full_images[zone_id]`, or a placeholder JPEG if none exists.

Both entities are grouped under a per-camera child device (via `camera_device_info()`), linked to the installation device as parent via `via_device`.

**Discovery:** Cameras are discovered in the background task. `get_camera_devices()` returns devices of type `"QR"` (Italy and some regions), `"YR"` (PIR cameras, Spain), `"YP"` (perimetral exterior, deviceType 103), `"QP"` (perimetral exterior, deviceType 107), or `"XR"` (its RequestImages sends only the camera code, with no deviceType, mediaType or resolution). For each device a `VerisureCamera` + `VerisureCameraFull` + `VerisureCaptureButton` are created using stored `async_add_entities` callbacks. The buttons are constructed with a `camera_entity=<thumbnail_entity>` reference so their deprecated `async_press` can delegate directly to `camera_entity.async_manual_capture()` instead of doing a runtime entity-id lookup. Devices with `isActive: null` are treated as active (only `isActive: False` is filtered out). YR and XR devices have `zoneId: null` in the API; zone_id falls back to the device type plus the two-digit code (e.g. `XR01`), or to the device `id` field when the code is not a number.

**Image lifecycle:**
1. On coordinator refresh (every 30 minutes), thumbnails are fetched for all cameras
2. When a thumbnail's `id_signal` changes, `CameraCoordinator` auto-fetches the full-resolution image (skips thumbnails older than 1 hour)
3. When `verisure_owa.capture_image` fires on a camera entity (from the camera card's refresh button, an automation, or — for backwards compat — a press on the deprecated `VerisureCaptureButton`), the camera entity's `async_manual_capture` calls `hub.capture_image()` which triggers a new capture via the client, validates/stores the result, pushes the new data into the `CameraCoordinator`, and launches a background task to fetch the full-resolution image. The capture flow waits for a strictly-newer frame before completing (see "Camera capture" above).
4. If a periodic coordinator poll completes mid-capture and the poll's fetched thumbnail is OLDER than what the capture stored, the coordinator's per-zone merge drops the fetched thumbnail and preserves the capture-stored fresh one and its full image — race fix for a real-world bug where the older frame from a concurrent poll overwrote the just-captured fresh one.

**Signals:**
- `SIGNAL_CAMERA_STATE` — capturing state changed (camera entity writes state without rotating token, so the frontend shows the capturing spinner)

**Extra state attributes:** `image_timestamp` — when the thumbnail was captured; `capturing` (thumbnail entity only) — True while a capture is in progress.

### Buttons (`button.py`)

Both button entities below are now **deprecated thin wrappers** that delegate to entity methods on the corresponding alarm-panel / camera entities. The bundled Lovelace cards (alarm card, camera card) invoke those methods directly via `verisure_owa.refresh_alarm` / `verisure_owa.capture_image` and don't look up these buttons at all. Both buttons remain registered so existing automations and Lovelace button cards continue to work; pressing one logs a one-line deprecation warning and will be removed in a future release.

**`VerisureRefreshButton`** (deprecated) — `async_press` forwards the current HA context to the alarm entity and calls `alarm_entity.async_manual_refresh()`. The real implementation lives on `BaseVerisureOwaAlarmPanel`:
- On success: updates `protom_response` on the client, clears `refresh_failed`, triggers a state write; unless a command is running on the installation or the answer is not a state letter, it also records the answer as the confirmed state, clears the unconfirmed flag and its "Arm not confirmed" notification, and shows the answer (`_apply_panel_answer`, shared with the pre-arm check)
- On timeout: sets `refresh_failed` (card shows stale data banner), injects a `COMMUNICATION_FAILED` activity event
- On 403: creates "Rate limited" persistent notification, sets `waf_blocked`, injects `COMMUNICATION_FAILED`

`async_manual_refresh` is also registered as the `verisure_owa.refresh_alarm` entity service (target: `alarm_control_panel`) — the canonical entry point.

**`VerisureCaptureButton`** (deprecated) — `async_press` forwards the current HA context to the matching camera entity (the thumbnail variant, captured at button construction) and calls `camera_entity.async_manual_capture()`. The real implementation lives on `VerisureCamera`: triggers `hub.capture_image()` (which requests the capture, polls for completion, and waits for a strictly-newer frame), then injects an `IMAGE_REQUEST` activity event with the real server `id_signal` so the activity-log card can fetch the photo.

`async_manual_capture` is also registered as the `verisure_owa.capture_image` entity service (target: `camera`) — the canonical entry point.

### Service registration: dual-domain (`securitas.*` + `verisure_owa.*`) vs v5+ (`verisure_owa.*` only)

Two service-registration paths coexist in `__init__.py`:

- `register_service_aliases` (uses `_ALIASED_SERVICES`) — registers each named service under `verisure_owa.<X>` as a thin forwarder to the `securitas.<X>` implementation that `platform.async_register_entity_service` produces. Used for `force_arm` and `force_arm_cancel` only — both pre-date the v5 rebrand and have existing automations against the `securitas.*` form to honour.
- `register_v5_entity_services` (uses `_V5_ENTITY_SERVICES` + `_register_verisure_owa_entity_service`) — registers each named service **only** under `verisure_owa.<X>`, with a manual entity-id dispatcher that looks up the target entity via `EntityComponent.get_entity(eid)` and calls the named method on it. Used for `refresh_alarm`, `capture_image`, `refresh_activity_log`, `fetch_activity_image`. The manual dispatcher exists because `EntityPlatform.async_register_entity_service` is bound to the integration's DOMAIN (= "securitas") and there's no way to use it directly under a foreign domain. Each handler sets the call's context on the entity via `entity.async_set_context()` before dispatching, mirroring HA's own machinery.

## Three-axis alarm model

Verisure installations have up to three independent alarm axes:

- **Interior** — `OFF` / `DAY` / `NIGHT` / `TOTAL` (`InteriorMode`)
- **Perimeter** — `OFF` / `ON` (`PerimeterMode`)
- **Annex** — `OFF` / `ON` (`AnnexMode`)

`AlarmState` is the joint state across all three axes. The status code returned by the API maps to a specific tuple via `PROTO_TO_STATE`. `CommandResolver` plans transitions between any two `AlarmState` values, emitting one or more API command steps; multi-axis transitions append per-axis steps in a deterministic order.

## Capability detection

`detect_peri()` and `detect_annex()` live in `verisure_owa_api/capabilities.py`. Detection runs on every config-entry load — there is no stored `CONF_HAS_PERI`. `detect_peri()` uses four layered signals (JWT capability set, active PERI service, SCH service `PERI` attribute, alarm partition `id="02"`) so it catches both Spanish SDVFAST panels (which advertise `PERI` via JWT cap or service attribute) and Italian SDVECU panels (which expose perimeter only via the alarm-partition list). `detect_annex()` requires both `ARMANNEX` and `DARMANNEX` capabilities.

**Why four signals, not just the JWT cap?** The cap claim appears to track contract/role permissions (what the tenant is licensed for), not what the physical panel is configured to do — and on Italian SDVECU it can be both incomplete and inverted. Two witnesses from the same OWNER login:

- *Perimeter*: an installation with an active `YP` outdoor camera has no `PERI` in the cap, yet the panel accepts perimeter commands. `alarm_partitions[id=02]` and the SCH service's `PERI` attribute reflect physical configuration; the cap does not.
- *Arming modes*: the cap lists `ARMNIGHT` while the panel rejects `ARMNIGHT1` (`"Request ARMNIGHT1 is not valid for Central Unit"`), and omits `ARMDAY` while the panel accepts `ARMDAY1`.

This is why the Interior sub-panel deliberately surfaces all three interior modes regardless of cap content; the resolver's `mark_unsupported` runtime fallback catches genuinely-rejected commands and the user gets a notification naming the failed command. See `tests/fixtures/capability_jwts/italy_owner_partial_only.json` for the regression evidence.

A single debug log line at startup makes misdetection diagnosable: search the log for `capability detection for <installation>` to see the resolved `has_peri`, `has_annex`, and full sorted capability set for each installation.

## Entity layout

Per installation:

- One **main panel** (always present) — friendly name `Main - <installation alias>`. Drives all three axes through the user-configurable `map_home`/`map_away`/`map_night`/`map_custom`/`map_vacation` mappings. Implementation class is `CombinedVerisureOwaAlarmPanel`; the user-facing term is "main panel" (contrasts with "Interior-only / Perimeter-only / Annex-only control panel"). Backwards compatible with all existing setups.
- Up to three opt-in **sub-panels** (Interior, Perimeter, Annex) — friendly names `<Axis> - <installation alias>` (e.g. `Interior - <alias>`). Each drives a single axis. Visibility is gated on (a) capability detection, AND (b) the per-axis toggle in the options flow. The Perimeter and Annex toggles are hidden when their respective capability is absent. The Interior toggle is hidden only when the installation has neither perimeter nor annex capability — with no other axis available, the main panel already drives the interior axis and a separate Interior tile would just be noise. Once any second axis is supported, the Interior toggle is offered immediately (it does not depend on whether the sibling toggle is currently enabled).

All four entities subscribe to the same `AlarmCoordinator`; commands from any entity update the joint `AlarmState`, and the coordinator update broadcasts new state to every entity. Sub-panel classes (`InteriorVerisureOwaAlarmPanel`, `PerimeterVerisureOwaAlarmPanel`, `AnnexVerisureOwaAlarmPanel`) inherit from `BaseVerisureOwaAlarmPanel` and override two hooks: `_resolve_target_state(ha_state)` projects an HA state onto the panel's axis (preserving the others), and `_extract_state(joint)` reads only the panel's axis from the joint state.

## Force-arm with sub-panels

The event-driven force-arm architecture generalizes naturally: each panel owns its own force context, fires `verisure_owa_arming_exception` (and the equivalent `securitas_arming_exception` — both are emitted by `events.fire_event`) with its own `entity_id`, and the built-in handler filters by entity_id so notifications mention the specific panel that triggered the exception. Subscribe to whichever name you prefer in your own automations; the `verisure_owa_*` form is recommended for forward compatibility with the deferred domain rename (see `docs/FUTURE_MIGRATION_PLAN.md`).

## Configuration

### Config flow (`config_flow.py`)

**Initial setup** (`FlowHandler`):
```
Step 1 (user): Country (auto-detected from HA), username, password
  → Session already running for this username? Borrow and hold it (no new login)
  → Otherwise build a new hub
→ finish_setup(): _sign_in_and_hold_session, then list installations
  → Own hub: under the per-account lock (_account_lock), borrow a session an
    entry or another dialog registered meanwhile, or else log in and register one
  → Borrowed hub: log in again if needed, outside the lock
  → TwoFactorRequiredError → 2FA flow
Step 2 (phone_list, if 2FA): Pick which phone to send OTP to
Step 3 (otp_challenge, if 2FA): Enter the SMS code, then back to finish_setup()
  → Handles: invalid code, expired code (auto-resends), send failure
  → Translated error messages in 7 languages (en, es, fr, it, pt, pt-BR, ca)
Step 4 (select_installation, if multiple): Pick which installation to configure
  → Auto-detection of perimeter / annex from service attributes + JWT capabilities + alarm partitions
  → get_services uses FOREGROUND priority to avoid blocking behind background queue traffic
  → Capabilities are published into hass.data so the options dialog opened
    immediately after entry creation can read them before the coordinator
    is stored under entry.entry_id (the published-cache fallback)
Step 5 (options): Four sections + collapsed Advanced
  - PIN code for disarming (PIN, require-PIN-to-arm)
  - Force-arm notifications (notify service, built-in notifications toggle)
  - Additional sub-panels (capability-gated Interior / Perimeter / Annex toggles —
    only shown when peri or annex is detected; Interior offered as soon as
    any sibling axis is supported)
  - Activity Log and Events (background activity polling toggle)
  - Advanced (collapsed): scan interval, delay between API requests,
    operation poll timeout
  → Title shows installation name ("Options for {installation_name}")
  → Section payloads are flattened back to flat top-level keys before storage
Step 6 (mappings): Map HA alarm buttons to Verisure OWA states
  Available options come from `dropdown_options(has_peri, has_annex)` —
  the four interior modes always, plus peri-bearing variants when has_peri,
  annex-bearing variants when has_annex, and peri+annex combinations when
  both are set. Mapping fields use `description={"suggested_value": ...}`
  rather than `default=`, so a cleared field persists as a missing key
  ("not used") instead of being re-filled with the default on submit.
  Description trailing sentence ("The optional ... panels do not use these
  mappings.") is rendered conditionally via {subpanels_note} placeholder,
  resolved server-side from translations into one of three pre-translated
  variants (peri-only, annex-only, both); empty when neither axis exists.
→ Create config entry per installation
```

Device IDs are generated during initial setup and stored in the config entry for reuse across restarts. The config flow registers its authenticated session in `hass.data[DOMAIN]["sessions"]` (keyed by username, exactly as typed) for reuse during `async_setup_entry`, avoiding duplicate login calls. The account's installations list goes in `hass.data["securitas_installations_cache"]` (`_store_installations_cache`, keyed by username, kept for `API_CACHE_TTL`), outside `hass.data[DOMAIN]` so it survives the integration's clean-up when the only entry unloads; the reload after reauth or Reconfigure switches the entry's account therefore reuses the list instead of fetching it again.

**Signing in again: reauth and Reconfigure** (`async_step_reauth` / `async_step_reauth_confirm`, and `async_step_reconfigure`):

Triggered when `async_setup_entry` raises `ConfigEntryAuthFailed` (on `TwoFactorRequiredError` or `AuthenticationError`). The most common everyday trigger is a refresh-token failure with no password fallback — e.g. token revoked, expired past its 180-day TTL, or dead on disk (an `xSRefreshLogin` null-deref crash or err 4 / 404 refusal of the stored token; one of either is treated as transient, because a single failure can be a server wobble, while a streak of them — two consecutive setup attempts, or three consecutive runtime renewals with no success in between, raised as `RefreshTokenDeadError` — escalates to reauth, #568).

When setup's login fails with `TwoFactorRequiredError` or `AuthenticationError` (not a dead-token streak), `_login_or_raise` also adds a Repairs issue (`sign_in_again`, one per account, its ID a hash of the username) explaining in plain language that the account must sign in again; a blocked account (`AccountBlockedError`) gets the `account_blocked` text instead, which says to unblock it with 'Forgot password' first. Its placeholder is the login, which Home Assistant does not save because the issue is not persistent. The issue is removed once a reauth or Reconfigure dialog succeeds for the account (`_finish_reauth`, which matters for a disabled entry, whose reload sets nothing up), once a setup signs in to the account again (`_get_or_create_session`; reusing a running session, another entry's or a setup dialog's, does not count), or once no entry uses the account any more: its last entry is deleted (`async_remove_entry`), or signed in again as another account (`_clear_sign_in_issues`).

The dialog presents a form pre-filled with the existing username and signs in with the username and password typed (plus a verification code if asked), never the entry's saved refresh token, which `_sign_in_again` drops before connecting because a login prefers a saved token over the password. Preserves existing device IDs from the entry being reauthenticated to maintain device identity. On successful login, `_finish_reauth` registers its own hub as the account's shared session under `_account_lock`, replacing any running one (see Session sharing), writes the **fresh refresh token** (not the password) to `entry.data` and to every other entry on the account, and reloads them all. The typed login is compared with the saved one exactly, since Verisure can reject a registered email in other capitals; any other spelling is an account switch, which is refused (`installation_not_on_account`) when that account cannot see the entry's installation, and otherwise moves the entry's unique ID to `<new email>_<installation>` unless another entry already holds that ID (Home Assistant reports taking another entry's ID as an integration bug). In that case both entries now work out to the same ID. `_finish_reauth` re-runs `_async_update_duplicate_entry_issues` as soon as it saves the new account, so the `duplicate_entry` Repairs issue appears when a switch creates such a clash and clears when a switch ends one, even when the entry is disabled and the reload sets nothing up. If 2FA is required during reauth, the full 2FA flow (phone selection, OTP) runs before completing. A dialog closed at the phone-selection or code step and reopened is asked for that step with no input. It then shows its first form again (`_restart_sign_in`), so submitting it asks Verisure for a new code. If Verisure fails to start it (`validate_device`), the dialog shows its sign-in form again (`reauth_confirm` or `reconfigure`) with `cannot_connect`, not the new-setup form, which would go on to create a new entry. Every login this flow runs — initial setup, reauth, Reconfigure and the 2FA completion — goes through `_login_with_family_fallback`, so the flow reaches the server the same way setup does (#606). The **Reconfigure** item in the entry's menu (`async_step_reconfigure`) runs the same sign-in (`_sign_in_again`) at any time, whether or not the entry needs reauth. It differs in its form's step ID (`reconfigure`) and closing reason (`reconfigure_successful`), and in two rules about other dialogs: an open Reconfigure dialog counts as an open setup dialog when deciding whether to tear the integration down (`_integration_in_use`), and `_finish_reauth` stops with `already_in_progress` while another dialog for the same installation that is not a reauth prompt holds the installation's unique ID. A dialog claims that ID (`async_set_unique_id`) only after its login has succeeded and its refresh-token and account-switch installation checks have passed, just before it waits for `_account_lock`, and holds it through the save and the reload until the dialog closes. A dialog that one of those checks sends back to its form never claimed the ID, so a reauth dialog finishing beside a Reconfigure that is merely open, or back at its form after a failed check, goes ahead. A sign-in dialog whose password or verification-code submission is still running when another dialog saves a sign-in for the same entry stops with `signed_in_again_elsewhere` instead of saving over it. One still running when another installation's dialog saves a sign-in to the same account stops with `account_signed_in_again_elsewhere`, because the installations share that account's session and its sign-in, started before that save, would replace the one just saved there. A dialog that is only open, or waiting for the user to type a code, at that moment is not affected. The saving dialog marks the others (`_overtake_sign_ins_in_flight`) from a list of running submissions and the entry each is for (`_sign_in_running`), kept outside `hass.data[DOMAIN]`, since the clean-up can run while a reauth submission waits.

**Options flow** (`VerisureOptionsFlowHandler`):
```
Step 1 (init): General settings — the same four-section + Advanced layout as
  the initial flow's Step 5 above (PIN section, Force-arm notifications
  section, capability-gated Sub-panels section, Activity Log and Events
  section, collapsed Advanced section).
  Sub-panel toggles are gated on detected capabilities; the Interior toggle is
  offered whenever any sibling axis is supported.

Step 2 (mappings): Alarm state mappings — same five mapping dropdowns as
  initial flow, with the same conditional {subpanels_note} placeholder.

Step 3 (lock_automations): Per-lock automation settings (skipped entirely
  when no locks are registered, going straight to CREATE_ENTRY).
  Renders one section per discovered lock (section key lock__<device_id>,
  section name substituted via {lock_alias_<did>} description placeholder).
  Inside each section, two groups of per-circuit boolean checkboxes:
  - lock_on_arm__<circuit> for each enabled circuit (Interior/Perimeter/Annex)
  - unlock_disarms__<circuit> for each enabled circuit
  On submit the booleans are compressed to circuit-name lists and stored
  as entry.options[CONF_LOCK_AUTOMATIONS][device_id]. Disabled circuits are
  omitted from the schema entirely.
```

All sections use HA's `data_entry_flow.section()` API. PIN, Force-arm notifications, and Sub-panels are open by default; Advanced is collapsed. Section payloads are flattened back to top-level keys via `_flatten_sections()` before storage so the persisted shape stays flat.

Changing options triggers `async_update_options()`, which compares each tracked option key (PIN, mappings, sub-panel toggles, lock automations, scan interval, etc.) against `entry.data` and reloads the integration if any has changed. The reload re-runs every entity's `async_added_to_hass`, which is how locks pick up their refreshed `_lock_on_arm_circuits` / `_unlock_disarms_circuits` slices.

## Key data flows

### User arms the alarm from HA

```
User presses "Arm Away" in HA UI
  → async_alarm_arm_away(code)
    → _check_code_for_arm_if_required(code)  # PIN check if configured
    → set_arm_state(ARMED_AWAY)
      → _wait_until_idle(); operation.begin("arm", [self], ARMED_AWAY)
      → _force_state(ARMING)                 # UI shows "Arming..."
      → _mode_to_alarm_state(ARMED_AWAY) = AlarmState(TOTAL, ON)  (example with peri)
      → _execute_transition(target=AlarmState(TOTAL, ON))
        → current = AlarmState from _planning_proto_code() (e.g. "B" → DAY+ON)
        → resolver.resolve(current, target) returns:
          Step 1: disarm [DARM1DARMPERI, DARM1]  (mode change needs disarm first)
          Step 2: arm [ARMINTEXT1, ARM1PERI1, ARM1+PERI1]
        → _execute_step(Step 1):
          → each command's answer is recorded as it returns
            (_send_single_command → coordinator.record_confirmed_proto_code)
          → try DARM1DARMPERI → success? done
          → VerisureOwaError (non-409)? mark_unsupported, try DARM1
        → _execute_step(Step 2):
          → try ARMINTEXT1 → success? done
          → fail? mark_unsupported, try ARM1PERI1
          → fail? mark_unsupported, try ARM1 then PERI1
        → Return OperationStatus with protomResponse="A"
      → update_status_alarm(status)
        → _last_proto_code = "A"
        → _status_map["A"] = ARMED_AWAY
        → _state = ARMED_AWAY                   # UI shows "Armed Away"
      → finally: operation.end()
```

### Periodic status poll

```
AlarmCoordinator fires every scan_interval seconds
  → _async_update_data()
    → queue.submit(client.get_general_status, installation)
      → client.get_general_status(installation)  # Cloud-only xSStatus, no panel wake
      → Return SStatus
    → Return AlarmStatusData(status, protom_response)
  → _handle_coordinator_update() on CombinedVerisureOwaAlarmPanel
    → Skip if _operation_in_progress
    → _clear_force_context()
    → _update_from_coordinator(data)
      → proto_code from status.status
      → _last_proto_code = proto_code  # resolver's fallback until a code is confirmed
      → protomResponse "D" → DISARMED
      → protomResponse in _status_map → mapped HA state
      → protomResponse unknown → ARMED_CUSTOM_BYPASS + notification
    → async_write_ha_state()
```

Periodic polling always uses the lightweight `xSStatus` (general status) endpoint for efficiency. The more expensive `CheckAlarm` path (protom round-trip to the panel) is used only for arm/disarm operations and the manual refresh button.

## Testing

### Overview

The test suite has **1028 tests** achieving **92% overall coverage**. Tests run on every PR via GitHub Actions with three parallel checks: Ruff lint/format, Pyright type checking, and pytest with a 90% coverage floor.

```bash
# Run the full suite
python -m pytest tests/ -v --tb=short

# Run with coverage
python -m pytest tests/ --cov=custom_components/verisure_owa --cov-report=term-missing

# Run a single test file
python -m pytest tests/test_client_auth.py -v

# Lint and type check
ruff check . && ruff format --check .
pyright custom_components/verisure_owa/
```

### Test architecture

Tests are organized by module, with a shared `conftest.py` providing fixtures and helpers.

```
tests/
├── conftest.py              Shared fixtures (API client, JWT helpers, response factories)
├── mock_graphql.py          Mock HTTP transport for integration tests (see below)
├── test_alarm_panel.py      Alarm entity: state mapping, arm/disarm, PIN validation, WAF handling
├── test_api_queue.py        ApiQueue priority, throttling, arrival order, cancellation
├── test_architecture.py     Structural tests (imports, file existence, module patterns)
├── test_auth.py             Login, refresh, 2FA, token lifecycle (HA-level)
├── test_binary_sensor.py    WiFi connection binary sensor (coordinator-driven)
├── test_button.py           Refresh button entity, capture button, 403 WAF notification
├── test_camera_api.py       Camera API operations: discover, capture, thumbnails
├── test_camera_platform.py  Camera entity platform setup and image serving
├── test_client_alarm.py     VerisureOwaClient alarm operations: arm, disarm, check_alarm, polling
├── test_client_auth.py      VerisureOwaClient auth lifecycle: login, refresh, 2FA, logout
├── test_client_camera.py    VerisureOwaClient camera operations: capture, thumbnail, full image
├── test_client_lock.py      VerisureOwaClient lock operations: get_modes, change_mode, config
├── test_client_misc.py      VerisureOwaClient misc: sentinel, air quality, services, installations
├── test_command_resolver.py CommandResolver state transitions, fallback chains
├── test_config_flow.py      Config flow (setup + 2FA + reauth/Reconfigure) and options flow
├── test_constants.py        SENTINEL_SERVICE_NAMES, VerisureOwaState enum, mapping tables
├── test_coordinators.py     DataUpdateCoordinators: alarm, sentinel, lock, camera
├── test_domains.py          Country-to-URL routing
├── test_exceptions.py       Exception hierarchy, message, log_detail, response_body
├── test_execute_request.py  HttpTransport request execution, retries, error handling
├── test_ha_platforms.py     Platform async_setup_entry for all entity types
├── test_helpers.py          DRY helpers: _poll_operation (409 retry, transient errors)
├── test_http_transport.py   HttpTransport: POST, retries, WAF detection, JSON parsing
├── test_hub.py              VerisureHub: camera management, lock management, queue
├── test_init.py             Integration setup, session sharing, background discovery
├── test_integration.py      Integration tests using MockGraphQLServer (see below)
├── test_log_filter.py       SensitiveDataFilter: secret redaction, installation masking
├── test_models.py           Pydantic domain models: null coercion, field mapping, enums
├── test_responses.py        Pydantic response envelopes: validation, null safety
└── test_services.py         Service discovery, Sentinel, air quality, smart lock service requests
```

### Key fixtures (`conftest.py`)

**API client fixtures:**
- `api` — A real `VerisureOwaClient` instance configured with test credentials (`test@example.com`, country `ES`). Uses a `MagicMock` for the `HttpTransport` so no real network calls are made.
- `mock_transport` — An `AsyncMock(spec=HttpTransport)` used by the `api` fixture.
- `mock_execute` — The `mock_transport.execute` AsyncMock. Tests set return values on this to control API responses without going through HTTP.

**JWT helpers:**
- `make_jwt(exp_minutes=15)` — Creates a real HS256 JWT with a configurable expiry. Used to test token parsing, expiry detection, and refresh logic.
- `FAKE_JWT` / `FAKE_REFRESH_TOKEN` — Pre-built JWTs for common test scenarios.

**Response factories:**
- `login_response()`, `refresh_response()`, `validate_device_response()` — Build realistic API response dicts with sensible defaults and overridable fields.
- `refresh_crash_response()` / `refresh_login_crash_error()` — The `xSRefreshLogin` server crash as a response dict / as the `VerisureOwaError` the client raises; the input contract for `is_refresh_login_crash`.
- `refresh_token_rejected_response()` / `refresh_token_rejected_error()` — The `xSRefreshLogin` err 4 / 404 refusal of the stored token as a response dict / as the `VerisureOwaError` the client raises; the input contract for `is_refresh_token_rejected`.

**Integration fixtures:**
- `make_installation(**overrides)` — Factory for `Installation` Pydantic model with defaults (number, panel, address, etc.).
- `make_config_entry_data()` — Builds a complete config entry data dict with all required keys.
- `make_securitas_hub_mock()` — Creates a `MagicMock` mimicking `VerisureHub` with `AsyncMock` methods for login, validate_device, etc.
- `setup_integration_data(hass, client, devices)` — Populates `hass.data[DOMAIN]` the same way `async_setup_entry` does.

### Testing patterns

**API client tests** (test_client_auth, test_client_alarm, test_client_lock, test_client_camera, test_client_misc): Use the `api` + `mock_execute` fixtures. Tests call the real method (e.g. `api.login()`) with a mocked `transport.execute` return value, then assert on state changes (`api.authentication_token`, `api.authentication_token_exp`, etc.). Golden contract tests assert exact wire-protocol payloads with hardcoded literals to catch unintentional protocol changes.

**HA platform tests** (test_alarm_panel, test_button, test_ha_platforms): Create entity instances directly with `MagicMock` dependencies. Use coordinator mocks to provide data. Example:

```python
alarm = make_alarm(has_peri=True)  # Creates CombinedVerisureOwaAlarmPanel with mocked hub + coordinator
alarm.client.arm_alarm = AsyncMock(return_value=arm_status)
await alarm.async_alarm_arm_away()
assert alarm._state == AlarmControlPanelState.ARMED_AWAY
```

**Config flow tests** (test_config_flow): Use the `hass` fixture from `pytest-homeassistant-custom-component` and HA's flow manager API:

```python
result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={...})
assert result["type"] == FlowResultType.FORM
```

**Integration setup tests** (test_init): Patch `VerisureHub` constructor and `async_forward_entry_setups` to test the full `async_setup_entry` flow without loading real platforms.

**Coordinator tests** (test_coordinators): Test all four coordinators with mocked `VerisureOwaClient` and `ApiQueue`. Verify data fetching, error handling (SessionExpiredError re-login, WAFBlockedError, general errors), and data preservation across refreshes.

### Integration tests (`test_integration.py`, `mock_graphql.py`)

Integration tests exercise the full stack from HA config-entry setup through to API behaviour, using a `MockGraphQLServer` that intercepts `aiohttp` POST calls at the HTTP transport level. Unlike unit tests, these let the transport and client run fully — header construction, JSON parsing, Pydantic validation, and error handling are all exercised.

**How the mock server works:**

`MockGraphQLServer` (in `tests/mock_graphql.py`) replaces the `aiohttp` session's POST method. Each call reads the `X-APOLLO-OPERATION-NAME` header, records the call, and returns the next queued response for that operation:

```python
server = MockGraphQLServer()
server.add_response("mkLoginToken", graphql_login())
server.add_response("mkInstallationList", graphql_installations())
server.set_default_response("CheckAlarm", graphql_check_alarm())

mock_http = server.make_http_client()
with patch("custom_components.verisure_owa.async_get_clientsession", return_value=mock_http):
    result = await async_setup_entry(hass, entry)

assert server.call_count("mkLoginToken") == 1
_, headers, _ = server.get_calls("CheckAlarm")[0]
assert headers["numinst"] == "123456"
```

Key design choices:
- **Queue-based**: each operation has a FIFO queue; `set_default_response()` provides a fallback when the queue is empty
- **Records all calls**: tests can assert on operation name, request headers, and JSON body
- **`queue_standard_setup()`**: convenience helper that queues login → list_installations → services and sets defaults for alarm status calls
- **Response factories**: `graphql_login()`, `graphql_installations()`, `graphql_alarm_status()`, `graphql_arm()`, `graphql_disarm()`, `graphql_sentinel()`, etc. return dicts matching the real Verisure GraphQL schema

**What integration tests cover:**
- Full setup flow: login → list installations → get services → forward platforms
- JWT parsing: authentication token expiry set correctly from `mkLoginToken` response
- Error handling: `AuthenticationError`, `TwoFactorRequiredError`, connection errors → correct return values
- Scoped request headers: `numinst`, `panel`, `X-Capabilities` present on installation-scoped calls
- Operation routing: `X-APOLLO-OPERATION-NAME` header matches the operation name for every call
- State from real API responses: `OperationStatus` proto codes map to correct HA states
- Polling behaviour: `ArmStatus`/`DisarmStatus` WAIT responses are retried
- Sensor data: `get_sentinel_data()` and `get_air_quality_data()` parse real response shapes
- Unload: `async_unload_entry` cleans up `hass.data[DOMAIN]` correctly

### Coverage by module

| Module | Coverage | Key gaps |
|--------|----------|----------|
| `__init__.py` | 81% | Lock config retry, card resource registration/removal |
| `hub.py` | 92% | Some camera/lock edge paths |
| `entity.py` | 79% | Properties and helpers used by non-coordinator entities |
| `coordinators.py` | 78% | Camera full-image fetch, thumbnail recency check |
| `alarm_control_panel.py` | 97% | `async_setup_entry`, some HA callbacks |
| `api_queue.py` | 100% | -- |
| `binary_sensor.py` | 100% | -- |
| `button.py` | 100% | -- |
| `camera.py` | 98% | Base64 decode error path |
| `config_flow.py` | 89% | Some flow branches |
| `client.py` | 92% | Rare error paths, camera capture timeout, Danalock fallback |
| `http_transport.py` | 97% | Retry-After header parsing edge case |
| `graphql_queries.py` | 100% | -- |
| `command_resolver.py` | 90% | Rare fallback paths |
| `models.py` | 99% | Null-safe base validator |
| `responses.py` | 99% | Null-safe base validator |
| `const.py` | 100% | Includes `SENTINEL_SERVICE_NAMES` |
| `domains.py` | 100% | -- |
| `exceptions.py` | 100% | -- |
| `lock.py` | 94% | Timer setup, some error paths |
| `sensor.py` | 95% | `async_setup_entry` |
| `log_filter.py` | 88% | Nested arg scanning |

### CI workflow (`.github/workflows/tests.yaml`)

Three parallel jobs run on every PR and push to main:

1. **Ruff lint & format** — `ruff check .` and `ruff format --check .`
2. **Pyright** — `pyright custom_components/verisure_owa/` for static type checking
3. **Tests** — `pytest` with `--cov-fail-under=90` to enforce minimum coverage

### Nightly workflow (`.github/workflows/nightly.yml`)

A scheduled run (cron `41 4 * * *`, plus `workflow_dispatch`) exercises the repo
against the **latest** upstream dependencies, separate from the pinned/ranged PR
CI. It installs the newest Home Assistant core + `pytest-homeassistant-custom-component`
and runs the unit + integration suites, and validates with hassfest + HACS
against current HA. This is an early-warning system for breakage from new HA
releases; it does not gate PRs. All other CI/validation/release workflows live
alongside it under `.github/workflows/`.

## File reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 1922 | Integration setup functions, session sharing, background discovery, coordinator creation, card resource registration |
| `hub.py` | 722 | `VerisureHub` (central hub wrapping VerisureOwaClient), `VerisureDevice` (device registry wrapper) |
| `entity.py` | 96 | `VerisureEntity` base class, `verisure_device_info()`, `camera_device_info()` |
| `coordinators.py` | 429 | `AlarmCoordinator`, `SentinelCoordinator`, `LockCoordinator`, `CameraCoordinator` |
| `config_flow.py` | 1663 | Config flow (setup + 2FA + reauth/Reconfigure + installation picker) and options flow (settings + mappings) |
| `alarm_control_panel.py` | 840 | Alarm entity (CoordinatorEntity) with state mapping, arm/disarm, force arm, PIN validation, WAF tracking |
| `sensor.py` | 185 | Sentinel temperature, humidity, air quality sensors (CoordinatorEntity) |
| `binary_sensor.py` | 63 | WiFi connection status diagnostic sensor (CoordinatorEntity, no polling) |
| `lock.py` | 345 | Multi-lock entity (CoordinatorEntity) with lock feature attributes |
| `camera.py` | 166 | Camera entities: VerisureCamera (thumbnail), VerisureCameraFull (full image), both CoordinatorEntity |
| `button.py` | 152 | Refresh button with WAF notification, capture button |
| `api_queue.py` | 125 | Priority-based rate-limited API queue (FOREGROUND/BACKGROUND) |
| `const.py` | 58 | Integration constants, signal names, config keys, platform list, card URLs, `SENTINEL_SERVICE_NAMES` |
| `log_filter.py` | 86 | `SensitiveDataFilter` -- log sanitization for secrets |
| `pin_crypto.py` | 56 | `hash_pin`/`verify_pin` -- PBKDF2-HMAC-SHA256 hashing for the local alarm/lock PIN |
| `verisure_owa_api/client.py` | 1764 | `VerisureOwaClient` -- auth lifecycle, typed GraphQL execution, all business operations |
| `verisure_owa_api/http_transport.py` | 154 | `HttpTransport` -- raw HTTP POST with retries, WAF detection, JSON parsing |
| `verisure_owa_api/graphql_queries.py` | 265 | GraphQL query and mutation string constants |
| `verisure_owa_api/command_resolver.py` | 182 | `CommandResolver`, `AlarmState`, `CommandStep` -- state transition logic |
| `verisure_owa_api/models.py` | 375 | Pydantic domain models (Installation, OperationStatus, SmartLock, CameraDevice, Sentinel, etc.) |
| `verisure_owa_api/responses.py` | 517 | Pydantic response envelopes for every GraphQL operation |
| `verisure_owa_api/const.py` | 107 | `VerisureOwaState`, command/protocol mappings, defaults |
| `verisure_owa_api/domains.py` | 50 | Country-to-URL routing |
| `verisure_owa_api/exceptions.py` | 121 | Exception hierarchy with `http_status`, `log_detail()`, and `ArmingExceptionError` |
| `www/verisure-owa-alarm-card.js` | 1841 | Custom Lovelace alarm card with WAF warning banner, multi-language. **Deprecated since v5.8.0**, together with the badge and Mushroom chip in `www/verisure-owa-alarm-chip.js`: the card shows a notice the user can close, and each of the three reports itself once per element instance over the `verisure_owa/deprecated_element` websocket command, which `card_resources.py` registers from `async_setup` and which logs one warning per element and dashboard until Home Assistant restarts. (Filename `securitas-alarm-card.js` is a byte-identical copy retained indefinitely as an alias served at the `/securitas_panel/` URL prefix so old user dashboards keep loading; the card picker only offers the `custom:verisure-owa-alarm-card` form.) |
| `www/verisure-owa-camera-card.js` | 376 | Custom Lovelace camera card with capture button, image timestamp overlay, and loading spinner. (Same legacy-copy treatment as the alarm card.) |
| `www/verisure-owa-activity-log-card.js` | — | Custom Lovelace **Activity Log** card showing recent alarm-panel activity. |

**Card cache-busting.** The card files are served from `/verisure-owa-panel` with a long browser cache lifetime, so every URL the integration serves from it carries `?v=<first 8 hex of the file's sha256>-<manifest version>`. `const.py::_card_url` stamps the registered entry points when `const.py` is imported. The relative imports between modules (for example `./verisure-owa-card-utils.js`) are stamped in the JS source by `scripts/stamp_card_imports.py`, dependencies first, so a change to one module changes the URL of every module that imports it, directly or through others. After editing a card module, run `python3 scripts/stamp_card_imports.py` and restart Home Assistant so it serves the new entry-point URLs. `tests/test_card_cache_busting.py`, `tests-js/integration/card-cache-busting.test.js` and the pre-push hook (`--check`) fail when a stamp is out of date, and the release workflow re-runs the script after each version bump.
