// Shared arming-exception presentation for the Alarm Card, Tile feature and
// native More Info extension. Keep this module dependency-free: More Info is
// loaded globally, so importing the full alarm card/shared bundle here would
// make every Home Assistant page pay for dashboard-only code.

export const ARM_EXCEPTION_TRANSLATIONS = {
  en: {
    force_arm: "Force Arm",
    cancel: "Cancel",
    open_sensors: "Open sensor(s) — arm anyway?",
    open_sensors_no_force: "Open sensor(s) — close them before arming",
    action_failed: "The alarm action failed. Please try again.",
    action_failed_detail: "The alarm action failed: {error}",
  },
  es: {
    force_arm: "Forzar armado",
    cancel: "Cancelar",
    open_sensors: "Sensor(es) abierto(s) — ¿armar igualmente?",
    open_sensors_no_force: "Sensor(es) abierto(s) — ciérrelos antes de armar",
    action_failed: "La acción de la alarma ha fallado. Inténtelo de nuevo.",
    action_failed_detail: "La acción de la alarma ha fallado: {error}",
  },
  fr: {
    force_arm: "Forcer l’armement",
    cancel: "Annuler",
    open_sensors: "Capteur(s) ouvert(s) — armer quand même ?",
    open_sensors_no_force: "Capteur(s) ouvert(s) — fermez-les avant d’armer",
    action_failed: "L’action de l’alarme a échoué. Veuillez réessayer.",
    action_failed_detail: "L’action de l’alarme a échoué : {error}",
  },
  it: {
    force_arm: "Forza armamento",
    cancel: "Annulla",
    open_sensors: "Sensore/i aperto/i — armare comunque?",
    open_sensors_no_force: "Sensore/i aperto/i — chiuderli prima di attivare",
    action_failed: "L’azione dell’allarme non è riuscita. Riprova.",
    action_failed_detail: "L’azione dell’allarme non è riuscita: {error}",
  },
  pt: {
    force_arm: "Forçar armamento",
    cancel: "Cancelar",
    open_sensors: "Sensor(es) aberto(s) — armar na mesma?",
    open_sensors_no_force: "Sensor(es) aberto(s) — feche-os antes de armar",
    action_failed: "A ação do alarme falhou. Tente novamente.",
    action_failed_detail: "A ação do alarme falhou: {error}",
  },
};

ARM_EXCEPTION_TRANSLATIONS["pt-BR"] = ARM_EXCEPTION_TRANSLATIONS.pt;

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
      .copy { min-width: 0; }
      .force-title { font-weight: var(--ha-font-weight-medium, 500); }
      .sensor-list {
        margin: var(--ha-space-3, 12px) 0 0;
        padding-inline-start: var(--ha-space-6, 24px);
        color: var(--secondary-text-color);
      }
      .actions {
        display: flex;
        justify-content: flex-end;
        margin-top: var(--ha-space-4, 16px);
      }
      ha-control-button-group { display: flex; }
      ha-control-button {
        display: block;
        width: auto;
        min-width: 40px;
        height: 40px;
        color: var(--primary-text-color);
        --control-button-border-radius: var(--ha-border-radius-md, 10px);
      }
      ha-control-button.force {
        min-width: 104px;
        color: var(--text-primary-color, #fff);
        --control-button-background-color: var(--warning-color, #ff9800);
        --control-button-background-opacity: 1;
      }
      ha-control-button.cancel {
        min-width: 88px;
        --control-button-background-color: var(--secondary-background-color);
        --control-button-background-opacity: 1;
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
      :host([presentation="compact"]) .actions { margin: 0; }
      :host([presentation="compact"]) ha-control-button {
        height: 32px;
        min-width: 32px;
        --mdc-icon-size: 18px;
      }
      :host([presentation="compact"]) ha-control-button.force {
        min-width: 84px;
        font-size: var(--ha-font-size-xs, 12px);
      }
      :host([presentation="compact"]) ha-control-button.cancel { min-width: 32px; width: 32px; }
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
    this._buttonGroup = document.createElement("ha-control-button-group");
    this._cancelButton = document.createElement("ha-control-button");
    this._cancelButton.className = "cancel dismiss";
    this._forceButton = document.createElement("ha-control-button");
    this._forceButton.className = "force";
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

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  set stateObj(stateObj) {
    this._stateObj = stateObj;
    this._render();
  }

  set entity(entityId) {
    this._entityId = entityId;
    this._render();
  }

  set presentation(presentation) {
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
    const lang = this._hass?.language || this._hass?.locale?.language || "en";
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
    this._cancelButton.label = cancelLabel;
    this._cancelButton.setAttribute("aria-label", cancelLabel);
    this._cancelButton.replaceChildren();
    if (presentation === "compact") {
      const closeIcon = document.createElement("ha-icon");
      closeIcon.setAttribute("icon", "mdi:close");
      this._cancelButton.appendChild(closeIcon);
    } else {
      this._cancelButton.textContent = cancelLabel;
    }
    this._forceButton.label = forceLabel;
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
      const lang = this._hass?.language || this._hass?.locale?.language || "en";
      const detail =
        error instanceof Error && error.message
          ? armExceptionTranslation(lang, "action_failed_detail", { error: error.message })
          : armExceptionTranslation(lang, "action_failed");
      this.dispatchEvent(
        new CustomEvent("hass-notification", {
          detail: { message: detail },
          bubbles: true,
          composed: true,
        }),
      );
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
