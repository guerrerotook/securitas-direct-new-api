# Gesture Actions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add configurable `tap_action`, `hold_action`, and `double_tap_action` to both `securitas-alarm-badge` and `securitas-alarm-card`, following the standard HA action config pattern.

**Architecture:** Two free helper functions (`attachGesture`, `executeAction`) added at the top of `securitas-alarm-card.js` handle gesture detection and action dispatch. The badge gets a PIN overlay (created in `document.body`, like the existing dialog) for `arm_or_disarm` gestures. The card wires gestures to its header icon area. A shared `SecuritasAlarmCardEditor` gains three gesture sections using `ha-form` instances and conditional DOM fields.

**Tech Stack:** Vanilla JavaScript custom elements, Home Assistant Lovelace card API, pointer events, `ha-form` / `ha-textfield` / `ha-select` web components.

---

## Context

All changes are in one file: `custom_components/securitas/www/securitas-alarm-card.js` (1175 lines).

Key structures to know:
- `ARM_ACTIONS` (line 201): array of `{ key, labelKey, feature, service }` — maps arm state keys like `"arm_away"` to service calls
- `INACTIVE_STATES` (line 198): Set of states where the alarm is NOT armed (disarmed, arming, pending, triggered, unavailable, unknown)
- `SecuritasAlarmCard._startPinEntry(action)` (line 267): sets `_uiState = "pin"`, stores `_pendingAction`, calls `_render()`
- `SecuritasAlarmCard._submitPin(entityId)` (line 538): calls service with `code: this._pin`
- `SecuritasAlarmBadge._openDialog()` (line 1085): creates a `document.body` overlay with the full alarm card inside
- `SecuritasAlarmCardEditor._render()` (line 858): currently renders entity picker + color pickers; uses `ha-form` for entity picker and direct DOM for color pickers

No Python files change. No Python tests needed. JS testing is manual (deploy and verify in HA).

Deploy command (from worktree root):
```bash
rsync -av --delete --exclude='__pycache__' \
  custom_components/securitas/ \
  /workspaces/homeassistant-core/config/custom_components/securitas/
```

---

### Task 1: `_defaultArmState` and `attachGesture` helpers

**Files:**
- Modify: `custom_components/securitas/www/securitas-alarm-card.js` — insert after line 208 (after `ARM_ACTIONS` block, before `SecuritasAlarmCard` class)

**Step 1: Add `_defaultArmState` helper after line 208**

```js
// ── Gesture helpers ───────────────────────────────────────────────────────────

/**
 * Returns the first arm state key supported by the entity, or "arm_away".
 * Used as the fallback arm_state for arm_or_disarm when none is configured.
 */
function _defaultArmState(hass, entityId) {
  const features = hass.states[entityId]?.attributes?.supported_features || 0;
  const first = ARM_ACTIONS.find(a => features & a.feature);
  return first ? first.key : "arm_away";
}
```

**Step 2: Add `attachGesture` function immediately after `_defaultArmState`**

