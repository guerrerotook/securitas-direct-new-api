# Architecture Guide

This document explains how the Securitas Direct integration works, aimed at developers who want to contribute.

## System overview

The integration has three layers:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Home Assistant Platform Layer                                       │
│  alarm_control_panel.py  sensor.py  binary_sensor.py                 │
│  lock.py  button.py  camera.py                                       │
│  entity.py  (SecuritasEntity base class)                             │
│  coordinators.py  (DataUpdateCoordinators)                           │
├──────────────────────────────────────────────────────────────────────┤
│  Integration Hub Layer                                               │
│  __init__.py  (setup functions)                                      │
│  hub.py  (SecuritasHub + SecuritasDirectDevice)                      │
│  config_flow.py  (ConfigFlow + OptionsFlow + ReauthFlow)             │
│  api_queue.py  (Priority-based rate limiting)                        │
│  log_filter.py  (SensitiveDataFilter)                                │
├──────────────────────────────────────────────────────────────────────┤
│  API Client Layer                                                    │
│  securitas_direct_new_api/                                           │
│  client.py  (SecuritasClient — auth, typed GraphQL, polling)         │
│  http_transport.py  (HttpTransport — raw HTTP with retries)          │
│  graphql_queries.py  command_resolver.py  domains.py                 │
│  models.py  responses.py  const.py  exceptions.py                    │
└──────────────────────────────────────────────────────────────────────┘
```

Every API call goes through `HttpTransport.execute()` (in `http_transport.py`), which sends POST requests over HTTP to Securitas' cloud. `SecuritasClient` (in `client.py`) composes an `HttpTransport` instance and adds authentication lifecycle, typed GraphQL execution via Pydantic response envelopes, and all business-level operations (login, arm/disarm, status checks, etc.). The integration hub (`SecuritasHub` in `hub.py`) wraps the API client and is shared by all entity platforms. Four `DataUpdateCoordinator` subclasses (in `coordinators.py`) handle periodic polling for alarm status, sentinel sensors, locks, and cameras. All entity platforms use the `CoordinatorEntity` pattern. Each platform creates entities for the installations discovered at startup.

## API client layer

**Location:** `custom_components/securitas/securitas_direct_new_api/`

### HttpTransport (`http_transport.py`)

The bottom transport layer. It has no knowledge of auth tokens, GraphQL structure, or Securitas API semantics. All it does is POST JSON to a base URL and return the parsed response.

**Request execution:** `execute(content, headers)`:
1. Merges caller-provided headers on top of defaults (`User-Agent`, `content-type`)
2. POSTs the JSON body via `aiohttp.ClientSession.post()`
3. Retries once on DNS errors (`ClientConnectorDNSError`)
4. Retries once on HTTP 403 with `Retry-After` header (rate limiting)
5. Raises `WAFBlockedError` immediately if 403 response contains `_Incapsula_Resource` (WAF blocks require longer backoff — retrying would extend the block)
6. Raises `SecuritasDirectError` on HTTP >= 400
7. Parses JSON and returns the dict

**Response log sanitization:** Before logging API responses at DEBUG level, `_sanitize_response_for_log()` replaces large fields (`hours`, `image`) with placeholder values (`["..."]` for lists, `"..."` for strings). This prevents base64-encoded camera images and hourly sensor arrays from flooding the debug log.

### SecuritasClient (`client.py`)

A standalone class (not inheritance-based) that composes an `HttpTransport` for the raw HTTP layer. It implements all business-level API operations: login, refresh, 2FA validation, arm/disarm, status checks, sentinel data, lock operations, camera operations, and service discovery. All GraphQL query and mutation strings are defined in `graphql_queries.py` and imported here.

**Architecture:** `SecuritasClient` takes an `HttpTransport` via its constructor (composition, not inheritance). This separation means the transport layer can be mocked independently of business logic in tests.

**Typed GraphQL execution:** `_execute_graphql()` is the central entry point for all installation-scoped operations. It:
1. Calls `_ensure_auth()` (skipped for auth operations like `mkLoginToken`, `RefreshLogin`, `mkSendOTP`, `mkValidateDevice`)
2. Builds headers via `_build_headers()`
3. Sends the request via `self._transport.execute()`
4. Checks for GraphQL-level errors via `_check_graphql_errors()`
5. Validates the JSON response into a typed Pydantic envelope via `response_type.model_validate(response_dict)`
6. Returns the typed Pydantic model

Auth operations that need to inspect the raw response structure use `_execute_raw()` instead, which skips Pydantic validation and returns the raw dict.

**403 session-expired retry:** When the Securitas server returns a GraphQL error with `data.status == 403` (indicating a server-side session expiry), `_check_graphql_errors()` raises `SessionExpiredError`. The `_execute_graphql()` method catches this, forces token re-authentication, and retries the operation once. A `_retried` flag prevents infinite retry loops.

**Authentication** is JWT-based with three mechanisms:

1. **Login** (`login()`) — Sends credentials, receives a JWT hash token. The JWT's `exp` claim sets `authentication_token_exp`. If the account needs 2FA, raises `TwoFactorRequiredError`. If the account is blocked, raises `AccountBlockedError`.

2. **Token refresh** (`refresh_token()`) — Uses a long-lived refresh token to get a new JWT without re-entering credentials. Returns `True` on success, `False` on failure.

3. **2FA device validation** (`validate_device()`) — For new devices: calls `validate_device()` which returns a list of phone numbers. The user picks one, `send_otp()` sends the SMS, then `validate_device()` is called again with the OTP code to complete registration.

**Token lifecycle:** Before every API operation, `_ensure_auth()` checks whether the JWT expires within the next minute. If so, it tries `refresh_token()` first, falling back to `login()`. Errors during refresh are caught with specific exception types (`SecuritasDirectError`, `asyncio.TimeoutError`) rather than bare `except`. Similarly, `_ensure_capabilities()` checks a per-installation capabilities JWT that's obtained from `get_services()`. On `logout()`, all tokens are cleared (`authentication_token`, `refresh_token_value`, `authentication_token_exp`, `login_timestamp`) to prevent stale credentials from being reused.

**DRY helpers:** Internal helpers reduce code duplication:

- `_decode_auth_token(token_str)` — Decodes a JWT (HS256, no signature verification), updates `authentication_token_exp` from the `exp` claim. Returns the decoded claims dict or `None` on failure. Used by `login()`, `refresh_token()`, and `validate_device()`.

- `_extract_response_data(response, field_name)` — Extracts `response["data"][field_name]`, raising `SecuritasDirectError` if the data is missing or `None`. Used by poll-status callbacks that work with raw dicts.

- `_poll_operation(check_fn, *, timeout, continue_on_msg)` — Polls `check_fn()` in a loop until the result is no longer `"WAIT"`. Handles transient errors (connection errors, timeouts, 409 "server busy") by retrying. Raises `OperationTimeoutError` after `timeout` seconds (default `poll_timeout`). Used by arm, disarm, status check, exception fetch, lock, and camera operations.

- `_ensure_auth(installation)` — Checks both the authentication token and the per-installation capabilities token, refreshing them as needed before executing a request.

- `_build_headers(operation, *, installation)` — Builds request headers including `app`, `auth` (JSON with JWT hash, user, country), `X-APOLLO-OPERATION-ID`, `X-APOLLO-OPERATION-NAME`, and optionally `numinst`/`panel`/`X-Capabilities` for installation-scoped requests. Auth operations (`mkValidateDevice`, `RefreshLogin`, `mkSendOTP`) use special headers with empty hash/refreshToken.

**Polling pattern:** Arm, disarm, status-check, exception-fetch, lock, and camera operations are asynchronous on the server side. The client sends the initial request, receives a `referenceId`, then polls a status endpoint via `_poll_operation()` (sleeping `poll_delay` seconds between attempts) until the response changes from `"WAIT"` to a final state or a wall-clock timeout is reached. Transient errors during polling — connection failures, timeouts, and 409 "server busy" responses — are automatically retried rather than failing the operation. After polling completes, `arm()` and `disarm()` check for `res: "ERROR"` with non-`NON_BLOCKING` error types (e.g. `TECHNICAL_ERROR`) and raise `SecuritasDirectError`, enabling the command resolver's fallback chain.

**Camera capture:** `capture_image()` submits the capture request, then polls `RequestImagesStatus` at 10-second intervals until the status transitions from "processing" to done. Once done, it fetches the updated thumbnail. The entire flow has a 90-second `asyncio.wait_for` deadline. If the deadline fires, it fetches one final thumbnail as a fallback (the CDN may have caught up). `get_full_image()` fetches full-resolution photos via `xSGetPhotoImages`, selects the largest BINARY image, base64-decodes it, and validates JPEG magic bytes.

**Device spoofing:** The client identifies itself as a Samsung Galaxy S22 running the Securitas mobile app v10.102.0. Device identity consists of three IDs generated at setup time: `device_id` (FCM-format token), `uuid` (16-char hex), and `id_device_indigitall` (UUID v4).

### Response envelopes (`responses.py`)

Every GraphQL operation has a typed Pydantic `BaseModel` envelope in `responses.py` that mirrors the exact shape of the API response. For example, `ArmPanelEnvelope` wraps `{"data": {"xSArmPanel": {res, msg, referenceId}}}`. This provides compile-time type safety and runtime validation — if the API response shape changes unexpectedly, `model_validate()` raises `ValidationError` which `_execute_graphql()` converts to `SecuritasDirectError`.

Envelopes use a `_NullSafeBase` base class that coerces `None` to `""` for any `str` field with a default. This is necessary because the Securitas API returns `null` for string fields during polling or when fields are not applicable, and Pydantic rejects `None` for `str` fields even with a default.

Shared inner models (`_ResMsg`, `_ResMsgRef`, `_OperationResult`, `_GeneralStatus`) are used across multiple envelopes to avoid duplication. `PanelError` carries force-arm context (allowForcing, referenceId, suid).

### Domain models (`models.py`)

Pydantic models for API domain objects. All domain models inherit from `_NullSafeBase` (same null-coercion logic as response envelopes). The most important ones:

- `Installation` — Represents a physical Securitas installation (number, alias, panel type, address, capabilities JWT, `alarm_partitions` list from services response). Uses `validation_alias` for API field name mapping (e.g. `numinst` -> `number`).
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

All GraphQL query and mutation strings are extracted into `graphql_queries.py`, keeping `client.py` focused on business logic. This module contains named constants for each operation (e.g. `VALIDATE_DEVICE_MUTATION`, `REFRESH_LOGIN_MUTATION`, `ARM_PANEL_MUTATION`, etc.) that `SecuritasClient` imports and passes to `_execute_graphql()`.

### Log sanitization (`log_filter.py`)

`SensitiveDataFilter` is a `logging.Filter` attached to all root logger handlers during integration setup. It redacts sensitive values (auth tokens, refresh tokens, usernames, passwords, OTP data) from log messages and arguments before they reach any handler (console, file, remote).

**How it works:**
- `update_secret(key, value)` registers a raw secret value with its redaction label (e.g. `"auth_token"` -> `[AUTH_TOKEN]`). Updating a key replaces the old value.
- `add_installation(number)` registers an installation number for partial masking (last 4 digits visible, e.g. `123456` -> `***3456`).
- The `filter()` method scans `record.msg` and `record.args` (including nested dicts/lists/tuples), replacing any known secret with its label.
- Registration happens in `SecuritasClient` via `_register_secret()` — called whenever tokens are obtained or refreshed (login, refresh, validate_device).
- Credentials (username, password) are registered at setup time in `async_setup_entry()`.
- The filter is removed from handlers on `async_unload_entry()`.

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

Securitas alarms have up to three independent axes: **interior mode** (disarmed, partial day, partial night, total), **perimeter** (on or off), and **annex** (on or off). Most installations only use the interior axis ± perimeter; the annex axis is used by some UK Vatrinus installations. The combination of interior × perimeter alone produces these 8 states:

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

**Location:** `securitas_direct_new_api/command_resolver.py`

The `CommandResolver` class models the alarm as three independent axes — `InteriorMode` (off, day, night, total), `PerimeterMode` (off, on), and `AnnexMode` (off, on) — combined into an `AlarmState`. It replaces the old `_use_multi_step` flag, `_send_arm_command()` / `_send_disarm_command()` methods, `COMPOUND_COMMAND_STEPS` constant, and `PERI_ARMED_PROTO_CODES` set.

**How it works:**

1. `resolve(current, target)` computes the state transition and returns an ordered list of `CommandStep` objects. Each step contains a list of command alternatives to try in order.

2. Combined commands are tried first (e.g. `ARMINTEXT1`, `ARM1PERI1`), with multi-step fallbacks using `+` separator (e.g. `ARM1+PERI1` means send `ARM1` then `PERI1` as separate sequential API calls).

3. For Total+Perimeter arm, `ARMINTEXT1` is ordered before `ARM1PERI1` — `ARMINTEXT1` arms interior+perimeter in one step without triggering the siren delay, which is important for Spanish WAF (Wife Acceptance Factor) safety.

4. **Runtime discovery of unsupported commands:** When a command fails with a non-409 `SecuritasDirectError`, `_execute_step()` calls `resolver.mark_unsupported(command)`, and the resolver skips it in all future resolutions. This is per-command granularity (not a global flag), so a disarm-specific failure (e.g. `DARM1DARMPERI`) does not disable unrelated compound arm commands. The unsupported set is in-memory and resets on HA restart.

5. **Disarm uses current state:** The resolver determines the disarm command from the current `AlarmState` (derived from `_last_proto_code`), not from configuration flags. If both interior and perimeter are armed, it tries `DARM1DARMPERI` first, falling back to `DARM1`. If only perimeter is armed, it tries `DARMPERI` first, falling back to `DARM1`.

6. **409 errors** (server busy) are re-raised immediately and do not trigger the fallback chain.

Home Assistant has five alarm buttons (Home, Away, Night, Vacation, Custom Bypass). The user maps each button to a Securitas state through the options flow. Standard installations get defaults without perimeter; perimeter installations get defaults that use perimeter states for Away (Total + Perimeter) and Custom (Perimeter Only). Both standard and perimeter installations default Night to Partial Night. Perimeter variants (e.g. Partial Night + Perimeter) are available in the options for perimeter installations and can be assigned to any button. The `Vacation` and `Custom Bypass` buttons are hidden unless a mapping is configured for them.

If the alarm is put into a state that is not mapped to any HA button (e.g. the perimeter is armed via a physical panel but perimeter support is not enabled in the integration), the entity reports `ARMED_CUSTOM_BYPASS` and logs the unmapped proto code at `info` level. This is not an error — it simply means the alarm is in a valid Securitas state that the user has not assigned to an HA button. To resolve it, enable perimeter support or map the relevant state in the integration options.

### Exceptions (`exceptions.py`)

```
SecuritasDirectError              Base class (http_status, message, response_body, log_detail())
├── AuthenticationError           Credentials rejected
│   └── AccountBlockedError       Account blocked by Securitas
├── TwoFactorRequiredError        2FA required
├── SessionExpiredError           JWT expired server-side (triggers re-auth in _execute_graphql)
├── APIResponseError              GraphQL-level error
├── WAFBlockedError               Incapsula WAF block (no retry)
├── APIConnectionError            Network-level failures (DNS, TCP, TLS)
├── OperationTimeoutError         Panel operation timeout
├── OperationFailedError          Panel rejection (carries error_code, error_type)
├── ArmingExceptionError          Open sensors blocking arm (carries force-arm context)
├── ImageCaptureError             Camera capture failure
└── UnexpectedStateError          Unrecognised protocol code (carries proto_code)
```

`SecuritasDirectError` takes `(message, *, http_status)` and has a `response_body` attribute that callers can set after construction. The `message` property returns the short human-readable description. The `log_detail()` method returns just the message for well-known HTTP statuses (400, 403, 409) and appends the response body for unknown errors to aid diagnosis.

`ArmingExceptionError` is raised when arming fails due to non-blocking exceptions (e.g. open window/door). It carries `reference_id`, `suid`, and the list of exceptions, providing the context needed to retry with `forceArmingRemoteId`.

## Integration hub layer

**Location:** `custom_components/securitas/hub.py` (SecuritasHub, SecuritasDirectDevice) and `custom_components/securitas/__init__.py` (setup functions only)

### SecuritasHub

The central coordinator between the HA layer and the API client. It owns a `SecuritasClient` session and is shared by all entity platforms via `hass.data[DOMAIN][entry.entry_id]["hub"]`.

**Key responsibilities:**
- **Login delegation** — Passes credentials through to `SecuritasClient`
- **Service discovery** — `get_services()` calls `SecuritasClient.get_services()` and caches the results per installation
- **API call serialization** — All API calls are submitted via `ApiQueue`, which enforces a minimum gap between calls to avoid triggering the Incapsula WAF rate limiter. See [ApiQueue](#apiqueue) below.
- **Camera management** — `get_camera_devices()` discovers cameras (cached), `capture_image()` requests new captures via the client and stores results. The hub handles HA-specific concerns: dispatcher signals (`SIGNAL_CAMERA_STATE`), image validation/storage, full-image background fetch, and coordinator data updates. After a capture completes, it pushes the new thumbnail and full image into the `CameraCoordinator` via `async_set_updated_data()`.
- **Lock management** — `get_lock_modes()` discovers locks (cached with TTL), `change_lock_mode()` performs lock/unlock via queue and invalidates cache, `get_lock_config()` fetches per-lock configuration (auto-detects Smartlock vs Danalock API).
- **Alarm operations** — `arm_alarm()`, `disarm_alarm()`, `refresh_alarm_status()` submit commands through the queue. `refresh_alarm_status()` uses the authoritative `CheckAlarm` round-trip (not just `xSStatus`).
- **Session sharing** — Multiple config entries for the same username share a single `SecuritasHub` instance via reference counting in `hass.data[DOMAIN]["sessions"]`. This prevents duplicate logins and reduces WAF pressure.

### Coordinators (`coordinators.py`)

Four `DataUpdateCoordinator` subclasses replace per-entity independent polling. Each coordinator owns a reference to the `SecuritasClient` and `ApiQueue`, fetches data on its configured interval, and handles `SessionExpiredError` (re-login + retry), `WAFBlockedError`, and general `SecuritasDirectError` by raising `UpdateFailed`.

**`AlarmCoordinator`** — Polls alarm status via `get_general_status()` (lightweight `xSStatus`, no panel wake). Returns `AlarmStatusData` with `SStatus` and `protom_response`. Update interval is the user-configured `scan_interval`.

**`SentinelCoordinator`** — Fetches sentinel data and air quality sequentially via `get_sentinel_data()` + `get_air_quality_data()`. Returns `SentinelData`. Fixed 30-minute interval (environmental data changes slowly).

**`LockCoordinator`** — Fetches lock modes via `get_lock_modes()`. Returns `LockData`. Update interval is the user-configured `scan_interval`.

**`CameraCoordinator`** — Fetches thumbnails for all cameras. Returns `CameraData` with `thumbnails` (per zone_id) and `full_images` (per zone_id). Fixed 30-minute interval. Individual camera failures are logged but don't fail the whole update — previous thumbnails are preserved. When a thumbnail's `id_signal` changes from the previous refresh, the coordinator automatically fetches the full-resolution image via `get_full_image()`. Thumbnails older than 1 hour are skipped for full-image fetch (they likely have no full image available on the CDN).

All coordinators share the same error-handling pattern: catch `SessionExpiredError` -> re-login -> retry once; catch `WAFBlockedError` or `SecuritasDirectError` -> raise `UpdateFailed`.

### ApiQueue (`api_queue.py`)

Serializes API calls with priority-based rate limiting to avoid WAF blocks. One queue is shared per API domain (country).

**Design:**
- Two priority levels: `FOREGROUND` (arm/disarm, user actions, setup) and `BACKGROUND` (polling)
- Both share the same minimum interval (`delay_check_operation`, default 2 seconds)
- Foreground requests preempt queued background work — background waits while any foreground requests are pending
- In-flight API calls are not cancelled; preemption happens between calls

**Algorithm:**
1. `submit(coro_fn, *args, priority, label)` accepts an async callable + args. The optional `label` overrides the function name in throttle log messages.
2. Foreground increments `_pending_foreground` and clears `_bg_event`
3. Background waits while `_pending_foreground > 0`
4. Lock ensures minimum gap between calls: `interval - elapsed_since_last_api_time`
5. Execute coroutine, update `_last_api_time`
6. Foreground decrements count, sets `_bg_event` when count reaches 0

### Setup flow (`async_setup_entry`)

**Critical rule:** Platform `async_setup_entry` functions must **never** make API calls. All API-based discovery is deferred to a background task that runs after setup completes. This avoids blocking HA startup.

```
1. Read config entry data into OrderedDict
2. Migrate old config: if no per-button mappings exist, derive from PERI_alarm checkbox
3. Check for device IDs (device_id, unique_id, id_device_indigitall)
   └── Missing? → raise ConfigEntryNotReady
