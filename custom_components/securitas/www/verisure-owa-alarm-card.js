/**
 * Verisure OWA Alarm Card
 *
 * A polished custom Lovelace card for the Verisure OWA integration.
 *
 * Features:
 *  - Reads `supported_features` from the entity — only shows arm buttons
 *    for modes that are actually configured (Away, Home, Night, Vacation, Custom)
 *  - PIN / code support: numeric keypad for digit codes, text input for
 *    alphanumeric codes; respects `code_arm_required` and always asks for
 *    code on Disarm when a code is configured
 *  - Arming-exception section: lists open sensors from `arm_exceptions`.
 *    Force Arm appears only when `force_arm_available` is true; panels that
 *    prohibit forcing still show the sensor warning and Cancel button
 *  - Handles `unavailable` and `unknown` entity states gracefully
 *  - Styling aligned with Home Assistant's design language (CSS variables)
 *
 * Card config:
 *   type: custom:securitas-alarm-card
 *   entity: alarm_control_panel.YOUR_PANEL_ID
 *   name: My Alarm          # optional — overrides friendly_name
 */

import { escHtml } from "./verisure-owa-card-utils.js?v=5.8.0";
import {
  autoForceActive,
  readAutoForce,
  writeAutoForce,
} from "./verisure-owa-arm-exception.js?v=5.8.0";
import {
  _t,
  STATE_CFG,
  STATE_COLOR_DEFAULTS,
  COLOR_EDITOR_STATES,
  STATE_LABEL_KEYS,
  INACTIVE_STATES,
  ARM_ACTIONS,
  GESTURE_KEYS,
  _filteredArmActions,
  defaultArmState,
  attachGesture,
  TRANSLATIONS,
  alarmEntitySuggestion,
  _makeLegacyShim,
} from "./verisure-owa-alarm-shared.js?v=5.8.0";

// Re-export the public helper API so existing imports of these names from
// this module keep working.
export {
  FEATURE,
  TRANSLATIONS,
  ARM_ACTIONS,
  defaultArmState,
  alarmEntitySuggestion,
} from "./verisure-owa-alarm-shared.js?v=5.8.0";

// The lightweight chip/badge are defined in verisure-owa-alarm-chip.js, which
// the integration registers as a SEPARATE Lovelace resource so the
// always-visible alarm chip renders without waiting for this heavier card
// bundle. It is deliberately NOT imported here: a relative import would resolve
// to a different URL than the registered chip resource (the resource carries
// _card_url's ?v=<hash>-<version>), so importing it would just fetch chip.js a
// second time for no benefit. Badge/chip taps now open HA's native More Info
// dialog; this custom card remains available as an explicit Lovelace card.

class VerisureOwaAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._uiState = "normal";   // normal | pin | force_arm
    this._pendingAction = null; // { service, label }
    this._pin = "";
    this._gestureCleanup = null;
    // Per-device auto-force-arm tick box (loaded from localStorage in
    // setConfig). `_pendingAutoForce` is armed only by a card-initiated arm,
    // so a stale/foreign force-arm context never triggers an auto-force.
    // `_autoForceArming` tracks that the arm reached the panel (state went to
    // arming/pending) so the intent is dropped once it resolves.
    this._autoForceArm = false;
    this._pendingAutoForce = false;
    this._autoForceArming = false;
  }

  disconnectedCallback() {
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
    // Force the next `set hass` call (which fires on reconnection) to
    // re-run `_render`. Without this, the cached `_lastKey` matches the
    // incoming state and the short-circuit skips re-render — leaving the
    // card without gesture listeners (cleaned up above) until something
    // else triggers a render. Symptom: hold-on-icon stops working after
    // any dashboard re-mount (tab switch, editor open/close, etc.) even
    // though the arm/disarm buttons keep working (their click listeners
    // live on the surviving DOM nodes).
    this._lastKey = null;
    // Zero in-flight PIN entry so it doesn't linger in memory if the card is
    // detached mid-entry (e.g. dashboard tab switch).
    this._pin = "";
    this._uiState = "normal";
    this._pendingAction = null;
    // Drop any armed auto-force intent — the card that initiated the arm is
    // going away, so it must not act on a force context after re-mount.
    this._pendingAutoForce = false;
    this._autoForceArming = false;
  }

  // ── Auto-force-arm (per-device) ──────────────────────────────────────────────
  // Storage and the capability gate live in the shared arm-exception module so
  // this card and the native More Info dialog can never drift apart on the
  // key: the tick is remembered per device and shared between the two.
  _readAutoForce() {
    return readAutoForce(this._config?.entity);
  }

  _writeAutoForce(on) {
    writeAutoForce(this._config?.entity, on);
  }

  _autoForceActive() {
    return autoForceActive(this._hass?.states?.[this._config?.entity], this._autoForceArm);
  }

  // When this dispatch will auto-force, ask the backend to skip the transient
  // "force-arm required?" prompt for the arm we are about to send — the
  // follow-up "force-armed" confirmation tells the user what happened instead.
  // Fired before the arm so the backend sees it when the exception lands.
  _suppressArmPrompt(entity) {
    if (!this._pendingAutoForce) return;
    this._hass.callService("verisure_owa", "suppress_arm_exception_prompt", {
      entity_id: entity,
    });
  }

  // Drop the auto-force intent if the arm never reaches the panel — the
  // service call rejects (invalid PIN raises ServiceValidationError, a network
  // error rejects) before any state transition, so nothing else would clear it
  // and a later, unrelated force-arm context could otherwise auto-force.
  _clearAutoForceOnReject(promise) {
    Promise.resolve(promise).catch(() => {
      this._pendingAutoForce = false;
      this._autoForceArming = false;
    });
  }

  // Called on every hass update. When this card's own arm hit a forceable
  // exception, force-arm automatically instead of waiting for the user.
  _maybeAutoForceArm(stateObj) {
    if (!this._pendingAutoForce || !stateObj) return;
    if (stateObj.attributes.force_arm_available === true) {
      this._pendingAutoForce = false;
      this._autoForceArming = false;
      // Re-check the authoritative gate at fire time: if the option was turned
      // off (or the tick cleared) after the arm was dispatched, don't force.
      if (this._autoForceActive()) {
        this._hass.callService("verisure_owa", "force_arm", {
          entity_id: this._config.entity,
        });
      }
      return;
    }
    const s = stateObj.state;
    if (s === "arming" || s === "pending") {
      // The arm reached the panel and is in flight — wait for it to resolve.
      this._autoForceArming = true;
      return;
    }
    // Any settled state with no forceable exception means the arm resolved:
    // armed OK, or a non-forceable rejection that bounced back to disarmed.
    // Drop the intent so a later, unrelated force context can't trigger it.
    // The `disarmed` guard covers the first tick after the click, before the
    // panel has moved to `arming` — keep waiting until we've seen it in flight.
    if (s !== "disarmed" || this._autoForceArming) {
      this._pendingAutoForce = false;
      this._autoForceArming = false;
    }
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = config;
    this._autoForceArm = this._readAutoForce();
    this._lastKey = null; // force re-render so color changes apply immediately
    // Memoize the `states` fingerprint so the per-tick `set hass` doesn't
    // re-allocate it for every unrelated entity update.
    this._statesFP = config.states === undefined
      ? "*"
      : (Array.isArray(config.states) ? config.states : []).join(",");
    if (this._hass) this._render();
  }

  // Returns the effective color for a state: user config override → STATE_CFG default
  _getColor(state) {
    return (this._config?.colors?.[state]) || STATE_CFG[state]?.color || "var(--disabled-color,#9E9E9E)";
  }

  set hass(hass) {
    this._hass = hass;
    // Only re-render if the relevant entity state/attributes changed
    const stateObj = hass.states[this._config.entity];
    // Act on a pending auto-force intent before the render short-circuit, so a
    // freshly-appeared force-arm context is handled even on the same tick.
    this._maybeAutoForceArm(stateObj);
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.arm_exception_active}|${stateObj.attributes.force_arm_available}|${(stateObj.attributes.arm_exceptions||[]).join(",")}|${stateObj.attributes.supported_features}|${stateObj.attributes.code_format}|${stateObj.attributes.code_arm_required}|${stateObj.attributes.waf_blocked}|${stateObj.attributes.refresh_failed}|${stateObj.attributes.auto_force_arm_enabled}|states:${this._statesFP || "*"}`
      : "missing";
    if (newKey !== this._lastKey) {
      this._lastKey = newKey;
      // If alarm just armed/disarmed, go back to normal UI
      if (stateObj && stateObj.state !== "disarmed" && this._uiState === "pin") {
        this._resetUI();
      }
      this._render();
    }
  }


  // ── UI state helpers ────────────────────────────────────────────────────────
  _resetUI() {
    this._uiState = "normal";
    this._pendingAction = null;
    this._pin = "";
  }

  _startPinEntry(action) {
    this._pendingAction = action;
    this._pin = "";
    this._uiState = "pin";
    this._render();
  }

  // Refresh formerly required finding a separate button entity on the
  // panel's device.  The verisure_owa.refresh_alarm entity service now
  // backs the refresh action directly on the alarm panel entity, so
  // there's nothing to look up.

  // ── Main render ─────────────────────────────────────────────────────────────
  _render() {
    if (!this._hass || !this._config) return;
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

    const lang = this._hass.language || "en";
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div class="missing">${_t(lang, "entity_not_found", { entity: escHtml(this._config.entity) })}</div></ha-card>`;
      return;
    }

    const state    = stateObj.state;
    const attrs    = stateObj.attributes;
    const stateCfg = STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)" };
    const cfg      = { icon: stateCfg.icon, color: this._getColor(state), label: _t(lang, STATE_LABEL_KEYS[state] || state) };
    const name     = this._config.name || attrs.friendly_name || this._config.entity;
    const features = attrs.supported_features || 0;

    const forceArmAvailable = attrs.force_arm_available === true;
    // Backwards compatibility: older backends exposed only
    // force_arm_available when an exception prompt was active.
    const armExceptionActive = attrs.arm_exception_active === true || forceArmAvailable;
    const wafBlocked        = attrs.waf_blocked === true;
    const refreshFailed     = attrs.refresh_failed === true;
    // Capability gate set by the integration options; only then is the
    // per-device auto-force-arm tick box offered.
    const autoForceEnabled  = attrs.auto_force_arm_enabled === true;

    const codeFormat      = attrs.code_format || null;        // "number" | "text" | null
    const codeArmRequired = attrs.code_arm_required === true; // need code to arm?
    const hasCode         = !!codeFormat;

    // Unavailable / unknown — show state but no action buttons
    const isUnavailable = state === "unavailable" || state === "unknown";

    // `_config.states` is a hide-only filter applied on top of
    // `supported_features` (which sub-panel runtime rejection has already
    // shrunk by the time we get here) — never shows buttons the entity
    // doesn't advertise.
    const { filtered: availableArmActions } = _filteredArmActions(features, this._config.states);
    const isArmed   = !INACTIVE_STATES.has(state);
    // Show Disarm during arming/pending too — alarm is already committed
    const canDisarm = isArmed || state === "arming" || state === "pending" || state === "triggered";
    const canArm    = state === "disarmed";

    this.shadowRoot.innerHTML = `
      <style>${this._styles(cfg)}</style>
      <ha-card>
        <div class="top-bar"></div>
        <div class="content">

          <!-- ── Header ── -->
          <div class="header">
            <div class="icon-wrap">
              <ha-icon icon="${cfg.icon}"></ha-icon>
            </div>
            <div class="title-block">
              <div class="entity-name">${escHtml(name)}</div>
              <div class="state-row">
                <div class="state-pill">${cfg.label}</div>
                <button class="refresh-btn" type="button" data-action="refresh" title="${_t(lang, "refresh")}" aria-label="${_t(lang, "refresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button>
              </div>
            </div>
          </div>

          <!-- ── Unavailable notice ── -->
          ${isUnavailable ? `<div class="unavailable-msg">${_t(lang, "entity_state_notice", { state: cfg.label })}</div>` : ""}

          <!-- ── WAF rate-limit banner ── -->
          ${wafBlocked ? `<div class="waf-banner"><ha-icon icon="mdi:shield-alert"></ha-icon> ${_t(lang, "waf_blocked")}</div>` : ""}

          <!-- ── Refresh failed banner ── -->
          ${refreshFailed ? `<div class="stale-banner"><ha-icon icon="mdi:clock-alert-outline"></ha-icon> ${_t(lang, "refresh_failed")}</div>` : ""}

          <!-- ── Arming exception / optional force-arm section ── -->
          ${!isUnavailable && armExceptionActive ? `
            <div id="arm-exception-slot"></div>
            ${canDisarm ? `<div class="btn-grid"><button class="btn btn-disarm" data-action="disarm">${_t(lang, "disarm")}</button></div>` : ""}
          ` : ""}

          <!-- ── PIN entry ── -->
          ${!isUnavailable && this._uiState === "pin" ? this._renderPin(codeFormat, lang) : ""}

          <!-- ── Normal buttons (hidden during pin entry / force arm / unavailable) ── -->
          ${!isUnavailable && this._uiState === "normal" && !armExceptionActive ? `
            <div class="btn-grid">
              ${canDisarm
                ? `<button class="btn btn-disarm" data-action="disarm">${_t(lang, "disarm")}</button>`
                : canArm
                  ? availableArmActions.map(a =>
                      `<button class="btn btn-arm" data-action="${a.key}">${_t(lang, a.labelKey)}</button>`
                    ).join("")
                  : ""
              }
            </div>
            ${canArm && autoForceEnabled ? `
              <label class="auto-force-toggle">
                <input type="checkbox" class="auto-force-checkbox" ${this._autoForceArm ? "checked" : ""}>
                <span>${_t(lang, "auto_force_arm")}</span>
              </label>` : ""}` : ""}

        </div>
      </ha-card>`;

    const armExceptionSlot = this.shadowRoot.getElementById("arm-exception-slot");
    if (armExceptionSlot) {
      const alert = document.createElement("verisure-owa-arm-exception-alert");
      alert.update({
        hass: this._hass,
        stateObj,
        entityId: this._config.entity,
        presentation: "full",
      });
      armExceptionSlot.appendChild(alert);
    }

    // Attach gesture actions to the header icon (always-visible touch target)
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
          startPinEntry: (svcAction) => this._startPinEntry(svcAction),
        },
        this._config.states,
      );
    }

    this._attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed);
  }

  // ── PIN entry section ───────────────────────────────────────────────────────
  _renderPin(codeFormat, lang) {
    const actionLabel = this._pendingAction?.labelKey
      ? _t(lang, this._pendingAction.labelKey)
      : (this._pendingAction?.label || "");

    if (codeFormat === "number") {
      return `
        <div class="pin-section">
          <div class="pin-label">${_t(lang, "enter_pin", { action: actionLabel })}</div>
          <input id="pin-keyboard-input" class="pin-input" type="password"
                 inputmode="numeric" autocomplete="off"
                 placeholder="\u2022\u2022\u2022\u2022" />
          <div class="keypad">
            ${[1,2,3,4,5,6,7,8,9].map(n =>
              `<button class="key" data-key="${n}">${n}</button>`
            ).join("")}
            <button class="key key-cancel" data-key="cancel" aria-label="${_t(lang, "cancel")}" title="${_t(lang, "cancel")}">✕</button>
            <button class="key" data-key="0">0</button>
            <button class="key key-del" data-key="del" aria-label="${_t(lang, "delete")}" title="${_t(lang, "delete")}">⌫</button>
          </div>
          <button class="btn btn-arm pin-confirm" data-action="confirm-pin">${_t(lang, "confirm")}</button>
        </div>`;
    }

    // Text code
    return `
      <div class="pin-section">
        <div class="pin-label">${_t(lang, "enter_code", { action: actionLabel })}</div>
        <input class="code-input" type="password" autocomplete="off"
               placeholder="${_t(lang, "code")}" id="code-input" />
        <div class="text-pin-btns">
          <button class="btn btn-cancel-force" data-action="cancel-pin">${_t(lang, "cancel")}</button>
          <button class="btn btn-arm" data-action="confirm-pin">${_t(lang, "confirm")}</button>
        </div>
      </div>`;
  }

  // ── Event listeners ─────────────────────────────────────────────────────────
  _attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed) {
    const entity = this._config.entity;

    // Arm / Disarm / Refresh buttons
    this.shadowRoot.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        this._handleAction(action, stateObj, codeFormat, codeArmRequired, hasCode, isArmed, entity);
      });
    });

    // Auto-force-arm tick box — remembered per device, never re-renders here.
    const autoForceCb = this.shadowRoot.querySelector(".auto-force-checkbox");
    if (autoForceCb) {
      autoForceCb.addEventListener("change", () => {
        this._autoForceArm = autoForceCb.checked;
        this._writeAutoForce(this._autoForceArm);
      });
    }

    // Numeric keypad + visible input
    const pinInput = this.shadowRoot.getElementById("pin-keyboard-input");
    const syncInput = () => {
      if (pinInput) { pinInput.value = this._pin; pinInput.focus(); }
    };
    this.shadowRoot.querySelectorAll("[data-key]").forEach(key => {
      key.addEventListener("click", () => {
        const k = key.dataset.key;
        if (k === "cancel") { this._resetUI(); this._render(); return; }
        if (k === "del")    { this._pin = this._pin.slice(0, -1); syncInput(); return; }
        this._pin += k;
        syncInput();
      });
    });
    if (pinInput) {
      // Restore in-flight PIN imperatively — never via the HTML value attribute.
      pinInput.value = this._pin;
      requestAnimationFrame(() => pinInput.focus());
      pinInput.addEventListener("input", e => {
        this._pin = e.target.value.replace(/\D/g, "");
        e.target.value = this._pin;
      });
      pinInput.addEventListener("keydown", e => {
        if (e.key === "Enter") this._submitPin(entity);
        if (e.key === "Escape") { this._resetUI(); this._render(); }
      });
    }

    // Text code input
    const codeInput = this.shadowRoot.getElementById("code-input");
    if (codeInput) {
      // Restore in-flight code imperatively — never via the HTML value attribute.
      codeInput.value = this._pin;
      requestAnimationFrame(() => codeInput.focus());
      codeInput.addEventListener("input", e => { this._pin = e.target.value; });
      codeInput.addEventListener("keydown", e => {
        if (e.key === "Enter") this._submitPin(entity);
      });
    }
  }

  _handleAction(action, stateObj, codeFormat, codeArmRequired, hasCode, isArmed, entity) {
    // Refresh — call the entity service directly on the alarm panel.
    if (action === "refresh") {
      const btn = this.shadowRoot.querySelector(".refresh-btn");
      if (btn) btn.classList.add("spinning");
      this._hass
        .callService("verisure_owa", "refresh_alarm", { entity_id: entity })
        .finally(() => {
          setTimeout(() => {
            const b = this.shadowRoot?.querySelector(".refresh-btn");
            if (b) b.classList.remove("spinning");
          }, 2000);
        });
      return;
    }
    if (action === "confirm-pin") { this._submitPin(entity); return; }
    if (action === "cancel-pin")  { this._resetUI(); this._render(); return; }

    // Disarm
    if (action === "disarm") {
      if (hasCode) {
        this._startPinEntry({ service: "alarm_disarm", labelKey: "disarm" });
      } else {
        this._hass.callService("alarm_control_panel", "alarm_disarm", { entity_id: entity });
      }
      return;
    }

    // Arm actions
    const armDef = ARM_ACTIONS.find(a => a.key === action);
    if (armDef) {
      if (hasCode && codeArmRequired) {
        this._startPinEntry({ service: armDef.service, labelKey: armDef.labelKey });
      } else {
        // Arm the auto-force intent as this card dispatches the arm, so a
        // resulting forceable exception is handled without the user.
        this._pendingAutoForce = this._autoForceActive();
        this._autoForceArming = false;
        this._suppressArmPrompt(entity);
        this._clearAutoForceOnReject(
          this._hass.callService("alarm_control_panel", armDef.service, { entity_id: entity }),
        );
      }
    }
  }

  _submitPin(entity) {
    if (!this._pendingAction || !this._pin) return;
    // Only arm the auto-force intent for arm commands, never for disarm.
    const isArm = this._pendingAction.service.startsWith("alarm_arm_");
    if (isArm) {
      this._pendingAutoForce = this._autoForceActive();
      this._autoForceArming = false;
      this._suppressArmPrompt(entity);
    }
    const result = this._hass.callService("alarm_control_panel", this._pendingAction.service, {
      entity_id: entity,
      code: this._pin,
    });
    if (isArm) this._clearAutoForceOnReject(result);
    this._resetUI();
    this._render();
  }

  // ── Styles ──────────────────────────────────────────────────────────────────
  _styles(cfg) {
    return `
      ha-card { overflow: hidden; }

      .missing { padding: 16px; color: var(--error-color); }

      .unavailable-msg {
        padding: 8px 0 12px;
        font-size: 0.85em;
        color: var(--secondary-text-color);
        text-align: center;
      }
      .waf-banner {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        margin: 4px 0 8px;
        border-radius: 8px;
        font-size: 0.85em;
        background: var(--warning-color, #FF9800);
        color: var(--text-primary-color, #fff);
      }
      .waf-banner ha-icon {
        --mdc-icon-size: 18px;
        flex-shrink: 0;
      }
      .stale-banner {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        margin: 4px 0 8px;
        border-radius: 8px;
        font-size: 0.85em;
        background: var(--info-color, #039BE5);
        color: var(--text-primary-color, #fff);
      }
      .stale-banner ha-icon {
        --mdc-icon-size: 18px;
        flex-shrink: 0;
      }

      /* colour accent strip at top */
      .top-bar {
        height: 4px;
        background: ${cfg.color};
        transition: background 0.4s;
      }

      .content { padding: var(--ha-card-padding, 16px); }

      /* ── Header ── */
      .header {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 20px;
      }
      .icon-wrap {
        width: 48px; height: 48px;
        border-radius: 50%;
        background: color-mix(in srgb, ${cfg.color} 13%, transparent);
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
        cursor: pointer;
        touch-action: none;
      }
      .icon-wrap ha-icon {
        --mdc-icon-size: 28px;
        color: ${cfg.color};
      }
      .entity-name {
        font-size: 1.05em;
        font-weight: 600;
        color: var(--primary-text-color);
        line-height: 1.3;
      }
      .state-pill {
        display: inline-block;
        margin-top: 3px;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75em;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        background: color-mix(in srgb, ${cfg.color} 13%, transparent);
        color: ${cfg.color};
      }
      .title-block { flex: 1; }
      /* Wraps state-pill + refresh-btn on the same row inside title-block,
         keeping the refresh button away from the card's top-right corner
         (where HA's modal close X appears when the card is opened from a
         mushroom chip or badge). */
      .state-row {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-top: 3px;
      }
      .state-pill { margin-top: 0; }
      .refresh-btn {
        width: 28px; height: 28px;
        border: none;
        border-radius: 50%;
        background: transparent;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
        transition: background 0.15s, transform 0.1s;
      }
      .refresh-btn:hover { background: var(--secondary-background-color); }
      .refresh-btn:active { transform: scale(0.9); }
      .refresh-btn ha-icon {
        --mdc-icon-size: 18px;
        color: var(--secondary-text-color);
      }
      .refresh-btn.spinning ha-icon {
        animation: spin 1s linear infinite;
      }
      @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }

      /* ── Buttons ── */
      .btn-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
        gap: 8px;
      }
      .btn {
        padding: 10px 8px;
        border: none;
        border-radius: 10px;
        font-size: 0.85em;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        transition: filter 0.15s, transform 0.1s;
        letter-spacing: 0.02em;
      }
      .btn:active { transform: scale(0.96); }
      .btn-arm {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
      }
      .btn-arm:hover    { filter: brightness(1.1); }
      .btn-disarm {
        background: var(--error-color, #F44336);
        color: var(--text-primary-color, #fff);
        grid-column: 1 / -1;
      }
      .btn-disarm:hover { filter: brightness(1.1); }

      /* ── Auto-force-arm tick box ── */
      .auto-force-toggle {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
        font-size: 0.8em;
        color: var(--secondary-text-color);
        cursor: pointer;
        user-select: none;
      }
      .auto-force-checkbox {
        flex-shrink: 0;
        width: 16px;
        height: 16px;
        accent-color: var(--primary-color);
        cursor: pointer;
      }

      #arm-exception-slot { margin-bottom: var(--ha-space-4, 16px); }

      /* Cancel button used by PIN/code entry. The arming-exception actions
         are native ha-control-button elements owned by the shared component. */
      .btn-cancel-force {
        flex: 1;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
      }
      .btn-cancel-force:hover { background: var(--divider-color); }

      /* ── PIN entry ── */
      .pin-section { margin-bottom: 4px; }
      .pin-label {
        font-size: 0.85em;
        color: var(--secondary-text-color);
        margin-bottom: 8px;
        text-align: center;
      }
      .keypad {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
        max-width: 240px;
        margin: 0 auto;
      }
      .key {
        padding: 14px 0;
        border: none;
        border-radius: 10px;
        font-size: 1.1em;
        font-weight: 500;
        font-family: inherit;
        cursor: pointer;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        transition: background 0.15s, transform 0.1s;
      }
      .key:hover   { background: var(--divider-color); }
      .key:active  { transform: scale(0.94); }
      .key-cancel  { color: var(--error-color, #F44336); }
      .key-del     { color: var(--primary-color); }
      .pin-input {
        display: block; width: 100%; box-sizing: border-box;
        text-align: center; font-size: 1.5em; letter-spacing: 0.3em;
        font-family: inherit;
        padding: 8px; margin-bottom: 8px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        background: var(--ha-card-background, var(--card-background-color, #fff));
        color: var(--primary-text-color);
        outline: none;
      }
      .pin-confirm {
        display: block;
        width: 100%;
        max-width: 240px;
        margin: 10px auto 0;
        box-sizing: border-box;
      }

      /* text code input */
      .code-input {
        width: 100%;
        box-sizing: border-box;
        padding: 10px 14px;
        border: 1.5px solid var(--divider-color);
        border-radius: 8px;
        font-size: 1em;
        font-family: inherit;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        margin-bottom: 12px;
        outline: none;
      }
      .code-input:focus { border-color: var(--primary-color); }
      .text-pin-btns { display: flex; gap: 8px; }
    `;
  }

  getCardSize() {
    if (this._uiState === "pin") return 6;
    const stateObj = this._hass?.states[this._config?.entity];
    if (stateObj?.attributes?.arm_exception_active || stateObj?.attributes?.force_arm_available) return 5;
    return 3;
  }

  static getConfigElement() {
    return document.createElement("verisure-owa-alarm-card-editor");
  }

  static getStubConfig(hass) {
    const entities = Object.keys(hass.states).filter(e => e.startsWith("alarm_control_panel."));
    return { entity: entities[0] || "" };
  }
}