```js
/**
 * Attaches pointer-based gesture listeners to `el`.
 *
 * Gesture logic:
 *  - Long-press  : pointerdown → 500 ms timer. Cancel on >10 px move or
 *                  pointerup/cancel before timer fires. When timer fires,
 *                  executes hold_action and suppresses the next click.
 *  - Double-tap  : first pointerup starts a 300 ms window. Second pointerup
 *                  within the window executes double_tap_action. Window
 *                  expiry executes tap_action.
 *  - Single tap  : click event executes tap_action (unless suppressed by
 *                  long-press).
 *
 * @param {HTMLElement}   el         - Element to attach listeners to
 * @param {object}        config     - Card/badge config (tap_action etc.)
 * @param {object}        hass       - Home Assistant hass object
 * @param {string}        entityId   - Alarm entity id
 * @param {HTMLElement}   srcEl      - Element to dispatch events from
 * @param {object}        callbacks  - { startPinEntry(action) }
 * @returns {Function}               - Cleanup function (removes listeners)
 */
function attachGesture(el, config, hass, entityId, srcEl, callbacks = {}) {
  let holdTimer = null;
  let holdFired = false;
  let downX = 0, downY = 0;
  let tapWindow = null;
  let firstTapTime = 0;

  const HOLD_MS    = 500;
  const DOUBLE_MS  = 300;
  const MOVE_PX    = 10;

  const tapAction       = config.tap_action       || { action: "more-info" };
  const holdAction      = config.hold_action      || { action: "none" };
  const doubleTapAction = config.double_tap_action || { action: "none" };

  function cancelHold() {
    if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
  }

  function onPointerDown(e) {
    holdFired = false;
    downX = e.clientX; downY = e.clientY;
    holdTimer = setTimeout(() => {
      holdTimer = null;
      holdFired = true;
      executeAction(holdAction, hass, entityId, srcEl, callbacks);
    }, HOLD_MS);
  }

  function onPointerMove(e) {
    if (holdTimer) {
      const dx = e.clientX - downX, dy = e.clientY - downY;
      if (Math.sqrt(dx * dx + dy * dy) > MOVE_PX) cancelHold();
    }
  }

  function onPointerUp() {
    cancelHold();
    if (holdFired) return; // hold already fired; suppress tap logic

    const now = Date.now();
    if (tapWindow) {
      // Second tap within window → double-tap
      clearTimeout(tapWindow);
      tapWindow = null;
      firstTapTime = 0;
      executeAction(doubleTapAction, hass, entityId, srcEl, callbacks);
    } else {
      // Start window; if no second tap arrives, execute single tap
      firstTapTime = now;
      tapWindow = setTimeout(() => {
        tapWindow = null;
        firstTapTime = 0;
        executeAction(tapAction, hass, entityId, srcEl, callbacks);
      }, DOUBLE_MS);
    }
  }

  function onPointerCancel() { cancelHold(); }

  function onClick(e) {
    // If hold fired, suppress click. Reset flag so next click is normal.
    if (holdFired) { holdFired = false; e.stopImmediatePropagation(); }
  }

  el.addEventListener("pointerdown",   onPointerDown);
  el.addEventListener("pointermove",   onPointerMove);
  el.addEventListener("pointerup",     onPointerUp);
  el.addEventListener("pointercancel", onPointerCancel);
  el.addEventListener("click",         onClick, true); // capture phase

  return function cleanup() {
    el.removeEventListener("pointerdown",   onPointerDown);
    el.removeEventListener("pointermove",   onPointerMove);
    el.removeEventListener("pointerup",     onPointerUp);
    el.removeEventListener("pointercancel", onPointerCancel);
    el.removeEventListener("click",         onClick, true);
    cancelHold();
    if (tapWindow) { clearTimeout(tapWindow); tapWindow = null; }
  };
}
```

**Step 3: Verify the file has no syntax errors**

```bash
cd /workspaces/securitas-direct-new-api/.worktrees/rewrite
node --input-type=module < custom_components/securitas/www/securitas-alarm-card.js 2>&1 | head -20
```

