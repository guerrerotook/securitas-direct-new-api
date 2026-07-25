// Verisure OWA alarm chip + badge — the compact, always-on-dashboard elements.
//
// Kept in their own lightweight module (separate from the heavy
// verisure-owa-alarm-card.js) so they render immediately on a cold dashboard
// load without first downloading the full card + editor. The full card is
// created lazily (document.createElement) only when the chip/badge popup
// opens, by which time the card module has loaded.

import {
  _t,
  STATE_CFG,
  GESTURE_KEYS,
  defaultArmState,
  attachGesture,
  _makeLegacyShim,
} from "./verisure-owa-alarm-shared.js?v=5.5.0";

class VerisureOwaAlarmBadge extends HTMLElement {
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
    if (this._pinOverlay) { this._pinOverlay.remove(); this._pinOverlay = null; }
    // Reset for re-render on reconnection — see VerisureOwaAlarmCard.disconnectedCallback.
    this._lastKey = null;
    this._pinState = null;
    this._pin = "";
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = config;
    this._lastKey = null;
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
      hold_action:       this._config.hold_action       || { action: "arm_or_disarm", arm_state: defaultArmState(this._hass, this._config.entity, this._config.states) },
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
      this._config.states,
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
          <button data-badge-key="cancel" aria-label="${_t(lang, "cancel")}" title="${_t(lang, "cancel")}" style="padding:10px;border:none;border-radius:8px;font-size:1em;cursor:pointer;background:var(--secondary-background-color);color:var(--error-color)">✕</button>
          <button data-badge-key="0" style="padding:10px;border:none;border-radius:8px;font-size:1em;font-weight:600;cursor:pointer;background:var(--secondary-background-color);color:var(--primary-text-color)">0</button>
          <button data-badge-key="del" aria-label="${_t(lang, "delete")}" title="${_t(lang, "delete")}" style="padding:10px;border:none;border-radius:8px;font-size:1em;cursor:pointer;background:var(--secondary-background-color);color:var(--primary-text-color)">⌫</button>
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

    // The full card lives in a separate module (verisure-owa-alarm-card.js)
    // loaded as its own Lovelace resource. On a slow cold load the chip/badge
    // can be tapped before that module has finished loading, so the
    // `securitas-alarm-card` element isn't defined yet. Fall back to HA's
    // native more-info dialog so the user can still arm/disarm rather than the
    // popup throwing.
    if (!customElements.get("securitas-alarm-card")) {
      this.dispatchEvent(new CustomEvent("hass-more-info", {
        detail: { entityId: this._config.entity },
        bubbles: true,
        composed: true,
      }));
      return;
    }

    this._dialogOpen = true;
    const lang = this._hass?.language || "en";

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
    closeBtn.setAttribute("aria-label", _t(lang, "close"));
    closeBtn.title = _t(lang, "close");
    Object.assign(closeBtn.style, {
      position: "absolute", top: "8px", right: "8px", width: "32px", height: "32px",
      border: "none", borderRadius: "50%", background: "var(--secondary-background-color)",
      color: "var(--primary-text-color)", fontSize: "1.1em", cursor: "pointer",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: "1",
    });

    content.appendChild(closeBtn);
    overlay.appendChild(content);
    document.body.appendChild(overlay);

    // Create the full alarm card inside the dialog.
    //
    // Strip the badge/chip's gesture config before passing it down. The same
    // tap_action key means different things in different contexts: on a badge
    // or chip, `more-info` is wired to open THIS popup; on the alarm-card,
    // `more-info` dispatches `hass-more-info` and opens HA's standard dialog.
    // Forwarding the badge's gestures verbatim would make a tap on the icon
    // inside the popup open HA's dialog on top of our popup.
    const innerConfig = { ...this._config };
    for (const k of GESTURE_KEYS) delete innerConfig[k];
    this._dialogCard = document.createElement("securitas-alarm-card");
    this._dialogCard.setConfig(innerConfig);
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

    // Close overlay when HA connection drops (e.g. restart). The connection's
    // addEventListener returns void, so we build our own unsubscribe via
    // removeEventListener (capturing the same conn) — otherwise each open would
    // leak a "disconnected" listener.
    if (this._hass?.connection) {
      const conn = this._hass.connection;
      conn.addEventListener("disconnected", close);
      this._unsubConnection = () =>
        conn.removeEventListener("disconnected", close);
    }
  }

  getCardSize() { return 1; }

  static getConfigElement() {
    return document.createElement("verisure-owa-alarm-card-editor");
  }

  static getStubConfig(hass) {
    const entities = Object.keys(hass.states).filter(e => e.startsWith("alarm_control_panel."));
    return { entity: entities[0] || "" };
  }
}

// ── Mushroom-compatible chip ─────────────────────────────────────────────────