4. Create SecuritasHub with aiohttp session + HttpTransport + SecuritasClient
5. Login
   ├── TwoFactorRequiredError → raise ConfigEntryAuthFailed (triggers reauth flow)
   ├── AuthenticationError → raise ConfigEntryAuthFailed (triggers reauth flow)
   └── SecuritasDirectError → raise ConfigEntryNotReady (HA retries)
6. Assign shared ApiQueue (per domain/country)
7. List installations, get_services() per installation
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
| alarm_control_panel | SecuritasAlarm entities (CoordinatorEntity) | None (coordinator-driven) |
| binary_sensor | WifiConnectedSensor entities (CoordinatorEntity) | None (coordinator-driven) |
| button | SecuritasRefreshButton entities | None (stores callback for capture buttons) |
| camera | Nothing | None (stores callback) |
| sensor | Sentinel sensors (CoordinatorEntity) | None (coordinator-driven) |
| lock | Nothing | None (stores callback) |

**Background discovery (`_async_discover_devices`):**

After all platforms are registered, a single background task discovers cameras and locks via API calls, then adds entities using the stored `async_add_entities` callbacks. This runs concurrently with HA startup, so the integration is immediately available (alarm panel, refresh buttons, sensors) while cameras and locks appear shortly after.

Camera discovery creates a `CameraCoordinator` (stored in entry data as `"camera_coordinator"`) and schedules its initial refresh. For each camera, both a `SecuritasCamera` (thumbnail) and `SecuritasCameraFull` (full-resolution) entity are created.

