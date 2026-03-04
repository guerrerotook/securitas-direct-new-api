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
 *  - Handles `unavailable` and `unknown` entity states gracefully
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

// ── Translations ─────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    disarmed: "Disarmed", armed_away: "Armed Away", armed_home: "Armed Home",
    armed_night: "Armed Night", armed_custom: "Armed Custom",
    arming: "Arming\u2026", pending: "Pending", triggered: "TRIGGERED",
    unavailable: "Unavailable", unknown: "Unknown",
    arm_away: "Arm Away", arm_home: "Arm Home", arm_night: "Arm Night",
    arm_custom: "Arm Custom", disarm: "Disarm",
    force_arm: "Force Arm", cancel: "Cancel",
    open_sensors: "Open sensor(s) \u2014 arm anyway?",
    enter_pin: "Enter PIN to {action}", enter_code: "Enter code to {action}",
    code: "Code", confirm: "Confirm",
    entity_not_found: "Entity not found: {entity}",
    editor_entity: "Entity", editor_select: "\u2014 Select alarm panel \u2014",
    editor_name: "Name (optional)", editor_name_placeholder: "Override friendly name",
    card_name: "Securitas Alarm Card",
    card_description: "Alarm card for Securitas Direct: dynamic arm modes, PIN support, force-arm for open sensors.",
  },
  es: {
    disarmed: "Desarmado", armed_away: "Armado (fuera)", armed_home: "Armado (casa)",
    armed_night: "Armado (noche)", armed_custom: "Armado (personalizado)",
    arming: "Armando\u2026", pending: "Pendiente", triggered: "ACTIVADA",
    unavailable: "No disponible", unknown: "Desconocido",
    arm_away: "Armar fuera", arm_home: "Armar casa", arm_night: "Armar noche",
    arm_custom: "Armar personalizado", disarm: "Desarmar",
    force_arm: "Forzar armado", cancel: "Cancelar",
    open_sensors: "Sensor(es) abierto(s) \u2014 \u00bfarmar igualmente?",
    enter_pin: "Introduzca PIN para {action}", enter_code: "Introduzca c\u00f3digo para {action}",
    code: "C\u00f3digo", confirm: "Confirmar",
    entity_not_found: "Entidad no encontrada: {entity}",
    editor_entity: "Entidad", editor_select: "\u2014 Seleccionar panel de alarma \u2014",
    editor_name: "Nombre (opcional)", editor_name_placeholder: "Nombre personalizado",
    card_name: "Tarjeta de Alarma Securitas",
    card_description: "Tarjeta de alarma para Securitas Direct: modos de armado, PIN y armado forzado.",
  },
  fr: {
    disarmed: "D\u00e9sarm\u00e9", armed_away: "Arm\u00e9 (absent)", armed_home: "Arm\u00e9 (domicile)",
    armed_night: "Arm\u00e9 (nuit)", armed_custom: "Arm\u00e9 (personnalis\u00e9)",
    arming: "Armement\u2026", pending: "En attente", triggered: "D\u00c9CLENCH\u00c9E",
    unavailable: "Indisponible", unknown: "Inconnu",
    arm_away: "Armer absent", arm_home: "Armer domicile", arm_night: "Armer nuit",
    arm_custom: "Armer personnalis\u00e9", disarm: "D\u00e9sarmer",
    force_arm: "Forcer l\u2019armement", cancel: "Annuler",
    open_sensors: "Capteur(s) ouvert(s) \u2014 armer quand m\u00eame\u00a0?",
    enter_pin: "Entrez le PIN pour {action}", enter_code: "Entrez le code pour {action}",
    code: "Code", confirm: "Confirmer",
    entity_not_found: "Entit\u00e9 introuvable\u00a0: {entity}",
    editor_entity: "Entit\u00e9", editor_select: "\u2014 S\u00e9lectionner le panneau d\u2019alarme \u2014",
    editor_name: "Nom (facultatif)", editor_name_placeholder: "Remplacer le nom",
    card_name: "Carte d\u2019alarme Securitas",
    card_description: "Carte d\u2019alarme Securitas Direct\u00a0: modes d\u2019armement, PIN et armement forc\u00e9.",
  },
  it: {
    disarmed: "Disarmato", armed_away: "Armato (fuori)", armed_home: "Armato (casa)",
    armed_night: "Armato (notte)", armed_custom: "Armato (personalizzato)",
    arming: "Armamento\u2026", pending: "In attesa", triggered: "ATTIVATO",
    unavailable: "Non disponibile", unknown: "Sconosciuto",
    arm_away: "Arma fuori", arm_home: "Arma casa", arm_night: "Arma notte",
    arm_custom: "Arma personalizzato", disarm: "Disarma",
    force_arm: "Forza armamento", cancel: "Annulla",
    open_sensors: "Sensore/i aperto/i \u2014 armare comunque?",
    enter_pin: "Inserisci PIN per {action}", enter_code: "Inserisci codice per {action}",
    code: "Codice", confirm: "Conferma",
    entity_not_found: "Entit\u00e0 non trovata: {entity}",
    editor_entity: "Entit\u00e0", editor_select: "\u2014 Seleziona pannello allarme \u2014",
    editor_name: "Nome (facoltativo)", editor_name_placeholder: "Nome personalizzato",
    card_name: "Scheda Allarme Securitas",
    card_description: "Scheda allarme Securitas Direct: modalit\u00e0 di armamento, PIN e armamento forzato.",
  },
  pt: {
    disarmed: "Desarmado", armed_away: "Armado (aus\u00eancia)", armed_home: "Armado (casa)",
    armed_night: "Armado (noite)", armed_custom: "Armado (personalizado)",
    arming: "A armar\u2026", pending: "Pendente", triggered: "DISPARADO",
    unavailable: "Indispon\u00edvel", unknown: "Desconhecido",
    arm_away: "Armar aus\u00eancia", arm_home: "Armar casa", arm_night: "Armar noite",
    arm_custom: "Armar personalizado", disarm: "Desarmar",
    force_arm: "For\u00e7ar armamento", cancel: "Cancelar",
    open_sensors: "Sensor(es) aberto(s) \u2014 armar na mesma?",
    enter_pin: "Introduza PIN para {action}", enter_code: "Introduza c\u00f3digo para {action}",
    code: "C\u00f3digo", confirm: "Confirmar",
    entity_not_found: "Entidade n\u00e3o encontrada: {entity}",
    editor_entity: "Entidade", editor_select: "\u2014 Selecionar painel de alarme \u2014",
    editor_name: "Nome (opcional)", editor_name_placeholder: "Nome personalizado",
    card_name: "Cart\u00e3o de Alarme Securitas",
    card_description: "Cart\u00e3o de alarme Securitas Direct: modos de armar, PIN e armamento for\u00e7ado.",
  },
};