class VerisureOwaAlarmChip extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dialogOpen = false;
    this._pinOverlay = null;
    this._pinState   = null;
    this._pin        = "";
    this._gestureCleanup = null;
  }

  disconnectedCallback() {
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
    if (this._pinOverlay) { this._pinOverlay.remove(); this._pinOverlay = null; }
    // Reset for re-render on reconnection — see VerisureOwaAlarmCard.disconnectedCallback.
    this._lastKey = null;
    this._pinState = null;
    this._pin = "";
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = config;
    this._lastKey = null;  // force re-render on config change
    if (this._hass) this._tryRender();
  }

  set config(config) { this.setConfig(config); }

  set hass(hass) {
    this._hass = hass;
    this._tryRender();
    if (this._dialogCard) this._dialogCard.hass = hass;
  }

  _tryRender() {
    if (!this._hass || !this._config) return;
    const stateObj = this._hass.states[this._config.entity];
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.force_arm_available}`
      : "missing";
    if (newKey !== this._lastKey) {
      this._lastKey = newKey;
      this._render();
    }
  }

  _render() {
    if (!this._hass || !this._config) return;

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-icon icon="mdi:shield-alert" style="color:var(--error-color)"></ha-icon>`;
      return;
    }

    const state = stateObj.state;
    const cfg = stateObj.attributes.force_arm_available
      ? { icon: "mdi:alert", color: "var(--warning-color, #FF9800)" }
      : STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)" };

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: flex;
          --chip-height: 36px;
          --chip-padding: 0 10px;
          --chip-border-radius: 19px;
          --chip-icon-size: 18px;
        }
        .chip {
          display: flex;
          align-items: center;
          justify-content: center;
          height: var(--chip-height);
          padding: var(--chip-padding);
          border-radius: var(--chip-border-radius);
          background: var(--ha-card-background, var(--card-background-color, #fff));
          box-shadow: var(--chip-box-shadow, 0 2px 4px rgba(0,0,0,0.06));
          cursor: pointer;
          transition: transform 0.1s;
          user-select: none;
          -webkit-user-select: none;
        }
        .chip:active { transform: scale(0.95); }
        .chip ha-icon {
          --mdc-icon-size: var(--chip-icon-size);
          color: ${cfg.color};
        }
      </style>
      <div class="chip" id="chip">
        <ha-icon icon="${cfg.icon}"></ha-icon>
      </div>`;

    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

    const chipEl = this.shadowRoot.getElementById("chip");
    const gestureConfig = {
      tap_action:        this._config.tap_action        || { action: "more-info" },
      hold_action:       this._config.hold_action       || { action: "none" },
      double_tap_action: this._config.double_tap_action || { action: "none" },
    };

    this._gestureCleanup = attachGesture(
      chipEl,
      gestureConfig,
      this._hass,
      this._config.entity,
      this,
      {
        onMoreInfo:    () => this._openDialog(),
        startPinEntry: (svcAction) => VerisureOwaAlarmBadge.prototype._startBadgePinEntry.call(this, svcAction),
      },
      this._config.states,
    );
  }

  _openDialog() {
    VerisureOwaAlarmBadge.prototype._openDialog.call(this);
  }

  _submitBadgePin(closeFn) {
    VerisureOwaAlarmBadge.prototype._submitBadgePin.call(this, closeFn);
  }

  getCardSize() { return 1; }
}

/* v8 ignore start -- defensive duplicate-registration guards;
   the "already defined" branches can't be hit in single-process tests. */
if (!customElements.get("verisure-owa-alarm-badge")) {
  customElements.define("verisure-owa-alarm-badge", VerisureOwaAlarmBadge);
}
if (!customElements.get("verisure-owa-alarm-chip")) {
  customElements.define("verisure-owa-alarm-chip", VerisureOwaAlarmChip);
}
if (!customElements.get("mushroom-verisure-owa-alarm-chip")) {
  customElements.define("mushroom-verisure-owa-alarm-chip", class extends VerisureOwaAlarmChip {});
}
if (!customElements.get("securitas-alarm-badge")) {
  customElements.define("securitas-alarm-badge",
    _makeLegacyShim(VerisureOwaAlarmBadge, "securitas-alarm-badge", "verisure-owa-alarm-badge"));
}
if (!customElements.get("securitas-alarm-chip")) {
  customElements.define("securitas-alarm-chip",
    _makeLegacyShim(VerisureOwaAlarmChip, "securitas-alarm-chip", "verisure-owa-alarm-chip"));
}
if (!customElements.get("mushroom-securitas-alarm-chip")) {
  customElements.define("mushroom-securitas-alarm-chip",
    _makeLegacyShim(VerisureOwaAlarmChip, "mushroom-securitas-alarm-chip", "mushroom-verisure-owa-alarm-chip"));
}

window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === "verisure-owa-alarm-chip")) {
  window.customCards.push({
    type:        "verisure-owa-alarm-chip",
    name:        "Verisure OWA Alarm Chip",
    description: "Mushroom-compatible alarm chip — shows alarm state with force-arm support.",
    preview:     false,
  });
}
window.customBadges = window.customBadges || [];
if (!window.customBadges.find(b => b.type === "verisure-owa-alarm-badge")) {
  window.customBadges.push({
    type:        "verisure-owa-alarm-badge",
    name:        "Verisure OWA Alarm Badge",
    description: "Compact alarm badge — click to open full alarm card with force-arm support.",
    preview:     false,
  });
}
/* v8 ignore stop */

export { VerisureOwaAlarmBadge, VerisureOwaAlarmChip };
