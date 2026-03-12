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
├──────────────────────────────────────────────────────────────────────┤
│  Integration Hub Layer                                               │
│  __init__.py  (setup functions)                                      │
│  hub.py  (SecuritasHub + SecuritasDirectDevice)                      │
│  config_flow.py  (ConfigFlow + OptionsFlow)                          │
│  api_queue.py  (Priority-based rate limiting)                        │
│  log_filter.py  (SensitiveDataFilter)                                │
├──────────────────────────────────────────────────────────────────────┤
│  API Client Layer                                                    │
│  securitas_direct_new_api/                                           │
│  http_client.py  (SecuritasHttpClient — auth, HTTP, polling)         │
│  apimanager.py  (ApiManager — business operations)                   │
│  graphql_queries.py  command_resolver.py  domains.py                 │
│  const.py  dataTypes.py  exceptions.py                               │
└──────────────────────────────────────────────────────────────────────┘
```

Every API call goes through `SecuritasHttpClient._execute_request()` (in `http_client.py`), which sends GraphQL mutations/queries over HTTP to Securitas' cloud. `ApiManager` inherits from `SecuritasHttpClient` and adds business-level operations (login, arm/disarm, status checks, etc.). The integration hub (`SecuritasHub` in `hub.py`) wraps the API client and is shared by all entity platforms. All entity platforms inherit from `SecuritasEntity` (in `entity.py`), which provides common attributes, state management, and notification helpers. Each platform creates entities for the installations discovered at startup.

## API client layer

**Location:** `custom_components/securitas/securitas_direct_new_api/`

### SecuritasHttpClient (`http_client.py`)

The HTTP transport layer. All communication with Securitas happens through GraphQL POST requests to country-specific endpoints (e.g. `customers.securitasdirect.es/owa-api/graphql`). `SecuritasHttpClient` handles authentication tokens, HTTP request execution with retries, GraphQL response extraction, and generic polling. It defines abstract methods (`login()`, `refresh_token()`, `get_all_services()`) that the subclass `ApiManager` implements.

**Request execution:** Every API call goes through `_execute_request()`, which:
1. Builds HTTP headers including `app`, `auth` (JSON with JWT hash, user, country), `X-APOLLO-OPERATION-NAME`, and optionally `numinst`/`panel`/`X-Capabilities` for installation-scoped requests
2. POSTs the GraphQL payload as JSON
3. Parses the response and raises `SecuritasDirectError` on connection or API errors. For HTTP errors (status >= 400), `http_status` is set on the exception. For GraphQL-level errors (HTTP 200 but errors in payload), the `data.status` field from the first error is extracted and set as `http_status` — this is how 409 "server busy" errors are surfaced, since the Securitas API returns them as HTTP 200 with a GraphQL error containing `"data": {"status": 409}`

**DRY helpers:** Internal helpers reduce code duplication:

- `_decode_auth_token(token_str)` — Decodes a JWT (HS256, no signature verification), updates `authentication_token_exp` from the `exp` claim. Returns the decoded claims dict or `None` on failure. Used by `login()`, `refresh_token()`, and `validate_device()`.

- `_extract_response_data(response, field_name)` — Extracts `response["data"][field_name]`, raising `SecuritasDirectError` if the data is missing or `None`. Used by all operation methods to validate responses consistently.

- `_poll_operation(check_fn, *, timeout, continue_on_msg)` — Polls `check_fn()` in a loop until the result is no longer `"WAIT"`. Handles transient errors (connection errors, timeouts, 409 "server busy") by retrying. 403 errors are not retried during polling (only at the `_execute_request` level). Raises `TimeoutError` after `timeout` seconds (default 60). Used by arm, disarm, status check, exception fetch, and lock operations.

- `_ensure_auth(installation)` — Checks both the authentication token and the per-installation capabilities token, refreshing them as needed before executing a request.

- `_execute_graphql(operation, query, variables, installation)` — High-level wrapper that calls `_ensure_auth()` then `_execute_request()`, providing a single entry point for installation-scoped GraphQL operations.

**Response log sanitization:** Before logging API responses at DEBUG level, `_sanitize_response_for_log()` replaces large fields (`hours`, `image`) with placeholder values (`["..."]` for lists, `"..."` for strings). This prevents base64-encoded camera images and hourly sensor arrays from flooding the debug log.

**Device spoofing:** The client identifies itself as a Samsung Galaxy S22 running the Securitas mobile app v10.102.0. Device identity consists of three IDs generated at setup time: `device_id` (FCM-format token), `uuid` (16-char hex), and `id_device_indigitall` (UUID v4).

### ApiManager (`apimanager.py`)

Inherits from `SecuritasHttpClient` and implements all business-level API operations: login, refresh, 2FA validation, arm/disarm, status checks, sentinel data, lock operations, camera operations, and service discovery. All GraphQL query and mutation strings are defined in `graphql_queries.py` and imported here.

**Authentication** is JWT-based with three mechanisms:

1. **Login** (`login()`) — Sends credentials, receives a JWT hash token. The JWT's `exp` claim sets `authentication_token_exp`. If the account needs 2FA, raises `Login2FAError`.

2. **Token refresh** (`refresh_token()`) — Uses a long-lived refresh token to get a new JWT without re-entering credentials. Falls back to full login if refresh fails.

3. **2FA device validation** (`validate_device()`) — For new devices: calls `validate_device()` which returns a list of phone numbers. The user picks one, `send_otp()` sends the SMS, then `validate_device()` is called again with the OTP code to complete registration.

**Token lifecycle:** Before every API operation, `_check_authentication_token()` checks whether the JWT expires within the next minute. If so, it tries `refresh_token()` first, falling back to `login()`. Errors during refresh are caught with specific exception types (`SecuritasDirectError`, `asyncio.TimeoutError`, `ClientConnectorError`) rather than bare `except`. Similarly, `_check_capabilities_token()` checks a per-installation capabilities JWT that's obtained from `get_all_services()`. On `logout()`, all tokens are cleared (`authentication_token`, `refresh_token_value`, `authentication_token_exp`, `login_timestamp`) to prevent stale credentials from being reused.

**Polling pattern:** Arm, disarm, status-check, and exception-fetch operations are asynchronous on the server side. The client sends the initial request, receives a `referenceId`, then polls a status endpoint via `_poll_operation()` (sleeping `delay_check_operation` seconds between attempts) until the response changes from `"WAIT"` to a final state or a wall-clock timeout (default 60 seconds) is reached. Transient errors during polling — connection failures, timeouts, and 409 "server busy" responses — are automatically retried rather than failing the operation. After polling completes, `arm_alarm()` and `disarm_alarm()` check for `res: "ERROR"` with non-`NON_BLOCKING` error types (e.g. `TECHNICAL_ERROR`) and raise `SecuritasDirectError`, enabling the command resolver's fallback chain.

### GraphQL queries (`graphql_queries.py`)

All GraphQL query and mutation strings are extracted into `graphql_queries.py`, keeping `apimanager.py` focused on business logic. This module contains named constants for each operation (e.g. `VALIDATE_DEVICE_MUTATION`, `REFRESH_LOGIN_MUTATION`, `ARM_ALARM_MUTATION`, etc.) that `ApiManager` imports and passes to `_execute_graphql()`.

### Log sanitization (`log_filter.py`)

`SensitiveDataFilter` is a `logging.Filter` attached to all root logger handlers during integration setup. It redacts sensitive values (auth tokens, refresh tokens, usernames, passwords, OTP data) from log messages and arguments before they reach any handler (console, file, remote).

**How it works:**
- `update_secret(key, value)` registers a raw secret value with its redaction label (e.g. `"auth_token"` → `[AUTH_TOKEN]`). Updating a key replaces the old value.
- `add_installation(number)` registers an installation number for partial masking (last 4 digits visible, e.g. `123456` → `***3456`).
- The `filter()` method scans `record.msg` and `record.args` (including nested dicts/lists/tuples), replacing any known secret with its label.
- Registration happens in `ApiManager` via `_register_secret()` — called whenever tokens are obtained or refreshed (login, refresh, validate_device).
- Credentials (username, password) are registered at setup time in `async_setup_entry()`.
- The filter is removed from handlers on `async_unload_entry()`.

**Error notifications:** When operations fail, error notifications shown to the user use only the short error message (`err.args[0]`), never the full error tuple which could contain headers, tokens, or response bodies.

### Debug logging conventions

All debug log messages use context prefixes for easy filtering:

| Prefix | Layer | Example |
|--------|-------|---------|
| `[operation:alias]` | HTTP (`http_client.py`) | Request variables and response in a single line |
| `[auth]` | HTTP (`http_client.py`) | Token refresh, re-authentication, capabilities checks |
| `[queue]` | Queue (`api_queue.py`) | Throttle delays and priority preemption |
| `[setup]` | Setup (`__init__.py`) | Card resource registration, entry migration |
| `[entity_id]` | Entity platforms | Per-entity state changes and operations |

### Country routing (`domains.py`)

`ApiDomains` maps country codes to API URLs and language codes. Supported countries: ES, FR, GB, IE, IT, BR, CL, AR, PT. Countries without an explicit entry fall back to a URL template using the country code as a subdomain.

### Alarm states and commands (`const.py`)

Securitas alarms have two independent axes: **interior mode** (disarmed, partial day, partial night, total) and **perimeter** (on or off). The combination produces 10 states defined in `SecuritasState`:

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

Two mapping tables connect these:
- `STATE_TO_COMMAND` — `SecuritasState` to API command string (e.g. `TOTAL` -> `"ARM1"`)
- `PROTO_TO_STATE` — single-letter protocol response code to `SecuritasState` (e.g. `"T"` -> `TOTAL`)

#### Command resolver

**Location:** `securitas_direct_new_api/command_resolver.py`

The `CommandResolver` class models the alarm as two independent axes — `InteriorMode` (off, day, night, total) and `PerimeterMode` (off, on) — combined into an `AlarmState`. It replaces the old `_use_multi_step` flag, `_send_arm_command()` / `_send_disarm_command()` methods, `COMPOUND_COMMAND_STEPS` constant, and `PERI_ARMED_PROTO_CODES` set.

**How it works:**

1. `resolve(current, target)` computes the state transition and returns an ordered list of `CommandStep` objects. Each step contains a list of command alternatives to try in order.

2. Combined commands are tried first (e.g. `ARMINTEXT1`, `ARM1PERI1`), with multi-step fallbacks using `+` separator (e.g. `ARM1+PERI1` means send `ARM1` then `PERI1` as separate sequential API calls).

3. For Total+Perimeter arm, `ARMINTEXT1` is ordered before `ARM1PERI1` — `ARMINTEXT1` arms interior+perimeter in one step without triggering the siren delay, which is important for Spanish WAF (Wife Acceptance Factor) safety.

4. **Runtime discovery of unsupported commands:** When a command fails with a non-409 `SecuritasDirectError`, `_execute_step()` calls `resolver.mark_unsupported(command)`, and the resolver skips it in all future resolutions. This is per-command granularity (not a global flag), so a disarm-specific failure (e.g. `DARM1DARMPERI`) does not disable unrelated compound arm commands. The unsupported set is in-memory and resets on HA restart.

5. **Disarm uses current state:** The resolver determines the disarm command from the current `AlarmState` (derived from `_last_proto_code`), not from configuration flags. If both interior and perimeter are armed, it tries `DARM1DARMPERI` first, falling back to `DARM1`. If only perimeter is armed, it tries `DARMPERI` first, falling back to `DARM1`.

6. **409 errors** (server busy) are re-raised immediately and do not trigger the fallback chain.

Home Assistant has five alarm buttons (Home, Away, Night, Vacation, Custom Bypass). The user maps each button to a Securitas state through the options flow. Standard installations get defaults without perimeter; perimeter installations get defaults that use perimeter states for Away (Total + Perimeter) and Custom (Perimeter Only). Both standard and perimeter installations default Night to Partial Night. Perimeter variants (e.g. Partial Night + Perimeter) are available in the options for perimeter installations and can be assigned to any button. The `Vacation` and `Custom Bypass` buttons are hidden unless a mapping is configured for them.

If the alarm is put into a state that is not mapped to any HA button (e.g. the perimeter is armed via a physical panel but perimeter support is not enabled in the integration), the entity reports `ARMED_CUSTOM_BYPASS` and logs the unmapped proto code at `info` level. This is not an error — it simply means the alarm is in a valid Securitas state that the user has not assigned to an HA button. To resolve it, enable perimeter support or map the relevant state in the integration options.

### Data types (`dataTypes.py`)

Dataclasses for API responses. The most important ones:

- `Installation` — Represents a physical Securitas installation (number, alias, panel type, address, capabilities JWT, `alarm_partitions` list from services response)
- `CheckAlarmStatus` — Alarm status response with `protomResponse` (the single-letter state code) and `protomResponseData`
- `ArmStatus` / `DisarmStatus` — Results of arm/disarm operations
- `Service` — A discovered service (e.g. "CONFORT" for Sentinel sensors, "DOORLOCK" for smart locks)
- `Sentinel` — Temperature, humidity, and air quality from a Sentinel device
- `SStatus` — General status with `wifi_connected` boolean (diagnostic)
- `OtpPhone` — Phone number option during 2FA setup
- `SmartLockMode` — Lock mode with `deviceId` field for multi-lock support
- `CameraDevice` — Camera device (id, code, zone_id, name, serial_number)
- `ThumbnailResponse` — Thumbnail data (id_signal, device_code, device_alias, timestamp, signal_type, image as base64)
- `DanalockConfig` — Full Danalock configuration (battery threshold, auto-lock time, arm-lock policies, latch hold-back)
- `DanalockFeatures` — Nested features (holdBackLatchTime, calibrationType, autolock)
- `DanalockAutolock` — Autolock settings (active, timeout)

### Exceptions (`exceptions.py`)

```
SecuritasDirectError              Base class (http_status attribute)
├── APIError                      API failures
├── ArmingExceptionError          Open sensors blocking arm (carries force-arm context)
└── LoginError                    Login failures
    ├── AuthError                 Access denied
    ├── TokenRefreshError         Token refresh issues
    └── Login2FAError             2FA required
