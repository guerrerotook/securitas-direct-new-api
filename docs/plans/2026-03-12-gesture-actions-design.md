# Gesture Actions Design — Badge and Alarm Card

**Date:** 2026-03-12
**Branch:** rewrite/v_four

## Goal

Add configurable tap, hold, and double-tap gesture actions to the Securitas alarm badge and alarm card, following the standard HA action config pattern.

---

## Section 1: Config schema

Both `securitas-alarm-badge` and `securitas-alarm-card` gain three new optional config keys: `tap_action`, `hold_action`, and `double_tap_action`. Each is a standard HA action object:

```yaml
tap_action:          # or hold_action / double_tap_action
  action: none | more-info | navigate | perform-action | arm_or_disarm

  # navigate:
  navigation_path: /lovelace/0

  # perform-action:
  perform_action: light.turn_on
  data:
    entity_id: light.living_room

  # arm_or_disarm:
  arm_state: armed_away    # which state to arm to (defaults to Away mapping)
```

`arm_or_disarm` is the only new action type. It is context-sensitive: arms to `arm_state` when the alarm is disarmed; disarms when it is armed in any state. If a PIN is configured (`code_format` is non-null), a PIN overlay is shown before executing.

### Defaults

**Badge:**
| Gesture | Default action |
|---------|---------------|
| `tap_action` | `more-info` (open dialog — unchanged) |
| `hold_action` | `arm_or_disarm`, `arm_state` = Away mapping |
| `double_tap_action` | `none` |

**Card:**
| Gesture | Default action |
|---------|---------------|
| `tap_action` | `none` |
| `hold_action` | `none` |
| `double_tap_action` | `none` |

"Away mapping" means the arm state the entity reports for `ARMED_AWAY` via `supported_features` — determined at runtime from the entity's `ARM_ACTIONS` list.

---

## Section 2: Gesture implementation

### `attachGesture(el, config, hass, entityId)`

A shared helper added near the top of the JS file. Attaches pointer event listeners to `el` based on `config.tap_action`, `config.hold_action`, and `config.double_tap_action`.

**Long-press detection:**
- `pointerdown` → start 500ms timer
- `pointermove` > 10px, or `pointerup`/`pointercancel` before timer fires → cancel timer
- Timer fires → execute `hold_action`
- If hold fires, suppress the subsequent `click` event (set a flag, clear on next `click`)

**Double-tap detection:**
- First `pointerup` → start 300ms window, record timestamp
- Second `pointerup` within window → execute `double_tap_action`, clear window
- Window expires without second tap → execute `tap_action` (single tap falls through)

**Single tap:**
- `click` event → execute `tap_action` (unless suppressed by long-press)

### `executeAction(action, hass, entityId, shadowRoot)`

Shared dispatcher:

| Action | Behaviour |
|--------|-----------|
| `none` | No-op |
| `more-info` | Fire `hass-more-info` custom event (standard HA pattern) |
| `navigate` | `history.pushState({}, "", path)` + fire `location-changed` event on `window` |
| `perform-action` | `hass.callService(domain, service, data)` |
| `arm_or_disarm` | Check entity state → arm or disarm (with PIN overlay if required) |

**PIN overlay for `arm_or_disarm`:** If `code_format` is set, mount a minimal PIN input overlay (reusing the card's existing `_startPinEntry` / `_submitPin` logic) before executing the service call. On cancel, no action is taken.

---

## Section 3: Editor UI

Both `SecuritasAlarmCardEditor` (shared by card and badge) gets three new sections, one per gesture. Each section follows the same structure:

**Section heading** (e.g. "Tap action", "Hold action", "Double-tap action")

**Action dropdown** — options vary slightly by gesture:
- Tap (badge only has `more-info` as a meaningful default): `Open dialog` / `None` / `Navigate` / `Perform action` / `Arm or disarm`
- Hold and double-tap: `None` / `Open dialog` / `Navigate` / `Perform action` / `Arm or disarm`

**Conditional fields** shown below the dropdown based on selected action:
- `navigate` → text field: `Navigation path`
- `perform-action` → text field: `Action` (e.g. `light.turn_on`), YAML textarea: `Action data`
- `arm_or_disarm` → dropdown: `Arm state` — populated from the entity's `supported_features` bitmask using the same `ARM_ACTIONS` list that drives the arm buttons. Includes only states the entity supports. Defaults to Away.

Config is stored as:
```json
{
  "tap_action": { "action": "more-info" },
  "hold_action": { "action": "arm_or_disarm", "arm_state": "armed_away" },
  "double_tap_action": { "action": "none" }
}
```

---

## Success criteria

- Badge single-click still opens the dialog
- Badge long-press arms when disarmed / disarms when armed (PIN required if configured)
- Both badge and card support all three gestures independently
- All four action types (`more-info`, `navigate`, `perform-action`, `arm_or_disarm`) work correctly
- Card editor shows three action sections for both card and badge
- Defaults require no config change for existing users