// pt-BR falls back to pt
TRANSLATIONS["pt-BR"] = TRANSLATIONS.pt;

function _t(lang, key, vars) {
  const l = TRANSLATIONS[lang] || TRANSLATIONS[lang?.split("-")[0]] || TRANSLATIONS.en;
  let s = l[key] || TRANSLATIONS.en[key] || key;
  if (vars) Object.entries(vars).forEach(([k, v]) => { s = s.replace(`{${k}}`, v); });
  return s;
}

// ── Per-state visual config ───────────────────────────────────────────────────
const STATE_CFG = {
  disarmed:           { icon: "mdi:shield-off-outline",  color: "var(--success-color,#4CAF50)" },
  armed_away:         { icon: "mdi:shield-lock",         color: "var(--error-color,#F44336)" },
  armed_home:         { icon: "mdi:shield-home",         color: "var(--warning-color,#FF9800)" },
  armed_night:        { icon: "mdi:shield-moon",         color: "#9C27B0" },
  armed_custom_bypass:{ icon: "mdi:shield-star",         color: "#00BCD4" },
  arming:             { icon: "mdi:shield-sync-outline", color: "var(--warning-color,#FF9800)" },
  pending:            { icon: "mdi:shield-alert-outline",color: "var(--warning-color,#FF9800)" },
  triggered:          { icon: "mdi:shield-alert",        color: "var(--error-color,#F44336)" },
  unavailable:        { icon: "mdi:shield-off-outline",  color: "var(--disabled-color,#9E9E9E)" },
  unknown:            { icon: "mdi:shield-off-outline",  color: "var(--disabled-color,#9E9E9E)" },
};

const STATE_LABEL_KEYS = {
  disarmed: "disarmed", armed_away: "armed_away", armed_home: "armed_home",
  armed_night: "armed_night", armed_custom_bypass: "armed_custom",
  arming: "arming", pending: "pending", triggered: "triggered",
  unavailable: "unavailable", unknown: "unknown",
};

// States where the alarm is considered armed (not disarmed/transitioning)
const INACTIVE_STATES = new Set(["disarmed", "arming", "pending", "triggered", "unavailable", "unknown"]);

