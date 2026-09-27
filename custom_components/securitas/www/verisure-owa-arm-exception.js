// Shared arming-exception presentation for the Alarm Card, Tile feature and
// native More Info extension. Keep this module dependency-free: More Info is
// loaded globally, so importing the full alarm card/shared bundle here would
// make every Home Assistant page pay for dashboard-only code.

export const ARM_EXCEPTION_TRANSLATIONS = {
  en: {
    force_arm: "Force Arm",
    auto_force_arm: "Automatically force-arm past open sensors",
    cancel: "Cancel",
    open_sensors: "Open sensor(s) — arm anyway?",
    open_sensors_no_force: "Open sensor(s) — close them before arming",
    action_failed: "The alarm action failed. Please try again.",
    action_failed_detail: "The alarm action failed: {error}",
  },
  es: {
    force_arm: "Forzar armado",
    auto_force_arm: "Forzar armado automáticamente con sensores abiertos",
    cancel: "Cancelar",
    open_sensors: "Sensor(es) abierto(s) — ¿armar igualmente?",
    open_sensors_no_force: "Sensor(es) abierto(s) — ciérrelos antes de armar",
    action_failed: "La acción de la alarma ha fallado. Inténtelo de nuevo.",
    action_failed_detail: "La acción de la alarma ha fallado: {error}",
  },
  fr: {
    force_arm: "Forcer l’armement",
    auto_force_arm: "Forcer l’armement automatiquement malgré les capteurs ouverts",
    cancel: "Annuler",
    open_sensors: "Capteur(s) ouvert(s) — armer quand même ?",
    open_sensors_no_force: "Capteur(s) ouvert(s) — fermez-les avant d’armer",
    action_failed: "L’action de l’alarme a échoué. Veuillez réessayer.",
    action_failed_detail: "L’action de l’alarme a échoué : {error}",
  },
  it: {
    force_arm: "Forza armamento",
    auto_force_arm: "Forza l’armamento automaticamente con sensori aperti",
    cancel: "Annulla",
    open_sensors: "Sensore/i aperto/i — armare comunque?",
    open_sensors_no_force: "Sensore/i aperto/i — chiuderli prima di attivare",
    action_failed: "L’azione dell’allarme non è riuscita. Riprova.",
    action_failed_detail: "L’azione dell’allarme non è riuscita: {error}",
  },
  pt: {
    force_arm: "Forçar armamento",
    auto_force_arm: "Forçar armamento automaticamente com sensores abertos",
    cancel: "Cancelar",
    open_sensors: "Sensor(es) aberto(s) — armar na mesma?",
    open_sensors_no_force: "Sensor(es) aberto(s) — feche-os antes de armar",
    action_failed: "A ação do alarme falhou. Tente novamente.",
    action_failed_detail: "A ação do alarme falhou: {error}",
  },
};

ARM_EXCEPTION_TRANSLATIONS["pt-BR"] = ARM_EXCEPTION_TRANSLATIONS.pt;

export function hassLanguage(hass) {
  return hass?.language || hass?.locale?.language || "en";
}

// ── Per-device auto-force-arm preference (shared by the alarm card, the
// native More Info dialog and the Tile feature) ─────────────────────────────
// Defined here, in the module every surface imports, so the storage key can
// never drift between them. The tick is remembered per device; More Info and
// the Tile follow each other's ticks, while the deprecated alarm card only reads
// it when its config loads.
export function autoForceStorageKey(entityId) {
  return `verisure-owa:auto-force-arm:${entityId}`;
}

export function readAutoForce(entityId) {
  try {
    return globalThis.localStorage?.getItem(autoForceStorageKey(entityId)) === "true";
  } catch {
    return false;
  }
}

// More Info and the Tile learn of a tick made elsewhere in this page from this
// event. Nothing listens for the browser's `storage` event, so a tick made in
// another tab shows only after the alarm changes or the surface is put back on
// the page.
export const AUTO_FORCE_CHANGED_EVENT = "verisure-owa-auto-force-changed";

export function writeAutoForce(entityId, on) {
  try {
    globalThis.localStorage?.setItem(autoForceStorageKey(entityId), on ? "true" : "false");
  } catch {
    /* private mode / storage disabled — the tick box just won't persist */
  }
  globalThis.dispatchEvent?.(
    new CustomEvent(AUTO_FORCE_CHANGED_EVENT, { detail: { entityId, on: on === true } }),
  );
}

