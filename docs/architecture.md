# Architecture Guide

This document explains how the Securitas Direct integration works, aimed at developers who want to contribute.

## System overview

The integration has three layers:

```
┌─────────────────────────────────────────────────────────┐
│  Home Assistant Platform Layer                          │
│  alarm_control_panel.py  sensor.py  lock.py  button.py  │
├─────────────────────────────────────────────────────────┤
│  Integration Hub Layer                                  │
│  __init__.py  (SecuritasHub + setup)                    │
│  config_flow.py  (ConfigFlow + OptionsFlow)             │
├─────────────────────────────────────────────────────────┤
│  API Client Layer                                       │
│  securitas_direct_new_api/                              │
│  apimanager.py  command_resolver.py  domains.py         │
│  const.py  dataTypes.py  exceptions.py                  │
└─────────────────────────────────────────────────────────┘
```

Every API call goes through `ApiManager._execute_request()`, which sends GraphQL mutations/queries over HTTP to Securitas' cloud. The integration hub (`SecuritasHub`) wraps the API client and is shared by all entity platforms. Each platform creates entities for the installations discovered at startup.

## API client layer

**Location:** `custom_components/securitas/securitas_direct_new_api/`

### ApiManager (`apimanager.py`)

The core API client. All communication with Securitas happens through GraphQL POST requests to country-specific endpoints (e.g. `customers.securitasdirect.es/owa-api/graphql`).

**Request execution:** Every API call goes through `_execute_request()`, which:
1. Builds HTTP headers including `app`, `auth` (JSON with JWT hash, user, country), `X-APOLLO-OPERATION-NAME`, and optionally `numinst`/`panel`/`X-Capabilities` for installation-scoped requests
2. POSTs the GraphQL payload as JSON
3. Parses the response and raises `SecuritasDirectError` on connection or API errors. For HTTP errors (status >= 400), `http_status` is set on the exception. For GraphQL-level errors (HTTP 200 but errors in payload), the `data.status` field from the first error is extracted and set as `http_status` — this is how 409 "server busy" errors are surfaced, since the Securitas API returns them as HTTP 200 with a GraphQL error containing `"data": {"status": 409}`

**DRY helpers:** Three internal helpers reduce code duplication across API methods:

- `_decode_auth_token(token_str)` — Decodes a JWT (HS256, no signature verification), updates `authentication_token_exp` from the `exp` claim. Returns the decoded claims dict or `None` on failure. Used by `login()`, `refresh_token()`, and `validate_device()`.

- `_extract_response_data(response, field_name)` — Extracts `response["data"][field_name]`, raising `SecuritasDirectError` if the data is missing or `None`. Used by all operation methods to validate responses consistently.

- `_poll_operation(check_fn, *, timeout, continue_on_msg)` — Polls `check_fn()` in a loop until the result is no longer `"WAIT"`. Handles transient errors (connection errors, timeouts, 409 "server busy") by retrying. 403 errors are not retried during polling (only at the `_execute_request` level). Raises `TimeoutError` after `timeout` seconds (default 60). Used by arm, disarm, status check, exception fetch, and lock operations.

**Device spoofing:** The client identifies itself as a Samsung Galaxy S22 running the Securitas mobile app v10.102.0. Device identity consists of three IDs generated at setup time: `device_id` (FCM-format token), `uuid` (16-char hex), and `id_device_indigitall` (UUID v4).

**Authentication** is JWT-based with three mechanisms:

1. **Login** (`login()`) — Sends credentials, receives a JWT hash token. The JWT's `exp` claim sets `authentication_token_exp`. If the account needs 2FA, raises `Login2FAError`.

2. **Token refresh** (`refresh_token()`) — Uses a long-lived refresh token to get a new JWT without re-entering credentials. Falls back to full login if refresh fails.

3. **2FA device validation** (`validate_device()`) — For new devices: calls `validate_device()` which returns a list of phone numbers. The user picks one, `send_otp()` sends the SMS, then `validate_device()` is called again with the OTP code to complete registration.