Expected: no output (exit 0), or only a "customElements not defined" type error (acceptable, that's a browser API).

**Step 4: Commit**

```bash
git add custom_components/securitas/www/securitas-alarm-card.js
git commit -m "feat(card): add attachGesture helper with long-press and double-tap detection"
```

---

### Task 2: `executeAction` dispatcher

**Files:**
- Modify: `custom_components/securitas/www/securitas-alarm-card.js` — add `executeAction` immediately after `attachGesture`

**Step 1: Add `executeAction` function**

```js
/**
 * Executes a HA-style action config object.
 *
 * @param {object}      action     - { action, navigation_path, perform_action, data, arm_state }
 * @param {object}      hass       - Home Assistant hass object
 * @param {string}      entityId   - Alarm entity id
 * @param {HTMLElement} srcEl      - Element to dispatch events from (for more-info)
 * @param {object}      callbacks  - { startPinEntry(serviceAction) }
 */
function executeAction(action, hass, entityId, srcEl, callbacks = {}) {
  if (!action || action.action === "none") return;

  switch (action.action) {

    case "more-info":
      srcEl.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }));
      break;

    case "navigate": {
      const path = action.navigation_path;
      if (path) {
        history.pushState({}, "", path);
        window.dispatchEvent(new Event("location-changed"));
      }
      break;
    }

    case "perform-action": {
      const call = action.perform_action || "";
      const dot  = call.indexOf(".");
      if (dot > 0) {
        hass.callService(call.slice(0, dot), call.slice(dot + 1), action.data || {});
      }
      break;
    }

    case "arm_or_disarm": {
      const stateObj = hass.states[entityId];
      if (!stateObj) return;
      const state          = stateObj.state;
      const attrs          = stateObj.attributes;
      const isArmed        = !INACTIVE_STATES.has(state);
      const hasCode        = !!attrs.code_format;
      const codeArmReq     = attrs.code_arm_required === true;

      if (isArmed || state === "arming" || state === "pending" || state === "triggered") {
        // Disarm
        const svcAction = { service: "alarm_disarm", labelKey: "disarm" };
        if (hasCode && callbacks.startPinEntry) {
          callbacks.startPinEntry(svcAction);
        } else {
          hass.callService("alarm_control_panel", "alarm_disarm", { entity_id: entityId });
        }
      } else if (state === "disarmed") {
        // Arm
        const armKey = action.arm_state || _defaultArmState(hass, entityId);
        const armDef = ARM_ACTIONS.find(a => a.key === armKey);
        if (!armDef) return;
        const svcAction = { service: armDef.service, labelKey: armDef.labelKey };
        if (hasCode && codeArmReq && callbacks.startPinEntry) {
          callbacks.startPinEntry(svcAction);
        } else {
          hass.callService("alarm_control_panel", armDef.service, { entity_id: entityId });
        }
      }
      break;
    }
  }
}
```

**Step 2: Verify syntax**

```bash
node --input-type=module < custom_components/securitas/www/securitas-alarm-card.js 2>&1 | head -20
```

**Step 3: Commit**

```bash
git add custom_components/securitas/www/securitas-alarm-card.js
git commit -m "feat(card): add executeAction dispatcher for HA-style gesture actions"
```

---

### Task 3: Badge PIN overlay and gesture wiring

The badge currently attaches a single `click` listener to the `.badge` div (line 1080–1082). Replace this with `attachGesture`, and add a `_startBadgePinEntry` method that creates a floating PIN overlay in `document.body` (similar to `_openDialog`).

**Files:**
- Modify: `custom_components/securitas/www/securitas-alarm-card.js` — `SecuritasAlarmBadge` class

**Step 1: Add `_uiState` instance variables to the badge constructor**

Find the `SecuritasAlarmBadge` constructor (currently line ~1020):
```js
constructor() {
  super();
  this.attachShadow({ mode: "open" });
  this._dialogOpen = false;
}
```

Replace with:
```js
constructor() {
  super();
  this.attachShadow({ mode: "open" });
  this._dialogOpen = false;
  this._pinOverlay = null;   // floating PIN overlay element (or null)
  this._pinState   = null;   // { service, labelKey } when PIN entry active
  this._pin        = "";
  this._gestureCleanup = null; // cleanup fn returned by attachGesture
}
```

**Step 2: Replace the click handler in `_renderBadge` with `attachGesture`**

Find lines 1080–1082:
```js
    this.shadowRoot.getElementById("badge").addEventListener("click", () => {
      this._openDialog();
    });
```

Replace with:
```js
    // Clean up previous gesture listeners (badge re-renders on state change)
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

    const badgeEl = this.shadowRoot.getElementById("badge");
    const tapDef  = this._config.tap_action       || { action: "more-info" };
    const holdDef = this._config.hold_action      || { action: "arm_or_disarm", arm_state: _defaultArmState(this._hass, this._config.entity) };
    const dblDef  = this._config.double_tap_action || { action: "none" };

    // Resolve more-info to open the dialog (badge-specific behaviour)
    const resolveMoreInfo = (cfg) =>
      cfg.action === "more-info" ? { ...cfg, _openDialog: true } : cfg;

    const effectiveConfig = {
      tap_action:        resolveMoreInfo(tapDef),
      hold_action:       resolveMoreInfo(holdDef),
      double_tap_action: resolveMoreInfo(dblDef),
    };

    const callbacks = {
      startPinEntry: (svcAction) => this._startBadgePinEntry(svcAction),
    };

    this._gestureCleanup = attachGesture(
      badgeEl,
      effectiveConfig,
      this._hass,
      this._config.entity,
      this,
      callbacks,
    );
```

Wait — `executeAction` doesn't know about `_openDialog: true`. We need to handle the badge's `more-info` action (open dialog) differently. The design says badge default tap is `more-info` which opens the dialog. But `more-info` in `executeAction` fires a `hass-more-info` custom event — the dialog is the badge's custom dialog, not the HA more-info dialog.

The correct approach: intercept `more-info` in the badge's callback rather than in `executeAction`. Add a `onMoreInfo` callback:

```js
const callbacks = {
  startPinEntry: (svcAction) => this._startBadgePinEntry(svcAction),
  onMoreInfo: () => this._openDialog(),
};
```

And update `executeAction`'s `more-info` case to check for the callback first:

```js
case "more-info":
  if (callbacks.onMoreInfo) {
    callbacks.onMoreInfo();
  } else {
    srcEl.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId },
      bubbles: true,
      composed: true,
    }));
  }
  break;
```

**Full replacement for lines 1080–1082:**

```js
    // Clean up previous gesture listeners (badge re-renders on state change)
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

    const badgeEl = this.shadowRoot.getElementById("badge");
    const gestureConfig = {
      tap_action:        this._config.tap_action        || { action: "more-info" },
      hold_action:       this._config.hold_action       || { action: "arm_or_disarm", arm_state: _defaultArmState(this._hass, this._config.entity) },
      double_tap_action: this._config.double_tap_action || { action: "none" },
    };

    this._gestureCleanup = attachGesture(
      badgeEl,
      gestureConfig,
      this._hass,
      this._config.entity,
      this,
      {
        onMoreInfo:    () => this._openDialog(),
        startPinEntry: (svcAction) => this._startBadgePinEntry(svcAction),
      },
    );
```

Also update `executeAction`'s `more-info` case as described above.

**Step 3: Add `_startBadgePinEntry` and `_submitBadgePin` methods to `SecuritasAlarmBadge`**

Add these methods before `_openDialog`:

```js
  _startBadgePinEntry(svcAction) {
    if (this._pinOverlay) return; // already showing

    const hass   = this._hass;
    const entity = this._config.entity;
    const lang   = hass.language || "en";
    const stateObj = hass.states[entity];
    const codeFormat = stateObj?.attributes?.code_format || "number";

    this._pinState = svcAction;
    this._pin      = "";

    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0", right: "0", bottom: "0",
      background: "rgba(0,0,0,0.5)", zIndex: "8",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: "16px",
    });

    const box = document.createElement("div");
    Object.assign(box.style, {
      width: "100%", maxWidth: "340px",
      borderRadius: "16px",
      background: "var(--card-background-color, var(--ha-card-background, #fff))",
      boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
      padding: "20px",
      fontFamily: "inherit",
    });

    const actionLabel = svcAction.labelKey ? _t(lang, svcAction.labelKey) : (svcAction.label || "");
    const promptKey   = codeFormat === "number" ? "enter_pin" : "enter_code";

    box.innerHTML = `
      <div style="font-size:0.9em;font-weight:600;color:var(--primary-text-color);margin-bottom:12px">
        ${_t(lang, promptKey, { action: actionLabel })}
      </div>
      ${codeFormat === "number" ? `
        <input id="badge-pin-input" type="password" inputmode="numeric" autocomplete="off"
               style="width:100%;box-sizing:border-box;padding:8px 12px;border:1px solid var(--divider-color);
                      border-radius:8px;font-size:1.1em;margin-bottom:12px;background:var(--secondary-background-color);
                      color:var(--primary-text-color)" placeholder="••••" />
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:12px">
          ${[1,2,3,4,5,6,7,8,9].map(n =>
            `<button data-badge-key="${n}" style="padding:10px;border:none;border-radius:8px;font-size:1em;font-weight:600;cursor:pointer;background:var(--secondary-background-color);color:var(--primary-text-color)">${n}</button>`
          ).join("")}
          <button data-badge-key="cancel" style="padding:10px;border:none;border-radius:8px;font-size:1em;cursor:pointer;background:var(--secondary-background-color);color:var(--error-color)">✕</button>
          <button data-badge-key="0" style="padding:10px;border:none;border-radius:8px;font-size:1em;font-weight:600;cursor:pointer;background:var(--secondary-background-color);color:var(--primary-text-color)">0</button>
          <button data-badge-key="del" style="padding:10px;border:none;border-radius:8px;font-size:1em;cursor:pointer;background:var(--secondary-background-color);color:var(--primary-text-color)">⌫</button>
        </div>
      ` : `
        <input id="badge-pin-input" type="password" autocomplete="off"
               style="width:100%;box-sizing:border-box;padding:8px 12px;border:1px solid var(--divider-color);
                      border-radius:8px;font-size:1em;margin-bottom:12px;background:var(--secondary-background-color);
                      color:var(--primary-text-color)" placeholder="${_t(lang, "code")}" />
      `}
      <div style="display:flex;gap:8px">
        <button id="badge-pin-cancel" style="flex:1;padding:10px;border:none;border-radius:8px;font-size:0.9em;font-weight:600;cursor:pointer;background:var(--secondary-background-color);color:var(--primary-text-color)">${_t(lang, "cancel")}</button>
        <button id="badge-pin-confirm" style="flex:1;padding:10px;border:none;border-radius:8px;font-size:0.9em;font-weight:600;cursor:pointer;background:var(--primary-color);color:var(--text-primary-color,#fff)">${_t(lang, "confirm")}</button>
      </div>`;

    overlay.appendChild(box);
    document.body.appendChild(overlay);
    this._pinOverlay = overlay;

    const close = () => {
      overlay.remove();
      this._pinOverlay = null;
      this._pinState   = null;
      this._pin        = "";
    };

    // Keypad
    const pinInput = box.querySelector("#badge-pin-input");
    const syncInput = () => { if (pinInput) pinInput.value = this._pin; };

    box.querySelectorAll("[data-badge-key]").forEach(btn => {
      btn.addEventListener("click", () => {
        const k = btn.dataset.badgeKey;
        if (k === "cancel") { close(); return; }
        if (k === "del")    { this._pin = this._pin.slice(0, -1); syncInput(); return; }
        this._pin += k; syncInput();
      });
    });

    if (pinInput) {
      requestAnimationFrame(() => pinInput.focus());
      pinInput.addEventListener("input", e => {
        this._pin = codeFormat === "number"
          ? e.target.value.replace(/\D/g, "")
          : e.target.value;
        if (codeFormat === "number") e.target.value = this._pin;
      });
      pinInput.addEventListener("keydown", e => {
        if (e.key === "Enter")  this._submitBadgePin(close);
        if (e.key === "Escape") close();
      });
    }

    box.querySelector("#badge-pin-cancel").addEventListener("click", close);
    box.querySelector("#badge-pin-confirm").addEventListener("click", () => this._submitBadgePin(close));

    // Tap outside to close
    overlay.addEventListener("click", e => { if (e.target === overlay) close(); });
  }

  _submitBadgePin(closeFn) {
    if (!this._pinState || !this._pin) return;
    this._hass.callService("alarm_control_panel", this._pinState.service, {
      entity_id: this._config.entity,
      code: this._pin,
    });
    closeFn();
  }
```

**Step 4: Verify syntax**

```bash
node --input-type=module < custom_components/securitas/www/securitas-alarm-card.js 2>&1 | head -20
```

**Step 5: Commit**

```bash
git add custom_components/securitas/www/securitas-alarm-card.js
git commit -m "feat(badge): add gesture actions with long-press arm/disarm and PIN overlay"
```

---

### Task 4: Wire gesture actions to the alarm card

The card gets gesture support on its header icon area (`.icon-wrap`). The card already has `_startPinEntry` and `_submitPin`. Wire them as callbacks. Store the cleanup function and call it before each re-render.

**Files:**
- Modify: `custom_components/securitas/www/securitas-alarm-card.js` — `SecuritasAlarmCard` class

**Step 1: Add `_gestureCleanup` to the card constructor**

Find the `SecuritasAlarmCard` constructor (line ~212):
```js
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._uiState = "normal";   // normal | pin | force_arm
    this._pendingAction = null; // { service, label }
    this._pin = "";
  }
```

Add one line:
```js
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._uiState = "normal";
    this._pendingAction = null;
    this._pin = "";
    this._gestureCleanup = null;
  }
```

**Step 2: Clean up gesture listeners at the top of `_render`**

Find the start of `_render()` (line ~290):
```js
  _render() {
    if (!this._hass || !this._config) return;
```

Add cleanup call:
```js
  _render() {
    if (!this._hass || !this._config) return;
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
```

**Step 3: Attach gesture to `.icon-wrap` at the end of `_render`, just before `_attachListeners`**

Find line ~379:
```js
    this._attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed);
```

Insert before it:
```js
    // Attach gesture actions to the header icon (always visible touch target)
    const iconWrap = this.shadowRoot.querySelector(".icon-wrap");
    if (iconWrap) {
      const gestureConfig = {
        tap_action:        this._config.tap_action        || { action: "none" },
        hold_action:       this._config.hold_action       || { action: "none" },
        double_tap_action: this._config.double_tap_action || { action: "none" },
      };
      this._gestureCleanup = attachGesture(
        iconWrap,
        gestureConfig,
        this._hass,
        this._config.entity,
        this,
        {
          onMoreInfo:    () => this.dispatchEvent(new CustomEvent("hass-more-info", {
                           detail: { entityId: this._config.entity }, bubbles: true, composed: true })),
          startPinEntry: (svcAction) => this._startPinEntry(svcAction),
        },
      );
    }

    this._attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed);
```

**Step 4: Verify syntax**

```bash
node --input-type=module < custom_components/securitas/www/securitas-alarm-card.js 2>&1 | head -20
```

**Step 5: Commit**

```bash
git add custom_components/securitas/www/securitas-alarm-card.js
git commit -m "feat(card): wire gesture actions to header icon area"
```

---

### Task 5: Editor UI — three gesture action sections

The `SecuritasAlarmCardEditor` gains three collapsible/sequential sections: Tap action, Hold action, Double-tap action. Each shows:
1. An action dropdown (`ha-select`)
2. Conditional fields below it: Navigation path (for `navigate`), Perform action + Data (for `perform-action`), Arm state dropdown (for `arm_or_disarm`)

**Files:**
- Modify: `custom_components/securitas/www/securitas-alarm-card.js` — `SecuritasAlarmCardEditor._render()`

**Step 1: Add a `_renderGestureSection` helper method to `SecuritasAlarmCardEditor`**

Add this method before `_render()` in the `SecuritasAlarmCardEditor` class:

```js
  /**
   * Renders one gesture section and returns the DOM node.
   * @param {string} gesture  - "tap" | "hold" | "double_tap"
   * @param {string} title    - Section heading text
   * @param {object} defaults - Default action config for this gesture
   */
  _buildGestureSection(gesture, title, defaults) {
    const configKey    = `${gesture}_action`;
    const current      = this._config[configKey] || defaults;
    const currentAction = current.action || defaults.action;

    const stateObj = this._hass?.states[this._config.entity];
    const features = stateObj?.attributes?.supported_features || 0;
    const supportedArmActions = ARM_ACTIONS.filter(a => features & a.feature);

    const section = document.createElement("div");
    section.innerHTML = `
      <div class="section-title">${title}</div>
      <div class="gesture-row">
        <label class="gesture-label">Action</label>
        <select class="gesture-select" id="${gesture}-action-select">
          <option value="none">None</option>
          <option value="more-info">Open dialog</option>
          <option value="navigate">Navigate</option>
          <option value="perform-action">Perform action</option>
          <option value="arm_or_disarm">Arm or disarm</option>
        </select>
      </div>
      <div id="${gesture}-navigate-fields" class="conditional-fields" style="display:none">
        <label class="gesture-label">Navigation path</label>
        <input type="text" id="${gesture}-nav-path" class="gesture-text"
               placeholder="/lovelace/0" value="" />
      </div>
      <div id="${gesture}-perform-fields" class="conditional-fields" style="display:none">
        <label class="gesture-label">Action (e.g. light.turn_on)</label>
        <input type="text" id="${gesture}-perform-action" class="gesture-text"
               placeholder="domain.service" value="" />
        <label class="gesture-label" style="margin-top:6px">Action data (YAML, optional)</label>
        <textarea id="${gesture}-perform-data" class="gesture-textarea"
                  placeholder="entity_id: light.living_room"></textarea>
      </div>
      <div id="${gesture}-arm-fields" class="conditional-fields" style="display:none">
        <label class="gesture-label">Arm state</label>
        <select class="gesture-select" id="${gesture}-arm-state-select">
          ${supportedArmActions.map(a =>
            `<option value="${a.key}">${a.key.replace("arm_", "").replace("_", " ").replace(/\b\w/g, c => c.toUpperCase())}</option>`
          ).join("") || '<option value="arm_away">Away</option>'}
        </select>
      </div>`;

    // Set initial values
    const sel = section.querySelector(`#${gesture}-action-select`);
    sel.value = currentAction;

    const navPath = section.querySelector(`#${gesture}-nav-path`);
    navPath.value = current.navigation_path || "";

    const perfAction = section.querySelector(`#${gesture}-perform-action`);
    perfAction.value = current.perform_action || "";

    const perfData = section.querySelector(`#${gesture}-perform-data`);
    perfData.value = current.data ? JSON.stringify(current.data, null, 2) : "";

    const armSel = section.querySelector(`#${gesture}-arm-state-select`);
    if (armSel) armSel.value = current.arm_state || _defaultArmState(this._hass, this._config.entity);

    // Show/hide conditional fields
    const showFields = (action) => {
      section.querySelector(`#${gesture}-navigate-fields`).style.display = action === "navigate"       ? "" : "none";
      section.querySelector(`#${gesture}-perform-fields`).style.display  = action === "perform-action" ? "" : "none";
      section.querySelector(`#${gesture}-arm-fields`).style.display      = action === "arm_or_disarm"  ? "" : "none";
    };
    showFields(currentAction);

    // Write config helper
    const writeConfig = () => {
      const action = sel.value;
      const cfg = { action };
      if (action === "navigate")       cfg.navigation_path = navPath.value.trim();
      if (action === "perform-action") {
        cfg.perform_action = perfAction.value.trim();
        try { cfg.data = perfData.value.trim() ? JSON.parse(perfData.value) : undefined; } catch (_) {}
      }
      if (action === "arm_or_disarm")  cfg.arm_state = armSel?.value;
      this._config = { ...this._config, [configKey]: cfg };
      this._fireChanged();
    };

    sel.addEventListener("change", () => { showFields(sel.value); writeConfig(); });
    navPath.addEventListener("input", writeConfig);
    perfAction.addEventListener("input", writeConfig);
    perfData.addEventListener("input", writeConfig);
    if (armSel) armSel.addEventListener("change", writeConfig);

    return section;
  }