// Auto-force only ever acts when BOTH the integration capability gate is on
// AND this device's tick box is ticked. The gate is authoritative: a
// remembered tick from when the gate was enabled must not keep auto-forcing
// after an admin turns the option off.
export function autoForceActive(stateObj, ticked) {
  return ticked === true && stateObj?.attributes?.auto_force_arm_enabled === true;
}

// How long a press stays valid while HA's PIN prompt is open (time to type).
export const AUTO_FORCE_INTENT_TTL_MS = 60_000;

// How long a press stays valid with no PIN prompt open, and after a Submit in
// one. The arm service call then follows within about a second (measured
// ~0.1 s after Submit), so this only has to outlast that; it also bounds how
// long an arm refused by HA (a wrong PIN) can leave the press behind.
export const AUTO_FORCE_ARM_START_MS = 10_000;

const PIN_PROMPT = "dialog-enter-code";

// HA's PIN prompt submits from the keypad's tick button, a text PIN's footer
// button, or Enter in the PIN box; anything else that closes it is a Cancel.
// Should HA rename these, no Submit is seen and nothing is auto-forced after a
// PIN: the user gets the normal Force Arm prompt instead.
function isPinSubmit(event) {
  const path = event.composedPath();
  if (!path.some((node) => node.localName === PIN_PROMPT)) return false;
  if (event.type === "keydown") {
    return event.key === "Enter" && path.some((node) => node.localName === "ha-input" && node.id === "code");
  }
  return path.some(
    (node) =>
      (node.localName === "ha-control-button" && node.classList?.contains("submit")) ||
      (node.localName === "ha-button" && node.slot === "primaryAction"),
  );
}

const IN_FLIGHT_STATES = new Set(["arming", "pending"]);

// Auto-force for the surfaces that wrap Home Assistant's own alarm-mode
// buttons (More Info, Tile). HA dispatches the arm, not our code, so the
// tracker listens for what HA's modes control announces — the chosen mode
// (`value-changed`) and its PIN prompt opening (`show-dialog`), being
// submitted (a click or Enter in it) and closing (`dialog-closed`) — and is fed
// every state update. Only an arm that follows a press on `controlTag` (and,
// when a PIN is asked for, a Submit) is forced; an arm started anywhere else
// (automation, another screen, the Verisure app) is left alone.
export class AutoForceArmTracker {
  constructor(controlTag) {
    this._controlTag = controlTag;
    this._disconnect = null;
    this._clearInputs();
    this._reset(null);
  }

  // The latest state and tick from update(), which a button press is judged
  // against.
  _clearInputs() {
    this._stateObj = null;
    this._ticked = false;
  }

  _reset(entityId) {
    this._entityId = entityId;
    this._intentAt = null;
    this._deadline = 0;
    this._promptOpen = false;
    this._submitted = false;
    this._pending = false;
    this._prevState = null;
  }

  // Listens on `scope` (an ancestor of the modes control) for presses and the
  // PIN prompt opening, and on window for the prompt being submitted and
  // closing: HA renders the prompt in its own shell, outside the surface. A
  // press before the first update() is ignored.
  connect(scope) {
    this.disconnect();
    const onValueChanged = (event) => this.noteValueChanged(event, this._stateObj, this._ticked);
    const onShowDialog = (event) => this.noteShowDialog(event);
    const onDialogClosed = (event) => this.noteDialogClosed(event);
    const onPromptInput = (event) => this.noteSubmit(event);
    // Capture: the press is recorded before the control's own handler can open the PIN prompt.
    scope.addEventListener("value-changed", onValueChanged, true);
    scope.addEventListener("show-dialog", onShowDialog);
    globalThis.addEventListener("dialog-closed", onDialogClosed);
    // Capture: the prompt's own handlers submit and close it on this event.
    globalThis.addEventListener("click", onPromptInput, true);
    globalThis.addEventListener("keydown", onPromptInput, true);
    this._disconnect = () => {
      scope.removeEventListener("value-changed", onValueChanged, true);
      scope.removeEventListener("show-dialog", onShowDialog);
      globalThis.removeEventListener("dialog-closed", onDialogClosed);
      globalThis.removeEventListener("click", onPromptInput, true);
      globalThis.removeEventListener("keydown", onPromptInput, true);
    };
  }

  // A button press belongs to the surface it was made on; once the surface is
  // removed, a later arm cannot be one it started.
  disconnect() {
    this._disconnect?.();
    this._disconnect = null;
    this._clearInputs();
    this._reset(null);
  }

  _syncEntity(stateObj) {
    if (stateObj.entity_id !== this._entityId) this._reset(stateObj.entity_id);
  }

