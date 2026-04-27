# Event-Driven Force-Arm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded force-arm notification flow with an event-driven architecture where `securitas_arming_exception` is the core primitive, and the built-in notification handler is toggleable.

**Architecture:** The alarm panel fires an HA event on every arming exception. A built-in handler (gated by a config toggle) listens for the event and reimplements the existing notification flow. Force Arm / Cancel buttons and services remain always available.

**Tech Stack:** Python, Home Assistant Core APIs (event bus, config flow, persistent notifications), pytest

**Spec:** `docs/superpowers/specs/2026-04-09-event-driven-force-arm-design.md`

**Branch:** `refactor` (not `main`)

**Run tests:** `pytest tests/ -v` (asyncio_mode = "auto" in pyproject.toml)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `custom_components/securitas/const.py` | Modify | Add `CONF_FORCE_ARM_NOTIFICATIONS`, `DEFAULT_FORCE_ARM_NOTIFICATIONS` |
| `custom_components/securitas/__init__.py` | Modify | Import new const, add to config dict builder and options update list |
| `custom_components/securitas/config_flow.py` | Modify | Add boolean toggle to `_build_settings_schema()` |
| `custom_components/securitas/strings.json` | Modify | Add label for new toggle |
| `custom_components/securitas/translations/en.json` | Modify | Add English label |
| `custom_components/securitas/translations/es.json` | Modify | Add Spanish label |
| `custom_components/securitas/translations/fr.json` | Modify | Add French label |
| `custom_components/securitas/translations/it.json` | Modify | Add Italian label |
| `custom_components/securitas/translations/pt.json` | Modify | Add Portuguese label |
| `custom_components/securitas/translations/pt-BR.json` | Modify | Add Brazilian Portuguese label |
| `custom_components/securitas/alarm_control_panel.py` | Modify | Fire event, add event handler, gate notifications behind toggle |
| `tests/test_alarm_panel.py` | Modify | Add/update tests for event firing, handler toggle, notification gating |
| `tests/conftest.py` | Modify | Add `force_arm_notifications` to `make_config_entry_data()` |
| `docs/architecture.md` | Modify | Document event-driven force-arm flow with examples |

---

### Task 1: Add Config Constants

**Files:**
- Modify: `custom_components/securitas/const.py:37-45`

- [ ] **Step 1: Write failing test — new constants exist**

Add to `tests/test_alarm_panel.py` at the top of the file, after the existing imports (around line 41):

```python
from custom_components.securitas.const import (
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
)
```

Then add a new test class after the existing imports block:

```python
class TestForceArmNotificationsConfig:
    """Tests for the force_arm_notifications config toggle."""

    def test_constants_exist(self):
        """Config constants for force_arm_notifications are defined."""
        assert CONF_FORCE_ARM_NOTIFICATIONS == "force_arm_notifications"
        assert DEFAULT_FORCE_ARM_NOTIFICATIONS is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_constants_exist -v`

Expected: `ImportError: cannot import name 'CONF_FORCE_ARM_NOTIFICATIONS'`

- [ ] **Step 3: Add constants to const.py**

In `custom_components/securitas/const.py`, after line 37 (`CONF_NOTIFY_GROUP = "notify_group"`), add:

```python
CONF_FORCE_ARM_NOTIFICATIONS = "force_arm_notifications"
```

After line 41 (`DEFAULT_CODE_ARM_REQUIRED = False`), add:

```python
DEFAULT_FORCE_ARM_NOTIFICATIONS = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_constants_exist -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/securitas/const.py tests/test_alarm_panel.py
git commit -m "feat: add CONF_FORCE_ARM_NOTIFICATIONS constant"
```

---

### Task 2: Wire Config Toggle Into Config Flow and Init

