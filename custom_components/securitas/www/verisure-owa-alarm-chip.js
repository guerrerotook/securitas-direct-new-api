// Verisure OWA alarm chip, badge + Tile feature — compact dashboard elements.
//
// Kept in their own lightweight module (separate from the heavy
// verisure-owa-alarm-card.js) so they render immediately on a cold dashboard
// load without first downloading the full card + editor. Badge/chip taps ask
// HA to open its native More Info dialog; the separate global More Info module
// adds the Verisure force-arm section there. The Tile feature remains self-
// contained in this lightweight module.

import {
  _t,
  STATE_CFG,
  attachGesture,
  callServiceWithErrorNotification,
  _makeLegacyShim,
} from "./verisure-owa-alarm-shared.js?v=5.8.0-beta.2";
import "./verisure-owa-arm-exception.js?v=5.8.0-beta.2";

const BADGE_DEFAULT_CONFIG = {
  show_name: false,
  show_state: true,
  show_icon: true,
};

const HA_THEME_COLORS = new Set([
  "primary", "accent", "red", "pink", "purple", "deep-purple", "indigo",
  "blue", "light-blue", "cyan", "teal", "green", "light-green", "lime",
  "yellow", "amber", "orange", "deep-orange", "brown", "light-grey", "grey",
  "dark-grey", "blue-grey", "black", "white", "primary-text",
  "secondary-text", "disabled",
]);

function badgeCssColor(color, fallback) {
  if (!color || color === "state") return fallback;
  return HA_THEME_COLORS.has(color) ? `var(--${color}-color)` : color;
}

function hassLanguage(hass) {
  return hass?.language || hass?.locale?.language || "en";
}

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

    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; min-width: 0; }
      :host([hidden]) { display: none; }
    `;
    this._alert = document.createElement("verisure-owa-arm-exception-alert");
    this.shadowRoot.append(style, this._alert);
  }

  connectedCallback() {
    this._render();
  }

  setConfig(config) {
    this._config = config || {};
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
    this._alert.update({
      hass: this._hass,
      stateObj,
      entityId: this._entityId(),
      presentation: "compact",
    });
    this._setVisible(this._alert.active);
  }
}

class VerisureOwaAlarmBadge extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
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
    if (this._hass) this._renderBadge();
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass.states[this._config.entity];
    const name = stateObj ? this._resolveName(stateObj) : "";
    const lang = hassLanguage(hass);
    const newKey = stateObj
      ? `${stateObj.state}|${stateObj.attributes.arm_exception_active}|${stateObj.attributes.force_arm_available}|${stateObj.attributes.entity_picture}|${name}|${lang}`
      : `missing|${lang}`;
    if (newKey !== this._lastKey) {
      this._lastKey = newKey;
      this._renderBadge();
    } else if (stateObj) {
      // A configured state_content attribute can change while the entity's
      // state stays the same. Forward every HA update to the native display
      // element without rebuilding the whole badge or its gesture handlers.
      this._updateStateDisplay(stateObj);
    }
  }

  _renderBadge() {
    if (!this._hass || !this._config) return;

    const stateObj = this._hass.states[this._config.entity];
    const lang = hassLanguage(this._hass);
    const style = document.createElement("style");
    style.textContent = `
      :host { display: inline-block; }
      ha-badge {
        cursor: pointer;
        transition: transform 0.1s ease;
      }
      ha-badge:active { transform: scale(0.95); }
      img[slot="icon"] { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; }
    `;
    if (!stateObj) {
      const name = typeof this._config.name === "string"
        ? this._config.name
        : this._config.entity;
      const badge = document.createElement("ha-badge");
      badge.label = name;
      badge.style.setProperty("--badge-color", "var(--error-color, #f44336)");
      const icon = document.createElement("ha-icon");
      icon.slot = "icon";
      icon.setAttribute("icon", "mdi:shield-alert");
      badge.append(icon, document.createTextNode(_t(lang, "unavailable")));
      this.shadowRoot.replaceChildren(style, badge);
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
      : badgeCssColor(this._config.colors?.[state] || this._config.color, icons.color);
    const showName = this._config.show_name === true;
    const showState = this._config.show_state !== false;
    const showIcon = this._config.show_icon !== false;
    const hasContent = showState || showName;
    const label = showState && showName ? name : "";

    const badgeEl = document.createElement("ha-badge");
    badgeEl.id = "badge";
    badgeEl.type = "button";
    badgeEl.label = label || undefined;
    badgeEl.iconOnly = !hasContent;
    if (showIcon) {
      const entityPicture =
        stateObj.attributes.entity_picture_local || stateObj.attributes.entity_picture;
      if (!armExceptionActive && this._config.show_entity_picture && entityPicture) {
        const picture = document.createElement("img");
        picture.slot = "icon";
        picture.setAttribute("aria-hidden", "true");
        picture.src = typeof this._hass.hassUrl === "function"
          ? this._hass.hassUrl(entityPicture)
          : entityPicture;
        badgeEl.appendChild(picture);
      } else if (armExceptionActive) {
        const alertIcon = document.createElement("ha-icon");
        alertIcon.slot = "icon";
        alertIcon.setAttribute("icon", icon);
        badgeEl.appendChild(alertIcon);
      } else {
        const stateIcon = document.createElement("ha-state-icon");
        stateIcon.slot = "icon";
        stateIcon.stateObj = stateObj;
        stateIcon.icon = icon;
        badgeEl.appendChild(stateIcon);
      }
    }
    if (showState) {
      const stateDisplay = document.createElement("state-display");
      stateDisplay.id = "badge-state";
      badgeEl.appendChild(stateDisplay);
    } else if (showName) {
      badgeEl.appendChild(document.createTextNode(name));
    }
    this.shadowRoot.replaceChildren(style, badgeEl);
    badgeEl.style.setProperty("--badge-color", color);
    this._updateStateDisplay(stateObj, name);

    // Clean up previous gesture listeners (badge re-renders on state change)
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }

    const gestureConfig = {
      tap_action:        this._config.tap_action        || { action: "more-info" },
      hold_action:       this._config.hold_action       || { action: "none" },
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
    const lang   = hassLanguage(hass);
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
    callServiceWithErrorNotification(
      this._hass,
      "alarm_control_panel",
      this._pinState.service,
      {
        entity_id: this._config.entity,
        code: this._pin,
      },
      undefined,
      this,
    );
    closeFn();
  }

  _openDialog() {
    // Let Home Assistant own the dialog shell, history/settings actions and
    // native alarm controls. The entity's custom_ui_more_info attribute selects
    // our small wrapper, which composes HA's stock control with Force Arm UI.
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId: this._config.entity },
      bubbles: true,
      composed: true,
    }));
  }

  getCardSize() { return 1; }

  static async getConfigElement() {
    // The entry-point URL carries a content hash generated by the backend.
    // Reuse it for the lazy editor chunk so editor-only fixes cannot remain
    // pinned behind an unchanged prerelease version in the browser cache.
    const sourceUrl = new URL(import.meta.url);
    const editorUrl = new URL("./verisure-owa-alarm-badge-editor.js", sourceUrl);
    editorUrl.search = sourceUrl.search;
    await import(editorUrl.href);
    return document.createElement("verisure-owa-alarm-badge-editor");
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
    description: "Alarm badge with name and state — click to open native More Info.",
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
