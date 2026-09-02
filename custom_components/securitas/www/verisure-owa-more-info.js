// Verisure OWA extension for Home Assistant's native alarm More Info control.
//
// The entity advertises this element through `custom_ui_more_info`. We keep
// Home Assistant's own alarm control intact and append only the integration-
// specific arming-exception UI below it. This lets HA continue to own alarm
// modes, PIN handling, state presentation, accessibility and responsive
// styling while Verisure adds the open-sensor and Force Arm workflow.

import { _t } from "./verisure-owa-alarm-shared.js?v=5.8.0-beta.2";
import { escHtml } from "./verisure-owa-card-utils.js?v=5.8.0-beta.2";

class VerisureOwaMoreInfo extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        #native-control { display: block; }
        #force-extension[hidden] { display: none; }
        .force-section {
          box-sizing: border-box;
          width: calc(100% - 32px);
          max-width: 520px;
          margin: var(--ha-space-4, 16px) auto 0;
          padding: var(--ha-space-4, 16px);
          border: 1px solid color-mix(in srgb, var(--warning-color, #ff9800) 45%, transparent);
          border-radius: var(--ha-card-border-radius, 12px);
          background: color-mix(in srgb, var(--warning-color, #ff9800) 12%, transparent);
          color: var(--primary-text-color);
        }
        .force-title {
          display: flex;
          align-items: center;
          gap: var(--ha-space-2, 8px);
          font-weight: var(--ha-font-weight-medium, 500);
        }
        .force-title ha-icon {
          flex: 0 0 auto;
          color: var(--warning-color, #ff9800);
        }
        .sensor-list {
          margin: var(--ha-space-3, 12px) 0 0;
          padding-inline-start: 24px;
          color: var(--secondary-text-color);
        }
        .force-actions {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: var(--ha-space-2, 8px);
          margin-top: var(--ha-space-4, 16px);
        }
        button {
          min-height: 40px;
          padding: 0 18px;
          border: 0;
          border-radius: var(--ha-button-border-radius, 20px);
          font: inherit;
          font-weight: var(--ha-font-weight-medium, 500);
          cursor: pointer;
        }
        button:disabled { cursor: progress; opacity: 0.6; }
        .cancel {
          background: transparent;
          color: var(--primary-color);
        }
        .force {
          background: var(--warning-color, #ff9800);
          color: var(--text-primary-color, #fff);
        }
      </style>
      <more-info-content id="native-control"></more-info-content>
      <div id="force-extension" hidden></div>`;
    this._nativeControl = this.shadowRoot.getElementById("native-control");
  }

  connectedCallback() {
    this._forwardNativeProperties();
    this._renderForceExtension();
  }

  set hass(hass) {
    this._hass = hass;
    this._forwardNativeProperties();
    this._renderForceExtension();
  }

  get hass() {
    return this._hass;
  }

  set stateObj(stateObj) {
    this._stateObj = stateObj;
    this._forwardNativeProperties();
    this._renderForceExtension();
  }

  get stateObj() {
    return this._stateObj;
  }

  set entry(entry) {
    this._entry = entry;
    this._forwardNativeProperties();
  }

  set editMode(editMode) {
    this._editMode = editMode;
    this._forwardNativeProperties();
  }

  set data(data) {
    this._data = data;
    this._forwardNativeProperties();
  }

  _forwardNativeProperties() {
    if (!this._nativeControl) return;
    // The outer HA more-info-content selected this custom element because the
    // entity advertises custom_ui_more_info. Feed an attribute-clean copy to a
    // nested stock more-info-content so HA follows its normal alarm path and
    // imports/renders more-info-alarm_control_panel itself. This avoids taking
    // a dependency on Lovelace-only window.loadCardHelpers and also keeps the
    // extension working when More Info is opened outside a dashboard.
    const stateObj = this._stateObj
      ? {
          ...this._stateObj,
          attributes: { ...this._stateObj.attributes },
        }
      : undefined;
    if (stateObj) delete stateObj.attributes.custom_ui_more_info;
    this._nativeControl.hass = this._hass;
    this._nativeControl.stateObj = stateObj;
    this._nativeControl.entry = this._entry;
    this._nativeControl.editMode = this._editMode;
    this._nativeControl.data = this._data;
  }

  _renderForceExtension() {
    const container = this.shadowRoot.getElementById("force-extension");
    if (!container) return;

    const attrs = this._stateObj?.attributes || {};
    const forceArmAvailable = attrs.force_arm_available === true;
    const active = attrs.arm_exception_active === true || forceArmAvailable;
    if (!active) {
      container.hidden = true;
      container.replaceChildren();
      return;
    }

    const lang = this._hass?.language || this._hass?.locale?.language || "en";
    const sensors = Array.isArray(attrs.arm_exceptions)
      ? attrs.arm_exceptions.map(sensor => String(sensor))
      : [];
    container.hidden = false;
    container.innerHTML = `
      <section class="force-section" role="alert">
        <div class="force-title">
          <ha-icon icon="mdi:alert"></ha-icon>
          <span>${_t(lang, forceArmAvailable ? "open_sensors" : "open_sensors_no_force")}</span>
        </div>
        ${sensors.length ? `<ul class="sensor-list">${sensors.map(sensor => `<li>${escHtml(sensor)}</li>`).join("")}</ul>` : ""}
        <div class="force-actions">
          <button class="cancel" type="button">${_t(lang, "cancel")}</button>
          ${forceArmAvailable ? `<button class="force" type="button">${_t(lang, "force_arm")}</button>` : ""}
        </div>
      </section>`;

    container.querySelector(".cancel").addEventListener("click", event => {
      this._callForceService("force_arm_cancel", event.currentTarget);
    });
    container.querySelector(".force")?.addEventListener("click", event => {
      this._callForceService("force_arm", event.currentTarget);
    });
  }

  _callForceService(service, button) {
    const entityId = this._stateObj?.entity_id;
    if (!entityId || !this._hass?.callService) return;
    button.disabled = true;
    Promise.resolve(
      this._hass.callService("verisure_owa", service, { entity_id: entityId }),
    ).finally(() => {
      if (button.isConnected) button.disabled = false;
    });
  }
}

if (!customElements.get("more-info-verisure-owa-alarm")) {
  customElements.define("more-info-verisure-owa-alarm", VerisureOwaMoreInfo);
}