Lock discovery uses the `LockCoordinator` created during setup. For locks whose initial config fetch fails, a deferred retry is scheduled at exponentially increasing intervals (60s, 120s, 300s).

### Options update (`async_update_options`)

When the user changes options (PIN code, scan interval, alarm mappings, etc.), the listener merges the new options into the config entry data and reloads the integration. This triggers a full teardown and re-setup.

### SecuritasDirectDevice (`hub.py`)

A thin wrapper around `Installation` that provides `device_info` for the HA device registry. Each physical installation becomes one device.

### SecuritasEntity (`entity.py`)

Base class for non-coordinator entities. Inherits from `homeassistant.helpers.entity.Entity` and provides:

- **Common attributes** — `_installation`, `_client` (the `SecuritasHub`), `_state`, `_last_state`, and `device_info` (via the `securitas_device_info()` helper that groups entities under the installation device).
- **State management** — `_force_state(state)` sets a transitional state and schedules an HA state write. Used during lock operations and similar.
- **Error notifications** — `_notify_error(title, message)` creates a persistent notification with an auto-generated ID scoped to the installation number.

The `SecuritasRefreshButton` and `SecuritasCaptureButton` inherit from `SecuritasEntity`. The alarm, sensor, binary sensor, lock, and camera entities use `CoordinatorEntity` instead and duplicate the relevant helper methods directly (to avoid diamond inheritance).

