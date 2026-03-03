/**
 * Securitas Direct Alarm Card
 *
 * A polished custom Lovelace card for the Securitas Direct integration.
 *
 * Features:
 *  - Reads `supported_features` from the entity — only shows arm buttons
 *    for modes that are actually configured (Away, Home, Night, Custom)
 *  - PIN / code support: numeric keypad for digit codes, text input for
 *    alphanumeric codes; respects `code_arm_required` and always asks for
 *    code on Disarm when a code is configured
 *  - Force-arm section: automatically appears when `force_arm_available`
 *    is true, lists open sensors from `arm_exceptions`, provides
 *    Force Arm and Cancel buttons — no helper entity required
 *  - Styling aligned with Home Assistant's design language (CSS variables)
 *
 * Card config:
 *   type: custom:securitas-alarm-card
 *   entity: alarm_control_panel.YOUR_PANEL_ID
 *   name: My Alarm          # optional — overrides friendly_name
 */

// ── AlarmControlPanelEntityFeature bitmask values ────────────────────────────
const FEATURE = {
  ARM_HOME: 1,
  ARM_AWAY: 2,
  ARM_NIGHT: 4,
  ARM_CUSTOM_BYPASS: 16,
};

// ── Per-state visual config ───────────────────────────────────────────────────
const STATE_CFG = {
  disarmed:           { icon: "mdi:shield-off-outline",  color: "var(--success-color,#4CAF50)",  label: "Disarmed" },
  armed_away:         { icon: "mdi:shield-lock",         color: "var(--error-color,#F44336)",    label: "Armed Away" },
  armed_home:         { icon: "mdi:shield-home",         color: "var(--warning-color,#FF9800)",  label: "Armed Home" },
  armed_night:        { icon: "mdi:shield-moon",         color: "#9C27B0",                       label: "Armed Night" },
  armed_custom_bypass:{ icon: "mdi:shield-star",         color: "#00BCD4",                       label: "Armed Custom" },
  arming:             { icon: "mdi:shield-sync-outline", color: "var(--warning-color,#FF9800)",  label: "Arming…" },
  pending:            { icon: "mdi:shield-alert-outline",color: "var(--warning-color,#FF9800)",  label: "Pending" },
  triggered:          { icon: "mdi:shield-alert",        color: "var(--error-color,#F44336)",    label: "TRIGGERED" },
};

// ── Arm action definitions ────────────────────────────────────────────────────
const ARM_ACTIONS = [
  { key: "arm_away",          label: "Arm Away",    feature: FEATURE.ARM_AWAY,         service: "alarm_arm_away" },
  { key: "arm_home",          label: "Arm Home",    feature: FEATURE.ARM_HOME,         service: "alarm_arm_home" },
  { key: "arm_night",         label: "Arm Night",   feature: FEATURE.ARM_NIGHT,        service: "alarm_arm_night" },
  { key: "arm_custom_bypass", label: "Arm Custom",  feature: FEATURE.ARM_CUSTOM_BYPASS,service: "alarm_arm_custom_bypass" },
];

// ─────────────────────────────────────────────────────────────────────────────

class SecuritasAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._uiState = "normal";   // normal | pin | force_arm
    this._pendingAction = null; // { service, label }
    this._pin = "";
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    // Only re-render if the relevant entity state/attributes changed
    const stateObj = hass.states[this._config.entity];
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.force_arm_available}|${(stateObj.attributes.arm_exceptions||[]).join(",")}`
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

  // ── Main render ─────────────────────────────────────────────────────────────
  _render() {
    if (!this._hass || !this._config) return;

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div class="missing">Entity not found: ${this._config.entity}</div></ha-card>`;
      return;
    }

    const state    = stateObj.state;
    const attrs    = stateObj.attributes;
    const cfg      = STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)", label: state };
    const name     = this._config.name || attrs.friendly_name || this._config.entity;
    const features = attrs.supported_features || 0;

    const forceArmAvailable = attrs.force_arm_available === true;
    const openSensors       = attrs.arm_exceptions || [];

    const codeFormat      = attrs.code_format || null;        // "number" | "text" | null
    const codeArmRequired = attrs.code_arm_required === true; // need code to arm?
    const hasCode         = !!codeFormat;

    // Determine which arm buttons to show
    const availableArmActions = ARM_ACTIONS.filter(a => features & a.feature);
    const isArmed = !["disarmed", "arming", "pending", "triggered"].includes(state);

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
              <div class="entity-name">${name}</div>
              <div class="state-pill">${cfg.label}</div>
            </div>
          </div>

          <!-- ── Force arm section ── -->
          ${forceArmAvailable ? this._renderForceArm(openSensors) : ""}

          <!-- ── PIN entry ── -->
          ${this._uiState === "pin" ? this._renderPin(codeFormat) : ""}

          <!-- ── Normal buttons (hidden during pin entry) ── -->
          ${this._uiState === "normal" && !forceArmAvailable ? `
            <div class="btn-grid">
              ${isArmed
                ? `<button class="btn btn-disarm" data-action="disarm">Disarm</button>`
                : availableArmActions.map(a =>
                    `<button class="btn btn-arm" data-action="${a.key}">${a.label}</button>`
                  ).join("")
              }
            </div>` : ""}

        </div>
      </ha-card>`;

    this._attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed);
  }

  // ── Force arm section ───────────────────────────────────────────────────────
  _renderForceArm(sensors) {
    const list = sensors.length
      ? `<ul class="sensor-list">${sensors.map(s => `<li>${s}</li>`).join("")}</ul>`
      : "";
    return `
      <div class="force-section">
        <div class="force-title">
          <ha-icon icon="mdi:alert"></ha-icon>
          Open sensor(s) — arm anyway?
        </div>
        ${list}
        <div class="force-btns">
          <button class="btn btn-force" data-action="force_arm">Force Arm</button>
          <button class="btn btn-cancel-force" data-action="cancel_force">Cancel</button>
        </div>
      </div>`;
  }

  // ── PIN entry section ───────────────────────────────────────────────────────
  _renderPin(codeFormat) {
    const masked = "●".repeat(this._pin.length) || " ";
    const label  = this._pendingAction?.label || "action";

    if (codeFormat === "number") {
      return `
        <div class="pin-section">
          <div class="pin-label">Enter PIN to ${label}</div>
          <div class="pin-display">${masked}</div>
          <div class="keypad">
            ${[1,2,3,4,5,6,7,8,9].map(n =>
              `<button class="key" data-key="${n}">${n}</button>`
            ).join("")}
            <button class="key key-cancel" data-key="cancel">✕</button>
            <button class="key" data-key="0">0</button>
            <button class="key key-del" data-key="del">⌫</button>
          </div>
        </div>`;
    }

    // Text code
    return `
      <div class="pin-section">
        <div class="pin-label">Enter code to ${label}</div>
        <input class="code-input" type="password" autocomplete="off"
               placeholder="Code" value="${this._pin}" id="code-input" />
        <div class="text-pin-btns">
          <button class="btn btn-arm" data-action="confirm-pin">Confirm</button>
          <button class="btn btn-cancel-force" data-action="cancel-pin">Cancel</button>
        </div>
      </div>`;
  }

  // ── Event listeners ─────────────────────────────────────────────────────────
  _attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed) {
    const entity = this._config.entity;

    // Arm / Disarm buttons
    this.shadowRoot.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        this._handleAction(action, stateObj, codeFormat, codeArmRequired, hasCode, isArmed, entity);
      });
    });

    // Numeric keypad
    this.shadowRoot.querySelectorAll("[data-key]").forEach(key => {
      key.addEventListener("click", () => {
        const k = key.dataset.key;
        if (k === "cancel") { this._resetUI(); this._render(); return; }
        if (k === "del")    { this._pin = this._pin.slice(0, -1); this._render(); return; }
        this._pin += k;
        this._render();
        // Auto-submit after reasonable PIN length (≥4 digits)
        if (this._pin.length >= 4) this._submitPin(entity);
      });
    });

    // Text code input
    const codeInput = this.shadowRoot.getElementById("code-input");
    if (codeInput) {
      codeInput.focus();
      codeInput.addEventListener("input", e => { this._pin = e.target.value; });
      codeInput.addEventListener("keydown", e => {
        if (e.key === "Enter") this._submitPin(entity);
      });
    }
  }

  _handleAction(action, stateObj, codeFormat, codeArmRequired, hasCode, isArmed, entity) {
    // Force-arm / cancel
    if (action === "force_arm") {
      this._hass.callService("securitas", "force_arm", { entity_id: entity });
      return;
    }
    if (action === "cancel_force") {
      this._hass.callService("securitas", "force_arm_cancel", { entity_id: entity });
      return;
    }
    if (action === "confirm-pin") { this._submitPin(entity); return; }
    if (action === "cancel-pin")  { this._resetUI(); this._render(); return; }

    // Disarm
    if (action === "disarm") {
      if (hasCode) {
        this._startPinEntry({ service: "alarm_disarm", label: "Disarm" });
      } else {
        this._hass.callService("alarm_control_panel", "alarm_disarm", { entity_id: entity });
      }
      return;
    }

    // Arm actions
    const armDef = ARM_ACTIONS.find(a => a.key === action);
    if (armDef) {
      if (hasCode && codeArmRequired) {
        this._startPinEntry({ service: armDef.service, label: armDef.label });
      } else {
        this._hass.callService("alarm_control_panel", armDef.service, { entity_id: entity });
      }
    }
  }

  _submitPin(entity) {
    if (!this._pendingAction || !this._pin) return;
    this._hass.callService("alarm_control_panel", this._pendingAction.service, {
      entity_id: entity,
      code: this._pin,
    });
    this._resetUI();
    this._render();
  }

  // ── Styles ──────────────────────────────────────────────────────────────────
  _styles(cfg) {
    return `
      ha-card { overflow: hidden; }

      .missing { padding: 16px; color: var(--error-color); }

      /* colour accent strip at top */
      .top-bar {
        height: 4px;
        background: ${cfg.color};
        transition: background 0.4s;
      }

      .content { padding: 16px; }

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
        background: ${cfg.color}22;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
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
        background: ${cfg.color}22;
        color: ${cfg.color};
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
        color: #fff;
        grid-column: 1 / -1;
      }
      .btn-disarm:hover { filter: brightness(1.1); }

      /* ── Force arm section ── */
      .force-section {
        border-radius: 12px;
        background: var(--warning-color, #FF9800)18;
        border: 1.5px solid var(--warning-color, #FF9800);
        padding: 14px;
        margin-bottom: 16px;
      }
      .force-title {
        display: flex; align-items: center; gap: 8px;
        font-weight: 600;
        font-size: 0.9em;
        color: var(--warning-color, #FF9800);
        margin-bottom: 8px;
      }
      .force-title ha-icon {
        --mdc-icon-size: 18px;
        color: var(--warning-color, #FF9800);
        flex-shrink: 0;
      }
      .sensor-list {
        list-style: none; padding: 0; margin: 0 0 12px 26px;
      }
      .sensor-list li {
        font-size: 0.85em;
        color: var(--secondary-text-color);
        padding: 2px 0;
      }
      .sensor-list li::before {
        content: "• ";
        color: var(--warning-color, #FF9800);
        font-weight: bold;
      }
      .force-btns {
        display: flex; gap: 8px;
      }
      .btn-force {
        flex: 2;
        background: var(--warning-color, #FF9800);
        color: #fff;
      }
      .btn-force:hover { filter: brightness(1.1); }
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
      .pin-display {
        text-align: center;
        font-size: 1.6em;
        letter-spacing: 0.25em;
        min-height: 2em;
        padding: 6px;
        background: var(--secondary-background-color);
        border-radius: 8px;
        margin-bottom: 12px;
        color: var(--primary-text-color);
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
        cursor: pointer;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        transition: background 0.15s, transform 0.1s;
      }
      .key:hover   { background: var(--divider-color); }
      .key:active  { transform: scale(0.94); }
      .key-cancel  { color: var(--error-color, #F44336); }
      .key-del     { color: var(--primary-color); }

      /* text code input */
      .code-input {
        width: 100%;
        box-sizing: border-box;
        padding: 10px 14px;
        border: 1.5px solid var(--divider-color);
        border-radius: 8px;
        font-size: 1em;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        margin-bottom: 12px;
        outline: none;
      }
      .code-input:focus { border-color: var(--primary-color); }
      .text-pin-btns { display: flex; gap: 8px; }
    `;
  }

  getCardSize() { return 3; }

  static getStubConfig() {
    return { entity: "alarm_control_panel.your_panel_id" };
  }
}

customElements.define("securitas-alarm-card", SecuritasAlarmCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        "securitas-alarm-card",
  name:        "Securitas Alarm Card",
  description: "Full-featured alarm card for Securitas Direct: dynamic arm modes, PIN support, force-arm for open sensors.",
  preview:     false,
});