**Files:**
- Modify: `custom_components/securitas/__init__.py:32-62,123-143,166-199`
- Modify: `custom_components/securitas/config_flow.py:43,110-121`
- Modify: `custom_components/securitas/strings.json:55-58,86-89`
- Modify: `custom_components/securitas/translations/en.json:55-58,86-89`
- Modify: `custom_components/securitas/translations/es.json:55-58,86-89`
- Modify: `custom_components/securitas/translations/fr.json:55-58,86-89`
- Modify: `custom_components/securitas/translations/it.json:55-58,86-89`
- Modify: `custom_components/securitas/translations/pt.json:55-58,86-89`
- Modify: `custom_components/securitas/translations/pt-BR.json:55-58,86-89`
- Modify: `tests/conftest.py:11-29,194-240`

- [ ] **Step 1: Write failing test — config dict includes new option**

Add to `tests/test_alarm_panel.py` inside `TestForceArmNotificationsConfig`:

```python
    def test_make_alarm_default_notifications_enabled(self):
        """By default, force_arm_notifications is True in config."""
        alarm = make_alarm()
        assert alarm.client.config.get("force_arm_notifications", True) is True

    def test_make_alarm_notifications_disabled(self):
        """force_arm_notifications=False is passed through config."""
        alarm = make_alarm(config={
            "has_peri": False,
            "map_home": "ARMHOME",
            "map_away": "ARMED",
            "map_night": "ARMNIGHT",
            "map_custom": None,
            "map_vacation": None,
            "scan_interval": 120,
            "force_arm_notifications": False,
        })
        assert alarm.client.config.get("force_arm_notifications") is False
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig -v`

Expected: PASS (these tests verify the mock wiring, not the real config flow)

- [ ] **Step 3: Add import to `__init__.py`**

In `custom_components/securitas/__init__.py`, add to the import block from `.const` (around line 51, after `CONF_NOTIFY_GROUP`):

```python
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
```

- [ ] **Step 4: Add to `_build_config_dict()` in `__init__.py`**

After line 191 (`config[CONF_NOTIFY_GROUP] = _opt(CONF_NOTIFY_GROUP, "")`), add:

```python
    config[CONF_FORCE_ARM_NOTIFICATIONS] = _opt(
        CONF_FORCE_ARM_NOTIFICATIONS, DEFAULT_FORCE_ARM_NOTIFICATIONS
    )
```

- [ ] **Step 5: Add to `async_update_options()` attribute list in `__init__.py`**

After line 136 (`CONF_NOTIFY_GROUP,`), add:

```python
            CONF_FORCE_ARM_NOTIFICATIONS,
```

- [ ] **Step 6: Add to config flow schema**

In `custom_components/securitas/config_flow.py`, add the import (around line 43, after `CONF_NOTIFY_GROUP`):

```python
    CONF_FORCE_ARM_NOTIFICATIONS,
    DEFAULT_FORCE_ARM_NOTIFICATIONS,
```

In `_build_settings_schema()`, after the `CONF_NOTIFY_GROUP` selector block (after line 121, before `vol.Optional(CONF_ADVANCED)`), add:

```python
            vol.Optional(
                CONF_FORCE_ARM_NOTIFICATIONS,
                default=defaults.get(
                    CONF_FORCE_ARM_NOTIFICATIONS, DEFAULT_FORCE_ARM_NOTIFICATIONS
                ),
            ): bool,
```

- [ ] **Step 7: Add to strings.json**

In `custom_components/securitas/strings.json`, add `"force_arm_notifications"` after `"notify_group"` in both `config.step.options.data` (line 58) and `options.step.init.data` (line 89):

```json
                    "force_arm_notifications": "Built-in force-arm notifications (disable to use your own automations)"
```

- [ ] **Step 8: Add to translation files**

Add the translated key after `"notify_group"` in both `config.step.options.data` and `options.step.init.data` sections of each file:

**`translations/en.json`:**
```json
                    "force_arm_notifications": "Built-in force-arm notifications (disable to use your own automations)"
```