The module also provides `securitas_device_info()` and `camera_device_info()` helpers for building `DeviceInfo` objects.

## Entity platforms

### Alarm control panel (`alarm_control_panel.py`)

The main entity. One `SecuritasAlarm` per installation. Inherits from `CoordinatorEntity[AlarmCoordinator]` and `AlarmControlPanelEntity`. The entity starts with `_state = None` (renders as "unknown" in HA) until the first successful coordinator update populates the real alarm state. This avoids showing a false "disarmed" state at startup.

**Coordinator integration:** The `_handle_coordinator_update()` callback skips updates while `_operation_in_progress` is True (during arm/disarm) to prevent stale API responses from overwriting the transitional state. On each coordinator update, `_clear_force_context()` is called and `_update_from_coordinator()` maps the `SStatus.status` proto code to an HA state.

**State mapping system:** During `__init__`, two dictionaries are built from the user's configuration:

- `_command_map`: HA state -> API command string. E.g. `ARMED_AWAY` -> `"ARM1"`. Only includes states the user has mapped (not `NOT_USED`).
- `_status_map`: Protocol response code -> HA state. E.g. `"T"` -> `ARMED_AWAY`. Built by reverse-looking up `PROTO_TO_STATE` for each configured Securitas state.

**`supported_features`** is derived from `_command_map` — only buttons with a configured mapping are exposed.

**Arm flow** (`async_alarm_arm_away` and friends):
```
1. _check_code_for_arm_if_required(code) — if PIN required for arming
2. _force_state(ARMING) — set transitional state, save previous in _last_state
3. set_arm_state(target_mode):
   a. Convert target HA mode to AlarmState via _mode_to_alarm_state()
   b. _execute_transition(target_alarm_state, **force_params):
      - Derives current AlarmState from _last_proto_code
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
   c. On error:
      - Notify user via persistent notification (short message only, never
        full error tuples with headers/tokens)
      - If a prior step succeeded (_last_arm_result), reflect that partial state
      - If no steps succeeded, revert to _last_state
   d. update_status_alarm() with the final response
```

**Disarm flow** (`async_alarm_disarm`):
```
1. _check_code(code) — raises ServiceValidationError if wrong
2. _force_state(DISARMING)
3. _execute_transition(AlarmState(OFF, OFF)):
   a. resolver.resolve(current, disarmed) returns CommandStep with ordered
      alternatives based on current state:
      - Both armed? → [DARM1DARMPERI, DARM1]
      - Only perimeter? → [DARMPERI, DARM1]
      - Only interior? → [DARM1]
   b. _execute_step() tries alternatives, marks failed ones unsupported
   c. 409 errors re-raised (server busy, not unsupported)
   d. Error on all attempts? → _notify_error() with short message, restore
      _last_state
4. update_status_alarm() with the response
```

**Arming exception flow** (open sensors blocking arm):
```
1. set_arm_state() catches ArmingExceptionError from _send_arm_command()
2. _set_force_context(exc, mode) — stores reference_id, suid, mode, exceptions
3. _fire_arming_exception_event(exc, mode) — fires securitas_arming_exception event
4. (if force_arm_notifications enabled) built-in handler listens for event:
   a. Persistent notification: lists each open sensor by name, explains how to force-arm
   b. Mobile notification (if notify_group configured): short message with
      Force Arm / Cancel action buttons
5. State reverts to _last_state
```

**Force arm flow** (`securitas.force_arm` / `securitas.force_arm_cancel` services):
```
force_arm:
  1. Read stored reference_id, suid, mode from _force_context
  2. _clear_force_context(force=True)
  3. _dismiss_arming_exception_notification() (if notifications enabled)
  4. set_arm_state(mode, force_arming_remote_id=ref_id, suid=suid)
     → API accepts force params and overrides the open-sensor exceptions

force_arm_cancel:
  1. _clear_force_context(force=True)
  2. _dismiss_arming_exception_notification() (if notifications enabled)
  3. async_write_ha_state()

Mobile notification actions (when built-in handler enabled):
  - SECURITAS_FORCE_ARM_<num> → async_force_arm()
  - SECURITAS_CANCEL_FORCE_ARM_<num> → _clear_force_context() + write state
```

**Force-arm context expiry:** The force-arm context has a 180-second TTL (`_FORCE_ARM_TTL`). When `_clear_force_context()` is called by a coordinator update and the context has aged past the TTL, it is cleared. If the built-in notification handler is enabled, a persistent notification is shown explaining the force-arm option has expired. This prevents stale force-arm contexts from being used after the panel has moved on.

The `_get_exceptions()` API call uses the same polling pattern as arm/disarm — the server returns `WAIT` on the first poll while the panel reports the open sensors, then `OK` with the full exception list on a subsequent poll.