// ── Config editor ─────────────────────────────────────────────────────────────

class VerisureOwaAlarmCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    // Suppresses the immediate parent round-trip on our own writes.
    this._internalWriteInFlight = false;
  }

  setConfig(config) {
    const prev = this._config;
    this._config = { ...config };
    // Structural changes (different entity / card type) always re-render —
    // the Arm modes checkboxes and gesture dropdowns are derived from the
    // entity's `supported_features`, so an in-editor entity switch must
    // refresh them even though it routes through _fireChanged.
    const structural = prev?.entity !== config.entity || prev?.type !== config.type;
    if (this._internalWriteInFlight && !structural) {
      this._internalWriteInFlight = false;
      return;
    }
    this._internalWriteInFlight = false;
    // External call (YAML edit, parent reset, initial mount) or internal
    // structural change. _render no-ops until `hass` arrives, so a pre-hass
    // mount is safe.
    this._render();
  }

  set hass(hass) {
    const alarmEntities = Object.keys(hass.states)
      .filter(e => e.startsWith("alarm_control_panel."))
      .sort()
      .join(",");
    const changed = alarmEntities !== this._lastEntities;
    this._hass = hass;
    if (changed || !this._lastEntities) {
      this._lastEntities = alarmEntities;
      this._render();
    }
  }

  _buildArmModesSection(lang) {
    const section = document.createElement("div");
    section.className = "arm-modes-section";

    const title = document.createElement("p");
    title.className = "section-title";
    title.textContent = _t(lang, "editor_arm_modes");
    section.appendChild(title);

    const hint = document.createElement("div");
    hint.className = "section-hint";
    hint.textContent = _t(lang, "editor_arm_modes_hint");
    section.appendChild(hint);

    const features = this._hass?.states[this._config.entity]?.attributes?.supported_features || 0;
    const { supported } = _filteredArmActions(features);

    if (supported.length === 0) {
      const empty = document.createElement("div");
      empty.className = "arm-modes-empty";
      empty.textContent = _t(lang, "editor_arm_modes_empty");
      section.appendChild(empty);
      return section;
    }

    const configStates = this._config.states;
    const supportedKeys = supported.map(a => a.key);

    const list = document.createElement("div");
    list.className = "arm-modes-list";

    supported.forEach(action => {
      const label   = document.createElement("label");
      const cb      = document.createElement("input");
      cb.type       = "checkbox";
      cb.dataset.armKey = action.key;
      cb.checked    = !Array.isArray(configStates) || configStates.includes(action.key);

      const text = document.createElement("span");
      text.textContent = _t(lang, action.labelKey);

      label.appendChild(cb);
      label.appendChild(text);
      list.appendChild(label);
    });
    section.appendChild(list);

    list.addEventListener("change", () => {
      const checked = Array.from(list.querySelectorAll("input[type='checkbox']"))
        .filter(cb => cb.checked)
        .map(cb => cb.dataset.armKey);

      // When every supported mode is checked, drop the `states` key so the
      // YAML stays minimal and naturally tracks future supported_features
      // expansions.
      const allChecked = checked.length === supportedKeys.length
        && supportedKeys.every(k => checked.includes(k));

      const nextConfig = allChecked
        ? (() => { const { states: _, ...rest } = this._config; return rest; })()
        : { ...this._config, states: checked };

      // Scrub any gesture whose `arm_state` is no longer in the user's
      // explicit non-empty subset — otherwise its dropdown would render a
      // value missing from its options. An empty list falls back to "all
      // supported" for the dropdown anyway, so saved arm_state stays valid.
      const nextStates = nextConfig.states;
      if (Array.isArray(nextStates) && nextStates.length > 0) {
        const newDefault = defaultArmState(this._hass, this._config.entity, nextStates);
        for (const gestureKey of GESTURE_KEYS) {
          const gestureAction = nextConfig[gestureKey];
          if (
            gestureAction?.action === "arm_or_disarm"
            && gestureAction.arm_state
            && !nextStates.includes(gestureAction.arm_state)
          ) {
            nextConfig[gestureKey] = { ...gestureAction, arm_state: newDefault };
          }
        }
      }

      this._config = nextConfig;
      this._fireChanged();
      this._populateGestureSlot();
    });

    return section;
  }

  _buildGestureSection(gesture, title, defaults) {
    const lang          = this._hass?.language || "en";
    const configKey     = `${gesture}_action`;
    const current       = this._config[configKey] || defaults;
    const currentAction = current.action || defaults.action;

    const features     = this._hass?.states[this._config.entity]?.attributes?.supported_features || 0;
    const configStates = this._config.states;
    const { supported, filtered } = _filteredArmActions(features, configStates);
    // When the user has explicitly hidden every supported mode the dropdown
    // has no honest options — render a helper hint instead. Otherwise fall
    // back through filtered → supported → ARM_ACTIONS so the dropdown is
    // never empty for non-user reasons (e.g. entity not loaded).
    const userHiddenAll = Array.isArray(configStates) && filtered.length === 0;
    let armOptions = [];
    if (!userHiddenAll) {
      armOptions = filtered.length > 0   ? filtered
                 : supported.length > 0  ? supported
                 :                         ARM_ACTIONS;
    }

    let actionValue   = currentAction;
    let armStateValue = userHiddenAll
      ? undefined
      : (current.arm_state || defaultArmState(this._hass, this._config.entity, configStates));

    const section = document.createElement("div");
    section.className = "gesture-section";

    // ── Action selector (ha-form with select) ────────────────────────────────
    const actionForm = document.createElement("ha-form");
    actionForm.hass   = this._hass;
    actionForm.data   = { action: actionValue };
    actionForm.schema = [{
      name: "action",
      selector: {
        select: {
          mode: "dropdown",
          options: [
            { value: "none",           label: _t(lang, "editor_action_none") },
            { value: "more-info",      label: _t(lang, "editor_action_more_info") },
            { value: "navigate",       label: _t(lang, "editor_action_navigate") },
            { value: "perform-action", label: _t(lang, "editor_action_perform") },
            { value: "arm_or_disarm",  label: _t(lang, "editor_action_arm_or_disarm") },
          ],
        },
      },
    }];
    actionForm.computeLabel = () => title;
    section.appendChild(actionForm);

    // ── Navigate sub-fields ──────────────────────────────────────────────────
    const navFields = document.createElement("div");
    navFields.className = "conditional-fields";
    navFields.style.display = currentAction === "navigate" ? "" : "none";
    const navForm = document.createElement("ha-form");
    navForm.hass   = this._hass;
    navForm.data   = { navigation_path: current.navigation_path || "" };
    navForm.schema = [{ name: "navigation_path", selector: { navigation: {} } }];
    navForm.computeLabel = () => _t(lang, "editor_navigation_path");
    navFields.appendChild(navForm);
    section.appendChild(navFields);

    // ── Perform-action sub-fields ────────────────────────────────────────────
    const perfFields = document.createElement("div");
    perfFields.className = "conditional-fields";
    perfFields.style.display = currentAction === "perform-action" ? "" : "none";
    const perfInput = document.createElement("ha-textfield");
    perfInput.label       = _t(lang, "editor_perform_action");
    perfInput.placeholder = "domain.service";
    perfInput.value       = current.perform_action || "";
    perfInput.style.width = "100%";
    const perfDataInput = document.createElement("ha-textfield");
    perfDataInput.label       = _t(lang, "editor_perform_data");
    perfDataInput.placeholder = '{"entity_id": "light.living_room"}';
    perfDataInput.value       = current.data ? JSON.stringify(current.data) : "";
    perfDataInput.style.width = "100%";
    perfFields.appendChild(perfInput);
    perfFields.appendChild(perfDataInput);
    section.appendChild(perfFields);

    // ── Arm-or-disarm sub-fields ─────────────────────────────────────────────
    const armFields = document.createElement("div");
    armFields.className = "conditional-fields";
    armFields.style.display = currentAction === "arm_or_disarm" ? "" : "none";
    let armForm = null;
    if (userHiddenAll) {
      const hint = document.createElement("div");
      hint.className = "arm-modes-empty";
      hint.textContent = _t(lang, "editor_arm_state_no_modes");
      armFields.appendChild(hint);
    } else {
      armForm = document.createElement("ha-form");
      armForm.hass   = this._hass;
      armForm.data   = { arm_state: armStateValue };
      armForm.schema = [{
        name: "arm_state",
        selector: {
          select: {
            mode: "dropdown",
            options: armOptions.map(a => ({
              value: a.key,
              label: a.key.replace("arm_", "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
            })),
          },
        },
      }];
      armForm.computeLabel = () => _t(lang, "editor_arm_state");
      armFields.appendChild(armForm);
    }
    section.appendChild(armFields);

    // Show/hide conditional fields
    const showFields = (action) => {
      navFields.style.display  = action === "navigate"        ? "" : "none";
      perfFields.style.display = action === "perform-action"  ? "" : "none";
      armFields.style.display  = action === "arm_or_disarm"   ? "" : "none";
    };

    // Write config
    const writeConfig = () => {
      const cfg = { action: actionValue };
      if (actionValue === "navigate") {
        const path = (navForm.data?.navigation_path || "").trim();
        if (path) cfg.navigation_path = path;
      }
      if (actionValue === "perform-action") {
        const call = perfInput.value.trim();
        if (call) cfg.perform_action = call;
        const raw = perfDataInput.value.trim();
        if (raw) { try { cfg.data = JSON.parse(raw); } catch (_) {} }
      }
      if (actionValue === "arm_or_disarm" && armStateValue) cfg.arm_state = armStateValue;
      this._config = { ...this._config, [configKey]: cfg };
      this._fireChanged();
    };

    actionForm.addEventListener("value-changed", (e) => {
      const v = e.detail?.value?.action;
      if (v !== undefined) {
        actionValue = v;
        actionForm.data = { action: actionValue };
        showFields(actionValue);
        writeConfig();
      }
    });
    if (armForm) {
      armForm.addEventListener("value-changed", (e) => {
        const v = e.detail?.value?.arm_state;
        if (v !== undefined) {
          armStateValue = v;
          armForm.data = { arm_state: armStateValue };
          writeConfig();
        }
      });
    }
    navForm.addEventListener("value-changed", (e) => {
      navForm.data = e.detail.value;
      writeConfig();
    });
    perfInput.addEventListener("input", writeConfig);
    perfDataInput.addEventListener("input", writeConfig);

    return section;
  }

  _render() {
    if (!this._hass) return;

    const lang = this._hass.language || "en";
    const colors = this._config.colors || {};

    // Shell with slots for HA native components + static color section
    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
        ha-entity-picker, ha-textfield { width: 100%; display: block; }
        .section-hint {
          font-size: 0.8em;
          color: var(--secondary-text-color);
        }
        /* Flat 3-column grid: label | picker | reset — all rows perfectly aligned */
        .color-grid {
          display: grid;
          grid-template-columns: 1fr 44px 28px;
          gap: 10px 12px;
          align-items: center;
          margin-top: 10px;
        }
        input[type="color"] {
          width: 44px;
          height: 28px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          cursor: pointer;
          padding: 2px;
          background: var(--secondary-background-color);
          display: block;
        }
        .reset-btn {
          background: none;
          border: none;
          cursor: pointer;
          color: var(--secondary-text-color);
          font-size: 1em;
          padding: 0;
          border-radius: 4px;
          width: 24px;
          height: 24px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .reset-btn:hover { color: var(--error-color); }
        .reset-btn[hidden] { visibility: hidden; display: flex; }
        #gesture-slot { display: flex; flex-direction: column; gap: 16px; }
        .gesture-section { display: flex; flex-direction: column; }
        .gesture-section ha-form, .gesture-section ha-textfield { display: block; width: 100%; }
        .conditional-fields {
          display: flex;
          flex-direction: column;
        }
        .arm-modes-section {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .arm-modes-section .section-title {
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .arm-modes-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin-top: 4px;
        }
        .arm-modes-list label {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          padding: 4px 0;
        }
        .arm-modes-list input[type="checkbox"] {
          margin: 0;
        }
        .arm-modes-empty {
          font-style: italic;
          color: var(--secondary-text-color);
          padding: 4px 0;
        }
      </style>
      <div class="editor">
        <ha-form id="entity-form"></ha-form>
        <div id="name-slot"></div>
        <div id="arm-modes-slot"></div>
        <div id="colors-slot"></div>
        <div id="gesture-slot"></div>
      </div>`;

    // ── State colors (ha-expansion-panel) ────────────────────────────────────
    const colorsSlot = this.shadowRoot.getElementById("colors-slot");
    const expansionPanel = document.createElement("ha-expansion-panel");
    expansionPanel.header = _t(lang, "editor_state_colors");
    const colorsContent = document.createElement("div");
    colorsContent.style.padding = "8px 0 4px 0";
    colorsContent.innerHTML = `
      <div class="section-hint">${_t(lang, "editor_colors_hint")}</div>
      <div class="color-grid">
        ${COLOR_EDITOR_STATES.map((state) => {
          const override = colors[state];
          const pickerVal = override || STATE_COLOR_DEFAULTS[state] || "#808080";
          return `
            <span>${_t(lang, STATE_LABEL_KEYS[state] || state)}</span>
            <input type="color" data-state="${state}" value="${pickerVal}" />
            <button class="reset-btn" data-reset="${state}" title="${_t(lang, "editor_reset_default")}" ${override ? "" : "hidden"}>↺</button>`;
        }).join("")}
      </div>`;
    expansionPanel.appendChild(colorsContent);
    colorsSlot.appendChild(expansionPanel);

    // ── Entity picker (via ha-form — handles lazy-loading internally) ────────
    const entityForm = this.shadowRoot.getElementById("entity-form");
    entityForm.hass = this._hass;
    entityForm.data = { entity: this._config.entity || "" };
    entityForm.schema = [
      {
        name: "entity",
        selector: {
          entity: { domain: "alarm_control_panel" },
        },
      },
    ];
    entityForm.computeLabel = () => _t(lang, "editor_entity");
    entityForm.addEventListener("value-changed", (e) => {
      const newEntity = e.detail.value?.entity;
      if (newEntity !== undefined) {
        this._config = { ...this._config, entity: newEntity };
        this._fireChanged();
      }
    });

    // ── Name field (HA native) ─────────────────────────────────────────────
    const nameTf = document.createElement("ha-textfield");
    nameTf.label = _t(lang, "editor_name");
    nameTf.value = this._config.name || "";
    nameTf.placeholder = _t(lang, "editor_name_placeholder");
    nameTf.addEventListener("input", (e) => {
      const val = e.target.value.trim();
      if (val) {
        this._config = { ...this._config, name: val };
      } else {
        const { name: _, ...rest } = this._config;
        this._config = rest;
      }
      this._fireChanged();
    });
    this.shadowRoot.getElementById("name-slot").appendChild(nameTf);

    // ── Arm modes section ────────────────────────────────────────────────────
    const armModesSlot = this.shadowRoot.getElementById("arm-modes-slot");
    if (armModesSlot) {
      armModesSlot.appendChild(this._buildArmModesSection(lang));
    }

    // Color pickers
    this.shadowRoot.querySelectorAll("input[type='color'][data-state]").forEach(input => {
      input.addEventListener("change", (e) => {
        const state = e.target.dataset.state;
        const newColors = { ...(this._config.colors || {}), [state]: e.target.value };
        this._config = { ...this._config, colors: newColors };
        // Show reset button for this state
        const resetBtn = this.shadowRoot.querySelector(`.reset-btn[data-reset="${state}"]`);
        if (resetBtn) resetBtn.removeAttribute("hidden");
        this._fireChanged();
      });
    });

    // Reset buttons — remove override and go back to default
    this.shadowRoot.querySelectorAll(".reset-btn[data-reset]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const state = e.target.dataset.reset;
        const { [state]: _, ...remainingColors } = this._config.colors || {};
        if (Object.keys(remainingColors).length === 0) {
          const { colors: __, ...rest } = this._config;
          this._config = rest;
        } else {
          this._config = { ...this._config, colors: remainingColors };
        }
        // Reset picker to default value and hide reset button
        const picker = this.shadowRoot.querySelector(`input[type="color"][data-state="${state}"]`);
        if (picker) picker.value = STATE_COLOR_DEFAULTS[state] || "#808080";
        btn.setAttribute("hidden", "");
        this._fireChanged();
      });
    });

    // ── Gesture action sections ──────────────────────────────────────────────
    this._populateGestureSlot();
  }

  // Build (or rebuild) the three gesture sections into the gesture-slot.
  // Extracted so the arm-modes checkbox handler can refresh the dropdowns
  // live when the user toggles which arm states are available — otherwise
  // each gesture's `arm_state` dropdown shows a stale options list until
  // the editor is closed and reopened.
  _populateGestureSlot() {
    const gestureSlot = this.shadowRoot.getElementById("gesture-slot");
    if (!gestureSlot) return;
    gestureSlot.innerHTML = "";

    const tapDefaults = { action: "none" };
    const holdDefaults = { action: "none" };
    const dblDefaults  = { action: "none" };

    const lang = this._hass?.language || "en";
    gestureSlot.appendChild(this._buildGestureSection("tap",        _t(lang, "editor_tap_action"),        tapDefaults));
    gestureSlot.appendChild(this._buildGestureSection("hold",       _t(lang, "editor_hold_action"),       holdDefaults));
    gestureSlot.appendChild(this._buildGestureSection("double_tap", _t(lang, "editor_double_tap_action"), dblDefaults));
  }


  _fireChanged() {
    this._internalWriteInFlight = true;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
    queueMicrotask(() => { this._internalWriteInFlight = false; });
  }
}

/* v8 ignore start -- defensive duplicate-registration guards;
   the "already defined" branches can't be hit in single-process tests. */
if (!customElements.get("verisure-owa-alarm-card")) {
  customElements.define("verisure-owa-alarm-card", VerisureOwaAlarmCard);
}
if (!customElements.get("verisure-owa-alarm-card-editor")) {
  customElements.define("verisure-owa-alarm-card-editor", VerisureOwaAlarmCardEditor);
}
if (!customElements.get("securitas-alarm-card")) {
  customElements.define("securitas-alarm-card",
    _makeLegacyShim(VerisureOwaAlarmCard));
}
if (!customElements.get("securitas-alarm-card-editor")) {
  customElements.define("securitas-alarm-card-editor",
    _makeLegacyShim(VerisureOwaAlarmCardEditor));
}

window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === "verisure-owa-alarm-card")) {
  window.customCards.push({
    type:        "verisure-owa-alarm-card",
    name:        TRANSLATIONS.en.card_name,
    description: TRANSLATIONS.en.card_description,
    preview:     false,
    getEntitySuggestion: alarmEntitySuggestion,
  });
}
/* v8 ignore stop */
