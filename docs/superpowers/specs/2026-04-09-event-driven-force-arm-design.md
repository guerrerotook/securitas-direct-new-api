# Event-Driven Force-Arm Design

## Summary

Replace the hard-coded force-arm notification flow with an event-driven
architecture. The alarm panel fires a `securitas_arming_exception` event
whenever arming is blocked by open sensors. A built-in handler (toggleable
via config) reimplements the existing notification behaviour. Users who
disable it can write their own automations against the event.

## Goals

1. Fire a HA event (`securitas_arming_exception`) on every arming exception
   — the core primitive that all downstream behaviour builds on.
2. Reimplement current notification flow (persistent + mobile + expiry) as
   a built-in handler that listens for this event.
3. Allow users to disable the built-in handler and replace it with custom
   automations.
4. Keep Force Arm / Cancel button entities and `force_arm` / `force_arm_cancel`
   services always available regardless of the toggle.

## Non-Goals

- Changing the force-arm API client logic (reference_id, suid, polling).
- Adding new button entities or services.
- Changing how force context is stored or expires.

---

## Event Definition

**Event name:** `securitas_arming_exception`

**When fired:** From `set_arm_state()` in `alarm_control_panel.py`, immediately
after storing force context, every time arming fails with a NON_BLOCKING error.
Fired regardless of the config toggle.

**Payload:**

```python
{
    # Top-level — easy to use in automations
    "entity_id": "alarm_control_panel.securitas_my_home",
    "mode": "armed_away",
    "zones": ["Kitchen window", "Bedroom sensor"],

    # Nested details — for power users
    "details": {
        "installation": "12345",
        "exceptions": [
            {"alias": "Kitchen window", "zone_id": "3", "device_type": "MAG"},
            ...
        ],
    },
}
```

- `entity_id`: the alarm panel entity that failed to arm.
- `mode`: the HA alarm state that was attempted (e.g. `armed_away`,
  `armed_home`, `armed_night`).
- `zones`: flat list of zone alias strings — convenient for templates.
- `details.installation`: the Securitas installation number.
- `details.exceptions`: full exception list from the API, preserving
  `alias`, `zone_id`, `device_type` for each open sensor.

---

## Config Toggle

**New option:** `force_arm_notifications` (bool, default `True`)

- Added to `const.py` as `CONF_FORCE_ARM_NOTIFICATIONS` with
  `DEFAULT_FORCE_ARM_NOTIFICATIONS = True`.
- Added to the options schema in `config_flow.py` alongside `notify_group`.
- Added to the config dict builder in `__init__.py`.
- Translated in `strings.json` and all translation files.

**When `True` (default):** The built-in handler listens for
`securitas_arming_exception` and creates persistent + mobile notifications,
registers the `mobile_app_notification_action` listener, and sends
expiry/dismissal notifications. Identical behaviour to today.

**When `False`:**
- The event still fires.
- Force context is still stored; entity attributes (`force_arm_available`,
  `arm_exceptions`) are still set/cleared.
- Force Arm / Cancel buttons and services still work.
- No persistent notification, no mobile notification, no mobile action
  listener, no expiry notification. Silent force-context expiry only.

The `notify_group` field remains in the config — it controls which mobile
app receives notifications when the built-in handler is active. Both
fields are irrelevant when the toggle is off, but there is no need to
hide `notify_group` dynamically.

---

## Implementation Changes to `alarm_control_panel.py`

### Current flow

```
ArmingExceptionError caught
  → _set_force_context()
  → _notify_arm_exceptions()
  → revert state
```

### New flow

```
ArmingExceptionError caught
  → _set_force_context()
  → _fire_arming_exception_event()      ← always
  → revert state
        ↓
  (if toggle on) event listener
        → _handle_arming_exception_event()
          → persistent notification
          → mobile notification
```

### Specific changes

1. **`set_arm_state()`** — replace `self._notify_arm_exceptions(exc)` with
   `self._fire_arming_exception_event(exc, mode)`.

2. **New `_fire_arming_exception_event(exc, mode)`** — builds the payload
   and calls `self.hass.bus.async_fire("securitas_arming_exception", data)`.

3. **`async_added_to_hass()`** — when `force_arm_notifications` config is
   `True`, register a listener on `securitas_arming_exception` that calls
   `_handle_arming_exception_event()`. Store the unsubscribe callback.

4. **New `_handle_arming_exception_event(event)`** — filters on
   `entity_id == self.entity_id`, then runs the existing persistent +
   mobile notification logic from `_notify_arm_exceptions()`.

5. **Mobile action listener** — also gated behind the toggle. When off,
   no mobile notifications exist to tap, so the
   `mobile_app_notification_action` listener is not registered.

   **`async_will_remove_from_hass()`** — unsubscribe both the event listener
   and the mobile action listener (if registered).

6. **`_clear_force_context()` / expiry** — the expiry notification
   (`_notify_force_arm_expired`) and dismissal
   (`_dismiss_arming_exception_notification`) are gated behind the toggle.
   When off, expiry silently clears force context and entity attributes.

7. **`_notify_arm_exceptions()` and `_dismiss_arming_exception_notification()`**
   — kept as-is but only called from the event handler path.

### What stays unchanged

- `_set_force_context()` / `_clear_force_context()` — always runs.
- Entity attributes (`force_arm_available`, `arm_exceptions`) — always
  set/cleared.
- `async_force_arm()` / `async_force_arm_cancel()` — always available.
- Force Arm / Cancel button entities — always present.

---

## Config Flow & Translation Changes

1. **`const.py`** — add `CONF_FORCE_ARM_NOTIFICATIONS = "force_arm_notifications"`
   and `DEFAULT_FORCE_ARM_NOTIFICATIONS = True`.

2. **`config_flow.py`** — add boolean toggle to `_settings_schema()` after
   `notify_group`.

3. **`__init__.py`** — add `CONF_FORCE_ARM_NOTIFICATIONS` to config dict
   builder.

4. **`strings.json`** — add label to `config.step.options.data` and
   `options.step.init.data`:
   `"force_arm_notifications": "Built-in force-arm notifications"`

5. **Translation files** (`en.json`, `es.json`, `fr.json`, `it.json`,
   `pt.json`, `pt-BR.json`) — add translated label.

---

## Documentation

Update `docs/architecture.md` to document the event-driven force-arm flow:

### Event-driven force-arm architecture

When arming is blocked by open sensors (NON_BLOCKING error from the API),
the alarm panel:

1. Stores force-arm context (reference_id, suid, mode, exceptions) with a
   180-second TTL.
2. Sets entity attributes `force_arm_available: true` and `arm_exceptions`
   with the list of open zone names.
3. Fires a `securitas_arming_exception` event on the HA event bus.

The built-in handler (enabled by default) listens for this event and creates
persistent and mobile notifications. Users can disable it via the
`force_arm_notifications` option and write their own automations.

### Built-in handler (when enabled)

- Creates a persistent notification listing open zones with instructions.
- Sends a mobile notification (if `notify_group` is configured) with
  Force Arm / Cancel action buttons.
- Listens for `mobile_app_notification_action` events to handle button taps.
- On force-context expiry (180s), updates the notification to inform the
  user the alarm was not armed.

### Disabling the built-in handler

Set **Built-in force-arm notifications** to off in the integration options
(Settings → Devices & Services → Securitas → Configure). The event still
fires, force-arm buttons and services still work — only the notifications
are suppressed.

### Custom automation examples

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

Force-arm automatically for `armed_away` (leaving home), but only notify
for `armed_night` (user may want to close the window before bed):

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
