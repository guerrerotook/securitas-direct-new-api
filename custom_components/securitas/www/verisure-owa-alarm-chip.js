// Verisure OWA alarm chip, badge + Tile feature — compact dashboard elements.
//
// Kept in their own lightweight module (separate from the heavy
// verisure-owa-alarm-card.js) so they render immediately on a cold dashboard
// load without first downloading the full card + editor. The full card is
// created lazily (document.createElement) only when the chip/badge popup
// opens, by which time the card module has loaded. The Tile feature remains
// self-contained in this lightweight module.

import {
  _t,
  STATE_CFG,
  GESTURE_KEYS,
  defaultArmState,
  attachGesture,
  _makeLegacyShim,
} from "./verisure-owa-alarm-shared.js?v=5.8.0-beta.2";
import { escHtml } from "./verisure-owa-card-utils.js?v=5.8.0-beta.2";

const BADGE_DEFAULT_CONFIG = {
  show_name: false,
  show_state: true,
  show_icon: true,
};

// Tile Card feature that surfaces the open-zone snapshot inline. Home
// Assistant forwards `hass`, the Tile's entity context and (for backwards
// compatibility with older custom features) `stateObj` to custom features.
// Keep this component framework-free so it stays in the lightweight
// chip/badge bundle and is available as soon as a dashboard loads.
class VerisureOwaArmExceptionFeature extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._context = {};
    this._stateObj = null;
    this._lastKey = null;
  }

  connectedCallback() {
    this._render();
  }

  setConfig(config) {
    this._config = config || {};
    this._lastKey = null;
    this._render();
  }

  static getStubConfig() {
    return { type: "custom:verisure-owa-arm-exception" };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  set context(context) {
    this._context = context || {};
    this._render();
  }

  // HA still forwards this property for compatibility with the original
  // custom Tile feature API. It also makes the feature usable in third-party
  // cards that provide a state object but not a Lovelace context.
  set stateObj(stateObj) {
    this._stateObj = stateObj;
    this._render();
  }

  _entityId() {
    return this._context?.entity_id || this._stateObj?.entity_id || null;
  }

  _entity() {
    const entityId = this._entityId();
    return (entityId && this._hass?.states?.[entityId]) || this._stateObj;
  }

  _setVisible(visible) {
    this.hidden = !visible;

    // Remove the HA feature wrapper from its grid while there is no warning;
    // hiding only the child would leave an empty feature row in the Tile.
    const root = this.getRootNode();
    if (root instanceof ShadowRoot && root.host?.localName === "hui-card-feature") {
      root.host.hidden = !visible;
    }
  }

  _render() {
    const stateObj = this._entity();
    const attrs = stateObj?.attributes || {};
    const forceArmAvailable = attrs.force_arm_available === true;
    const active = attrs.arm_exception_active === true || forceArmAvailable;
    const sensors = Array.isArray(attrs.arm_exceptions)
      ? attrs.arm_exceptions.map(sensor => String(sensor))
      : [];
    const lang = this._hass?.language || this._hass?.locale?.language || "en";
    const key = `${active}|${forceArmAvailable}|${lang}|${sensors.join("\u0000")}`;

    this._setVisible(active);
    if (!active || key === this._lastKey) return;
    this._lastKey = key;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-width: 0;
        }
        :host([hidden]) { display: none; }
        .warning {
          box-sizing: border-box;
          min-height: var(--feature-height, 42px);
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto;
          align-items: center;
          gap: 8px;
          padding: 7px 8px;
          border: 1px solid color-mix(in srgb, var(--warning-color, #ff9800) 45%, transparent);
          border-radius: var(--feature-border-radius, 12px);
          background: color-mix(in srgb, var(--warning-color, #ff9800) 14%, transparent);
          color: var(--primary-text-color);
        }
        ha-icon {
          --mdc-icon-size: 20px;
          align-self: start;
          margin-top: 1px;
          color: var(--warning-color, #ff9800);
        }
        .copy { min-width: 0; }
        .title {
          font-size: 12px;
          font-weight: 600;
          line-height: 16px;
        }
        .sensors {
          margin-top: 1px;
          font-size: 12px;
          line-height: 16px;
          color: var(--secondary-text-color);
          overflow-wrap: anywhere;
        }
        .actions {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        button {
          min-height: 30px;
          border: none;
          border-radius: 15px;
          cursor: pointer;
          font: inherit;
          font-size: 12px;
          font-weight: 600;
        }
        .force {
          padding: 0 10px;
          background: var(--warning-color, #ff9800);
          color: var(--text-primary-color, #fff);
        }
        .dismiss {
          width: 30px;
          padding: 0;
          background: transparent;
          color: var(--secondary-text-color);
          font-size: 16px;
        }
      </style>
      <div class="warning" role="alert">
        <ha-icon icon="mdi:alert"></ha-icon>
        <div class="copy">
          <div class="title">${_t(lang, forceArmAvailable ? "open_sensors" : "open_sensors_no_force")}</div>
          ${sensors.length ? `<div class="sensors">${sensors.map(escHtml).join(", ")}</div>` : ""}
        </div>
        <div class="actions">
          ${forceArmAvailable ? `<button class="force" type="button">${_t(lang, "force_arm")}</button>` : ""}
          <button class="dismiss" type="button" title="${_t(lang, "cancel")}" aria-label="${_t(lang, "cancel")}">✕</button>
        </div>
      </div>`;

    this.shadowRoot.querySelector(".force")?.addEventListener("click", e => {
      e.stopPropagation();
      const entityId = this._entityId();
      if (entityId) {
        this._hass?.callService("verisure_owa", "force_arm", { entity_id: entityId });
      }
    });
    this.shadowRoot.querySelector(".dismiss")?.addEventListener("click", e => {
      e.stopPropagation();
      const entityId = this._entityId();
      if (entityId) {
        this._hass?.callService("verisure_owa", "force_arm_cancel", { entity_id: entityId });
      }
    });
  }
}

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
    this._config = { ...BADGE_DEFAULT_CONFIG, ...config };
    this._lastKey = null;
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass.states[this._config.entity];
    const name = stateObj ? this._resolveName(stateObj) : "";
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.arm_exception_active}|${stateObj.attributes.force_arm_available}|${name}|${hass.language}`
      : "missing";
    if (newKey !== this._lastKey) {
      this._lastKey = newKey;
      this._renderBadge();
    } else if (stateObj) {
      // A configured state_content attribute can change while the entity's
      // state stays the same. Forward every HA update to the native display
      // element without rebuilding the whole badge or its gesture handlers.
      this._updateStateDisplay(stateObj);
    }
    // Forward hass to the dialog card if open
    if (this._dialogCard) this._dialogCard.hass = hass;
  }

  _renderBadge() {
    if (!this._hass || !this._config) return;

    const stateObj = this._hass.states[this._config.entity];
    const lang = this._hass.language || this._hass.locale?.language || "en";
    if (!stateObj) {
      const name = typeof this._config.name === "string"
        ? this._config.name
        : this._config.entity;
      this.shadowRoot.innerHTML = `
        <style>:host { display: inline-block; }</style>
        <ha-badge label="${escHtml(name)}" style="--badge-color:var(--error-color,#f44336)">
          <ha-icon slot="icon" icon="mdi:shield-alert"></ha-icon>
          ${_t(lang, "unavailable")}
        </ha-badge>`;
      return;
    }

    const state = stateObj.state;
    const name = this._resolveName(stateObj);
    const armExceptionActive =
      stateObj.attributes.arm_exception_active || stateObj.attributes.force_arm_available;
    const icons = armExceptionActive
      ? { icon: "mdi:alert", color: "var(--warning-color, #FF9800)" }
      : STATE_CFG[state] || { icon: "mdi:shield", color: "var(--disabled-color,#9E9E9E)" };
    const icon = armExceptionActive ? icons.icon : (this._config.icon || icons.icon);
    const color = armExceptionActive
      ? icons.color
      : (this._config.colors?.[state] || icons.color);
    const showName = this._config.show_name === true;
    const showState = this._config.show_state !== false;
    const showIcon = this._config.show_icon !== false;
    const hasContent = showState || showName;
    const label = showState && showName ? name : "";

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: inline-block; }
        ha-badge {
          cursor: pointer;
          transition: transform 0.1s ease;
        }
        ha-badge:active { transform: scale(0.95); }
      </style>
      <ha-badge id="badge" type="button" ${label ? `label="${escHtml(label)}"` : ""} ${hasContent ? "" : "icon-only"}>
        ${showIcon ? `<ha-icon slot="icon" icon="${escHtml(icon)}"></ha-icon>` : ""}
        ${showState ? `<state-display id="badge-state"></state-display>` : showName ? escHtml(name) : ""}
      </ha-badge>`;

    const badgeEl = this.shadowRoot.getElementById("badge");
    badgeEl.style.setProperty("--badge-color", color);
    this._updateStateDisplay(stateObj, name);

    // Clean up previous gesture listeners (badge re-renders on state change)
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

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

  _updateStateDisplay(stateObj, resolvedName) {
    const stateDisplay = this.shadowRoot.getElementById("badge-state");
    if (!stateDisplay) return;
    stateDisplay.hass = this._hass;
    stateDisplay.stateObj = stateObj;
    stateDisplay.content = this._config.state_content;
    stateDisplay.timeFormat = this._config.time_format;
    stateDisplay.name = resolvedName || this._resolveName(stateObj);
  }

  _resolveName(stateObj) {
    if (typeof this._hass?.formatEntityName === "function") {
      try {
        return this._hass.formatEntityName(stateObj, this._config.name);
      } catch (_) {
        // Older/minimal HA clients may not expose all entity registries needed
        // by structured entity-name configs. Fall back to the friendly name.
      }
    }
    if (typeof this._config.name === "string") return this._config.name;
    const nameItems = Array.isArray(this._config.name)
      ? this._config.name
      : this._config.name ? [this._config.name] : [];
    if (nameItems.length && nameItems.every(item => item?.type === "text")) {
      return nameItems.map(item => item.text || "").join(" ");
    }
    return stateObj.attributes.friendly_name || this._config.entity;
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

  static getDefaultConfig() {
    return { ...BADGE_DEFAULT_CONFIG };
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
      ? `${stateObj.state}|${stateObj.attributes.arm_exception_active}|${stateObj.attributes.force_arm_available}`
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
    const cfg = stateObj.attributes.arm_exception_active || stateObj.attributes.force_arm_available
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
if (!customElements.get("verisure-owa-arm-exception")) {
  customElements.define("verisure-owa-arm-exception", VerisureOwaArmExceptionFeature);
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
    description: "Alarm badge with name and state — click to open the full alarm card.",
    preview:     true,
  });
}
window.customCardFeatures = window.customCardFeatures || [];
if (!window.customCardFeatures.find(f => f.type === "verisure-owa-arm-exception")) {
  window.customCardFeatures.push({
    type: "verisure-owa-arm-exception",
    name: "Verisure OWA Open Sensors",
    isSupported: (hass, context) => {
      const entityId = context?.entity_id || "";
      if (!entityId.startsWith("alarm_control_panel.")) return false;
      const registryEntry = hass?.entities?.[entityId];
      return !registryEntry || registryEntry.platform === "securitas";
    },
    // HA before the context-based custom-feature API calls `supported` with
    // the state object instead. Current HA prefers isSupported above.
    supported: stateObj => stateObj?.entity_id?.startsWith("alarm_control_panel.") === true,
    configurable: false,
  });
}
/* v8 ignore stop */

export { VerisureOwaAlarmBadge, VerisureOwaAlarmChip, VerisureOwaArmExceptionFeature };