**Token lifecycle:** Before every API operation, `_check_authentication_token()` checks whether the JWT expires within the next minute. If so, it tries `refresh_token()` first, falling back to `login()`. Errors during refresh are caught with specific exception types (`SecuritasDirectError`, `asyncio.TimeoutError`, `ClientConnectorError`) rather than bare `except`. Similarly, `_check_capabilities_token()` checks a per-installation capabilities JWT that's obtained from `get_all_services()`. On `logout()`, all tokens are cleared (`authentication_token`, `refresh_token_value`, `authentication_token_exp`, `login_timestamp`) to prevent stale credentials from being reused.

**Polling pattern:** Arm, disarm, status-check, and exception-fetch operations are asynchronous on the server side. The client sends the initial request, receives a `referenceId`, then polls a status endpoint via `_poll_operation()` (sleeping `delay_check_operation` seconds between attempts) until the response changes from `"WAIT"` to a final state or a wall-clock timeout (default 60 seconds) is reached. Transient errors during polling — connection failures, timeouts, and 409 "server busy" responses — are automatically retried rather than failing the operation. After polling completes, `arm_alarm()` and `disarm_alarm()` check for `res: "ERROR"` with non-`NON_BLOCKING` error types (e.g. `TECHNICAL_ERROR`) and raise `SecuritasDirectError`, enabling the command resolver's fallback chain.

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

5. **Disarm uses current state:** The resolver determines the disarm command from the current `AlarmState` (derived from `_last_proto_code`), not from configuration flags. If both interior and perimeter are armed, it tries `DARM1DARMPERI` first, falling back to `DARM1`. If only perimeter is armed, it tries `DPERI1` first, falling back to `DARM1`.

6. **409 errors** (server busy) are re-raised immediately and do not trigger the fallback chain.

Home Assistant has five alarm buttons (Home, Away, Night, Vacation, Custom Bypass). The user maps each button to a Securitas state through the options flow. Standard installations get defaults without perimeter; perimeter installations get defaults that use perimeter states for Away (Total + Perimeter) and Custom (Perimeter Only). Both standard and perimeter installations default Night to Partial Night. Perimeter variants (e.g. Partial Night + Perimeter) are available in the options for perimeter installations and can be assigned to any button. The `Vacation` and `Custom Bypass` buttons are hidden unless a mapping is configured for them.

If the alarm is put into a state that is not mapped to any HA button (e.g. the perimeter is armed via a physical panel but perimeter support is not enabled in the integration), the entity reports `ARMED_CUSTOM_BYPASS` and logs the unmapped proto code at `info` level. This is not an error — it simply means the alarm is in a valid Securitas state that the user has not assigned to an HA button. To resolve it, enable perimeter support or map the relevant state in the integration options.

### Data types (`dataTypes.py`)

Dataclasses for API responses. The most important ones:

- `Installation` — Represents a physical Securitas installation (number, alias, panel type, address, capabilities JWT)
- `CheckAlarmStatus` — Alarm status response with `protomResponse` (the single-letter state code) and `protomResponseData`
- `ArmStatus` / `DisarmStatus` — Results of arm/disarm operations
- `Service` — A discovered service (e.g. "CONFORT" for Sentinel sensors, "DOORLOCK" for smart locks)
- `Sentinel` — Temperature, humidity, and air quality from a Sentinel device
- `OtpPhone` — Phone number option during 2FA setup

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

**Location:** `custom_components/securitas/__init__.py`

### SecuritasHub

The central coordinator. It owns an `ApiManager` session and is shared by all entity platforms via `hass.data[DOMAIN][SecuritasHub.__name__]`.