```

`SecuritasDirectError` is thrown with up to 4 args: `(message, response_dict, headers, content)` and an optional `http_status` keyword argument. The `http_status` attribute carries the HTTP status code (for HTTP errors) or the GraphQL error `data.status` value (e.g. 409 for "server busy"). This allows callers to distinguish transient concurrency errors from permanent failures. The `login()` method distinguishes between errors that have response data (wrapped in `LoginError` or `Login2FAError`) and connection errors (re-raised as `SecuritasDirectError` to trigger HA's `ConfigEntryNotReady` retry).

`ArmingExceptionError` is raised when arming fails due to non-blocking exceptions (e.g. open window/door). It carries `reference_id`, `suid`, and the list of exceptions, providing the context needed to retry with `forceArmingRemoteId`.

## Integration hub layer

**Location:** `custom_components/securitas/hub.py` (SecuritasHub, SecuritasDirectDevice) and `custom_components/securitas/__init__.py` (setup functions only)

### SecuritasHub

The central coordinator. It owns an `ApiManager` session and is shared by all entity platforms via `hass.data[DOMAIN][SecuritasHub.__name__]`.

**Key responsibilities:**
- **Login delegation** — Passes credentials through to `ApiManager`
- **Service discovery** — `get_services()` calls `ApiManager.get_all_services()` and caches the results
- **Status polling** — `update_overview()` checks the alarm status using `check_general_status()` which returns the last known cloud status without waking the panel
- **API call cooldown** — All API calls are submitted via `ApiQueue`, which enforces a minimum gap between calls to avoid triggering the Incapsula WAF rate limiter. See [ApiQueue](#apiqueue) below.
- **Camera management** — `get_camera_devices()` discovers cameras, `capture_image()` requests new captures and polls for completion, `fetch_latest_thumbnail()` lazy-fetches on first frontend request. Cached images stored per installation+zone with `get_camera_image()` / `get_camera_timestamp()`.
- **Lock management** — `get_lock_modes()` discovers locks (cached with TTL), `change_lock_mode()` performs lock/unlock via queue, `get_danalock_config()` fetches Danalock-specific settings.
- **Caching** — `_cached_api_call()` provides a generic caching wrapper with a double-check pattern (cache checked before queue submit + after serialization) to prevent duplicate API calls when multiple entities request the same data.
- **Session sharing** — Multiple config entries for the same username share a single `SecuritasHub` instance via reference counting in `hass.data[DOMAIN]["sessions"]`. This prevents duplicate logins and reduces WAF pressure.
- **403 re-raise** — `update_overview()` re-raises 403 `SecuritasDirectError` so the calling alarm entity can set `waf_blocked`. Non-403 errors are swallowed and return an empty `CheckAlarmStatus`.

### ApiQueue (`api_queue.py`)

Serializes API calls with priority-based rate limiting to avoid WAF blocks. One queue is shared per API domain (country).

**Design:**
- Two priority levels: `FOREGROUND` (arm/disarm, user actions, setup) and `BACKGROUND` (polling)
- Both share the same minimum interval (`delay_check_operation`, default 2 seconds)
- Foreground requests preempt queued background work — background waits while any foreground requests are pending
- In-flight API calls are not cancelled; preemption happens between calls

**Algorithm:**
1. `submit(coro_fn, *args, priority, label)` accepts an async callable + args. The optional `label` overrides the function name in throttle log messages (used by `_cached_api_call` to log the real API method name + cache key instead of the inner wrapper name).
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
   └── Missing? → re-run import flow to generate them
4. Create SecuritasHub with aiohttp session
5. Login
   ├── Login2FAError → show persistent notification, start import flow
   ├── LoginError → show persistent notification, start import flow
   └── SecuritasDirectError → raise ConfigEntryNotReady (HA retries)
6. List installations
7. For each installation: get_services() → create SecuritasDirectDevice
8. Store devices in hass.data[DOMAIN][entry.entry_id]
9. Forward to platforms: alarm_control_panel, binary_sensor, sensor, button, camera, lock
   └── Each platform stores its async_add_entities callback in entry_data
       and creates only entities it can build without API calls
10. Launch background task (_async_discover_devices) to:
    ├── Discover camera devices → add Camera + CaptureButton entities
    └── Discover lock devices → add Lock entities
```