```

**Step 2: Call `_buildGestureSection` at the end of `_render()`**

In `_render()`, just before the closing `</div>` of the outer editor div (before the color pickers section), add a `<div id="gesture-slot"></div>` placeholder in the HTML, then populate it after the rest of the editor setup code.

Find the end of the editor HTML string, which currently is (around line 934):
```js
        </div>
      </div>`;
```

Add a slot before the closing `</div>`:
```js
        </div>
        <div id="gesture-slot"></div>
      </div>`;
```

Then after the existing event listeners code (after the reset buttons section, before the end of `_render()`), add:

```js
    // ── Gesture action sections ──────────────────────────────────────────────
    const gestureSlot = this.shadowRoot.getElementById("gesture-slot");
    if (gestureSlot) {
      gestureSlot.innerHTML = "";

      const isBadge = this._config.type === "custom:securitas-alarm-badge";

      const tapDefaults   = isBadge ? { action: "more-info" }   : { action: "none" };
      const holdDefaults  = { action: "arm_or_disarm",
                              arm_state: _defaultArmState(this._hass, this._config.entity) };
      const dblDefaults   = { action: "none" };

      gestureSlot.appendChild(this._buildGestureSection("tap",        "Tap action",         tapDefaults));
      gestureSlot.appendChild(this._buildGestureSection("hold",       "Hold action",        holdDefaults));
      gestureSlot.appendChild(this._buildGestureSection("double_tap", "Double-tap action",  dblDefaults));
    }
