// Shared helpers, constants, and translations for the Verisure OWA alarm
// Lovelace elements (card, editor, badge, chip).
//
// Split out of verisure-owa-alarm-card.js so the lightweight chip/badge can
// load from their own small module without pulling in the heavy card + editor
// code — keeping the always-visible alarm chip fast to render on a cold
// dashboard load. Imported with a ?v=<version> cache-bust query so it can be
// served with a long max-age yet still re-fetched on each release (kept in
// sync by tests-js/integration/card-cache-busting.test.js).

import { formatTranslation } from "./verisure-owa-card-utils.js?v=5.4.1";

// ── AlarmControlPanelEntityFeature bitmask values ────────────────────────────
export const FEATURE = {
  ARM_HOME: 1,
  ARM_AWAY: 2,
  ARM_NIGHT: 4,
  ARM_CUSTOM_BYPASS: 16,
  ARM_VACATION: 32,
};

// ── Translations ─────────────────────────────────────────────────────────────
export const TRANSLATIONS = {
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
    waf_blocked: "Rate limited by Verisure servers. Please wait a few minutes.",
    refresh_failed: "Refresh timed out — data may be stale.",
    entity_not_found: "Entity not found: {entity}",
    editor_entity: "Entity", editor_select: "\u2014 Select alarm panel \u2014",
    editor_name: "Name (optional)", editor_name_placeholder: "Override friendly name",
    editor_arm_modes: "Arm modes",
    editor_arm_modes_hint: "Uncheck modes to hide their buttons. Modes not supported by the entity are not shown.",
    editor_arm_modes_empty: "This entity reports no supported arm modes.",
    editor_arm_state_no_modes: "Enable at least one arm mode above to set this action.",
    delete: "Delete",
    close: "Close",
    entity_state_notice: "Entity status: {state}",
    editor_state_colors: "State Colors",
    editor_colors_hint: "Optional — leave at default or pick a custom color per state.",
    editor_reset_default: "Reset to default",
    editor_action_none: "None",
    editor_action_more_info: "Open dialog",
    editor_action_navigate: "Navigate",
    editor_action_perform: "Perform action",
    editor_action_arm_or_disarm: "Arm or disarm",
    editor_navigation_path: "Navigation path",
    editor_perform_action: "Action (e.g. light.turn_on)",
    editor_perform_data: "Data (JSON, optional)",
    editor_arm_state: "Arm state",
    editor_tap_action: "Tap action",
    editor_hold_action: "Hold action",
    editor_double_tap_action: "Double-tap action",
    card_name: "Verisure OWA Alarm Card",
    card_description: "Alarm card for Verisure: dynamic arm modes, PIN support, force-arm for open sensors.",
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
    waf_blocked: "Bloqueado por los servidores de Verisure. Espere unos minutos.",
    refresh_failed: "La actualización ha caducado — los datos pueden estar desactualizados.",
    entity_not_found: "Entidad no encontrada: {entity}",
    editor_entity: "Entidad", editor_select: "\u2014 Seleccionar panel de alarma \u2014",
    editor_name: "Nombre (opcional)", editor_name_placeholder: "Nombre personalizado",
    editor_arm_modes: "Modos de armado",
    editor_arm_modes_hint: "Desmarque los modos para ocultar sus botones. Los modos no admitidos por la entidad no se muestran.",
    editor_arm_modes_empty: "Esta entidad no admite ningún modo de armado.",
    editor_arm_state_no_modes: "Habilite al menos un modo de armado arriba para configurar esta acción.",
    delete: "Borrar",
    close: "Cerrar",
    entity_state_notice: "Estado de la entidad: {state}",
    editor_state_colors: "Colores de estado",
    editor_colors_hint: "Opcional: deje el valor predeterminado o elija un color personalizado por estado.",
    editor_reset_default: "Restablecer al valor predeterminado",
    editor_action_none: "Ninguna",
    editor_action_more_info: "Abrir diálogo",
    editor_action_navigate: "Navegar",
    editor_action_perform: "Ejecutar acción",
    editor_action_arm_or_disarm: "Armar o desarmar",
    editor_navigation_path: "Ruta de navegación",
    editor_perform_action: "Acción (p. ej. light.turn_on)",
    editor_perform_data: "Datos (JSON, opcional)",
    editor_arm_state: "Modo de armado",
    editor_tap_action: "Acción al tocar",
    editor_hold_action: "Acción al mantener pulsado",
    editor_double_tap_action: "Acción al tocar dos veces",
    card_name: "Tarjeta de Alarma Verisure",
    card_description: "Tarjeta de alarma para Verisure: modos de armado, PIN y armado forzado.",
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
    waf_blocked: "Bloqu\u00e9 par les serveurs Verisure. Veuillez patienter quelques minutes.",
    refresh_failed: "L\u2019actualisation a expir\u00e9 — les donn\u00e9es peuvent \u00eatre obsol\u00e8tes.",
    entity_not_found: "Entit\u00e9 introuvable\u00a0: {entity}",
    editor_entity: "Entit\u00e9", editor_select: "\u2014 S\u00e9lectionner le panneau d\u2019alarme \u2014",
    editor_name: "Nom (facultatif)", editor_name_placeholder: "Remplacer le nom",
    editor_arm_modes: "Modes d’armement",
    editor_arm_modes_hint: "D\u00e9cochez les modes pour masquer leurs boutons. Les modes non pris en charge par l’entit\u00e9 ne sont pas affich\u00e9s.",
    editor_arm_modes_empty: "Cette entit\u00e9 ne prend en charge aucun mode d\u2019armement.",
    editor_arm_state_no_modes: "Activez au moins un mode d\u2019armement ci-dessus pour configurer cette action.",
    delete: "Supprimer",
    close: "Fermer",
    entity_state_notice: "\u00c9tat de l\u2019entit\u00e9\u00a0: {state}",
    editor_state_colors: "Couleurs d\u2019\u00e9tat",
    editor_colors_hint: "Facultatif \u2014 laissez la valeur par d\u00e9faut ou choisissez une couleur personnalis\u00e9e par \u00e9tat.",
    editor_reset_default: "R\u00e9initialiser par d\u00e9faut",
    editor_action_none: "Aucune",
    editor_action_more_info: "Ouvrir la bo\u00eete de dialogue",
    editor_action_navigate: "Naviguer",
    editor_action_perform: "Ex\u00e9cuter une action",
    editor_action_arm_or_disarm: "Armer ou d\u00e9sarmer",
    editor_navigation_path: "Chemin de navigation",
    editor_perform_action: "Action (p. ex. light.turn_on)",
    editor_perform_data: "Donn\u00e9es (JSON, facultatif)",
    editor_arm_state: "\u00c9tat d\u2019armement",
    editor_tap_action: "Action sur appui",
    editor_hold_action: "Action sur appui long",
    editor_double_tap_action: "Action sur double appui",
    card_name: "Carte d\u2019alarme Verisure",
    card_description: "Carte d\u2019alarme Verisure\u00a0: modes d\u2019armement, PIN et armement forc\u00e9.",
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
    waf_blocked: "Bloccato dai server Verisure. Attendere qualche minuto.",
    refresh_failed: "Aggiornamento scaduto — i dati potrebbero non essere aggiornati.",
    entity_not_found: "Entit\u00e0 non trovata: {entity}",
    editor_entity: "Entit\u00e0", editor_select: "\u2014 Seleziona pannello allarme \u2014",
    editor_name: "Nome (facoltativo)", editor_name_placeholder: "Nome personalizzato",
    editor_arm_modes: "Modalità di armamento",
    editor_arm_modes_hint: "Deseleziona le modalità per nasconderne i pulsanti. Le modalità non supportate dall\u2019entità non vengono mostrate.",
    editor_arm_modes_empty: "Questa entità non supporta alcuna modalità di armamento.",
    editor_arm_state_no_modes: "Abilita almeno una modalità di armamento sopra per configurare questa azione.",
    delete: "Cancella",
    close: "Chiudi",
    entity_state_notice: "Stato dell’entità: {state}",
    editor_state_colors: "Colori di stato",
    editor_colors_hint: "Opzionale: lascia il valore predefinito o scegli un colore personalizzato per stato.",
    editor_reset_default: "Ripristina predefinito",
    editor_action_none: "Nessuna",
    editor_action_more_info: "Apri finestra di dialogo",
    editor_action_navigate: "Naviga",
    editor_action_perform: "Esegui azione",
    editor_action_arm_or_disarm: "Arma o disarma",
    editor_navigation_path: "Percorso di navigazione",
    editor_perform_action: "Azione (es. light.turn_on)",
    editor_perform_data: "Dati (JSON, opzionale)",
    editor_arm_state: "Stato di armamento",
    editor_tap_action: "Azione al tocco",
    editor_hold_action: "Azione alla pressione prolungata",
    editor_double_tap_action: "Azione al doppio tocco",
    card_name: "Scheda Allarme Verisure",
    card_description: "Scheda allarme Verisure: modalit\u00e0 di armamento, PIN e armamento forzato.",
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
    waf_blocked: "Bloqueado pelos servidores da Verisure. Aguarde alguns minutos.",
    refresh_failed: "A atualiza\u00e7\u00e3o expirou — os dados podem estar desatualizados.",
    entity_not_found: "Entidade n\u00e3o encontrada: {entity}",
    editor_entity: "Entidade", editor_select: "\u2014 Selecionar painel de alarme \u2014",
    editor_name: "Nome (opcional)", editor_name_placeholder: "Nome personalizado",
    editor_arm_modes: "Modos de armar",
    editor_arm_modes_hint: "Desmarque os modos para ocultar os seus bot\u00f5es. Os modos n\u00e3o suportados pela entidade n\u00e3o s\u00e3o mostrados.",
    editor_arm_modes_empty: "Esta entidade n\u00e3o suporta nenhum modo de armar.",
    editor_arm_state_no_modes: "Ative pelo menos um modo de armar acima para configurar esta a\u00e7\u00e3o.",
    delete: "Apagar",
    close: "Fechar",
    entity_state_notice: "Estado da entidade: {state}",
    editor_state_colors: "Cores de estado",
    editor_colors_hint: "Opcional \u2014 mantenha o padr\u00e3o ou escolha uma cor personalizada por estado.",
    editor_reset_default: "Repor para o padr\u00e3o",
    editor_action_none: "Nenhuma",
    editor_action_more_info: "Abrir caixa de di\u00e1logo",
    editor_action_navigate: "Navegar",
    editor_action_perform: "Executar a\u00e7\u00e3o",
    editor_action_arm_or_disarm: "Armar ou desarmar",
    editor_navigation_path: "Caminho de navega\u00e7\u00e3o",
    editor_perform_action: "A\u00e7\u00e3o (ex.: light.turn_on)",
    editor_perform_data: "Dados (JSON, opcional)",
    editor_arm_state: "Modo de armar",
    editor_tap_action: "A\u00e7\u00e3o ao tocar",
    editor_hold_action: "A\u00e7\u00e3o ao manter premido",
    editor_double_tap_action: "A\u00e7\u00e3o ao tocar duas vezes",
    card_name: "Cart\u00e3o de Alarme Verisure",
    card_description: "Cart\u00e3o de alarme Verisure: modos de armar, PIN e armamento for\u00e7ado.",
  },
};