  // Must be called synchronously from the event listener: composedPath() is
  // empty once dispatch has finished. The event is only read, never stopped,
  // so HA's own handler still dispatches the arm.
  noteValueChanged(event, stateObj, ticked) {
    if (!stateObj) return;
    const mode = event.detail?.value;
    if (typeof mode !== "string" || !mode.startsWith("armed_")) return;
    if (!event.composedPath().some((node) => node.localName === this._controlTag)) return;
    this._syncEntity(stateObj);
    if (stateObj.state !== "disarmed" || !autoForceActive(stateObj, ticked)) return;
    this._intentAt = Date.now();
    this._deadline = this._intentAt + AUTO_FORCE_ARM_START_MS;
  }

  // Synchronous from the listener, like noteValueChanged.
  noteShowDialog(event) {
    if (this._intentAt === null || event.detail?.dialogTag !== PIN_PROMPT) return;
    if (!event.composedPath().some((node) => node.localName === this._controlTag)) return;
    this._promptOpen = true;
    this._submitted = false;
    this._deadline = this._intentAt + AUTO_FORCE_INTENT_TTL_MS;
  }

  // Synchronous from the listener, like noteValueChanged. A Submit after the
  // typing cap does not revive the press.
  noteSubmit(event) {
    if (this._intentAt === null || !this._promptOpen || this._submitted) return;
    if (Date.now() > this._deadline || !isPinSubmit(event)) return;
    this._submitted = true;
    this._deadline = Date.now() + AUTO_FORCE_ARM_START_MS;
  }

  // The arm follows a Submit before the prompt finishes closing (measured
  // ~0.1 s vs ~0.25 s), so closing only matters when nothing was submitted:
  // that is a Cancel, and the press goes with it.
  noteDialogClosed(event) {
    if (this._intentAt === null || !this._promptOpen) return;
    if (event.detail?.dialog !== PIN_PROMPT) return;
    this._promptOpen = false;
    if (!this._submitted) this._intentAt = null;
  }

  // Runs on every state update, including repeats of the same state.
  update(stateObj, ticked, hass) {
    this._stateObj = stateObj || null;
    this._ticked = ticked;
    if (!stateObj) return;
    this._syncEntity(stateObj);
    const s = stateObj.state;
    const entityId = stateObj.entity_id;

    if (this._intentAt !== null && this._prevState === "disarmed" && s !== "disarmed") {
      // While the prompt is open, an arm before its Submit is not this one.
      const fresh = Date.now() <= this._deadline && (!this._promptOpen || this._submitted);
      this._intentAt = null;
      if (fresh && IN_FLIGHT_STATES.has(s) && autoForceActive(stateObj, ticked)) {
        this._pending = true;
        // Fired as the arm goes in flight, before the exception lands, so the
        // transient "force-arm required?" prompt may be skipped entirely; if
        // it loses that race the backend still dismisses it on force-arm.
        this._call(hass, "suppress_arm_exception_prompt", entityId);
        this._prevState = s;
        return;
      }
    }

    if (this._pending) {
      if (stateObj.attributes?.force_arm_available === true) {
        this._pending = false;
        // The gate or tick may have been turned off since the arm started.
        if (autoForceActive(stateObj, ticked)) this._call(hass, "force_arm", entityId);
      } else if (!IN_FLIGHT_STATES.has(s)) {
        // Settled with no forceable exception (armed, or a non-forceable
        // rejection back to disarmed): a later force context is not ours.
        this._pending = false;
      }
    }
    this._prevState = s;
  }

  // Best effort: a failure (offline panel, missing service, a dropped
  // connection that throws before returning a promise) only means the step did
  // not happen, and must not escape into the surface's render or surface as an
  // unhandled rejection.
  _call(hass, service, entityId) {
    if (!entityId || !hass?.callService) return;
    try {
      const result = hass.callService("verisure_owa", service, { entity_id: entityId });
      Promise.resolve(result).catch(() => {});
    } catch {
      /* the step did not happen */
    }
  }
}

export function armExceptionTranslation(lang, key, vars) {
  const table =
    ARM_EXCEPTION_TRANSLATIONS[lang] ||
    ARM_EXCEPTION_TRANSLATIONS[lang?.split("-")[0]] ||
    ARM_EXCEPTION_TRANSLATIONS.en;
  let value = table[key] || ARM_EXCEPTION_TRANSLATIONS.en[key] || key;
  for (const [name, replacement] of Object.entries(vars || {})) {
    const safeReplacement = String(replacement);
    value = value.replaceAll(`{${name}}`, () => safeReplacement);
  }
  return value;
}