**`translations/es.json`:**
```json
                    "force_arm_notifications": "Notificaciones integradas de forzar armado (desactivar para usar sus propias automatizaciones)"
```

**`translations/fr.json`:**
```json
                    "force_arm_notifications": "Notifications intégrées de forçage d'armement (désactiver pour utiliser vos propres automatisations)"
```

**`translations/it.json`:**
```json
                    "force_arm_notifications": "Notifiche integrate di attivazione forzata (disattivare per usare le proprie automazioni)"
```

**`translations/pt.json`:**
```json
                    "force_arm_notifications": "Notificações integradas de armar forçado (desativar para usar as suas próprias automatizações)"
```

**`translations/pt-BR.json`:**
```json
                    "force_arm_notifications": "Notificações integradas de armar forçado (desativar para usar suas próprias automatizações)"
```

- [ ] **Step 9: Update `make_config_entry_data()` in conftest.py**

In `tests/conftest.py`, add to the `make_config_entry_data()` function signature (after `notify_group: str = ""` on line 212):

```python
    force_arm_notifications: bool = True,
```

And add to the import block (after `CONF_NOTIFY_GROUP` on line 23):

```python
    CONF_FORCE_ARM_NOTIFICATIONS,
```

And add to the return dict (after `CONF_NOTIFY_GROUP: notify_group,` on line 239):

```python
        CONF_FORCE_ARM_NOTIFICATIONS: force_arm_notifications,
```

- [ ] **Step 10: Run full test suite**

Run: `pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 11: Commit**

```bash
git add custom_components/securitas/__init__.py custom_components/securitas/config_flow.py custom_components/securitas/strings.json custom_components/securitas/translations/ tests/conftest.py tests/test_alarm_panel.py
git commit -m "feat: wire force_arm_notifications toggle into config flow"
```

---

### Task 3: Fire `securitas_arming_exception` Event

**Files:**
- Modify: `custom_components/securitas/alarm_control_panel.py:25-33,558-601`
- Modify: `tests/test_alarm_panel.py`

- [ ] **Step 1: Write failing test — event is fired on arming exception**

Add to `tests/test_alarm_panel.py` inside `TestForceArmNotificationsConfig`:

```python
    async def test_arming_exception_fires_event(self):
        """ArmingExceptionError fires securitas_arming_exception event."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-123", "suid-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door", "zone_id": "3"}],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        alarm.hass.bus.async_fire.assert_called_once()
        call_args = alarm.hass.bus.async_fire.call_args
        assert call_args[0][0] == "securitas_arming_exception"
        event_data = call_args[0][1]
        assert event_data["entity_id"] == alarm.entity_id
        assert event_data["mode"] == AlarmControlPanelState.ARMED_HOME
        assert event_data["zones"] == ["Kitchen Door"]
        assert event_data["details"]["installation"] == "123456"
        assert event_data["details"]["exceptions"] == exc.exceptions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_arming_exception_fires_event -v`

Expected: FAIL — `async_fire` not called (current code calls `_notify_arm_exceptions` directly)

- [ ] **Step 3: Add `CONF_FORCE_ARM_NOTIFICATIONS` import to alarm_control_panel.py**

In `custom_components/securitas/alarm_control_panel.py`, add to the import block from `.` (around line 28, after `CONF_NOTIFY_GROUP`):

```python
    CONF_FORCE_ARM_NOTIFICATIONS,
```

- [ ] **Step 4: Add `_fire_arming_exception_event()` method**

Add to `SecuritasAlarm` class, after the `_set_force_context()` method (after line 615):

```python
    def _fire_arming_exception_event(
        self, exc: ArmingExceptionError, mode: str
    ) -> None:
        """Fire securitas_arming_exception event on the HA event bus."""
        zones = [e.get("alias", "unknown") for e in exc.exceptions]
        self.hass.bus.async_fire(
            "securitas_arming_exception",
            {
                "entity_id": self.entity_id,
                "mode": mode,
                "zones": zones,
                "details": {
                    "installation": self.installation.number,
                    "exceptions": exc.exceptions,
                },
            },
        )
```

- [ ] **Step 5: Replace `_notify_arm_exceptions()` call with `_fire_arming_exception_event()`**

In `set_arm_state()` (around line 583-587), change the `ArmingExceptionError` handler from:

```python
        except ArmingExceptionError as exc:
            self._set_force_context(exc, mode)
            self._state = self._last_state
            self._notify_arm_exceptions(exc)
            self.async_write_ha_state()
```

to:

```python
        except ArmingExceptionError as exc:
            self._set_force_context(exc, mode)
            self._state = self._last_state
            self._fire_arming_exception_event(exc, mode)
            self.async_write_ha_state()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_arming_exception_fires_event -v`

Expected: PASS

- [ ] **Step 7: Run full test suite to check for regressions**

Run: `pytest tests/ -v`

Expected: Some existing `TestForceArmContext` tests will now fail because they assert on `async_create_task` call counts for notifications that no longer fire directly. Note which tests fail — we'll fix them in Task 4.

- [ ] **Step 8: Commit**

```bash
git add custom_components/securitas/alarm_control_panel.py tests/test_alarm_panel.py
git commit -m "feat: fire securitas_arming_exception event on arming failure"
```

---

### Task 4: Add Built-In Event Handler Gated by Toggle

**Files:**
- Modify: `custom_components/securitas/alarm_control_panel.py:224-245`
- Modify: `tests/test_alarm_panel.py`

- [ ] **Step 1: Write failing test — handler creates notifications when toggle is on**

Add to `tests/test_alarm_panel.py` inside `TestForceArmNotificationsConfig`:

```python
    async def test_handler_creates_notifications_when_enabled(self):
        """Built-in handler creates persistent + mobile notifications when enabled."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = True
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-123", "suid-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        # Register the built-in handler (simulates async_added_to_hass)
        alarm._register_arming_exception_handler()

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Event fired + two notifications (persistent + mobile)
        alarm.hass.bus.async_fire.assert_called_once()
        # persistent_notification + notify group = 2 async_create_task calls
        assert alarm.hass.async_create_task.call_count == 2