```

**Step 3: Add gesture section styles to the editor's `<style>` block**

Inside the editor's `this.shadowRoot.innerHTML = \`<style>...\`` block, add these rules before the closing backtick/semicolon:

```css
        .gesture-row {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-top: 8px;
        }
        .gesture-label {
          font-size: 0.85em;
          color: var(--secondary-text-color);
          flex-shrink: 0;
        }
        .gesture-select {
          flex: 1;
          padding: 6px 10px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          font-size: 0.85em;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          cursor: pointer;
        }
        .gesture-text {
          width: 100%;
          box-sizing: border-box;
          padding: 6px 10px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          font-size: 0.85em;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          margin-top: 4px;
        }
        .gesture-textarea {
          width: 100%;
          box-sizing: border-box;
          padding: 6px 10px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          font-size: 0.85em;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          font-family: monospace;
          min-height: 60px;
          resize: vertical;
          margin-top: 4px;
        }
        .conditional-fields {
          margin-top: 6px;
          padding: 8px 10px;
          background: color-mix(in srgb, var(--primary-color) 5%, transparent);
          border-radius: 8px;
        }
```

**Step 4: Verify syntax**

```bash
node --input-type=module < custom_components/securitas/www/securitas-alarm-card.js 2>&1 | head -20
```

**Step 5: Commit**

