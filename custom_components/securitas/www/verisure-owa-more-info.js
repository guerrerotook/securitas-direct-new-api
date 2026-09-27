// Verisure OWA extension for Home Assistant's native alarm More Info control.
//
// Home Assistant continues to own alarm modes, PIN handling, state display,
// accessibility and responsive layout. This wrapper composes the native
// control with the shared arming-exception element and a per-device
// auto-force-arm tick box (mirroring the dashboard card's option).

import {
  armExceptionTranslation,
  autoForceActive,
  hassLanguage,
  readAutoForce,
  writeAutoForce,
} from "./verisure-owa-arm-exception.js?v=5.8.0";

class VerisureOwaMoreInfo extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });

    // Per-device auto-force-arm state. Home Assistant's stock control
    // dispatches the arm here (not our code), so the intent is armed by
    // observing the panel move disarmed→arming rather than by a click we own.
    // `_pendingAutoForce` therefore never fires for a stale/foreign force
    // context that was already present when the dialog opened.
    this._autoForceArm = false;
    this._pendingAutoForce = false;
    this._prevState = null;
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

    this._autoForceField = document.createElement("ha-formfield");
    this._autoForceField.className = "auto-force-toggle";
    this._autoForceField.hidden = true;
    this._autoForceCheckbox = document.createElement("ha-checkbox");
    this._autoForceCheckbox.className = "auto-force-checkbox";
    this._autoForceField.appendChild(this._autoForceCheckbox);
    this._autoForceCheckbox.addEventListener("change", (event) => {
      event.stopPropagation();
      this._autoForceArm = this._autoForceCheckbox.checked === true;
      if (this._entityId) writeAutoForce(this._entityId, this._autoForceArm);
      this._lastSyncKey = null; // reflect the new tick immediately
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
    this._forwardNativeProperties();
    this._syncAutoForce();
    this._updateForceExtension();
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

  // Fire-and-forget verisure_owa service call for an auto-force step. A
  // rejection (offline panel, missing service) just means this step didn't
  // happen — contain it so it never surfaces as an unhandled promise rejection
  // in the browser console. Returns the settled promise for tests.
  _bestEffortCall(service, entityId) {
    if (!entityId || !this._hass?.callService) return Promise.resolve();
    return Promise.resolve(
      this._hass.callService("verisure_owa", service, { entity_id: entityId }),
    ).catch(() => {});
  }

  // Request to skip the transient "force-arm required?" prompt for the arm now
  // in flight — fired as the panel moves to `arming`, before the exception
  // lands, so the prompt may be suppressed entirely. If it loses the race the
  // backend still dismisses the prompt on force-arm; either way the follow-up
  // "force-armed" confirmation is what tells the user what happened.
  _suppressArmPrompt(entityId) {
    this._bestEffortCall("suppress_arm_exception_prompt", entityId);
  }

  // Called on every hass/stateObj update. When a user arm (dispatched by HA's
  // stock control) hits a forceable exception, force-arm automatically instead
  // of leaving the prompt for the user. Mirrors the dashboard card's
  // state-machine, but arms the intent from the observed disarmed→arming
  // transition since this wrapper does not own the arm dispatch.
  _maybeAutoForceArm(stateObj) {
    if (!stateObj) return;
    const s = stateObj.state;
    const entityId = stateObj.entity_id;
    const forceable = stateObj.attributes?.force_arm_available === true;

    // Arm-start: a fresh arm just went in-flight from disarmed. Arm the intent
    // and pre-suppress the prompt best-effort. Because the intent is only ever
    // armed here — once the panel is already in flight — there is no
    // "clicked but not yet arming" gap to track (unlike the dashboard card,
    // which arms on its own click a tick before the panel moves).
    if (
      !this._pendingAutoForce &&
      this._prevState === "disarmed" &&
      (s === "arming" || s === "pending") &&
      autoForceActive(stateObj, this._autoForceArm)
    ) {
      this._pendingAutoForce = true;
      this._suppressArmPrompt(entityId);
      this._prevState = s;
      return;
    }

    if (this._pendingAutoForce) {
      if (forceable) {
        this._pendingAutoForce = false;
        // Re-check the authoritative gate at fire time: if the option was
        // turned off (or the tick cleared) after the arm started, don't force.
        if (autoForceActive(stateObj, this._autoForceArm)) {
          this._bestEffortCall("force_arm", entityId);
        }
        this._prevState = s;
        return;
      }
      if (s === "arming" || s === "pending") {
        // The arm reached the panel and is in flight — wait for it to resolve.
        this._prevState = s;
        return;
      }
      // Any settled state with no forceable exception means the arm resolved:
      // armed OK, or a non-forceable rejection that bounced back to disarmed.
      // Drop the intent so a later, unrelated force context can't trigger it.
      this._pendingAutoForce = false;
    }
    this._prevState = s;
  }

  _syncAutoForce() {
    if (!this._autoForceField) return;
    const stateObj = this._resolvedStateObj();
    const entityId = stateObj?.entity_id || null;
    if (entityId && entityId !== this._entityId) {
      this._entityId = entityId;
      this._autoForceArm = readAutoForce(entityId);
      // Drop any intent/transition state from a previous entity so a reused
      // instance can't carry a stale pending force-arm across a swap.
      this._pendingAutoForce = false;
      this._prevState = null;
      this._lastSyncKey = null;
    }
    if (!stateObj) return;

    // The state machine must run every tick (it catches a force context that
    // appears on the same tick), but the presentation below only changes with
    // the gate, language and tick state — memoize it so the common no-op tick,
    // and the paired set hass/set stateObj call, skip the DOM/translation work.
    this._maybeAutoForceArm(stateObj);

    // The tick box is a pre-arm preference, offered only while the alarm can
    // be armed and the integration capability gate is on.
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
