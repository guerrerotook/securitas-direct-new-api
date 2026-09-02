// Verisure OWA extension for Home Assistant's native alarm More Info control.
//
// Home Assistant continues to own alarm modes, PIN handling, state display,
// accessibility and responsive layout. This wrapper only composes the native
// control with the shared arming-exception element.

import "./verisure-owa-arm-exception.js?v=5.8.0-beta.2";

class VerisureOwaMoreInfo extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; }
      #native-control { display: block; }
      #force-extension {
        box-sizing: border-box;
        width: calc(100% - 32px);
        max-width: 520px;
        margin: var(--ha-space-4, 16px) auto 0;
      }
    `;
    this._nativeControl = document.createElement("more-info-content");
    this._nativeControl.id = "native-control";
    this._forceExtension = document.createElement("verisure-owa-arm-exception-alert");
    this._forceExtension.id = "force-extension";
    this.shadowRoot.append(style, this._nativeControl, this._forceExtension);
  }

  connectedCallback() {
    this._forwardNativeProperties();
    this._updateForceExtension();
  }

  set hass(hass) {
    this._hass = hass;
    this._forwardNativeProperties();
    this._updateForceExtension();
  }

  get hass() {
    return this._hass;
  }

  set stateObj(stateObj) {
    this._stateObj = stateObj;
    this._forwardNativeProperties();
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