```

- [ ] **Step 2: Write failing test — handler skips notifications when toggle is off**

Add to `tests/test_alarm_panel.py` inside `TestForceArmNotificationsConfig`:

```python
    async def test_handler_skips_notifications_when_disabled(self):
        """No notifications when force_arm_notifications is False."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = ArmingExceptionError(
            "ref-123", "suid-123",
            [{"status": "0", "deviceType": "MG", "alias": "Kitchen Door"}],
        )
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        # Event still fires
        alarm.hass.bus.async_fire.assert_called_once()
        # No notifications
        alarm.hass.async_create_task.assert_not_called()
        # But force context is still stored
        assert alarm._force_context is not None
        assert alarm._attr_extra_state_attributes["force_arm_available"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_handler_creates_notifications_when_enabled tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_handler_skips_notifications_when_disabled -v`

Expected: FAIL — `_register_arming_exception_handler` does not exist yet

- [ ] **Step 4: Add `_notifications_enabled` property**

Add to `SecuritasAlarm` class, after the `_arming_exception_notification_id` property (after line 657):

```python
    @property
    def _notifications_enabled(self) -> bool:
        """Return True if the built-in force-arm notification handler is active."""
        return self._client.config.get("force_arm_notifications", True)
```

- [ ] **Step 5: Add `_register_arming_exception_handler()` method**

Add to `SecuritasAlarm` class, after the `_notifications_enabled` property. Also add `self._arming_event_unsub = None` to `__init__` (after line 184, `self._mobile_action_unsub = None`):

In `__init__`:
```python
        self._arming_event_unsub = None
```

New method:
```python
    def _register_arming_exception_handler(self) -> None:
        """Register event listener for built-in arming exception notifications."""
        @callback
        def _handle_arming_exception_event(event: Event) -> None:
            """Handle securitas_arming_exception event for this entity."""
            if event.data.get("entity_id") != self.entity_id:
                return
            self._notify_arm_exceptions_from_event(event)

        self._arming_event_unsub = self.hass.bus.async_listen(
            "securitas_arming_exception",
            _handle_arming_exception_event,
        )
```

- [ ] **Step 6: Add `_notify_arm_exceptions_from_event()` method**

This reuses the existing notification logic from `_notify_arm_exceptions()` but reads from event data instead of the exception object. Add after `_register_arming_exception_handler()`:

```python
    def _notify_arm_exceptions_from_event(self, event: Event) -> None:
        """Send notifications about arming exceptions from event data."""
        zones = event.data.get("zones", [])
        if zones:
            sensor_list = "\n".join(f"- {z}" for z in zones)
            short_details = ", ".join(zones)
        else:
            sensor_list = "- (unknown sensor)"
            short_details = "open sensor"

        title = "Securitas: Arm blocked — open sensor(s)"
        persistent_message = (
            f"Arming was blocked because the following sensor(s) are open:\n"
            f"{sensor_list}\n\n"
            f"To arm anyway, tap **Force Arm** on the alarm card "
            f"or on your mobile notification."
        )
        mobile_message = f"Arm blocked — open sensor(s): {short_details}. Arm anyway?"

        self.hass.async_create_task(
            self.hass.services.async_call(
                domain="persistent_notification",
                service="create",
                service_data={
                    "title": title,
                    "message": persistent_message,
                    "notification_id": self._arming_exception_notification_id,
                },
            )
        )

        notify_group = self.client.config.get(CONF_NOTIFY_GROUP)
        if notify_group:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    domain="notify",
                    service=notify_group,
                    service_data={
                        "title": title,
                        "message": mobile_message,
                        "data": {
                            "tag": self._arming_exception_notification_id,
                            "actions": [
                                {
                                    "action": (
                                        "SECURITAS_FORCE_ARM"
                                        f"_{self.installation.number}"
                                    ),
                                    "title": "Force Arm",
                                },
                                {
                                    "action": (
                                        "SECURITAS_CANCEL_FORCE_ARM"
                                        f"_{self.installation.number}"
                                    ),
                                    "title": "Cancel",
                                },
                            ],
                        },
                    },
                )
            )
```

- [ ] **Step 7: Update `async_added_to_hass()` to gate listeners behind toggle**

Replace the current `async_added_to_hass()` (lines 224-230):

```python
    async def async_added_to_hass(self) -> None:
        """Register event listeners when added to HA."""
        await super().async_added_to_hass()
        if self._notifications_enabled:
            self._register_arming_exception_handler()
            self._mobile_action_unsub = self.hass.bus.async_listen(
                "mobile_app_notification_action",
                self._handle_mobile_action,
            )
```

- [ ] **Step 8: Update `async_will_remove_from_hass()` to clean up both listeners**

Replace the current `async_will_remove_from_hass()` (lines 242-245):

```python
    async def async_will_remove_from_hass(self) -> None:
        """Unregister event listeners when removed from HA."""
        if self._arming_event_unsub:
            self._arming_event_unsub()
        if self._mobile_action_unsub:
            self._mobile_action_unsub()
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig -v`

Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add custom_components/securitas/alarm_control_panel.py tests/test_alarm_panel.py
git commit -m "feat: add built-in event handler gated by force_arm_notifications toggle"
```

---

### Task 5: Gate Expiry and Dismissal Notifications Behind Toggle

**Files:**
- Modify: `custom_components/securitas/alarm_control_panel.py:619-634,724-749,751-791`
- Modify: `tests/test_alarm_panel.py`

- [ ] **Step 1: Write failing test — expiry notification suppressed when disabled**

Add to `tests/test_alarm_panel.py` inside `TestForceArmNotificationsConfig`:

```python
    def test_force_context_expiry_silent_when_disabled(self):
        """When notifications disabled, force context expiry does not notify."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm._force_context = {
            "reference_id": "ref-123",
            "suid": "suid-123",
            "mode": AlarmControlPanelState.ARMED_HOME,
            "exceptions": [],
            "created_at": datetime.now() - timedelta(seconds=300),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True
        alarm._attr_extra_state_attributes["arm_exceptions"] = ["Door"]

        alarm.coordinator.data = AlarmStatusData(
            status=SStatus(status="D"), protom_response="D"
        )

        alarm._handle_coordinator_update()

        # Force context cleared
        assert alarm._force_context is None
        assert "force_arm_available" not in alarm._attr_extra_state_attributes
        # No notification calls
        alarm.hass.async_create_task.assert_not_called()