**Why disarm-before-rearm?** The Securitas API treats interior and perimeter as independent axes. Sending `ARMDAY1` while the perimeter is armed leaves the perimeter armed. Transitioning from `Partial+Perimeter` to `Partial` (no perimeter) would silently fail without disarming first. The `CommandResolver` handles this automatically: when the interior mode changes and the current interior is not off, it inserts a disarm step before the arm step.

**WAF rate-limit handling:** When the Securitas Incapsula WAF blocks requests with 403, the integration tracks this via a `waf_blocked` attribute on the alarm entity's `extra_state_attributes`. The custom Lovelace card reads this attribute to show an orange warning banner. A `_set_waf_blocked(blocked)` helper method manages the attribute and auto-dismisses the "Rate limited" persistent notification when the block clears. The attribute is:
- **Set** on 403 errors from status polls, arm/disarm operations, and button presses
- **Cleared** on successful arm/disarm operations and successful status polls
- 403 on arm/disarm shows only the rate-limited notification (the generic "Error arming/disarming" notification is suppressed to avoid duplicates)

**PIN code validation:**
- `_check_code(code)` — Always checked for disarm. Raises `ServiceValidationError` if the code doesn't match the configured PIN. No PIN configured = any code accepted.
- `_check_code_for_arm_if_required(code)` — Only checked for arm operations if `code_arm_required` is True AND a PIN is configured.
- `code_format` — `None` if no PIN configured, `NUMBER` if the PIN is all digits, `TEXT` otherwise.

### Event-driven force-arm architecture

When arming is blocked by open sensors (the API returns a `NON_BLOCKING` error), the alarm panel raises an `ArmingExceptionError` and immediately does three things:

1. Stores force-arm context (`reference_id`, `suid`, `mode`, `exceptions`) with a 180-second TTL (`_FORCE_ARM_TTL`).
2. Sets entity attributes `force_arm_available: true` and `arm_exceptions` (list of open zone names) on `extra_state_attributes`.
3. Fires a `securitas_arming_exception` event on the HA event bus.

**Event payload:**
```python
{
    "entity_id": "alarm_control_panel.securitas_my_home",
    "mode": "armed_away",
    "zones": ["Kitchen window", "Bedroom sensor"],
    "details": {
        "installation": "12345",
        "exceptions": [
            {"alias": "Kitchen window", "zone_id": "3", "device_type": "MAG"},
        ],
    },
}
```

**Built-in handler (enabled by default):**

When the built-in handler is active it:
- Creates a persistent notification listing open zones with instructions for how to force-arm.
- Sends a mobile notification (if `notify_group` is configured) with **Force Arm** / **Cancel** action buttons.
- Listens for `mobile_app_notification_action` events to handle button taps (`SECURITAS_FORCE_ARM_<num>` → `async_force_arm()`, `SECURITAS_CANCEL_FORCE_ARM_<num>` → cancel).
- When force-arm context expires (180 s), updates the notification to inform the user the alarm was not armed.

**Disabling the built-in handler:**

Set **Built-in force-arm notifications** to off in the integration options (Settings → Devices & Services → Securitas → Configure). The `securitas_arming_exception` event still fires, `force_arm_available` / `arm_exceptions` attributes are still set, and the `securitas.force_arm` / `securitas.force_arm_cancel` services still work — only the notifications are suppressed. This lets you replace the built-in notifications with custom automations.

**Custom automation examples:**

#### Auto force-arm when leaving home
```yaml
- id: securitas_auto_force_arm
  alias: "Alarm: auto force-arm when leaving"
  triggers:
    - trigger: event
      event_type: securitas_arming_exception
  conditions:
    - condition: template
      value_template: "{{ trigger.event.data.mode == 'armed_away' }}"
  actions:
    - action: securitas.force_arm
      target:
        entity_id: "{{ trigger.event.data.entity_id }}"
  mode: single
```

#### Notify with open zone details
```yaml
- id: securitas_notify_open_zones
  alias: "Alarm: notify about open zones"
  triggers:
    - trigger: event
      event_type: securitas_arming_exception
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
- id: securitas_smart_force_arm
  alias: "Alarm: smart force-arm by mode"
  triggers:
    - trigger: event
      event_type: securitas_arming_exception
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
            - action: securitas.force_arm
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
- id: securitas_delayed_force_arm
  alias: "Alarm: notify then force-arm after 30s"
  triggers:
    - trigger: event
      event_type: securitas_arming_exception
  actions:
    - action: notify.mobile_app_phone
      data:
        title: "Alarm blocked"
        message: >
          Open zones: {{ trigger.event.data.zones | join(', ') }}.
          Force-arming in 30 seconds...
    - delay: "00:00:30"
    - action: securitas.force_arm
      target:
        entity_id: "{{ trigger.event.data.entity_id }}"
  mode: single
```