**Key responsibilities:**
- **Login delegation** — Passes credentials through to `ApiManager`
- **Service discovery** — `get_services()` calls `ApiManager.get_all_services()` and caches the results
- **Status polling** — `update_overview()` checks the alarm status using one of two strategies:
  - **Panel check** (default, `check_alarm_panel=True`): Sends `check_alarm()` to get a `referenceId`, waits 1 second, then calls `check_alarm_status()` to poll the panel directly
  - **General status** (`check_alarm_panel=False`): Calls `check_general_status()` which returns the last known cloud status without waking the panel

### Setup flow (`async_setup_entry`)

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
8. Store devices in hass.data[DOMAIN][CONF_INSTALLATION_KEY]
9. Forward to platforms: alarm_control_panel, sensor, lock
```

### Options update (`async_update_options`)

When the user changes options (PIN code, scan interval, alarm mappings, etc.), the listener merges the new options into the config entry data and reloads the integration. This triggers a full teardown and re-setup.

### SecuritasDirectDevice

A thin wrapper around `Installation` that provides `device_info` for the HA device registry. Each physical installation becomes one device.

## Entity platforms

### Alarm control panel (`alarm_control_panel.py`)

The main entity. One `SecuritasAlarm` per installation.

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

**Status updates:** `async_track_time_interval` fires `async_update_status()` every `scan_interval` seconds (default 120). This calls `SecuritasHub.update_overview()` and then `update_status_alarm()` to map the response to an HA state.

**PIN code validation:**
- `_check_code(code)` — Always checked for disarm. Raises `ServiceValidationError` if the code doesn't match the configured PIN. No PIN configured = any code accepted.
- `_check_code_for_arm_if_required(code)` — Only checked for arm operations if `code_arm_required` is True AND a PIN is configured.
- `code_format` — `None` if no PIN configured, `NUMBER` if the PIN is all digits, `TEXT` otherwise.

### Sensors (`sensor.py`)

Three sensor types from Sentinel environmental monitoring devices:

- **SentinelTemperature** — Temperature in Celsius
- **SentinelHumidity** — Humidity as percentage
- **SentinelAirQuality** — Air quality index with message (e.g. "Good")

Sensors are discovered during platform setup by scanning services for ones matching the Sentinel name (language-dependent: "CONFORT" in Spanish, "COMFORTO" in Portuguese). Each sensor polls its data independently via `async_update()` with a 30-minute interval.

### Smart lock (`lock.py`)

`SecuritasLock` controls DOORLOCK services. Discovered during setup by matching `service.request == "DOORLOCK"`.

**Lock states** (string codes from the API):
- `"1"` = open/unlocked
- `"2"` = locked
- `"3"` = opening (transitional)
- `"4"` = locking (transitional)

Lock and unlock operations use `change_lock_mode(lock=True/False)` which follows the same polling pattern as arm/disarm. Status is polled via `get_lock_current_mode()` on the scan interval.

### Refresh button (`button.py`)

`SecuritasRefreshButton` — A simple button entity that calls `SecuritasHub.update_overview()` when pressed. Allows users to manually trigger a status refresh outside the normal polling interval.

## Configuration

### Config flow (`config_flow.py`)

**Initial setup** (`FlowHandler`):
```
Step 1: User enters username, password, country, PIN, 2FA preference
Step 2 (if 2FA): Phone list — user picks which phone to send OTP to
Step 3 (if 2FA): OTP challenge — user enters the SMS code
Final: Login, list installations, create config entry
```

Device IDs are generated during initial setup and stored in the config entry for reuse across restarts.

**Options flow** (`SecuritasOptionsFlowHandler`):
```
Step 1 (init): General settings
  - PIN code (optional, for HA-side validation only)
  - Code required to arm (bool)
  - Perimeter alarm support (bool)
  - Check alarm panel directly (bool)
  - Scan interval (seconds)
  - Delay between status checks (float, 1.0-15.0)

Step 2 (mappings): Alarm state mappings
  - Map Home button → Securitas state
  - Map Away button → Securitas state
  - Map Night button → Securitas state
  - Map Vacation button → Securitas state
  - Map Custom Bypass button → Securitas state
  Available options change based on perimeter support (STD_OPTIONS vs PERI_OPTIONS)