```

- [ ] **Step 2: Write failing test — force_arm dismissal suppressed when disabled**

```python
    async def test_force_arm_no_dismiss_when_disabled(self):
        """When notifications disabled, force_arm skips notification dismissal."""
        alarm = make_alarm()
        alarm.client.config["force_arm_notifications"] = False
        alarm._state = AlarmControlPanelState.DISARMED
        alarm._force_context = {
            "reference_id": "ref-456",
            "suid": "suid-456",
            "mode": AlarmControlPanelState.ARMED_AWAY,
            "exceptions": [{"alias": "Window"}],
            "created_at": datetime.now(),
        }
        alarm._attr_extra_state_attributes["force_arm_available"] = True

        alarm.client.arm_alarm = AsyncMock(
            return_value=OperationStatus(
                operation_status="OK",
                message="",
                status="",
                installation_number="123456",
                protom_response="T",
                protom_response_data="",
            )
        )

        # Reset call tracking before the force_arm call
        alarm.hass.async_create_task.reset_mock()

        await alarm.async_force_arm()

        # No notification dismissal calls — async_create_task should not be
        # called for persistent_notification or notify service calls
        alarm.hass.async_create_task.assert_not_called()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_force_context_expiry_silent_when_disabled tests/test_alarm_panel.py::TestForceArmNotificationsConfig::test_force_arm_no_dismiss_when_disabled -v`

Expected: FAIL — expiry still calls `_notify_force_arm_expired()` unconditionally

- [ ] **Step 4: Gate `_clear_force_context()` expiry notification**

In `_clear_force_context()` (around line 631), change:

```python
            # Expired — update notification to inform user
            self._notify_force_arm_expired()