#### TTS announcement of open zones
```yaml
- id: securitas_tts_open_zones
  alias: "Alarm: announce open zones on speaker"
  triggers:
    - trigger: event
      event_type: securitas_arming_exception
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

`SecuritasLock` controls DOORLOCK services. Uses `CoordinatorEntity[LockCoordinator]`. Supports multiple locks per installation — each lock is identified by a `device_id` (extracted from the API response, defaults to `"01"`).

**Discovery:** Locks are discovered in the background task (`_async_discover_devices`). When a DOORLOCK service is found, `get_lock_modes()` returns all known lock devices. For each lock, `get_lock_config(device_id)` is called to fetch metadata from the `xSGetSmartlockConfig` API response (location name, serial number, device family). Each lock creates a separate HA device with `via_device` linking to the installation device as parent; name, model, and serial number in the `DeviceInfo` come from the config response. If the config fetch fails, the lock still works but falls back to using the installation alias as the device name with no serial number or model. A deferred retry schedule (60s, 120s, 300s) attempts to fetch config later. One `SecuritasLock` entity is created per device. Unique IDs follow the format `v4_securitas_direct.{number}_lock_{device_id}`.

**Lock states** (string codes from the API):
- `"1"` = unlocked
- `"2"` = locked
- `"3"` = unlocking (transitional)
- `"4"` = locking (transitional)

Lock and unlock operations use `change_lock_mode(lock=True/False)` which follows the same polling pattern as arm/disarm. After the command is acknowledged, the hub invalidates the lock-modes cache so stale data is not returned by subsequent polls. The entity then reads fresh state from the `LockCoordinator` data. While a lock command is in flight, `_operation_in_progress` suppresses coordinator updates to prevent stale API responses from briefly overwriting the transitional state. Periodic background polling via `LockCoordinator` resumes on the scan interval once the command completes.

**Phantom entries:** Some lock models (e.g. SmartLock Tácito) return duplicate `smartlockInfo` entries in the `xSGetLockCurrentMode` response — a phantom entry with `lockStatus: null` and `statusTimestamp: "0"` alongside the real entry (see `docs/graphql_locks/smartlocktacito.json`). `get_lock_current_mode()` skips entries with `lockStatus: null` to prevent phantom lock entities and broken status detection.

**Lock features:** Lock features are fetched via `xSGetSmartlockConfig` and exposed as `extra_state_attributes`, including `holdBackLatchTime` (latch hold-back for door opening). When `holdBackLatchTime > 0`, the entity advertises `LockEntityFeature.OPEN` so users can trigger door unlatching from the UI even when the lock is already unlocked. The `async_open()` method sends the same `change_lock_mode(lock=False)` command — there is no separate API mutation for opening. Note: `is_open` always returns `False` because the API does not distinguish between "unlocked" and "open" (latch held back) — status `"1"` means unlocked. Reporting `is_open=True` would cause HA to grey out the "Open" button indefinitely since the API never transitions away from `"1"` after an unlock.

### Camera (`camera.py`)

Two camera entity types per discovered camera, both using `CoordinatorEntity[CameraCoordinator]`:

- **`SecuritasCamera`** — Shows the last captured thumbnail image. `async_camera_image()` returns the decoded thumbnail from `self.coordinator.data.thumbnails[zone_id]`, or a placeholder JPEG if none exists. On `_handle_coordinator_update()`, rotates the access token so the frontend re-fetches.

- **`SecuritasCameraFull`** — Shows the last full-resolution image. `async_camera_image()` returns `self.coordinator.data.full_images[zone_id]`, or a placeholder JPEG if none exists.

Both entities are grouped under a per-camera child device (via `camera_device_info()`), linked to the installation device as parent via `via_device`.

**Discovery:** Cameras are discovered in the background task. `get_camera_devices()` returns devices of type `"QR"` (Italy and some regions), `"YR"` (PIR cameras, Spain), `"YP"` (perimetral exterior, deviceType 103), or `"QP"` (perimetral exterior, deviceType 107). For each device a `SecuritasCamera` + `SecuritasCameraFull` + `SecuritasCaptureButton` are created using stored `async_add_entities` callbacks. Devices with `isActive: null` are treated as active (only `isActive: False` is filtered out). YR devices have `zoneId: null` in the API; zone_id falls back to the device `id` field.

**Image lifecycle:**
1. On coordinator refresh (every 30 minutes), thumbnails are fetched for all cameras
2. When a thumbnail's `id_signal` changes, `CameraCoordinator` auto-fetches the full-resolution image (skips thumbnails older than 1 hour)
3. When `SecuritasCaptureButton` is pressed, `hub.capture_image()` triggers a new capture via the client, validates/stores the result, pushes the new data into the `CameraCoordinator`, and launches a background task to fetch the full-resolution image

**Signals:**
- `SIGNAL_CAMERA_STATE` — capturing state changed (camera entity writes state without rotating token, so the frontend shows the capturing spinner)

**Extra state attributes:** `image_timestamp` — when the thumbnail was captured; `capturing` (thumbnail entity only) — True while a capture is in progress.

### Buttons (`button.py`)

**`SecuritasRefreshButton`** — Triggers a manual alarm status refresh via `hub.refresh_alarm_status()`, which calls `SecuritasClient.check_alarm()` (authoritative `CheckAlarm` + `CheckAlarmStatus` polling round-trip to the panel, not just a lightweight `xSStatus` read). One per installation.
- On success: updates `protom_response` on the client, clears `refresh_failed` on the alarm entity, triggers a state write
- On timeout: sets `refresh_failed` on the alarm entity (card shows stale data banner)
- On 403: creates "Rate limited" persistent notification and sets `waf_blocked` on the alarm entity

**`SecuritasCaptureButton`** — Requests a new image capture from a Securitas camera. One per camera device, discovered alongside cameras in the background task. Calls `hub.capture_image()` which requests the capture, polls for completion, and stores the resulting image. Grouped under the per-camera child device.

## Three-axis alarm model

Verisure installations have up to three independent alarm axes:

- **Interior** — `OFF` / `DAY` / `NIGHT` / `TOTAL` (`InteriorMode`)
- **Perimeter** — `OFF` / `ON` (`PerimeterMode`)
- **Annex** — `OFF` / `ON` (`AnnexMode`)

`AlarmState` is the joint state across all three axes. The status code returned by the API maps to a specific tuple via `PROTO_TO_STATE`. `CommandResolver` plans transitions between any two `AlarmState` values, emitting one or more API command steps; multi-axis transitions append per-axis steps in a deterministic order.

## Capability detection

`detect_peri()` and `detect_annex()` live in `securitas_direct_new_api/capabilities.py`. Detection runs on every config-entry load — there is no stored `CONF_HAS_PERI`. `detect_peri()` uses four layered signals (JWT capability set, active PERI service, SCH service `PERI` attribute, alarm partition `id="02"`) so it catches both Spanish SDVFAST panels (which advertise `PERI` via JWT cap or service attribute) and Italian SDVECU panels (which expose perimeter only via the alarm-partition list). `detect_annex()` requires both `ARMANNEX` and `DARMANNEX` capabilities.

**Why four signals, not just the JWT cap?** The cap claim appears to track contract/role permissions (what the tenant is licensed for), not what the physical panel is configured to do — and on Italian SDVECU it can be both incomplete and inverted. Two witnesses from the same OWNER login:

- *Perimeter*: an installation with an active `YP` outdoor camera has no `PERI` in the cap, yet the panel accepts perimeter commands. `alarm_partitions[id=02]` and the SCH service's `PERI` attribute reflect physical configuration; the cap does not.
- *Arming modes*: the cap lists `ARMNIGHT` while the panel rejects `ARMNIGHT1` (`"Request ARMNIGHT1 is not valid for Central Unit"`), and omits `ARMDAY` while the panel accepts `ARMDAY1`.

This is why the Interior sub-panel deliberately surfaces all three interior modes regardless of cap content; the resolver's `mark_unsupported` runtime fallback catches genuinely-rejected commands and the user gets a notification naming the failed command. See `tests/fixtures/capability_jwts/italy_owner_partial_only.json` for the regression evidence.

A single debug log line at startup makes misdetection diagnosable: search the log for `capability detection for <installation>` to see the resolved `has_peri`, `has_annex`, and full sorted capability set for each installation.

## Entity layout

Per installation:

- One **combined** alarm panel (always present) — drives all three axes through the user-configurable `map_home`/`map_away`/`map_night`/`map_custom`/`map_vacation` mappings. Backwards compatible with all existing setups.
- Up to three opt-in **sub-panels** (Interior, Perimeter, Annex) — each drives a single axis. Visibility is gated on (a) capability detection, AND (b) the per-axis toggle in the options flow. Toggles for unsupported axes are hidden. The Interior toggle is also hidden unless at least one sibling sub-panel is currently enabled (with no siblings, the combined panel IS the interior panel — a redundant Interior tile would just be noise).

All four entities subscribe to the same `AlarmCoordinator`; commands from any entity update the joint `AlarmState`, and the coordinator update broadcasts new state to every entity. Sub-panel classes (`InteriorSecuritasAlarmPanel`, `PerimeterSecuritasAlarmPanel`, `AnnexSecuritasAlarmPanel`) inherit from `BaseSecuritasAlarmPanel` and override two hooks: `_resolve_target_state(ha_state)` projects an HA state onto the panel's axis (preserving the others), and `_extract_state(joint)` reads only the panel's axis from the joint state.

## Force-arm with sub-panels

The event-driven force-arm architecture generalizes naturally: each panel owns its own force context, fires `securitas_arming_exception` with its own `entity_id`, and the built-in handler filters by entity_id so notifications mention the specific panel that triggered the exception.

## Configuration

### Config flow (`config_flow.py`)

**Initial setup** (`FlowHandler`):
```
Step 1 (user): Country (auto-detected from HA), username, password
  → Login attempt; if Login2FAError → 2FA flow
  → Existing session for same username? Reuse it (avoids duplicate login)