// pt-BR falls back to pt
TRANSLATIONS["pt-BR"] = TRANSLATIONS.pt;

export const _t = (lang, key, vars) => formatTranslation(lang, TRANSLATIONS, key, vars);

// ── Per-state visual config ───────────────────────────────────────────────────
export const STATE_CFG = {
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
export const STATE_COLOR_DEFAULTS = {
  disarmed:            "#4CAF50",
  armed_away:          "#F44336",
  armed_home:          "#FF9800",
  armed_night:         "#9C27B0",
  armed_vacation:      "#2196F3",
  armed_custom_bypass: "#00BCD4",
  triggered:           "#F44336",
};

// States shown in the color editor (excludes transient/unavailable states).
// Labels are localized at render time via _t(STATE_LABEL_KEYS[state]); this is
// just the ordered state list.
export const COLOR_EDITOR_STATES = [
  "disarmed",
  "armed_away",
  "armed_home",
  "armed_night",
  "armed_vacation",
  "armed_custom_bypass",
  "triggered",
];

export const STATE_LABEL_KEYS = {
  disarmed: "disarmed", armed_away: "armed_away", armed_home: "armed_home",
  armed_night: "armed_night", armed_vacation: "armed_vacation",
  armed_custom_bypass: "armed_custom",
  arming: "arming", pending: "pending", triggered: "triggered",
  unavailable: "unavailable", unknown: "unknown",
};

// States where the alarm is considered armed (not disarmed/transitioning)
export const INACTIVE_STATES = new Set(["disarmed", "arming", "pending", "triggered", "unavailable", "unknown"]);

// ── Arm action definitions ────────────────────────────────────────────────────
export const ARM_ACTIONS = [
  { key: "arm_away",          labelKey: "arm_away",    feature: FEATURE.ARM_AWAY,         service: "alarm_arm_away" },
  { key: "arm_home",          labelKey: "arm_home",    feature: FEATURE.ARM_HOME,         service: "alarm_arm_home" },
  { key: "arm_night",         labelKey: "arm_night",    feature: FEATURE.ARM_NIGHT,        service: "alarm_arm_night" },
  { key: "arm_vacation",      labelKey: "arm_vacation", feature: FEATURE.ARM_VACATION,     service: "alarm_arm_vacation" },
  { key: "arm_custom_bypass", labelKey: "arm_custom",   feature: FEATURE.ARM_CUSTOM_BYPASS,service: "alarm_arm_custom_bypass" },
];

export const GESTURE_KEYS = ["tap_action", "hold_action", "double_tap_action"];

// ── Gesture helpers ───────────────────────────────────────────────────────────

/**
 * Returns `{ supported, filtered }` for an entity's arm capabilities.
 *  - `supported`: ARM_ACTIONS the entity advertises via `supported_features`.
 *  - `filtered`:  `supported` further intersected with `configStates` when
 *                 that array is provided; otherwise equal to `supported`.
 *
 * Used everywhere we need to honor both the entity's capabilities and the
 * user's optional `states` hide list.
 */
export function _filteredArmActions(features, configStates) {
  const supported = ARM_ACTIONS.filter(a => features & a.feature);
  const filtered = Array.isArray(configStates)
    ? supported.filter(a => configStates.includes(a.key))
    : supported;
  return { supported, filtered };
}

/**
 * First arm state key the entity supports (and is in `configStates`, if
 * given), with fallbacks so callers always get a usable key.
 */
export function defaultArmState(hass, entityId, configStates) {
  const features = hass.states[entityId]?.attributes?.supported_features || 0;
  const { supported, filtered } = _filteredArmActions(features, configStates);
  const pool = filtered.length > 0 ? filtered : supported;
  return pool.length > 0 ? pool[0].key : "arm_away";
}

// Entity registry platform this integration registers entities under. The
// domain is `securitas` (a rename to `verisure_owa` was reversed before
// release, so no install ever uses it).
const _OUR_PLATFORMS = new Set(["securitas"]);

// Card-picker suggestion hook: when the user selects one of our alarm panels,
// offer both the full card and the compact chip as variants.
export function alarmEntitySuggestion(hass, entityId) {
  if (!entityId.startsWith("alarm_control_panel.")) return null;
  if (!_OUR_PLATFORMS.has(hass?.entities?.[entityId]?.platform)) return null;
  return [
    { config: { type: "custom:verisure-owa-alarm-card", entity: entityId } },
    { config: { type: "custom:verisure-owa-alarm-chip", entity: entityId } },
  ];
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
 * @param {HTMLElement}   el          - Element to attach listeners to
 * @param {object}        config      - Card/badge config (tap_action etc.)
 * @param {object}        hass        - Home Assistant hass object
 * @param {string}        entityId    - Alarm entity id
 * @param {HTMLElement}   srcEl       - Element to dispatch events from
 * @param {object}        callbacks   - { startPinEntry(action), onMoreInfo() }
 * @param {string[]}      [cardStates] - Card's `_config.states` (optional);
 *                                       passed to executeAction so its
 *                                       arm_or_disarm fallback honors the
 *                                       user's filtered subset.
 * @returns {Function}                - Cleanup function (removes listeners)
 */
export function attachGesture(el, config, hass, entityId, srcEl, callbacks = {}, cardStates) {
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
      executeAction(holdAction, hass, entityId, srcEl, callbacks, cardStates);
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
      executeAction(doubleTapAction, hass, entityId, srcEl, callbacks, cardStates);
    } else {
      tapWindow = setTimeout(() => {
        tapWindow = null;
        executeAction(tapAction, hass, entityId, srcEl, callbacks, cardStates);
      }, DOUBLE_MS);
    }
  }

  function onPointerCancel() { cancelHold(); }

  function onClick(e) {
    // Our gesture handler owns the click on this element. Always swallow
    // the native click so it cannot bubble to a parent's tap_action handler
    // (e.g. an HA tile-card wrapper or dashboard view default) — otherwise
    // a single tap would fire both our action AND the parent's, opening
    // duplicate dialogs.
    if (holdFired) holdFired = false;
    e.stopImmediatePropagation();
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
 * @param {object}      action      - { action, navigation_path, perform_action, data, arm_state }
 * @param {object}      hass        - Home Assistant hass object
 * @param {string}      entityId    - Alarm entity id
 * @param {HTMLElement} srcEl       - Element to dispatch events from (for more-info)
 * @param {object}      callbacks   - { startPinEntry(serviceAction), onMoreInfo() }
 * @param {string[]}    [cardStates] - Card's `_config.states` (optional); when
 *                                     `arm_or_disarm` has no explicit
 *                                     `arm_state`, the fallback default is
 *                                     drawn from this filtered subset.
 */
function executeAction(action, hass, entityId, srcEl, callbacks = {}, cardStates) {
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
        const armKey = action.arm_state || defaultArmState(hass, entityId, cardStates);
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

// ── Legacy tag-name alias factory ─────────────────────────────────────────────
// Returns a thin subclass so a `securitas-*` (pre-v5) tag renders identically
// to its canonical `verisure-owa-*` element.
export function _makeLegacyShim(canonicalClass, _oldTag, _newTag) {
  return class extends canonicalClass {};
}