```

to:

```python
            # Expired — update notification to inform user
            if self._notifications_enabled:
                self._notify_force_arm_expired()
```

- [ ] **Step 5: Gate notification dismissal in `async_force_arm()`**

In `async_force_arm()` (around line 788-789), change:

```python
        self._clear_force_context(force=True)
        self._dismiss_arming_exception_notification()
```

to:

```python
        self._clear_force_context(force=True)
        if self._notifications_enabled:
            self._dismiss_arming_exception_notification()
```

- [ ] **Step 6: Gate notification dismissal in `async_force_arm_cancel()`**

In `async_force_arm_cancel()` (around line 764-765), change:

```python
        self._clear_force_context(force=True)
        self._dismiss_arming_exception_notification()
```

to:

```python
        self._clear_force_context(force=True)
        if self._notifications_enabled:
            self._dismiss_arming_exception_notification()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_alarm_panel.py::TestForceArmNotificationsConfig -v`

Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `pytest tests/ -v`

Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add custom_components/securitas/alarm_control_panel.py tests/test_alarm_panel.py
git commit -m "feat: gate force-arm notifications behind toggle"
```

---

### Task 6: Clean Up Old Direct Notification Call

**Files:**
- Modify: `custom_components/securitas/alarm_control_panel.py`
- Modify: `tests/test_alarm_panel.py`

- [ ] **Step 1: Remove the now-unused `_notify_arm_exceptions()` method**

