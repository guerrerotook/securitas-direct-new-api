/**
 * Securitas Direct Alarm Card
 *
 * A polished custom Lovelace card for the Securitas Direct integration.
 *
 * Features:
 *  - Reads `supported_features` from the entity — only shows arm buttons
 *    for modes that are actually configured (Away, Home, Night, Vacation, Custom)
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
  ARM_VACATION: 32,
};

// ── Translations ─────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    disarmed: "Disarmed", armed_away: "Armed Away", armed_home: "Armed Home",
    armed_night: "Armed Night", armed_vacation: "Armed Vacation",
    armed_custom: "Armed Custom",
    arming: "Arming\u2026", pending: "Pending", triggered: "TRIGGERED",
    unavailable: "Unavailable", unknown: "Unknown",
    arm_away: "Arm Away", arm_home: "Arm Home", arm_night: "Arm Night",
    arm_vacation: "Arm Vacation", arm_custom: "Arm Custom", disarm: "Disarm",
    force_arm: "Force Arm", cancel: "Cancel",
    open_sensors: "Open sensor(s) \u2014 arm anyway?",
    enter_pin: "Enter PIN to {action}", enter_code: "Enter code to {action}",
    code: "Code", confirm: "Confirm",
    refresh: "Refresh status",
    waf_blocked: "Rate limited by Securitas servers. Please wait a few minutes.",
    refresh_failed: "Refresh timed out — data may be stale.",
    entity_not_found: "Entity not found: {entity}",
    editor_entity: "Entity", editor_select: "\u2014 Select alarm panel \u2014",
    editor_name: "Name (optional)", editor_name_placeholder: "Override friendly name",
    card_name: "Securitas Alarm Card",
    card_description: "Alarm card for Securitas Direct: dynamic arm modes, PIN support, force-arm for open sensors.",
  },
  es: {
    disarmed: "Desarmado", armed_away: "Armado (fuera)", armed_home: "Armado (casa)",
    armed_night: "Armado (noche)", armed_vacation: "Armado (vacaciones)",
    armed_custom: "Armado (personalizado)",
    arming: "Armando\u2026", pending: "Pendiente", triggered: "ACTIVADA",
    unavailable: "No disponible", unknown: "Desconocido",
    arm_away: "Armar fuera", arm_home: "Armar casa", arm_night: "Armar noche",
    arm_vacation: "Armar vacaciones", arm_custom: "Armar personalizado", disarm: "Desarmar",
    force_arm: "Forzar armado", cancel: "Cancelar",
    open_sensors: "Sensor(es) abierto(s) \u2014 \u00bfarmar igualmente?",
    enter_pin: "Introduzca PIN para {action}", enter_code: "Introduzca c\u00f3digo para {action}",
    code: "C\u00f3digo", confirm: "Confirmar",
    refresh: "Actualizar estado",
    waf_blocked: "Bloqueado por los servidores de Securitas. Espere unos minutos.",
    refresh_failed: "La actualización ha caducado — los datos pueden estar desactualizados.",
    entity_not_found: "Entidad no encontrada: {entity}",
    editor_entity: "Entidad", editor_select: "\u2014 Seleccionar panel de alarma \u2014",
    editor_name: "Nombre (opcional)", editor_name_placeholder: "Nombre personalizado",
    card_name: "Tarjeta de Alarma Securitas",
    card_description: "Tarjeta de alarma para Securitas Direct: modos de armado, PIN y armado forzado.",
  },
  fr: {
    disarmed: "D\u00e9sarm\u00e9", armed_away: "Arm\u00e9 (absent)", armed_home: "Arm\u00e9 (domicile)",
    armed_night: "Arm\u00e9 (nuit)", armed_vacation: "Arm\u00e9 (vacances)",
    armed_custom: "Arm\u00e9 (personnalis\u00e9)",
    arming: "Armement\u2026", pending: "En attente", triggered: "D\u00c9CLENCH\u00c9E",
    unavailable: "Indisponible", unknown: "Inconnu",
    arm_away: "Armer absent", arm_home: "Armer domicile", arm_night: "Armer nuit",
    arm_vacation: "Armer vacances", arm_custom: "Armer personnalis\u00e9", disarm: "D\u00e9sarmer",
    force_arm: "Forcer l\u2019armement", cancel: "Annuler",
    open_sensors: "Capteur(s) ouvert(s) \u2014 armer quand m\u00eame\u00a0?",
    enter_pin: "Entrez le PIN pour {action}", enter_code: "Entrez le code pour {action}",
    code: "Code", confirm: "Confirmer",
    refresh: "Actualiser le statut",
    waf_blocked: "Bloqu\u00e9 par les serveurs Securitas. Veuillez patienter quelques minutes.",
    refresh_failed: "L\u2019actualisation a expir\u00e9 — les donn\u00e9es peuvent \u00eatre obsol\u00e8tes.",
    entity_not_found: "Entit\u00e9 introuvable\u00a0: {entity}",
    editor_entity: "Entit\u00e9", editor_select: "\u2014 S\u00e9lectionner le panneau d\u2019alarme \u2014",
    editor_name: "Nom (facultatif)", editor_name_placeholder: "Remplacer le nom",
    card_name: "Carte d\u2019alarme Securitas",
    card_description: "Carte d\u2019alarme Securitas Direct\u00a0: modes d\u2019armement, PIN et armement forc\u00e9.",
  },
  it: {
    disarmed: "Disarmato", armed_away: "Armato (fuori)", armed_home: "Armato (casa)",
    armed_night: "Armato (notte)", armed_vacation: "Armato (vacanza)",
    armed_custom: "Armato (personalizzato)",
    arming: "Armamento\u2026", pending: "In attesa", triggered: "ATTIVATO",
    unavailable: "Non disponibile", unknown: "Sconosciuto",
    arm_away: "Arma fuori", arm_home: "Arma casa", arm_night: "Arma notte",
    arm_vacation: "Arma vacanza", arm_custom: "Arma personalizzato", disarm: "Disarma",
    force_arm: "Forza armamento", cancel: "Annulla",
    open_sensors: "Sensore/i aperto/i \u2014 armare comunque?",
    enter_pin: "Inserisci PIN per {action}", enter_code: "Inserisci codice per {action}",
    code: "Codice", confirm: "Conferma",
    refresh: "Aggiorna stato",
    waf_blocked: "Bloccato dai server Securitas. Attendere qualche minuto.",
    refresh_failed: "Aggiornamento scaduto — i dati potrebbero non essere aggiornati.",
    entity_not_found: "Entit\u00e0 non trovata: {entity}",
    editor_entity: "Entit\u00e0", editor_select: "\u2014 Seleziona pannello allarme \u2014",
    editor_name: "Nome (facoltativo)", editor_name_placeholder: "Nome personalizzato",
    card_name: "Scheda Allarme Securitas",
    card_description: "Scheda allarme Securitas Direct: modalit\u00e0 di armamento, PIN e armamento forzato.",
  },
  pt: {
    disarmed: "Desarmado", armed_away: "Armado (aus\u00eancia)", armed_home: "Armado (casa)",
    armed_night: "Armado (noite)", armed_vacation: "Armado (f\u00e9rias)",
    armed_custom: "Armado (personalizado)",
    arming: "A armar\u2026", pending: "Pendente", triggered: "DISPARADO",
    unavailable: "Indispon\u00edvel", unknown: "Desconhecido",
    arm_away: "Armar aus\u00eancia", arm_home: "Armar casa", arm_night: "Armar noite",
    arm_vacation: "Armar f\u00e9rias", arm_custom: "Armar personalizado", disarm: "Desarmar",
    force_arm: "For\u00e7ar armamento", cancel: "Cancelar",
    open_sensors: "Sensor(es) aberto(s) \u2014 armar na mesma?",
    enter_pin: "Introduza PIN para {action}", enter_code: "Introduza c\u00f3digo para {action}",
    code: "C\u00f3digo", confirm: "Confirmar",
    refresh: "Atualizar estado",
    waf_blocked: "Bloqueado pelos servidores da Securitas. Aguarde alguns minutos.",
    refresh_failed: "A atualiza\u00e7\u00e3o expirou — os dados podem estar desatualizados.",
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
  armed_vacation:     { icon: "mdi:shield-airplane",     color: "#2196F3" },
  armed_custom_bypass:{ icon: "mdi:shield-star",         color: "#00BCD4" },
  arming:             { icon: "mdi:shield-sync-outline", color: "var(--warning-color,#FF9800)" },
  pending:            { icon: "mdi:shield-alert-outline",color: "var(--warning-color,#FF9800)" },
  triggered:          { icon: "mdi:shield-alert",        color: "var(--error-color,#F44336)" },
  unavailable:        { icon: "mdi:shield-off-outline",  color: "var(--disabled-color,#9E9E9E)" },
  unknown:            { icon: "mdi:shield-off-outline",  color: "var(--disabled-color,#9E9E9E)" },
};

// Hex fallbacks used by the editor color pickers (CSS vars can't be used in <input type="color">)
const STATE_COLOR_DEFAULTS = {
  disarmed:            "#4CAF50",
  armed_away:          "#F44336",
  armed_home:          "#FF9800",
  armed_night:         "#9C27B0",
  armed_vacation:      "#2196F3",
  armed_custom_bypass: "#00BCD4",
  triggered:           "#F44336",
};

// States shown in the color editor (excludes transient/unavailable states)
const COLOR_EDITOR_STATES = [
  { state: "disarmed",            label: "Disarmed" },
  { state: "armed_away",          label: "Armed Away" },
  { state: "armed_home",          label: "Armed Home" },
  { state: "armed_night",         label: "Armed Night" },
  { state: "armed_vacation",      label: "Armed Vacation" },
  { state: "armed_custom_bypass", label: "Armed Custom / Bypass" },
  { state: "triggered",           label: "Triggered" },
];

const STATE_LABEL_KEYS = {
  disarmed: "disarmed", armed_away: "armed_away", armed_home: "armed_home",
  armed_night: "armed_night", armed_vacation: "armed_vacation",
  armed_custom_bypass: "armed_custom",
  arming: "arming", pending: "pending", triggered: "triggered",
  unavailable: "unavailable", unknown: "unknown",
};

// States where the alarm is considered armed (not disarmed/transitioning)
const INACTIVE_STATES = new Set(["disarmed", "arming", "pending", "triggered", "unavailable", "unknown"]);

// ── Arm action definitions ────────────────────────────────────────────────────
const ARM_ACTIONS = [
  { key: "arm_away",          labelKey: "arm_away",    feature: FEATURE.ARM_AWAY,         service: "alarm_arm_away" },
  { key: "arm_home",          labelKey: "arm_home",    feature: FEATURE.ARM_HOME,         service: "alarm_arm_home" },
  { key: "arm_night",         labelKey: "arm_night",    feature: FEATURE.ARM_NIGHT,        service: "alarm_arm_night" },
  { key: "arm_vacation",      labelKey: "arm_vacation", feature: FEATURE.ARM_VACATION,     service: "alarm_arm_vacation" },
  { key: "arm_custom_bypass", labelKey: "arm_custom",   feature: FEATURE.ARM_CUSTOM_BYPASS,service: "alarm_arm_custom_bypass" },
];

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
 * @param {object}        callbacks  - { startPinEntry(action), onMoreInfo() }
 * @returns {Function}               - Cleanup function (removes listeners)
 */