```bash
git add custom_components/securitas/www/securitas-alarm-card.js
git commit -m "feat(editor): add three gesture action sections (tap/hold/double-tap)"
```

---

### Task 6: Manual verification and final cleanup

**Step 1: Deploy to HA**

```bash
rsync -av --delete --exclude='__pycache__' \
  /workspaces/securitas-direct-new-api/.worktrees/rewrite/custom_components/securitas/ \
  /workspaces/homeassistant-core/config/custom_components/securitas/
```

**Step 2: Bump version to bust card JS cache**

In `custom_components/securitas/manifest.json`, bump the patch version (e.g. `0.7.3` → `0.7.4`).

```bash
git add custom_components/securitas/manifest.json custom_components/securitas/www/securitas-alarm-card.js
git commit -m "chore: bump version for gesture actions release"
```

**Step 3: Manual verification checklist**

After restarting HA dev server and clearing browser cache:

- [ ] Badge: single click still opens the dialog (default `tap_action: more-info`)
- [ ] Badge: long-press arms when disarmed / disarms when armed (default `hold_action: arm_or_disarm`)
- [ ] Badge: if `code_format` set, long-press shows PIN overlay before acting
- [ ] Badge: double-tap does nothing by default (default `double_tap_action: none`)
- [ ] Card: hold on icon area — when `hold_action: arm_or_disarm` configured, arms/disarms
- [ ] Card editor: three gesture sections appear for both card and badge
- [ ] Card editor: selecting "Navigate" shows navigation path field
- [ ] Card editor: selecting "Arm or disarm" shows arm state dropdown populated from entity features
- [ ] Card editor: gesture config persists when changing entity selector

---

## Success Criteria

- Badge single-click still opens the dialog
- Badge long-press arms when disarmed / disarms when armed (PIN required if configured)
- Both badge and card support all three gestures independently
- All four action types (`more-info`, `navigate`, `perform-action`, `arm_or_disarm`) work
- Card editor shows three action sections for both card and badge
- Defaults require no config change for existing users