**What each platform does at setup (synchronous):**

| Platform | Creates | API calls |
|----------|---------|-----------|
| alarm_control_panel | SecuritasAlarm entities | None (starts as "unknown") |
| binary_sensor | WifiConnectedSensor entities | None (updated via dispatcher) |
| button | SecuritasRefreshButton entities | None (stores callback for capture buttons) |
| camera | Nothing | None (stores callback) |
| sensor | Sentinel sensors | None (uses cached services) |
| lock | Nothing | None (stores callback) |

**Background discovery (`_async_discover_devices`):**

After all platforms are registered, a single background task discovers cameras and locks via API calls, then adds entities using the stored `async_add_entities` callbacks. This runs concurrently with HA startup, so the integration is immediately available (alarm panel, refresh buttons, sensors) while cameras and locks appear shortly after.

### Options update (`async_update_options`)

When the user changes options (PIN code, scan interval, alarm mappings, etc.), the listener merges the new options into the config entry data and reloads the integration. This triggers a full teardown and re-setup.

### SecuritasDirectDevice (`hub.py`)

A thin wrapper around `Installation` that provides `device_info` for the HA device registry. Each physical installation becomes one device.

### SecuritasEntity (`entity.py`)

Base class for all Securitas Direct entities. Inherits from `homeassistant.helpers.entity.Entity` and provides:

- **Common attributes** — `_installation`, `_client` (the `SecuritasHub`), `_state`, `_last_state`, and `device_info` (via the `securitas_device_info()` helper that groups entities under the installation device).
- **State management** — `_force_state(state)` sets a transitional state and schedules an HA state write. Used by entities during arm/disarm/lock operations to show "Arming...", "Locking...", etc.
- **Error notifications** — `_notify_error(title, message)` creates a persistent notification with an auto-generated ID scoped to the installation number.

All entity platforms (`alarm_control_panel`, `sensor`, `binary_sensor`, `lock`, `button`) inherit from `SecuritasEntity`. The `camera` platform uses only the `securitas_device_info()` helper.

The module also provides `schedule_initial_updates(hass, entities, delay)` which schedules a deferred state refresh for entities after setup, avoiding API calls during platform initialization.

## Polling intervals

Home Assistant has a built-in polling mechanism: if a platform module defines a module-level `SCAN_INTERVAL` constant and an entity's `should_poll` property returns `True` (the default), HA calls `async_update()` on each entity at that interval.

The integration has a **user-configurable scan interval** (`scan_interval` in options, default `DEFAULT_SCAN_INTERVAL = 120` seconds). Each platform handles polling differently:

| Platform | Module-level `SCAN_INTERVAL` | Actually used? | How polling works |
|----------|------------------------------|----------------|-------------------|
| `alarm_control_panel.py` | `timedelta(minutes=20)` | No (dead code) | Uses `async_track_time_interval` with the user's configured `scan_interval`. The 20-minute constant is a safety fallback if HA's default polling somehow fires. |
| `lock.py` | `timedelta(minutes=20)` | No (dead code) | Same as alarm — uses `async_track_time_interval` with configured interval. |
| `sensor.py` | `timedelta(minutes=30)` | **Yes** | Relies on HA's built-in polling. Does not read the user's configured interval. 30 minutes is appropriate for environmental data (temperature, humidity, air quality) which changes slowly. |