function attachGesture(el, config, hass, entityId, srcEl, callbacks = {}) {
  let holdTimer = null;
  let holdFired = false;
  let downX = 0, downY = 0;
  let tapWindow = null;


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
    if (holdFired) return;

    if (tapWindow) {
      clearTimeout(tapWindow);
      tapWindow = null;
      executeAction(doubleTapAction, hass, entityId, srcEl, callbacks);
    } else {
      tapWindow = setTimeout(() => {
        tapWindow = null;
        executeAction(tapAction, hass, entityId, srcEl, callbacks);
      }, DOUBLE_MS);
    }
  }

  function onPointerCancel() { cancelHold(); }

  function onClick(e) {
    if (holdFired) { holdFired = false; e.stopImmediatePropagation(); }
  }

  el.addEventListener("pointerdown",   onPointerDown);
  el.addEventListener("pointermove",   onPointerMove);
  el.addEventListener("pointerup",     onPointerUp);
  el.addEventListener("pointercancel", onPointerCancel);
  el.addEventListener("click",         onClick, true);

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

/**
 * Executes a HA-style action config object.
 *
 * @param {object}      action     - { action, navigation_path, perform_action, data, arm_state }
 * @param {object}      hass       - Home Assistant hass object
 * @param {string}      entityId   - Alarm entity id
 * @param {HTMLElement} srcEl      - Element to dispatch events from (for more-info)
 * @param {object}      callbacks  - { startPinEntry(serviceAction), onMoreInfo() }
 */