Step 2 (phone_list, if 2FA): Pick which phone to send OTP to
Step 3 (otp_challenge, if 2FA): Enter the SMS code
  → Handles: invalid code, expired code (auto-resends), send failure
  → Translated error messages in 6 languages (en, es, fr, it, pt, pt-BR)
→ finish_setup(): Login, list installations, get_services per installation
Step 4 (select_installation, if multiple): Pick which installation to configure
  → Auto-detection of perimeter support from service attributes (PERI attribute)
  → get_services uses FOREGROUND priority to avoid blocking behind background queue traffic
Step 5 (options): PIN, code-required-to-arm, notify service
  → Title shows installation name ("Options for {installation_name}")
  → Advanced section (collapsed): scan interval, delay between API requests
Step 6 (mappings): Map HA alarm buttons to Securitas states
  Available options change based on perimeter support (STD_OPTIONS vs PERI_OPTIONS)
→ Create config entry per installation
```

Device IDs are generated during initial setup and stored in the config entry for reuse across restarts. The config flow caches authenticated sessions and installations in `hass.data[DOMAIN]` for reuse during `async_setup_entry`, avoiding duplicate login calls.

**Reauth flow** (`async_step_reauth` / `async_step_reauth_confirm`):

Triggered when `async_setup_entry` raises `ConfigEntryAuthFailed` (on `TwoFactorRequiredError` or `AuthenticationError`). Presents a form pre-filled with the existing username. Preserves existing device IDs from the entry being reauthenticated to maintain device identity. On successful login, updates the config entry with new credentials and reloads the integration. If 2FA is required during reauth, the full 2FA flow (phone selection, OTP) runs before completing.

**Options flow** (`SecuritasOptionsFlowHandler`):
```
Step 1 (init): General settings
  - PIN code (optional, for HA-side validation only)
  - Code required to arm (bool)
  - Notify service for arming exceptions
  - Advanced section (collapsed): scan interval, delay between API requests

Step 2 (mappings): Alarm state mappings
  - Map Home button → Securitas state
  - Map Away button → Securitas state
  - Map Night button → Securitas state
  - Map Vacation button → Securitas state
  - Map Custom Bypass button → Securitas state
  Available options change based on perimeter support (STD_OPTIONS vs PERI_OPTIONS)
```

The Advanced section uses HA's `data_entry_flow.section()` with `collapsed: True` to hide rarely-changed timing fields. Section data is flattened back to top-level keys on submission for storage compatibility.

Changing options triggers `async_update_options()`, which merges the new values into the config entry and reloads the integration.

## Key data flows

### User arms the alarm from HA

```
User presses "Arm Away" in HA UI
  → async_alarm_arm_away(code)
    → _check_code_for_arm_if_required(code)  # PIN check if configured
    → _force_state(ARMING)                   # UI shows "Arming..."
    → set_arm_state(ARMED_AWAY)
      → _mode_to_alarm_state(ARMED_AWAY) = AlarmState(TOTAL, ON)  (example with peri)
      → _execute_transition(target=AlarmState(TOTAL, ON))
        → current = AlarmState from _last_proto_code (e.g. "B" → DAY+ON)
        → resolver.resolve(current, target) returns:
          Step 1: disarm [DARM1DARMPERI, DARM1]  (mode change needs disarm first)
          Step 2: arm [ARMINTEXT1, ARM1PERI1, ARM1+PERI1]
        → _execute_step(Step 1):
          → try DARM1DARMPERI → success? done
          → SecuritasDirectError (non-409)? mark_unsupported, try DARM1
        → _execute_step(Step 2):
          → try ARMINTEXT1 → success? done
          → fail? mark_unsupported, try ARM1PERI1
          → fail? mark_unsupported, try ARM1 then PERI1
        → Return OperationStatus with protomResponse="A"
      → update_status_alarm(status)
        → _last_proto_code = "A"
        → _status_map["A"] = ARMED_AWAY
        → _state = ARMED_AWAY                   # UI shows "Armed Away"
```

### Periodic status poll

```
AlarmCoordinator fires every scan_interval seconds
  → _async_update_data()
    → queue.submit(client.get_general_status, installation)
      → client.get_general_status(installation)  # Cloud-only xSStatus, no panel wake
      → Return SStatus
    → Return AlarmStatusData(status, protom_response)
  → _handle_coordinator_update() on SecuritasAlarm
    → Skip if _operation_in_progress
    → _clear_force_context()
    → _update_from_coordinator(data)
      → proto_code from status.status
      → _last_proto_code = proto_code  # Track for resolver's current state
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
python -m pytest tests/ --cov=custom_components/securitas --cov-report=term-missing

# Run a single test file
python -m pytest tests/test_client_auth.py -v

