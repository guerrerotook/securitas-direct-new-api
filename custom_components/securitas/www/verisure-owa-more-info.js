// Verisure OWA extension for Home Assistant's native alarm More Info control.
//
// Home Assistant continues to own alarm modes, PIN handling, state display,
// accessibility and responsive layout. This wrapper composes the native
// control with the shared arming-exception element and a per-device
// auto-force-arm tick box, shared with the Tile feature, that force-arms past
// open sensors for arms started from this dialog's own mode buttons.

import {
  AUTO_FORCE_CHANGED_EVENT,
  AutoForceArmTracker,
  armExceptionTranslation,
  hassLanguage,
  readAutoForce,
  writeAutoForce,
} from "./verisure-owa-arm-exception.js?v=5.9.0";

class VerisureOwaMoreInfo extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });

    this._autoForceArm = false;
    this._autoForceTracker = new AutoForceArmTracker(
      "ha-state-control-alarm_control_panel-modes",
    );
    this._entityId = null;
    this._lastSyncKey = null;

    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; }
      #native-control { display: block; }
      .auto-force-toggle {
        box-sizing: border-box;
        width: calc(100% - 32px);
        max-width: 520px;
        margin: var(--ha-space-3, 12px) auto 0;
        --mdc-typography-body2-font-size: var(--ha-font-size-m, 14px);
      }
      .auto-force-toggle[hidden] { display: none; }
      #force-extension {
        box-sizing: border-box;
        width: calc(100% - 32px);
        max-width: 520px;
        margin: var(--ha-space-4, 16px) auto 0;
      }
    `;
    this._nativeControl = document.createElement("more-info-content");
    this._nativeControl.id = "native-control";
    this._onAutoForceChanged = (event) => {
      if (event.detail?.entityId !== this._entityId) return;
      this._autoForceArm = event.detail.on === true;
      this._lastSyncKey = null;
      this._syncAutoForce();
    };

    this._autoForceField = document.createElement("ha-formfield");
    this._autoForceField.className = "auto-force-toggle";
    this._autoForceField.hidden = true;
    this._autoForceCheckbox = document.createElement("ha-checkbox");
    this._autoForceCheckbox.className = "auto-force-checkbox";
    this._autoForceField.appendChild(this._autoForceCheckbox);
    this._autoForceCheckbox.addEventListener("change", (event) => {
      event.stopPropagation();
      // _onAutoForceChanged hears this write and takes the new tick.
      if (this._entityId) writeAutoForce(this._entityId, this._autoForceCheckbox.checked === true);
    });

    this._forceExtension = document.createElement("verisure-owa-arm-exception-alert");
    this._forceExtension.id = "force-extension";
    this.shadowRoot.append(
      style,
      this._nativeControl,
      this._autoForceField,
      this._forceExtension,
    );
  }

  connectedCallback() {
    this._autoForceTracker.connect(this._nativeControl);
    globalThis.addEventListener(AUTO_FORCE_CHANGED_EVENT, this._onAutoForceChanged);
    this._forwardNativeProperties();
    this._syncAutoForce();
    this._updateForceExtension();
  }

  disconnectedCallback() {
    this._autoForceTracker.disconnect();
    globalThis.removeEventListener(AUTO_FORCE_CHANGED_EVENT, this._onAutoForceChanged);
  }

  set hass(hass) {
    this._hass = hass;
    this._forwardNativeProperties();
    this._syncAutoForce();
    this._updateForceExtension();
  }

  get hass() {
    return this._hass;
  }

  set stateObj(stateObj) {
    this._stateObj = stateObj;
    this._forwardNativeProperties();
    this._syncAutoForce();
    this._updateForceExtension();
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
    // imports/renders more-info-alarm_control_panel itself without recursion.
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

  // ── Auto-force-arm (per-device) ──────────────────────────────────────────
  _resolvedStateObj() {
    return (this._entityId && this._hass?.states?.[this._entityId]) || this._stateObj || null;
  }

  _syncAutoForce() {
    if (!this._autoForceField) return;
    const stateObj = this._resolvedStateObj();
    const entityId = stateObj?.entity_id || null;
    if (entityId && entityId !== this._entityId) {
      this._entityId = entityId;
      this._autoForceArm = readAutoForce(entityId);
      this._lastSyncKey = null;
    }
    // The tracker runs on every update (it catches a force context that
    // appears on the same tick) and judges a button press by the last one.
    this._autoForceTracker.update(stateObj, this._autoForceArm, this._hass);
    if (!stateObj) return;

    // The tick box is a pre-arm preference, offered only while the alarm can
    // be armed and the integration capability gate is on. It only changes with
    // the gate, language and tick state, so it is memoized: the common no-op
    // update, and the paired set hass/set stateObj call, skip the DOM work.
    const gateOn = stateObj.attributes?.auto_force_arm_enabled === true;
    const show = gateOn && stateObj.state === "disarmed";
    const lang = hassLanguage(this._hass);
    const key = `${show}|${lang}|${this._autoForceArm}`;
    if (key === this._lastSyncKey) return;
    this._lastSyncKey = key;

    this._autoForceField.hidden = !show;
    if (show) {
      this._autoForceField.setAttribute(
        "label",
        armExceptionTranslation(lang, "auto_force_arm"),
      );
      this._autoForceCheckbox.checked = this._autoForceArm;
    }
  }

  _updateForceExtension() {
    if (!this._forceExtension) return;
    this._forceExtension.update({
      hass: this._hass,
      stateObj: this._stateObj,
      entityId: this._stateObj?.entity_id,
      presentation: "full",
    });
  }
}

/* v8 ignore start -- defensive duplicate-registration guard. */
if (!customElements.get("more-info-verisure-owa-alarm")) {
  customElements.define("more-info-verisure-owa-alarm", VerisureOwaMoreInfo);
}
/* v8 ignore stop */