function executeAction(action, hass, entityId, srcEl, callbacks = {}) {
  if (!action || action.action === "none") return;

  switch (action.action) {

    case "more-info":
      if (callbacks.onMoreInfo) {
        callbacks.onMoreInfo();
      } else if (srcEl) {
        srcEl.dispatchEvent(new CustomEvent("hass-more-info", {
          detail: { entityId },
          bubbles: true,
          composed: true,
        }));
      }
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

// ─────────────────────────────────────────────────────────────────────────────

class SecuritasAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._uiState = "normal";   // normal | pin | force_arm
    this._pendingAction = null; // { service, label }
    this._pin = "";
    this._gestureCleanup = null;
  }

  disconnectedCallback() {
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = config;
    this._lastKey = null; // force re-render so color changes apply immediately
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
    const refreshKey = this._findRefreshEntity() || "";
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.force_arm_available}|${(stateObj.attributes.arm_exceptions||[]).join(",")}|${stateObj.attributes.supported_features}|${stateObj.attributes.code_format}|${stateObj.attributes.code_arm_required}|${stateObj.attributes.waf_blocked}|${stateObj.attributes.refresh_failed}|${refreshKey}`
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

  // ── Find the refresh button entity for this alarm panel ─────────────────────
  _findRefreshEntity() {
    if (!this._hass) return null;
    if (this._config.refresh_entity) return this._config.refresh_entity;
    // Find the refresh button on the same device as the configured entity
    const entities = this._hass.entities;
    if (!entities) return null;
    const panelEntry = entities[this._config.entity];
    if (!panelEntry || !panelEntry.device_id) return null;
    const match = Object.keys(entities).find(
      e => e.startsWith("button.refresh_") && entities[e].device_id === panelEntry.device_id
    );
    return match || null;
  }

  // ── Main render ─────────────────────────────────────────────────────────────
  _render() {
    if (!this._hass || !this._config) return;
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

    const lang = this._hass.language || "en";
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div class="missing">${_t(lang, "entity_not_found", { entity: this._esc(this._config.entity) })}</div></ha-card>`;
      return;
    }

    const state    = stateObj.state;
    const attrs    = stateObj.attributes;
    const refreshEntity = this._findRefreshEntity();
    const stateCfg = STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)" };
    const cfg      = { icon: stateCfg.icon, color: this._getColor(state), label: _t(lang, STATE_LABEL_KEYS[state] || state) };
    const name     = this._config.name || attrs.friendly_name || this._config.entity;
    const features = attrs.supported_features || 0;

    const forceArmAvailable = attrs.force_arm_available === true;
    const openSensors       = attrs.arm_exceptions || [];
    const wafBlocked        = attrs.waf_blocked === true;
    const refreshFailed     = attrs.refresh_failed === true;

    const codeFormat      = attrs.code_format || null;        // "number" | "text" | null
    const codeArmRequired = attrs.code_arm_required === true; // need code to arm?
    const hasCode         = !!codeFormat;

    // Unavailable / unknown — show state but no action buttons
    const isUnavailable = state === "unavailable" || state === "unknown";

    // Determine which arm buttons to show
    const availableArmActions = ARM_ACTIONS.filter(a => features & a.feature);
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
              <div class="entity-name">${this._esc(name)}</div>
              <div class="state-pill">${cfg.label}</div>
            </div>
            ${refreshEntity ? `<button class="refresh-btn" type="button" data-action="refresh" title="${_t(lang, "refresh")}" aria-label="${_t(lang, "refresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button>` : ""}
          </div>

          <!-- ── Unavailable notice ── -->
          ${isUnavailable ? `<div class="unavailable-msg">Entity is ${cfg.label.toLowerCase()}.</div>` : ""}

          <!-- ── WAF rate-limit banner ── -->
          ${wafBlocked ? `<div class="waf-banner"><ha-icon icon="mdi:shield-alert"></ha-icon> ${_t(lang, "waf_blocked")}</div>` : ""}

          <!-- ── Refresh failed banner ── -->
          ${refreshFailed ? `<div class="stale-banner"><ha-icon icon="mdi:clock-alert-outline"></ha-icon> ${_t(lang, "refresh_failed")}</div>` : ""}

          <!-- ── Force arm section ── -->
          ${!isUnavailable && forceArmAvailable ? `
            ${this._renderForceArm(openSensors, lang)}
            ${canDisarm ? `<div class="btn-grid"><button class="btn btn-disarm" data-action="disarm">${_t(lang, "disarm")}</button></div>` : ""}
          ` : ""}

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
          onMoreInfo: () => this.dispatchEvent(new CustomEvent("hass-more-info", {
            detail: { entityId: this._config.entity },
            bubbles: true,
            composed: true,
          })),
          startPinEntry: (svcAction) => this._startPinEntry(svcAction),
        },
      );
    }

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
    const actionLabel = this._pendingAction?.labelKey
      ? _t(lang, this._pendingAction.labelKey)
      : (this._pendingAction?.label || "");

    if (codeFormat === "number") {
      return `
        <div class="pin-section">
          <div class="pin-label">${_t(lang, "enter_pin", { action: actionLabel })}</div>
          <input id="pin-keyboard-input" class="pin-input" type="password"
                 inputmode="numeric" autocomplete="off" value="${this._pin}"
                 placeholder="\u2022\u2022\u2022\u2022" />
          <div class="keypad">
            ${[1,2,3,4,5,6,7,8,9].map(n =>
              `<button class="key" data-key="${n}">${n}</button>`
            ).join("")}
            <button class="key key-cancel" data-key="cancel" aria-label="Cancel" title="Cancel">✕</button>
            <button class="key" data-key="0">0</button>
            <button class="key key-del" data-key="del" aria-label="Backspace" title="Backspace">⌫</button>
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

    // Arm / Disarm / Refresh buttons
    this.shadowRoot.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const action = btn.dataset.action;
        this._handleAction(action, stateObj, codeFormat, codeArmRequired, hasCode, isArmed, entity);
      });
    });

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
      requestAnimationFrame(() => codeInput.focus());
      codeInput.addEventListener("input", e => { this._pin = e.target.value; });
      codeInput.addEventListener("keydown", e => {
        if (e.key === "Enter") this._submitPin(entity);
      });
    }
  }

  _handleAction(action, stateObj, codeFormat, codeArmRequired, hasCode, isArmed, entity) {
    // Refresh
    if (action === "refresh") {
      const refreshEntity = this._findRefreshEntity();
      if (refreshEntity) {
        const btn = this.shadowRoot.querySelector(".refresh-btn");
        if (btn) btn.classList.add("spinning");
        this._hass.callService("button", "press", { entity_id: refreshEntity })
          .finally(() => {
            setTimeout(() => {
              const b = this.shadowRoot?.querySelector(".refresh-btn");
              if (b) b.classList.remove("spinning");
            }, 2000);
          });
      }
      return;
    }
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
      .refresh-btn {
        width: 36px; height: 36px;
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
        --mdc-icon-size: 20px;
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

      /* ── Force arm section ── */
      .force-section {
        border-radius: 12px;
        background: color-mix(in srgb, var(--warning-color, #FF9800) 9%, transparent);
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
        color: var(--text-primary-color, #fff);
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
    if (!this._selfUpdate) {
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

  _buildGestureSection(gesture, title, defaults) {
    const configKey     = `${gesture}_action`;
    const current       = this._config[configKey] || defaults;
    const currentAction = current.action || defaults.action;

    const stateObj  = this._hass?.states[this._config.entity];
    const features  = stateObj?.attributes?.supported_features || 0;
    const supported = ARM_ACTIONS.filter(a => features & a.feature);
    const armOptions = supported.length > 0 ? supported : ARM_ACTIONS;

    // Mutable state (avoids re-reading form.data which may lag)
    let actionValue   = currentAction;
    let armStateValue = current.arm_state || _defaultArmState(this._hass, this._config.entity);

    const section = document.createElement("div");
    section.className = "gesture-section";

    // Section heading
    const heading = document.createElement("div");
    heading.className = "section-title";
    heading.textContent = title;
    section.appendChild(heading);

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
            { value: "none",           label: "None" },
            { value: "more-info",      label: "Open dialog" },
            { value: "navigate",       label: "Navigate" },
            { value: "perform-action", label: "Perform action" },
            { value: "arm_or_disarm",  label: "Arm or disarm" },
          ],
        },
      },
    }];
    actionForm.computeLabel = () => "Action";
    section.appendChild(actionForm);

    // ── Navigate sub-fields ──────────────────────────────────────────────────
    const navFields = document.createElement("div");
    navFields.className = "conditional-fields";
    navFields.style.display = currentAction === "navigate" ? "" : "none";
    const navInput = document.createElement("ha-textfield");
    navInput.label       = "Navigation path";
    navInput.placeholder = "/lovelace/0";
    navInput.value       = current.navigation_path || "";
    navInput.style.width = "100%";
    navFields.appendChild(navInput);
    section.appendChild(navFields);

    // ── Perform-action sub-fields ────────────────────────────────────────────
    const perfFields = document.createElement("div");
    perfFields.className = "conditional-fields";
    perfFields.style.display = currentAction === "perform-action" ? "" : "none";
    const perfInput = document.createElement("ha-textfield");
    perfInput.label       = "Action (e.g. light.turn_on)";
    perfInput.placeholder = "domain.service";
    perfInput.value       = current.perform_action || "";
    perfInput.style.width = "100%";
    const perfDataInput = document.createElement("ha-textfield");
    perfDataInput.label       = "Data (JSON, optional)";
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
    const armForm = document.createElement("ha-form");
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
    armForm.computeLabel = () => "Arm state";
    armFields.appendChild(armForm);
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
        const path = navInput.value.trim();
        if (path) cfg.navigation_path = path;
      }
      if (actionValue === "perform-action") {
        const call = perfInput.value.trim();
        if (call) cfg.perform_action = call;
        const raw = perfDataInput.value.trim();
        if (raw) { try { cfg.data = JSON.parse(raw); } catch (_) {} }
      }
      if (actionValue === "arm_or_disarm") cfg.arm_state = armStateValue;
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
    armForm.addEventListener("value-changed", (e) => {
      const v = e.detail?.value?.arm_state;
      if (v !== undefined) {
        armStateValue = v;
        armForm.data = { arm_state: armStateValue };
        writeConfig();
      }
    });
    navInput.addEventListener("input", writeConfig);
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
        .section-title {
          font-weight: 600;
          font-size: 0.9em;
          color: var(--primary-text-color);
          padding-bottom: 6px;
          border-bottom: 1px solid var(--divider-color);
        }
        .section-hint {
          font-size: 0.8em;
          color: var(--secondary-text-color);
          margin-top: -8px;
        }
        /* Flat 3-column grid: label | picker | reset — all rows perfectly aligned */
        .color-grid {
          display: grid;
          grid-template-columns: 1fr 44px 28px;
          gap: 10px 12px;
          align-items: center;
        }
        .color-label {
          font-size: 0.85em;
          color: var(--primary-text-color);
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
        details > summary { cursor: pointer; user-select: none; }
        details > summary::-webkit-details-marker { display: none; }
        details > summary::marker { display: none; }
        details > summary::after { content: " ▸"; font-size: 0.75em; }
        details[open] > summary::after { content: " ▾"; }
        .gesture-section { display: flex; flex-direction: column; gap: 8px; }
        .gesture-section ha-form, .gesture-section ha-textfield { display: block; width: 100%; }
        .conditional-fields {
          padding: 8px 0 0 0;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
      </style>
      <div class="editor">
        <ha-form id="entity-form"></ha-form>
        <div id="name-slot"></div>
        <details>
          <summary class="section-title">State Colors</summary>
          <div style="padding-top:10px">
            <div class="section-hint">Optional — leave at default or pick a custom color per state.</div>
            <div class="color-grid" style="margin-top:10px">
              ${COLOR_EDITOR_STATES.map(({ state, label }) => {
                const override = colors[state];
                const pickerVal = override || STATE_COLOR_DEFAULTS[state] || "#808080";
                return `
                  <span class="color-label">${label}</span>
                  <input type="color" data-state="${state}" value="${pickerVal}" />
                  <button class="reset-btn" data-reset="${state}" title="Reset to default" ${override ? "" : "hidden"}>↺</button>`;
              }).join("")}
            </div>
          </div>
        </details>
        <div id="gesture-slot"></div>
      </div>`;

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

    // ── Name field (HA native) ───────────────────────────────────────────────
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
    const gestureSlot = this.shadowRoot.getElementById("gesture-slot");
    if (gestureSlot) {
      const isBadge = this._config.type === "custom:securitas-alarm-badge";
      const tapDefaults  = isBadge ? { action: "more-info" } : { action: "none" };
      const holdDefaults = {
        action: "arm_or_disarm",
        arm_state: _defaultArmState(this._hass, this._config.entity),
      };
      const dblDefaults  = { action: "none" };

      gestureSlot.appendChild(this._buildGestureSection("tap",        "Tap action",        tapDefaults));
      gestureSlot.appendChild(this._buildGestureSection("hold",       "Hold action",       holdDefaults));
      gestureSlot.appendChild(this._buildGestureSection("double_tap", "Double-tap action", dblDefaults));
    }
  }


  _fireChanged() {
    this._selfUpdate = true;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
    this._selfUpdate = false;
  }
}

// ── Badge card ────────────────────────────────────────────────────────────────

class SecuritasAlarmBadge extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dialogOpen = false;
    this._pinOverlay = null;   // floating PIN overlay element (or null)
    this._pinState   = null;   // { service, labelKey } when PIN entry active
    this._pin        = "";
    this._gestureCleanup = null; // cleanup fn returned by attachGesture
  }

  disconnectedCallback() {
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
    if (this._pinOverlay) { this._pinOverlay.remove(); this._pinOverlay = null; this._pinState = null; this._pin = ""; }
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
  }

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

if (!customElements.get("securitas-alarm-card"))   customElements.define("securitas-alarm-card", SecuritasAlarmCard);
if (!customElements.get("securitas-alarm-card-editor")) customElements.define("securitas-alarm-card-editor", SecuritasAlarmCardEditor);
if (!customElements.get("securitas-alarm-badge"))  customElements.define("securitas-alarm-badge", SecuritasAlarmBadge);

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