```

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
      → check_alarm_panel == True?
        → session.check_alarm(installation)      # Returns referenceId
        → asyncio.sleep(1)
        → session.check_alarm_status(ref_id)      # Polls until not "WAIT"
        → Return CheckAlarmStatus
      → check_alarm_panel == False?
        → session.check_general_status(installation)  # Cloud-only, no panel wake
        → Return CheckAlarmStatus from SStatus
    → update_status_alarm(status)
      → _last_proto_code = status.protomResponse  # Track for resolver's current state
      → protomResponse "D" → DISARMED
      → protomResponse in _status_map → mapped HA state
      → protomResponse unknown → ARMED_CUSTOM_BYPASS + notification
    → async_write_ha_state()
```

## Testing

### Overview

The test suite has 539 tests achieving 95% overall coverage. Tests run on every PR via GitHub Actions with three parallel checks: Ruff lint/format, Pyright type checking, and pytest with a 90% coverage floor.

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
├── test_alarm_panel.py      Alarm entity: state mapping, arm/disarm, PIN validation
├── test_auth.py             Login, refresh, 2FA, token lifecycle
├── test_button.py           Refresh button entity
├── test_config_flow.py      Config flow (setup + 2FA) and options flow
├── test_command_resolver.py  CommandResolver state transitions, fallback chains
├── test_constants.py        SecuritasState enum, mapping tables
├── test_domains.py          Country-to-URL routing
├── test_execute_request.py  HTTP request execution, headers, error handling, http_status
├── test_ha_platforms.py     Platform async_setup_entry for all entity types
├── test_helpers.py          DRY helpers: _poll_operation (409 retry, transient errors)
├── test_init.py             Integration setup, SecuritasHub, device info, options
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

`MockGraphQLServer` (in `tests/mock_graphql.py`) replaces `http_client.post` on `ApiManager`. Each call reads the `X-APOLLO-OPERATION-NAME` header, records the call, and returns the next queued response for that operation:

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
| `__init__.py` | 97% | `get_config_entry` edge case |
| `alarm_control_panel.py` | 95% | `async_setup_entry`, some HA callbacks |
| `button.py` | 100% | — |
| `config_flow.py` | 99% | One unreachable branch |
| `apimanager.py` | 97% | Rare error paths, some polling branches |
| `lock.py` | 85% | `async_setup_entry`, some state transitions |
| `sensor.py` | 82% | `async_setup_entry`, sensor discovery |
| `const.py` | 100% | — |
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
| `__init__.py` | 478 | Integration setup, `SecuritasHub`, `SecuritasDirectDevice`, log filter setup |
| `config_flow.py` | 362 | Config flow (setup + 2FA) and options flow (settings + mappings) |
| `alarm_control_panel.py` | 713 | Alarm entity with state mapping, arm/disarm, force arm, PIN validation |
| `sensor.py` | 195 | Sentinel temperature, humidity, air quality sensors |
| `lock.py` | 211 | Smart lock entity |
| `button.py` | 83 | Manual refresh button |
| `constants.py` | 21 | `SentinelName` language mapping |
| `log_filter.py` | 86 | `SensitiveDataFilter` — log sanitization for secrets |
| `securitas_direct_new_api/apimanager.py` | 1296 | GraphQL API client with auth, polling, DRY helpers, all operations |
| `securitas_direct_new_api/command_resolver.py` | 206 | `CommandResolver`, `AlarmState`, `CommandStep` — state transition logic |
| `securitas_direct_new_api/const.py` | 100 | `SecuritasState`, command/protocol mappings, defaults |
| `securitas_direct_new_api/dataTypes.py` | 168 | Response dataclasses |
| `securitas_direct_new_api/domains.py` | 49 | Country-to-URL routing |
| `securitas_direct_new_api/exceptions.py` | 53 | Exception hierarchy with `http_status` and `ArmingExceptionError` |
