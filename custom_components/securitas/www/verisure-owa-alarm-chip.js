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
  _makeLegacyShim,
} from "./verisure-owa-alarm-shared.js?v=5.8.0-beta.2";
import "./verisure-owa-arm-exception.js?v=5.8.0-beta.2";

const BADGE_DEFAULT_CONFIG = {
  show_name: false,
  show_state: true,
  show_icon: true,
};

const COMPACT_ACTION_KEYS = ["tap_action", "hold_action", "double_tap_action"];

// Replace the removed conditional Badge/Chip action as old YAML is loaded.
// The native More Info dialog provides mode selection and PIN handling.
function migrateCompactAlarmConfig(config) {
  let migrated = config;
  for (const key of COMPACT_ACTION_KEYS) {
    if (config[key]?.action !== "arm_or_disarm") continue;
    if (migrated === config) migrated = { ...config };
    migrated[key] = { action: "more-info" };
  }
  return migrated;
}

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

  setConfig() {
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
    this._gestureCleanup = null; // cleanup fn returned by attachGesture
  }

  disconnectedCallback() {
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
    // Reset for re-render on reconnection — see VerisureOwaAlarmCard.disconnectedCallback.
    this._lastKey = null;
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = { ...BADGE_DEFAULT_CONFIG, ...migrateCompactAlarmConfig(config) };
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

    this._gestureCleanup = attachGesture(
      badgeEl,
      this._config,
      this._hass,
      this._config.entity,
      this,
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
    this._gestureCleanup = null;
  }

  disconnectedCallback() {
    if (this._gestureCleanup) { this._gestureCleanup(); this._gestureCleanup = null; }
    // Reset for re-render on reconnection — see VerisureOwaAlarmCard.disconnectedCallback.
    this._lastKey = null;
  }

  setConfig(config) {
    if (!config.entity) throw new Error("Please define an entity");
    this._config = migrateCompactAlarmConfig(config);
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
    this._gestureCleanup = attachGesture(
      chipEl,
      this._config,
      this._hass,
      this._config.entity,
      this,
    );
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