export function notifyActionFailure(hass, srcEl, error) {
  if (!srcEl) return;
  const lang = hassLanguage(hass);
  const message =
    error instanceof Error && error.message
      ? armExceptionTranslation(lang, "action_failed_detail", { error: error.message })
      : armExceptionTranslation(lang, "action_failed");
  srcEl.dispatchEvent(
    new CustomEvent("hass-notification", {
      detail: { message },
      bubbles: true,
      composed: true,
    }),
  );
}

export function armExceptionState(stateObj) {
  const attrs = stateObj?.attributes || {};
  const forceArmAvailable = attrs.force_arm_available === true;
  return {
    active: attrs.arm_exception_active === true || forceArmAvailable,
    forceArmAvailable,
    sensors: Array.isArray(attrs.arm_exceptions)
      ? attrs.arm_exceptions.map((sensor) => String(sensor))
      : [],
  };
}

function appendTextElement(parent, tagName, className, text) {
  const element = document.createElement(tagName);
  element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

export class VerisureOwaArmExceptionAlert extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._presentation = "full";
    this._busy = false;
    this._lastKey = null;

    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; min-width: 0; }
      :host([hidden]) { display: none; }
      .warning {
        box-sizing: border-box;
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        align-items: start;
        gap: var(--ha-space-2, 8px);
        padding: var(--ha-space-4, 16px);
        border: 1px solid color-mix(in srgb, var(--warning-color, #ff9800) 45%, transparent);
        border-radius: var(--ha-card-border-radius, 12px);
        background: color-mix(in srgb, var(--warning-color, #ff9800) 12%, transparent);
        color: var(--primary-text-color);
      }
      .warning-icon {
        --mdc-icon-size: 20px;
        color: var(--warning-color, #ff9800);
      }
      .copy { min-width: 0; text-align: start; }
      .force-title { font-weight: var(--ha-font-weight-medium, 500); }
      .sensor-list {
        margin: var(--ha-space-3, 12px) 0 0;
        padding-inline-start: var(--ha-space-6, 24px);
        color: var(--secondary-text-color);
      }
      .actions {
        grid-column: 2;
        display: flex;
        justify-content: flex-end;
        margin-top: var(--ha-space-4, 16px);
      }
      .button-group { display: flex; gap: var(--ha-space-3, 12px); }
      ha-button { --ha-button-height: 40px; }
      ha-button.force {
        min-width: 104px;
      }
      ha-button.cancel {
        min-width: 88px;
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }
      :host([presentation="compact"]) .warning {
        min-height: var(--feature-height, 42px);
        grid-template-columns: auto minmax(0, 1fr) auto;
        align-items: center;
        gap: var(--ha-space-2, 8px);
        padding: 7px 8px;
        border-radius: var(--feature-border-radius, 12px);
        background: color-mix(in srgb, var(--warning-color, #ff9800) 14%, transparent);
      }
      :host([presentation="compact"]) .warning-icon { align-self: start; margin-top: 1px; }
      :host([presentation="compact"]) .force-title,
      :host([presentation="compact"]) .sensor-list {
        font-size: var(--ha-font-size-xs, 12px);
        line-height: var(--ha-line-height-condensed, 16px);
      }
      :host([presentation="compact"]) .sensor-list {
        display: inline;
        margin: 1px 0 0;
        padding: 0;
        list-style: none;
        overflow-wrap: anywhere;
      }
      :host([presentation="compact"]) .sensor-list li { display: inline; }
      :host([presentation="compact"]) .sensor-list li:not(:last-child)::after { content: ", "; }
      :host([presentation="compact"]) .actions { grid-column: auto; margin: 0; }
      :host([presentation="compact"]) ha-button {
        --ha-button-height: 32px;
        min-width: 32px;
        --mdc-icon-size: 18px;
      }
      :host([presentation="compact"]) ha-button.force {
        min-width: 84px;
        font-size: var(--ha-font-size-xs, 12px);
      }
      :host([presentation="compact"]) ha-button.cancel {
        min-width: 32px;
        width: 32px;
        --wa-form-control-padding-inline: 0;
      }
    `;

    this._section = document.createElement("section");
    this._section.className = "warning force-section";
    this._section.setAttribute("role", "alert");

    const icon = document.createElement("ha-icon");
    icon.className = "warning-icon";
    icon.setAttribute("icon", "mdi:alert");
    this._section.appendChild(icon);

    this._copy = document.createElement("div");
    this._copy.className = "copy";
    this._title = appendTextElement(this._copy, "div", "force-title", "");
    this._sensorList = document.createElement("ul");
    this._sensorList.className = "sensor-list sensors";
    this._copy.appendChild(this._sensorList);
    this._section.appendChild(this._copy);

    this._actions = document.createElement("div");
    this._actions.className = "actions force-btns";
    this._buttonGroup = document.createElement("div");
    this._buttonGroup.className = "button-group";
    this._cancelButton = document.createElement("ha-button");
    this._cancelButton.className = "cancel dismiss";
    this._cancelButton.setAttribute("appearance", "filled");
    this._cancelButton.setAttribute("variant", "neutral");
    this._forceButton = document.createElement("ha-button");
    this._forceButton.className = "force";
    this._forceButton.setAttribute("appearance", "filled");
    this._forceButton.setAttribute("variant", "warning");
    this._buttonGroup.append(this._cancelButton, this._forceButton);
    this._actions.appendChild(this._buttonGroup);
    this._section.appendChild(this._actions);

    this.shadowRoot.append(style, this._section);

    this._cancelButton.addEventListener("click", (event) => {
      event.stopPropagation();
      void this._callService("force_arm_cancel");
    });
    this._forceButton.addEventListener("click", (event) => {
      event.stopPropagation();
      void this._callService("force_arm");
    });
  }

  connectedCallback() {
    this._render();
  }

  update({ hass, stateObj, entityId, presentation } = {}) {
    this._hass = hass;
    this._stateObj = stateObj;
    this._entityId = entityId || stateObj?.entity_id || null;
    this._presentation = presentation || "full";
    this._render();
  }

  get active() {
    return armExceptionState(this._resolvedStateObj()).active;
  }

  _resolvedStateObj() {
    return (this._entityId && this._hass?.states?.[this._entityId]) || this._stateObj;
  }

  _render() {
    if (!this.shadowRoot) return;
    const state = armExceptionState(this._resolvedStateObj());
    const lang = hassLanguage(this._hass);
    const presentation = this._presentation === "compact" ? "compact" : "full";
    const key = `${state.active}|${state.forceArmAvailable}|${lang}|${presentation}|${state.sensors.join("\u0000")}`;
    this.hidden = !state.active;
    this.setAttribute("presentation", presentation);
    if (!state.active || key === this._lastKey) return;
    this._lastKey = key;

    this._title.textContent = armExceptionTranslation(
      lang,
      state.forceArmAvailable ? "open_sensors" : "open_sensors_no_force",
    );
    this._sensorList.replaceChildren();
    for (const sensor of state.sensors) {
      appendTextElement(this._sensorList, "li", "sensor", sensor);
    }
    this._sensorList.hidden = state.sensors.length === 0;

    const cancelLabel = armExceptionTranslation(lang, "cancel");
    const forceLabel = armExceptionTranslation(lang, "force_arm");
    this._cancelButton.setAttribute("aria-label", cancelLabel);
    this._cancelButton.replaceChildren();
    if (presentation === "compact") {
      const closeIcon = document.createElement("ha-icon");
      closeIcon.setAttribute("icon", "mdi:close");
      closeIcon.setAttribute("aria-hidden", "true");
      const accessibleLabel = document.createElement("span");
      accessibleLabel.className = "visually-hidden";
      accessibleLabel.textContent = cancelLabel;
      this._cancelButton.append(closeIcon, accessibleLabel);
    } else {
      this._cancelButton.textContent = cancelLabel;
    }
    this._forceButton.setAttribute("aria-label", forceLabel);
    this._forceButton.textContent = forceLabel;
    this._forceButton.hidden = !state.forceArmAvailable;
    this._setBusy(this._busy);
  }

  _setBusy(busy) {
    this._busy = busy;
    this._cancelButton.disabled = busy;
    this._forceButton.disabled = busy;
  }

  async _callService(service) {
    const entityId = this._entityId || this._stateObj?.entity_id;
    if (!entityId || !this._hass?.callService || this._busy) return;
    this._setBusy(true);
    try {
      await this._hass.callService("verisure_owa", service, { entity_id: entityId });
    } catch (error) {
      notifyActionFailure(this._hass, this, error);
    } finally {
      if (this.isConnected) this._setBusy(false);
    }
  }
}

/* v8 ignore start -- defensive duplicate-registration guard. */
if (!customElements.get("verisure-owa-arm-exception-alert")) {
  customElements.define("verisure-owa-arm-exception-alert", VerisureOwaArmExceptionAlert);
}
/* v8 ignore stop */
