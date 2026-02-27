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
│  apimanager.py  domains.py  const.py  dataTypes.py      │
│  exceptions.py                                          │
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
3. Parses the response and raises `SecuritasDirectError` on connection or API errors

**Device spoofing:** The client identifies itself as a Samsung Galaxy S22 running the Securitas mobile app v10.102.0. Device identity consists of three IDs generated at setup time: `device_id` (FCM-format token), `uuid` (16-char hex), and `id_device_indigitall` (UUID v4).

**Authentication** is JWT-based with three mechanisms:

1. **Login** (`login()`) — Sends credentials, receives a JWT hash token. The JWT's `exp` claim sets `authentication_token_exp`. If the account needs 2FA, raises `Login2FAError`.

2. **Token refresh** (`refresh_token()`) — Uses a long-lived refresh token to get a new JWT without re-entering credentials. Falls back to full login if refresh fails.

3. **2FA device validation** (`validate_device()`) — For new devices: calls `validate_device()` which returns a list of phone numbers. The user picks one, `send_otp()` sends the SMS, then `validate_device()` is called again with the OTP code to complete registration.

**Token lifecycle:** Before every API operation, `_check_authentication_token()` checks whether the JWT expires within the next minute. If so, it tries `refresh_token()` first, falling back to `login()`. Similarly, `_check_capabilities_token()` checks a per-installation capabilities JWT that's obtained from `get_all_services()`.

**Polling pattern:** Arm, disarm, and status-check operations are asynchronous on the server side. The client sends the initial request, receives a `referenceId`, then polls a status endpoint in a loop (sleeping `delay_check_operation` seconds between attempts) until the response changes from `"WAIT"` to `"OK"` or a timeout is reached.

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
| `PARTIAL_NIGHT_PERI` | night | on | `ARMNIGHT1PERI1` | — |
| `TOTAL_PERI` | full | on | `ARM1PERI1` | `A` |

Two mapping tables connect these:
- `STATE_TO_COMMAND` — `SecuritasState` to API command string (e.g. `TOTAL` -> `"ARM1"`)
- `PROTO_TO_STATE` — single-letter protocol response code to `SecuritasState` (e.g. `"T"` -> `TOTAL`)

Home Assistant has only four alarm buttons (Home, Away, Night, Custom Bypass). The user maps each button to a Securitas state through the options flow. Standard installations get defaults without perimeter; perimeter installations get defaults that include perimeter states. The `Custom Bypass` button is hidden unless a mapping is configured for it (typically perimeter-only mode).

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
SecuritasDirectError          Base class
├── APIError                  API failures
└── LoginError                Login failures
    ├── AuthError             Access denied
    ├── TokenRefreshError     Token refresh issues
    └── Login2FAError         2FA required
```

`SecuritasDirectError` is thrown with up to 4 args: `(message, response_dict, headers, content)`. The `login()` method distinguishes between errors that have response data (wrapped in `LoginError` or `Login2FAError`) and connection errors (re-raised as `SecuritasDirectError` to trigger HA's `ConfigEntryNotReady` retry).

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
   a. Look up command from _command_map
   b. If _last_status was an armed state → disarm first (required because
      Securitas treats interior and perimeter as independent axes)
      - Disarm error? Log warning, continue anyway
   c. Call session.arm_alarm(command)
   d. update_status_alarm() with the response
```

**Disarm flow** (`async_alarm_disarm`):
```
1. _check_code(code) — raises ServiceValidationError if wrong
2. __force_state(DISARMING)
3. Call session.disarm_alarm(disarm_command)
   - Error? → _notify_error(), restore _last_status
4. update_status_alarm() with the response
```

**Why disarm-before-rearm?** The Securitas API treats interior and perimeter as independent axes. Sending `ARMDAY1` while the perimeter is armed leaves the perimeter armed. Transitioning from `Partial+Perimeter` to `Partial` (no perimeter) would silently fail without disarming first.

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
      → _command_map[ARMED_AWAY] = "ARM1"
      → _last_status == ARMED_HOME?          # Currently armed?
        → session.disarm_alarm("DARM1")      #   Disarm first
        → asyncio.sleep(1)
      → session.arm_alarm("ARM1")
        → _execute_request(GraphQL mutation)
        → API returns referenceId
        → Poll _check_arm_status() until res != "WAIT"
        → Return ArmStatus with protomResponse="T"
      → update_status_alarm(status)
        → _status_map["T"] = ARMED_AWAY
        → _state = ARMED_AWAY                # UI shows "Armed Away"
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
      → protomResponse "D" → DISARMED
      → protomResponse in _status_map → mapped HA state
      → protomResponse unknown → ARMED_CUSTOM_BYPASS + notification
    → async_write_ha_state()
```

## File reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 452 | Integration setup, `SecuritasHub`, `SecuritasDirectDevice` |
| `config_flow.py` | 351 | Config flow (setup + 2FA) and options flow (settings + mappings) |
| `alarm_control_panel.py` | 381 | Alarm entity with state mapping, arm/disarm, PIN validation |
| `sensor.py` | 185 | Sentinel temperature, humidity, air quality sensors |
| `lock.py` | 218 | Smart lock entity |
| `button.py` | 80 | Manual refresh button |
| `constants.py` | 21 | `SentinelName` language mapping |
| `securitas_direct_new_api/apimanager.py` | 1063 | GraphQL API client with auth, polling, all operations |
| `securitas_direct_new_api/const.py` | 98 | `SecuritasState`, command/protocol mappings, defaults |
| `securitas_direct_new_api/dataTypes.py` | 166 | Response dataclasses |
| `securitas_direct_new_api/domains.py` | 51 | Country-to-URL routing |
| `securitas_direct_new_api/exceptions.py` | 26 | Exception hierarchy |