The alarm and lock platforms manage their own timers because they need per-entity control (e.g. skipping polls during `_operation_in_progress`, supporting `scan_interval=0` to disable polling). The sensor platform uses the simpler HA-native approach since sensor data changes slowly and doesn't need the same level of control.

## Entity platforms

### Alarm control panel (`alarm_control_panel.py`)

The main entity. One `SecuritasAlarm` per installation. The entity starts with `_state = None` (renders as "unknown" in HA) until the first successful API poll populates the real alarm state. This avoids showing a false "disarmed" state at startup.

**State mapping system:** During `__init__`, two dictionaries are built from the user's configuration:

- `_command_map`: HA state -> API command string. E.g. `ARMED_AWAY` -> `"ARM1"`. Only includes states the user has mapped (not `NOT_USED`).
- `_status_map`: Protocol response code -> HA state. E.g. `"T"` -> `ARMED_AWAY`. Built by reverse-looking up `PROTO_TO_STATE` for each configured Securitas state.

**`supported_features`** is derived from `_command_map` — only buttons with a configured mapping are exposed.

**Arm flow** (`async_alarm_arm_away` and friends):
```
1. _check_code_for_arm_if_required(code) — if PIN required for arming
2. __force_state(ARMING) — set transitional state, save previous in _last_status
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
      - If no steps succeeded, revert to _last_status
   d. update_status_alarm() with the final response
```

**Disarm flow** (`async_alarm_disarm`):
```
1. _check_code(code) — raises ServiceValidationError if wrong
2. __force_state(DISARMING)
3. _execute_transition(AlarmState(OFF, OFF)):
   a. resolver.resolve(current, disarmed) returns CommandStep with ordered
      alternatives based on current state:
      - Both armed? → [DARM1DARMPERI, DARM1]
      - Only perimeter? → [DARMPERI, DARM1]
      - Only interior? → [DARM1]
   b. _execute_step() tries alternatives, marks failed ones unsupported
   c. 409 errors re-raised (server busy, not unsupported)
   d. Error on all attempts? → _notify_error() with short message, restore
      _last_status
4. update_status_alarm() with the response
```

**Arming exception flow** (open sensors blocking arm):
```
1. set_arm_state() catches ArmingExceptionError from _send_arm_command()
2. _set_force_context(exc, mode) — stores reference_id, suid, mode, exceptions
3. _notify_arm_exceptions(exc):
   a. Persistent notification: lists each open sensor by name (from _get_exceptions
      polling), explains how to force-arm
   b. Mobile notification (if notify_group configured): short message with
      Force Arm / Cancel action buttons
4. State reverts to _last_status
```

**Force arm flow** (`securitas.force_arm` / `securitas.force_arm_cancel` services):
```
force_arm:
  1. Read stored reference_id, suid, mode from _force_context
  2. _clear_force_context(force=True)
  3. _dismiss_arming_exception_notification()
  4. set_arm_state(mode, force_arming_remote_id=ref_id, suid=suid)
     → API accepts force params and overrides the open-sensor exceptions

force_arm_cancel:
  1. _clear_force_context(force=True)
  2. _dismiss_arming_exception_notification()
  3. async_write_ha_state()

Mobile notification actions:
  - SECURITAS_FORCE_ARM_<num> → async_force_arm()
  - SECURITAS_CANCEL_FORCE_ARM_<num> → _clear_force_context() + write state
```

The `_get_exceptions()` API call uses the same polling pattern as arm/disarm — the server returns `WAIT` on the first poll while the panel reports the open sensors, then `OK` with the full exception list on a subsequent poll.

**Why disarm-before-rearm?** The Securitas API treats interior and perimeter as independent axes. Sending `ARMDAY1` while the perimeter is armed leaves the perimeter armed. Transitioning from `Partial+Perimeter` to `Partial` (no perimeter) would silently fail without disarming first. The `CommandResolver` handles this automatically: when the interior mode changes and the current interior is not off, it inserts a disarm step before the arm step.

**Status updates:** `async_track_time_interval` fires `async_update_status()` every `scan_interval` seconds (default 120). This calls `SecuritasHub.update_overview()` and then `update_status_alarm()` to map the response to an HA state. Polls are skipped when `_operation_in_progress` is True (during arm/disarm) to prevent concurrent API calls.

**WAF rate-limit handling:** When the Securitas Incapsula WAF blocks requests with 403, the integration tracks this via a `waf_blocked` attribute on the alarm entity's `extra_state_attributes`. The custom Lovelace card reads this attribute to show an orange warning banner. A `_set_waf_blocked(blocked)` helper method manages the attribute and auto-dismisses the "Rate limited" persistent notification when the block clears. The attribute is:
- **Set** on 403 errors from status polls, arm/disarm operations, and button presses
- **Cleared** on successful arm/disarm operations and successful status polls
- 403 on arm/disarm shows only the rate-limited notification (the generic "Error arming/disarming" notification is suppressed to avoid duplicates)