// ── Arm action definitions ────────────────────────────────────────────────────
const ARM_ACTIONS = [
  { key: "arm_away",          labelKey: "arm_away",    feature: FEATURE.ARM_AWAY,         service: "alarm_arm_away" },
  { key: "arm_home",          labelKey: "arm_home",    feature: FEATURE.ARM_HOME,         service: "alarm_arm_home" },
  { key: "arm_night",         labelKey: "arm_night",   feature: FEATURE.ARM_NIGHT,        service: "alarm_arm_night" },
  { key: "arm_custom_bypass", labelKey: "arm_custom",  feature: FEATURE.ARM_CUSTOM_BYPASS,service: "alarm_arm_custom_bypass" },
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

  // ── HTML escaping — prevents XSS via user-controlled strings ───────────────
  _esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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

    const lang = this._hass.language || "en";
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div class="missing">${_t(lang, "entity_not_found", { entity: this._esc(this._config.entity) })}</div></ha-card>`;
      return;
    }

    const state    = stateObj.state;
    const attrs    = stateObj.attributes;
    const stateCfg = STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)" };
    const cfg      = { ...stateCfg, label: _t(lang, STATE_LABEL_KEYS[state] || state) };
    const name     = this._config.name || attrs.friendly_name || this._config.entity;
    const features = attrs.supported_features || 0;

    const forceArmAvailable = attrs.force_arm_available === true;
    const openSensors       = attrs.arm_exceptions || [];

    const codeFormat      = attrs.code_format || null;        // "number" | "text" | null
    const codeArmRequired = attrs.code_arm_required === true; // need code to arm?
    const hasCode         = !!codeFormat;

    // Unavailable / unknown — show state but no action buttons
    const isUnavailable = state === "unavailable" || state === "unknown";

    // Determine which arm buttons to show
    const availableArmActions = ARM_ACTIONS.filter(a => features & a.feature);
    const isArmed   = !INACTIVE_STATES.has(state);
    // Show Disarm during arming/pending too — alarm is already committed
    const canDisarm = isArmed || state === "arming" || state === "pending";
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
              <div class="entity-name">${this._esc(name)}</div>
              <div class="state-pill">${cfg.label}</div>
            </div>
          </div>

          <!-- ── Unavailable notice ── -->
          ${isUnavailable ? `<div class="unavailable-msg">Entity is ${cfg.label.toLowerCase()}.</div>` : ""}

          <!-- ── Force arm section ── -->
          ${!isUnavailable && forceArmAvailable ? this._renderForceArm(openSensors, lang) : ""}

          <!-- ── PIN entry ── -->
          ${!isUnavailable && this._uiState === "pin" ? this._renderPin(codeFormat, lang) : ""}

          <!-- ── Normal buttons (hidden during pin entry / force arm / unavailable) ── -->
          ${!isUnavailable && this._uiState === "normal" && !forceArmAvailable ? `
            <div class="btn-grid">
              ${canDisarm
                ? `<button class="btn btn-disarm" data-action="disarm">${_t(lang, "disarm")}</button>`
                : canArm
                  ? availableArmActions.map(a =>
                      `<button class="btn btn-arm" data-action="${a.key}">${_t(lang, a.labelKey)}</button>`
                    ).join("")
                  : ""
              }
            </div>` : ""}

        </div>
      </ha-card>`;

    this._attachListeners(stateObj, codeFormat, codeArmRequired, hasCode, isArmed);
  }

  // ── Force arm section ───────────────────────────────────────────────────────
  _renderForceArm(sensors, lang) {
    const list = sensors.length
      ? `<ul class="sensor-list">${sensors.map(s => `<li>${this._esc(s)}</li>`).join("")}</ul>`
      : "";
    return `
      <div class="force-section">
        <div class="force-title">
          <ha-icon icon="mdi:alert"></ha-icon>
          ${_t(lang, "open_sensors")}
        </div>
        ${list}
        <div class="force-btns">
          <button class="btn btn-cancel-force" data-action="cancel_force">${_t(lang, "cancel")}</button>
          <button class="btn btn-force" data-action="force_arm">${_t(lang, "force_arm")}</button>
        </div>
      </div>`;
  }

  // ── PIN entry section ───────────────────────────────────────────────────────
  _renderPin(codeFormat, lang) {
    const masked = "●".repeat(this._pin.length) || " ";
    const actionLabel = this._pendingAction?.labelKey
      ? _t(lang, this._pendingAction.labelKey)
      : (this._pendingAction?.label || "");

    if (codeFormat === "number") {
      return `
        <div class="pin-section">
          <div class="pin-label">${_t(lang, "enter_pin", { action: actionLabel })}</div>
          <div class="pin-display">${masked}</div>
          <input id="pin-keyboard-input" class="pin-keyboard-input" type="tel"
                 inputmode="numeric" autocomplete="off" />
          <div class="keypad">
            ${[1,2,3,4,5,6,7,8,9].map(n =>
              `<button class="key" data-key="${n}">${n}</button>`
            ).join("")}
            <button class="key key-cancel" data-key="cancel">✕</button>
            <button class="key" data-key="0">0</button>
            <button class="key key-del" data-key="del">⌫</button>
          </div>
          <button class="btn btn-arm pin-confirm" data-action="confirm-pin">${_t(lang, "confirm")}</button>
        </div>`;
    }

    // Text code
    return `
      <div class="pin-section">
        <div class="pin-label">${_t(lang, "enter_code", { action: actionLabel })}</div>
        <input class="code-input" type="password" autocomplete="off"
               placeholder="${_t(lang, "code")}" value="${this._esc(this._pin)}" id="code-input" />
        <div class="text-pin-btns">
          <button class="btn btn-cancel-force" data-action="cancel-pin">${_t(lang, "cancel")}</button>
          <button class="btn btn-arm" data-action="confirm-pin">${_t(lang, "confirm")}</button>
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
      });
    });

    // Numeric keypad — hidden input captures physical keyboard typing
    const pinKeyboard = this.shadowRoot.getElementById("pin-keyboard-input");
    if (pinKeyboard) {
      pinKeyboard.focus();
      pinKeyboard.addEventListener("keydown", e => {
        if (e.key === "Backspace") { this._pin = this._pin.slice(0, -1); this._render(); return; }
        if (e.key === "Enter")     { this._submitPin(entity); return; }
        if (e.key === "Escape")    { this._resetUI(); this._render(); return; }
      });
      pinKeyboard.addEventListener("input", e => {
        const digits = e.target.value.replace(/\D/g, "");
        if (digits) { this._pin += digits; e.target.value = ""; this._render(); }
      });
    }

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
      const serviceData = { entity_id: entity };
      if (this._pin) serviceData.code = this._pin;
      this._hass.callService("securitas", "force_arm", serviceData);
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

      .unavailable-msg {
        padding: 8px 0 12px;
        font-size: 0.85em;
        color: var(--secondary-text-color);
        text-align: center;
      }

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
      /* hidden input that captures physical keyboard for numeric PIN */
      .pin-keyboard-input {
        position: absolute; opacity: 0;
        width: 1px; height: 1px; pointer-events: none;
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
    if (stateObj?.attributes?.force_arm_available) return 5;
    return 3;
  }

  static getConfigElement() {
    return document.createElement("securitas-alarm-card-editor");
  }

  static getStubConfig(hass) {
    const entities = Object.keys(hass.states).filter(e => e.startsWith("alarm_control_panel."));
    return { entity: entities[0] || "" };
  }
}

// ── Config editor ─────────────────────────────────────────────────────────────

class SecuritasAlarmCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this._initialized) {
      this._initialized = true;
      this._render();
    }
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

  _render() {
    if (!this._hass) return;

    const lang = this._hass.language || "en";
    const entities = Object.keys(this._hass.states)
      .filter(e => e.startsWith("alarm_control_panel."))
      .sort();

    const selected = this._config.entity || "";
    const name = this._config.name || "";

    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; }
        .row { margin-bottom: 16px; }
        label {
          display: block;
          font-weight: 500;
          font-size: 0.85em;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
        }
        select, input {
          width: 100%;
          box-sizing: border-box;
          padding: 8px 12px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          font-size: 1em;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        select:focus, input:focus {
          outline: none;
          border-color: var(--primary-color);
        }
      </style>
      <div class="editor">
        <div class="row">
          <label>${_t(lang, "editor_entity")}</label>
          <select id="entity">
            <option value="" ${!selected ? "selected" : ""}>${_t(lang, "editor_select")}</option>
            ${entities.map(e =>
              `<option value="${e}" ${e === selected ? "selected" : ""}>${this._hass.states[e].attributes.friendly_name || e}</option>`
            ).join("")}
          </select>
        </div>
        <div class="row">
          <label>${_t(lang, "editor_name")}</label>
          <input id="name" type="text" value="${this._escapeAttr(name)}" placeholder="${_t(lang, "editor_name_placeholder")}" />
        </div>
      </div>`;

    this.shadowRoot.getElementById("entity").addEventListener("change", (e) => {
      this._config = { ...this._config, entity: e.target.value };
      this._fireChanged();
    });

    this.shadowRoot.getElementById("name").addEventListener("input", (e) => {
      const val = e.target.value.trim();
      if (val) {
        this._config = { ...this._config, name: val };
      } else {
        const { name: _, ...rest } = this._config;
        this._config = rest;
      }
      this._fireChanged();
    });
  }

  _escapeAttr(s) {
    return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  _fireChanged() {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
  }
}

