# Configurable Alarm State Mapping

## Problem

The Securitas Direct integration treats perimeter sensors as an afterthought. It provides a checkbox to enable perimeter mode, but then maps all perimeter-related response codes (`E`, `B`, `A`) to a single HA state (`ARMED_CUSTOM_BYPASS`). This loses critical information: "total + perimeter" and "perimeter only" are very different security postures but display identically.

The integration also repurposes HA buttons for different Securitas states depending on the perimeter checkbox (e.g. Night becomes Partial+Perimeter in PERI mode) but this remapping is hidden and not configurable.

## Verisure Alarm States

Verisure provides 8 alarm states, which are combinations of interior mode (Disarmed/Partial Day/Partial Night/Total) and perimeter (on/off):

| Securitas State            | `protomResponse` | API Command      | `msg` key                                      |
|----------------------------|------------------|------------------|-------------------------------------------------|
| Disarmed                   | `D`              | `DARM1`          | `alarm-manager.inactive_alarm`                  |
| Disarmed + Perimeter       | `D`              | `DARM1DARMPERI`  | `alarm-manager.inactive_alarm`                  |
| Perimeter only             | `E`              | `PERI1`          | `alarm-manager.status_panel.active_perimetral_alarm_msg` |
| Partial Day                | `P`              | `ARMDAY1`        | `alarm-manager.status_panel.armed_partial`      |
| Partial Night              | `Q`              | `ARMNIGHT1`      | `alarm-manager.status_panel.armed_night`        |
| Partial Day + Perimeter    | `B`              | `ARMDAY1PERI1`   | `alarm-manager.status_panel.armed_partial_plus_perimeter` |
| Partial Night + Perimeter  | —                | `ARMNIGHT1PERI1` | —                                               |
| Total                      | `T`              | `ARM1`           | `alarm-manager.status.active_alarm_msg`         |
| Total + Perimeter          | `A`              | `ARM1PERI1`      | `alarm-manager.active_perimeter_plus_alarm`     |

Note: Partial Night (`Q` / `ARMNIGHT1`) exists in some countries but not all. The `protomResponse` code and `msg` key for Partial Night + Perimeter are not yet confirmed.

## Design

### Configuration Model

Each HA alarm action (Home, Away, Night, Custom) maps to one Securitas state. Disarm always maps to Disarmed (`D`, command `DARM1` or `DARM1DARMPERI`). Each mapping can also be set to "Not used" to disable that button.

### Config Flow UI

The options flow (Configure button on integration page) presents:

1. **Perimeter checkbox** (same as today): "My system has perimeter sensors"

2. **Per-button dropdowns** for Home, Away, Night, Custom:
   - If **no perimeter**, each dropdown offers: Not used, Disarmed, Partial Day, Partial Night, Total
   - If **perimeter**, each dropdown offers: Not used, Disarmed, Disarmed + Perimeter, Partial Day, Partial Night, Total, Perimeter only, Partial Day + Perimeter, Partial Night + Perimeter, Total + Perimeter

### Default Mappings

Defaults match current integration behavior to avoid breaking changes:

| HA State   | STD default (no perimeter)  | PERI default (with perimeter)       |
|------------|-----------------------------|-------------------------------------|
| Disarmed   | Disarmed (`D`)              | Disarmed + Perimeter (`D`)          |
| Home       | Partial Day (`P`)           | Partial Day (`P`)                   |
| Away       | Total (`T`)                 | Total + Perimeter (`A`)             |
| Night      | Partial Night (`Q`)         | Partial Night + Perimeter           |
| Custom     | Not used                    | Perimeter only (`E`)                |

### Bidirectional Mapping

The stored config drives both directions:

**Outgoing (HA button press -> Securitas command):** Each Securitas state maps to a known API command (see table above). When the user presses "Away" and it's configured as "Total + Perimeter", send `ARM1PERI1`. Disarm always sends `DARM1DARMPERI` (safe: disarms everything regardless of current state).

**Incoming (status poll -> HA state):** Reverse lookup from the user's config. When `protomResponse` is `B`, find which HA button is configured as "Partial Day + Perimeter" and set that HA state. If a response code comes back that isn't mapped to any configured button, set the HA state to `ARMED_CUSTOM_BYPASS`.

### Supported Features

The `supported_features` property on the alarm entity should be dynamic based on the mapping config. If a button is set to "Not used", its corresponding feature flag is not advertised, and HA won't show that button in the UI.

## Files to Modify

### `securitas_direct_new_api/const.py`

Replace the `SecDirAlarmState` enum and `STD_COMMANDS_MAP`/`PERI_COMMANDS_MAP` with a simpler model:

- Define a `SecuritasState` enum with values: `NOT_USED`, `DISARMED`, `DISARMED_PERI`, `PARTIAL_DAY`, `PARTIAL_NIGHT`, `TOTAL`, `PERI_ONLY`, `PARTIAL_DAY_PERI`, `PARTIAL_NIGHT_PERI`, `TOTAL_PERI`
- Each value maps to a command string and a `protomResponse` code
- Define the two default mapping presets (STD and PERI)

### `config_flow.py`

Update the options flow:

- Keep the perimeter checkbox
- Add 4 select dropdowns (Home, Away, Night, Custom)
- Filter available options based on perimeter checkbox
- Store the per-button mapping in the config entry data

### `alarm_control_panel.py`

- Remove hardcoded `STD_STATE_MAP`, `PERI_STATE_MAP`, and the if/elif chain in `update_status_alarm`
- Build outgoing map (HA state -> Securitas command) and incoming map (protomResponse code -> HA state) from stored config at init time
- Make `supported_features` dynamic based on which buttons are mapped to "Not used"

### `__init__.py`

- Add config entry migration: convert existing entries (perimeter checkbox on/off, no per-button config) to the new format using the default mapping presets
- Bump config entry version

## Migration

On upgrade, existing config entries are migrated automatically:

- If perimeter checkbox was off: apply STD defaults
- If perimeter checkbox was on: apply PERI defaults

No user action required. Behavior is identical to before migration.