# Lint and type check
ruff check . && ruff format --check .
pyright custom_components/
```

### Test architecture

Tests are organized by module, with a shared `conftest.py` providing fixtures and helpers.

```
tests/
├── conftest.py              Shared fixtures (API client, JWT helpers, response factories)
├── mock_graphql.py          Mock HTTP transport for integration tests (see below)
├── test_alarm_panel.py      Alarm entity: state mapping, arm/disarm, PIN validation, WAF handling
├── test_api_queue.py        ApiQueue priority, throttling, preemption
├── test_architecture.py     Structural tests (imports, file existence, module patterns)
├── test_auth.py             Login, refresh, 2FA, token lifecycle (HA-level)
├── test_binary_sensor.py    WiFi connection binary sensor (coordinator-driven)
├── test_button.py           Refresh button entity, capture button, 403 WAF notification
├── test_camera_api.py       Camera API operations: discover, capture, thumbnails
├── test_camera_platform.py  Camera entity platform setup and image serving
├── test_client_alarm.py     SecuritasClient alarm operations: arm, disarm, check_alarm, polling
├── test_client_auth.py      SecuritasClient auth lifecycle: login, refresh, 2FA, logout
├── test_client_camera.py    SecuritasClient camera operations: capture, thumbnail, full image
├── test_client_lock.py      SecuritasClient lock operations: get_modes, change_mode, config
├── test_client_misc.py      SecuritasClient misc: sentinel, air quality, services, installations
├── test_command_resolver.py CommandResolver state transitions, fallback chains
├── test_config_flow.py      Config flow (setup + 2FA + reauth) and options flow
├── test_constants.py        SENTINEL_SERVICE_NAMES, SecuritasState enum, mapping tables
├── test_coordinators.py     DataUpdateCoordinators: alarm, sentinel, lock, camera
├── test_domains.py          Country-to-URL routing
├── test_exceptions.py       Exception hierarchy, message, log_detail, response_body
├── test_execute_request.py  HttpTransport request execution, retries, error handling
├── test_ha_platforms.py     Platform async_setup_entry for all entity types
├── test_helpers.py          DRY helpers: _poll_operation (409 retry, transient errors)
├── test_http_transport.py   HttpTransport: POST, retries, WAF detection, JSON parsing
├── test_hub.py              SecuritasHub: camera management, lock management, queue
├── test_init.py             Integration setup, session sharing, background discovery
├── test_integration.py      Integration tests using MockGraphQLServer (see below)
├── test_log_filter.py       SensitiveDataFilter: secret redaction, installation masking
├── test_models.py           Pydantic domain models: null coercion, field mapping, enums
├── test_responses.py        Pydantic response envelopes: validation, null safety
└── test_services.py         Service discovery, Sentinel, air quality, smart lock service requests
```

### Key fixtures (`conftest.py`)

**API client fixtures:**
- `api` — A real `SecuritasClient` instance configured with test credentials (`test@example.com`, country `ES`). Uses a `MagicMock` for the `HttpTransport` so no real network calls are made.
- `mock_transport` — An `AsyncMock(spec=HttpTransport)` used by the `api` fixture.
- `mock_execute` — The `mock_transport.execute` AsyncMock. Tests set return values on this to control API responses without going through HTTP.

**JWT helpers:**
- `make_jwt(exp_minutes=15)` — Creates a real HS256 JWT with a configurable expiry. Used to test token parsing, expiry detection, and refresh logic.
- `FAKE_JWT` / `FAKE_REFRESH_TOKEN` — Pre-built JWTs for common test scenarios.

**Response factories:**
- `login_response()`, `refresh_response()`, `validate_device_response()` — Build realistic API response dicts with sensible defaults and overridable fields.

**Integration fixtures:**
- `make_installation(**overrides)` — Factory for `Installation` Pydantic model with defaults (number, panel, address, etc.).
- `make_config_entry_data()` — Builds a complete config entry data dict with all required keys.
- `make_securitas_hub_mock()` — Creates a `MagicMock` mimicking `SecuritasHub` with `AsyncMock` methods for login, validate_device, etc.
- `setup_integration_data(hass, client, devices)` — Populates `hass.data[DOMAIN]` the same way `async_setup_entry` does.

### Testing patterns

**API client tests** (test_client_auth, test_client_alarm, test_client_lock, test_client_camera, test_client_misc): Use the `api` + `mock_execute` fixtures. Tests call the real method (e.g. `api.login()`) with a mocked `transport.execute` return value, then assert on state changes (`api.authentication_token`, `api.authentication_token_exp`, etc.). Golden contract tests assert exact wire-protocol payloads with hardcoded literals to catch unintentional protocol changes.

**HA platform tests** (test_alarm_panel, test_button, test_ha_platforms): Create entity instances directly with `MagicMock` dependencies. Use coordinator mocks to provide data. Example:

```python
alarm = make_alarm(has_peri=True)  # Creates SecuritasAlarm with mocked hub + coordinator
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

**Integration setup tests** (test_init): Patch `SecuritasHub` constructor and `async_forward_entry_setups` to test the full `async_setup_entry` flow without loading real platforms.

**Coordinator tests** (test_coordinators): Test all four coordinators with mocked `SecuritasClient` and `ApiQueue`. Verify data fetching, error handling (SessionExpiredError re-login, WAFBlockedError, general errors), and data preservation across refreshes.

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
with patch("custom_components.securitas.async_get_clientsession", return_value=mock_http):
    result = await async_setup_entry(hass, entry)

assert server.call_count("mkLoginToken") == 1
_, headers, _ = server.get_calls("CheckAlarm")[0]
assert headers["numinst"] == "123456"
```

Key design choices:
- **Queue-based**: each operation has a FIFO queue; `set_default_response()` provides a fallback when the queue is empty
- **Records all calls**: tests can assert on operation name, request headers, and JSON body
- **`queue_standard_setup()`**: convenience helper that queues login → list_installations → services and sets defaults for alarm status calls
- **Response factories**: `graphql_login()`, `graphql_installations()`, `graphql_alarm_status()`, `graphql_arm()`, `graphql_disarm()`, `graphql_sentinel()`, etc. return dicts matching the real Securitas GraphQL schema

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
2. **Pyright** — `pyright custom_components/` for static type checking
3. **Tests** — `pytest` with `--cov-fail-under=90` to enforce minimum coverage

## File reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 848 | Integration setup functions, session sharing, background discovery, coordinator creation, card resource registration |
| `hub.py` | 576 | `SecuritasHub` (central hub wrapping SecuritasClient), `SecuritasDirectDevice` (device registry wrapper) |
| `entity.py` | 96 | `SecuritasEntity` base class, `securitas_device_info()`, `camera_device_info()` |
| `coordinators.py` | 429 | `AlarmCoordinator`, `SentinelCoordinator`, `LockCoordinator`, `CameraCoordinator` |
| `config_flow.py` | 791 | Config flow (setup + 2FA + reauth + installation picker) and options flow (settings + mappings) |
| `alarm_control_panel.py` | 840 | Alarm entity (CoordinatorEntity) with state mapping, arm/disarm, force arm, PIN validation, WAF tracking |
| `sensor.py` | 185 | Sentinel temperature, humidity, air quality sensors (CoordinatorEntity) |
| `binary_sensor.py` | 63 | WiFi connection status diagnostic sensor (CoordinatorEntity, no polling) |
| `lock.py` | 345 | Multi-lock entity (CoordinatorEntity) with lock feature attributes |
| `camera.py` | 166 | Camera entities: SecuritasCamera (thumbnail), SecuritasCameraFull (full image), both CoordinatorEntity |
| `button.py` | 152 | Refresh button with WAF notification, capture button |
| `api_queue.py` | 125 | Priority-based rate-limited API queue (FOREGROUND/BACKGROUND) |
| `const.py` | 58 | Integration constants, signal names, config keys, platform list, card URLs, `SENTINEL_SERVICE_NAMES` |
| `log_filter.py` | 86 | `SensitiveDataFilter` -- log sanitization for secrets |
| `securitas_direct_new_api/client.py` | 1764 | `SecuritasClient` -- auth lifecycle, typed GraphQL execution, all business operations |
| `securitas_direct_new_api/http_transport.py` | 154 | `HttpTransport` -- raw HTTP POST with retries, WAF detection, JSON parsing |
| `securitas_direct_new_api/graphql_queries.py` | 265 | GraphQL query and mutation string constants |
| `securitas_direct_new_api/command_resolver.py` | 182 | `CommandResolver`, `AlarmState`, `CommandStep` -- state transition logic |
| `securitas_direct_new_api/models.py` | 375 | Pydantic domain models (Installation, OperationStatus, SmartLock, CameraDevice, Sentinel, etc.) |
| `securitas_direct_new_api/responses.py` | 517 | Pydantic response envelopes for every GraphQL operation |
| `securitas_direct_new_api/const.py` | 107 | `SecuritasState`, command/protocol mappings, defaults |
| `securitas_direct_new_api/domains.py` | 50 | Country-to-URL routing |
| `securitas_direct_new_api/exceptions.py` | 121 | Exception hierarchy with `http_status`, `log_detail()`, and `ArmingExceptionError` |
| `www/securitas-alarm-card.js` | 1841 | Custom Lovelace alarm card with WAF warning banner, multi-language |
| `www/securitas-camera-card.js` | 376 | Custom Lovelace camera card with capture button, image timestamp overlay, and loading spinner |