**PIN code validation:**
- `_check_code(code)` — Always checked for disarm. Raises `ServiceValidationError` if the code doesn't match the configured PIN. No PIN configured = any code accepted.
- `_check_code_for_arm_if_required(code)` — Only checked for arm operations if `code_arm_required` is True AND a PIN is configured.
- `code_format` — `None` if no PIN configured, `NUMBER` if the PIN is all digits, `TEXT` otherwise.

### Sensors (`sensor.py`)

Three sensor types:

- **SentinelTemperature** — Temperature in Celsius
- **SentinelHumidity** — Humidity as percentage
- **SentinelAirQuality** — Air quality index with message (e.g. "Good")

Sentinel sensors are discovered during platform setup by scanning services for ones matching the Sentinel name (language-dependent: "CONFORT" in Spanish, "COMFORTO" in Portuguese). No API calls are made during setup — entities start with unknown state. Data is populated by `async_update()` using HA's built-in polling at a 30-minute interval (see [Polling intervals](#polling-intervals)).

### Binary sensors (`binary_sensor.py`)

- **WifiConnectedSensor** — Diagnostic binary sensor showing the panel's WiFi connection status from `SStatus.wifi_connected`. One per installation. Does not poll — instead listens for `SIGNAL_XSSTATUS_UPDATE` dispatcher signals fired by the alarm entity's periodic status checks. Uses `BinarySensorDeviceClass.CONNECTIVITY` and `EntityCategory.DIAGNOSTIC`.

### Smart lock (`lock.py`)

`SecuritasLock` controls DOORLOCK services. Supports multiple locks per installation — each lock is identified by a `device_id` (extracted from the API response, defaults to `"01"`).

**Discovery:** Locks are discovered in the background task (`_async_discover_devices`). When a DOORLOCK service is found, `get_lock_modes()` returns all known lock devices. For each lock, `get_smart_lock_config(device_id)` is called to fetch metadata from the `xSGetSmartlockConfig` API response (location name, serial number, device family). Each lock creates a separate HA device with `via_device` linking to the installation device as parent; name, model, and serial number in the `DeviceInfo` come from the config response. If the config fetch fails, the lock still works but falls back to using the installation alias as the device name with no serial number or model. One `SecuritasLock` entity is created per device. Unique IDs follow the format `v4_securitas_direct.{number}_lock_{device_id}`.

**Lock states** (string codes from the API):
- `"1"` = open/unlocked
- `"2"` = locked
- `"3"` = opening (transitional)
- `"4"` = locking (transitional)

Lock and unlock operations use `change_lock_mode(lock=True/False)` which follows the same polling pattern as arm/disarm. Status is polled via `get_lock_current_mode()` on the scan interval.

**Danalock configuration:** On first update, each lock lazily fetches its `DanalockConfig` via `get_danalock_config()`. This exposes battery threshold, arm-lock policies (lock before full/partial arm, unlock after disarm), auto-lock timeout, and `holdBackLatchTime` (latch hold-back for door opening) as `extra_state_attributes`. Config fetch is optional — errors are tolerated and logged. When `holdBackLatchTime > 0`, the entity advertises `LockEntityFeature.OPEN` so users can trigger door unlatching from the UI even when the lock is already unlocked. The `async_open()` method sends the same `change_lock_mode(lock=False)` command — there is no separate API mutation for opening.

### Camera (`camera.py`)

`SecuritasCamera` shows the last captured image from a Securitas camera device. One entity per discovered camera, grouped under the installation device.

**Discovery:** Cameras are discovered in the background task. `get_camera_devices()` returns devices of type `"QR"` (Italy and some regions) or `"YR"` (PIR cameras, Spain). For each device a `SecuritasCamera` + `SecuritasCaptureButton` are created using stored `async_add_entities` callbacks. Devices with `isActive: null` are treated as active (only `isActive: False` is filtered out). YR devices have `zoneId: null` in the API; zone_id falls back to the device `id` field.

**Image lifecycle:**
1. On first frontend request, `async_camera_image()` lazy-fetches the latest thumbnail via `fetch_latest_thumbnail()`
2. Subsequent requests return the cached image (or a placeholder JPG if none exists)
3. When `SecuritasCaptureButton` is pressed, `capture_image()`:
   - Sets the `capturing` state and dispatches `SIGNAL_CAMERA_STATE` so the frontend shows a spinner
   - Fetches the current baseline thumbnail to detect missed intermediate images
   - If the baseline image differs from the locally stored image, stores and displays it immediately (before the new capture arrives), then fires `SIGNAL_CAMERA_UPDATE`
   - Requests a new capture via `request_images`, polls for completion, then polls the thumbnail until `idSignal` changes
   - Fires `SIGNAL_CAMERA_UPDATE` on success (rotates access token so frontend re-fetches), or `SIGNAL_CAMERA_STATE` on failure (clears spinner without rotating token)

**Signals:**
- `SIGNAL_CAMERA_UPDATE` — new image available; camera entity rotates its access token so the frontend re-fetches
- `SIGNAL_CAMERA_STATE` — capturing state changed (no image update); entity writes state without rotating token

**Extra state attributes:** `image_timestamp` — when the thumbnail was captured; `capturing` — True while a capture is in progress.

### Buttons (`button.py`)

**`SecuritasRefreshButton`** — Triggers a manual alarm status refresh via `check_alarm()` + `check_alarm_status()` (using the shared `_poll_operation` polling loop). One per installation.
- On success: clears `refresh_failed` on the alarm entity
- On timeout: sets `refresh_failed` on the alarm entity (card shows stale data banner)
- On 403: creates "Rate limited" persistent notification and sets `waf_blocked` on the alarm entity
- The alarm entity is looked up via `hass.data[DOMAIN]["alarm_entities"]`