// ── Badge card ────────────────────────────────────────────────────────────────

class SecuritasAlarmBadge extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dialogOpen = false;
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass.states[this._config.entity];
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.force_arm_available}`
      : "missing";
    if (newKey !== this._lastKey) {
      this._lastKey = newKey;
      this._renderBadge();
    }
    // Forward hass to the dialog card if open
    if (this._dialogCard) this._dialogCard.hass = hass;
  }

  _renderBadge() {
    if (!this._hass || !this._config) return;

    const lang = this._hass.language || "en";
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-icon icon="mdi:shield-alert" style="color:var(--error-color)"></ha-icon>`;
      return;
    }

    const state = stateObj.state;
    const icons = stateObj.attributes.force_arm_available
      ? { icon: "mdi:alert", color: "var(--warning-color, #FF9800)" }
      : STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)" };

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: inline-block; }
        .badge {
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: transform 0.1s;
        }
        .badge:active { transform: scale(0.9); }
        .badge ha-icon {
          --mdc-icon-size: 24px;
          color: ${icons.color};
        }
      </style>
      <div class="badge" id="badge">
        <ha-icon icon="${icons.icon}"></ha-icon>
      </div>`;

    this.shadowRoot.getElementById("badge").addEventListener("click", () => {
      this._openDialog();
    });
  }

  _openDialog() {
    if (this._dialogOpen) return;
    this._dialogOpen = true;

    const overlay = document.createElement("div");
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0", right: "0", bottom: "0",
      background: "rgba(0,0,0,0.5)", zIndex: "7",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: "16px",
    });

    const content = document.createElement("div");
    Object.assign(content.style, {
      width: "100%", maxWidth: "400px", maxHeight: "90vh", overflowY: "auto",
      borderRadius: "16px", background: "var(--card-background-color, var(--ha-card-background, #fff))",
      boxShadow: "0 8px 32px rgba(0,0,0,0.25)", position: "relative",
    });

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "\u2715";
    Object.assign(closeBtn.style, {
      position: "absolute", top: "8px", right: "8px", width: "32px", height: "32px",
      border: "none", borderRadius: "50%", background: "var(--secondary-background-color)",
      color: "var(--primary-text-color)", fontSize: "1.1em", cursor: "pointer",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: "1",
    });

    content.appendChild(closeBtn);
    overlay.appendChild(content);
    document.body.appendChild(overlay);

    // Create the full alarm card inside the dialog
    this._dialogCard = document.createElement("securitas-alarm-card");
    this._dialogCard.setConfig(this._config);
    this._dialogCard.hass = this._hass;
    content.appendChild(this._dialogCard);

    // Close handlers
    const close = () => {
      this._dialogOpen = false;
      this._dialogCard = null;
      overlay.remove();
      if (this._unsubConnection) {
        this._unsubConnection();
        this._unsubConnection = null;
      }
    };
    closeBtn.addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });

    // Close overlay when HA connection drops (e.g. restart)
    if (this._hass?.connection) {
      this._unsubConnection = this._hass.connection.addEventListener(
        "disconnected", close
      );
    }
  }

  getCardSize() { return 1; }

  static getConfigElement() {
    return document.createElement("securitas-alarm-card-editor");
  }

  static getStubConfig(hass) {
    const entities = Object.keys(hass.states).filter(e => e.startsWith("alarm_control_panel."));
    return { entity: entities[0] || "" };
  }
}

customElements.define("securitas-alarm-card", SecuritasAlarmCard);
customElements.define("securitas-alarm-card-editor", SecuritasAlarmCardEditor);
customElements.define("securitas-alarm-badge", SecuritasAlarmBadge);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        "securitas-alarm-card",
  name:        TRANSLATIONS.en.card_name,
  description: TRANSLATIONS.en.card_description,
  preview:     false,
});
window.customBadges = window.customBadges || [];
window.customBadges.push({
  type:        "securitas-alarm-badge",
  name:        "Securitas Alarm Badge",
  description: "Compact alarm badge — click to open full alarm card with force-arm support.",
  preview:     false,
});