Delete the `_notify_arm_exceptions()` method (lines 659-722). It has been replaced by `_notify_arm_exceptions_from_event()`.

- [ ] **Step 2: Update existing tests that assert on old notification behaviour**

The following tests in `TestForceArmContext` need updating because notifications now come from the event handler, not directly from `set_arm_state()`:

**`test_arming_exception_sends_persistent_notification`** (line 1518) — This test asserts `async_create_task.assert_called()`. Now notifications come from the event handler, not directly. Update to verify the event fires instead:

```python
    async def test_arming_exception_sends_persistent_notification(self):
        """ArmingExceptionError fires event (handler creates notifications)."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        alarm.hass.bus.async_fire.assert_called_once()
        assert alarm.hass.bus.async_fire.call_args[0][0] == "securitas_arming_exception"
```

**`test_arming_exception_notifies_configured_group`** (line 1532) — Update similarly:

```python
    async def test_arming_exception_notifies_configured_group(self):
        """ArmingExceptionError fires event (handler sends to notify group)."""
        alarm = make_alarm()
        alarm.client.config["notify_group"] = "mobile_app_phone"
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        alarm.hass.bus.async_fire.assert_called_once()
```

**`test_arming_exception_no_notify_group_only_persistent`** (line 1547) — Update similarly:

```python
    async def test_arming_exception_no_notify_group_only_persistent(self):
        """Without notify_group, event still fires (handler creates only persistent)."""
        alarm = make_alarm()
        alarm._state = AlarmControlPanelState.ARMING
        alarm._last_state = AlarmControlPanelState.DISARMED

        exc = self._make_arming_exception()
        alarm.client.arm_alarm = AsyncMock(side_effect=exc)

        await alarm.set_arm_state(AlarmControlPanelState.ARMED_HOME)

        alarm.hass.bus.async_fire.assert_called_once()
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add custom_components/securitas/alarm_control_panel.py tests/test_alarm_panel.py
git commit -m "refactor: remove old direct notification path, update tests for event-driven flow"
```

---

### Task 7: Update Documentation

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Read current architecture.md to find the force-arm section**

Run: `grep -n "force.arm\|Force.Arm\|arming.exception" docs/architecture.md` to locate the relevant section.

- [ ] **Step 2: Update the force-arm section**

Replace or extend the existing force-arm documentation with the event-driven architecture description from the design spec. Include:

1. **Event-driven force-arm architecture** — the three steps (store context, set attributes, fire event)
2. **Built-in handler** — what it does when enabled
3. **Disabling the built-in handler** — instructions
4. **Custom automation examples:**
   - Auto force-arm when leaving home
   - Notify with open zone details
   - Different behaviour per mode (force-arm for away, notify for night)
   - Notify then auto force-arm after delay
   - TTS announcement of open zones

Copy the example YAML blocks from the design spec at `docs/superpowers/specs/2026-04-09-event-driven-force-arm-design.md`, "Custom automation examples" section.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: document event-driven force-arm architecture with automation examples"
```

---

### Task 8: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`

Expected: All PASS, no warnings

- [ ] **Step 2: Verify no ruff/lint issues**

Run: `ruff check custom_components/securitas/alarm_control_panel.py custom_components/securitas/const.py custom_components/securitas/__init__.py custom_components/securitas/config_flow.py`

Expected: No errors

- [ ] **Step 3: Verify the event-driven flow end-to-end by reading the code**

Trace the flow manually through the code:
1. `set_arm_state()` catches `ArmingExceptionError` → calls `_set_force_context()` → calls `_fire_arming_exception_event()` → reverts state
2. If toggle on: `_register_arming_exception_handler()` listener → calls `_notify_arm_exceptions_from_event()` → persistent + mobile notifications
3. If toggle off: event fires, no listener, no notifications, force context still stored

- [ ] **Step 4: Commit any remaining fixes**

If any issues found, fix and commit.