**`SecuritasCaptureButton`** — Requests a new image capture from a Securitas camera. One per camera device, discovered alongside cameras in the background task. Calls `hub.capture_image()` which requests the capture, polls for completion, and stores the resulting image.

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
    → __force_state(ARMING)                  # UI shows "Arming..."
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
        → Return ArmStatus with protomResponse="A"
      → update_status_alarm(status)
        → _last_proto_code = "A"
        → _status_map["A"] = ARMED_AWAY
        → _state = ARMED_AWAY                   # UI shows "Armed Away"
```

### Periodic status poll

```
async_track_time_interval fires every scan_interval seconds
  → async_update_status()
    → client.update_overview(installation)
      → session.check_general_status(installation)  # Cloud-only xSStatus, no panel wake
      → Return CheckAlarmStatus from SStatus
    → update_status_alarm(status)
      → _last_proto_code = status.protomResponse  # Track for resolver's current state
      → protomResponse "D" → DISARMED
      → protomResponse in _status_map → mapped HA state
      → protomResponse unknown → ARMED_CUSTOM_BYPASS + notification
    → async_write_ha_state()
```

Periodic polling always uses the lightweight `xSStatus` (general status) endpoint for efficiency. The more expensive `CheckAlarm` path (protom round-trip to the panel) is used only for arm/disarm operations and the manual refresh button.

## Testing

### Overview

The test suite has **824 tests** achieving **92% overall coverage**. Tests run on every PR via GitHub Actions with three parallel checks: Ruff lint/format, Pyright type checking, and pytest with a 90% coverage floor.

```bash
# Run the full suite
python -m pytest tests/ -v --tb=short

# Run with coverage
python -m pytest tests/ --cov=custom_components/securitas --cov-report=term-missing

# Run a single test file
python -m pytest tests/test_auth.py -v

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
├── test_auth.py             Login, refresh, 2FA, token lifecycle
├── test_button.py           Refresh button entity, 403 WAF notification + alarm entity sync
├── test_camera_api.py       Camera API operations: discover, capture, thumbnails
├── test_camera_platform.py  Camera entity platform setup and image serving
├── test_config_flow.py      Config flow (setup + 2FA) and options flow
├── test_command_resolver.py  CommandResolver state transitions, fallback chains
├── test_constants.py        SecuritasState enum, mapping tables
├── test_domains.py          Country-to-URL routing
├── test_execute_request.py  HTTP request execution, headers, error handling, http_status
├── test_ha_platforms.py     Platform async_setup_entry for all entity types
├── test_helpers.py          DRY helpers: _poll_operation (409 retry, transient errors)
├── test_init.py             Integration setup, SecuritasHub, device info, options, API cooldown
├── test_integration.py      Integration tests using MockGraphQLServer (see below)
├── test_log_filter.py       SensitiveDataFilter: secret redaction, installation masking
├── test_operations.py       Arm, disarm, check alarm, polling
├── test_services.py         Service discovery, Sentinel, air quality, smart lock
└── test_smart_lock.py       Lock mode changes, status polling
```

### Key fixtures (`conftest.py`)

**API client fixtures:**
- `api` — A real `ApiManager` instance configured with test credentials (`test@example.com`, country `ES`). Uses a `MagicMock` for the HTTP client so no real network calls are made.
- `mock_execute` — Patches `ApiManager._execute_request` so tests can set return values without going through HTTP. Most auth and operation tests use this.
- `mock_post` / `mock_response` — Lower-level mocks for the `aiohttp` POST context manager, used by `test_execute_request.py` to test header construction and error handling.

**JWT helpers:**
- `make_jwt(exp_minutes=15)` — Creates a real HS256 JWT with a configurable expiry. Used to test token parsing, expiry detection, and refresh logic.
- `FAKE_JWT` / `FAKE_REFRESH_TOKEN` — Pre-built JWTs for common test scenarios.

**Response factories:**
- `login_response()`, `refresh_response()`, `validate_device_response()` — Build realistic API response dicts with sensible defaults and overridable fields.

**Integration fixtures:**
- `make_installation(**overrides)` — Factory for `Installation` dataclass with defaults (number, panel, address, etc.).
- `make_config_entry_data()` — Builds a complete config entry data dict with all required keys.
- `make_securitas_hub_mock()` — Creates a `MagicMock` mimicking `SecuritasHub` with `AsyncMock` methods for login, validate_device, etc.
- `setup_integration_data(hass, client, devices)` — Populates `hass.data[DOMAIN]` the same way `async_setup_entry` does.

### Testing patterns

**API client tests** (test_auth, test_operations, test_services, test_execute_request): Use the `api` + `mock_execute` fixtures. Tests call the real method (e.g. `api.login()`) with a mocked `_execute_request` return value, then assert on state changes (`api.authentication_token`, `api.authentication_token_exp`, etc.).

**HA platform tests** (test_alarm_panel, test_button, test_ha_platforms): Create entity instances directly with `MagicMock` dependencies. Patch `async_track_time_interval` and HA state-writing methods to avoid needing a running HA event loop. Example:

```python
alarm = make_alarm(has_peri=True)  # Creates SecuritasAlarm with mocked hub
alarm.client.session.arm_alarm = AsyncMock(return_value=arm_status)
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

### Integration tests (`test_integration.py`, `mock_graphql.py`)

Integration tests exercise the full stack from HA config-entry setup through to API behaviour, using a `MockGraphQLServer` that intercepts `aiohttp` POST calls at the HTTP transport level. Unlike unit tests, these let `_execute_request()` run fully — header construction, JSON parsing, and error handling are all exercised.

**How the mock server works:**

`MockGraphQLServer` (in `tests/mock_graphql.py`) replaces `http_client.post` on the `SecuritasHttpClient` transport layer. Each call reads the `X-APOLLO-OPERATION-NAME` header, records the call, and returns the next queued response for that operation:

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
- Error handling: `LoginError`, `Login2FAError`, connection errors → correct return values
- Scoped request headers: `numinst`, `panel`, `X-Capabilities` present on installation-scoped calls
- Operation routing: `X-APOLLO-OPERATION-NAME` header matches the operation name for every call
- State from real API responses: `CheckAlarmStatus` proto codes map to correct HA states
- Polling behaviour: `ArmStatus`/`DisarmStatus` WAIT responses are retried
- Sensor data: `get_sentinel_data()` and `get_air_quality_data()` parse real response shapes
- Unload: `async_unload_entry` cleans up `hass.data[DOMAIN]` correctly

### Coverage by module

| Module | Coverage | Key gaps |
|--------|----------|----------|
| `__init__.py` | 86% | Platform setup, session sharing, lock/camera discovery |
| `hub.py` | 89% | Some camera/lock edge paths |
| `entity.py` | 100% | — |
| `alarm_control_panel.py` | 96% | `async_setup_entry`, some HA callbacks |
| `api_queue.py` | 100% | — |
| `binary_sensor.py` | 100% | — |
| `button.py` | 93% | Capture button edge cases |
| `camera.py` | 83% | Signal handlers, extra state attributes |
| `config_flow.py` | 88% | Some flow branches |
| `http_client.py` | 97% | Rare error paths |
| `apimanager.py` | 93% | Rare error paths, some polling branches |
| `graphql_queries.py` | 100% | — |
| `lock.py` | 95% | Timer setup, some error paths |
| `sensor.py` | 91% | `async_setup_entry`, sensor discovery |
| `command_resolver.py` | 92% | Rare fallback paths |
| `log_filter.py` | 88% | Nested arg scanning |
| `const.py` | 100% | Includes `SentinelName` (moved from `constants.py`) |
| `dataTypes.py` | 100% | — |
| `domains.py` | 100% | — |
| `exceptions.py` | 100% | — |

### CI workflow (`.github/workflows/tests.yaml`)

Three parallel jobs run on every PR and push to main:

1. **Ruff lint & format** — `ruff check .` and `ruff format --check .`
2. **Pyright** — `pyright custom_components/` for static type checking
3. **Tests** — `pytest` with `--cov-fail-under=90` to enforce minimum coverage

## File reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 620 | Integration setup functions, session sharing, background discovery, card resource registration |
| `hub.py` | 612 | `SecuritasHub` (central coordinator), `SecuritasDirectDevice` (device registry wrapper) |
| `entity.py` | 95 | `SecuritasEntity` base class, `securitas_device_info()`, `schedule_initial_updates()` |
| `config_flow.py` | 667 | Config flow (setup + 2FA + installation picker) and options flow (settings + mappings) |
| `alarm_control_panel.py` | 794 | Alarm entity with state mapping, arm/disarm, force arm, PIN validation, WAF tracking |
| `sensor.py` | 247 | Sentinel temperature, humidity, air quality sensors |
| `binary_sensor.py` | 64 | WiFi connection status diagnostic sensor (dispatcher-based, no polling) |
| `lock.py` | 246 | Multi-lock entity with Danalock config attributes |
| `camera.py` | 98 | Camera entity with lazy thumbnail fetching |
| `button.py` | 150 | Refresh button with WAF notification, capture button |
| `api_queue.py` | 104 | Priority-based rate-limited API queue (FOREGROUND/BACKGROUND) |
| `const.py` | 66 | Integration constants, signal names, config keys, platform list, card URLs, SentinelName language mapping |
| `log_filter.py` | 86 | `SensitiveDataFilter` — log sanitization for secrets |
| `securitas_direct_new_api/http_client.py` | 513 | `SecuritasHttpClient` — HTTP transport, auth tokens, request execution, polling |
| `securitas_direct_new_api/apimanager.py` | 1292 | `ApiManager` — business operations (inherits SecuritasHttpClient) |
| `securitas_direct_new_api/graphql_queries.py` | 256 | GraphQL query and mutation string constants |
| `securitas_direct_new_api/command_resolver.py` | 207 | `CommandResolver`, `AlarmState`, `CommandStep` — state transition logic |
| `securitas_direct_new_api/const.py` | 107 | `SecuritasState`, command/protocol mappings, defaults |
| `securitas_direct_new_api/dataTypes.py` | 211 | Response dataclasses (including Danalock, Camera, SStatus) |
| `securitas_direct_new_api/domains.py` | 49 | Country-to-URL routing |
| `securitas_direct_new_api/exceptions.py` | 84 | Exception hierarchy with `http_status` and `ArmingExceptionError` |
| `www/securitas-alarm-card.js` | 1175 | Custom Lovelace alarm card with WAF warning banner, multi-language |
| `www/securitas-camera-card.js` | 344 | Custom Lovelace camera card with capture button, image timestamp overlay, and loading spinner |
