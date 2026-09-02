// Native-style visual editor for the Verisure OWA alarm Badge.
//
// This intentionally uses Home Assistant's ha-form selector API without Lit.
// Keeping it in a separate, dynamically imported module prevents the compact
// Badge from depending on the much larger Alarm Card editor at runtime.

import {
  _filteredArmActions,
  _t,
  defaultArmState,
} from "./verisure-owa-alarm-shared.js?v=5.8.0-beta.2";

const DEFAULT_CONFIG = {
  show_name: false,
  show_state: true,
  show_icon: true,
};

const ACTION_KEYS = ["tap_action", "hold_action", "double_tap_action"];
const LEGACY_KEYS = ["colors", "states"];

function displayedElements(config) {
  const result = [];
  if (config.show_name === true) result.push("name");
  if (config.show_state !== false) result.push("state");
  if (config.show_icon !== false) result.push("icon");
  return result;
}

function stateContentHasTimestamp(content) {
  const values = Array.isArray(content) ? content : content ? [content] : [];
  return values.some((value) => ["last_updated", "last_changed", "last_triggered"].includes(value));
}

class VerisureOwaAlarmBadgeEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};

    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; }
      ha-form { display: block; width: 100%; }
    `;
    this._form = document.createElement("ha-form");
    this._form.id = "badge-form";
    this._form.addEventListener("value-changed", (event) => {
      event.stopPropagation();
      this._valueChanged(event.detail?.value || {});
    });
    this.shadowRoot.append(style, this._form);
  }

  setConfig(config) {
    this._config = { ...DEFAULT_CONFIG, ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _schema() {
    const localize = (key, fallback) => this._hass?.localize?.(key) || fallback;
    const contentSchema = [
      {
        name: "name",
        selector: { entity_name: {} },
        context: { entity: "entity" },
      },
      {
        name: "",
        type: "grid",
        schema: [
          {
            name: "color",
            selector: {
              ui_color: { default_color: "state", include_state: true },
            },
          },
          {
            name: "icon",
            selector: { icon: {} },
            context: { icon_entity: "entity" },
          },
          {
            name: "show_entity_picture",
            selector: { boolean: {} },
          },
        ],
      },
      {
        name: "displayed_elements",
        selector: {
          select: {
            mode: "list",
            multiple: true,
            options: ["name", "state", "icon"].map((value) => ({
              value,
              label: localize(
                `ui.panel.lovelace.editor.badge.entity.displayed_elements_options.${value}`,
                value.replace(/^./, (character) => character.toUpperCase()),
              ),
            })),
          },
        },
      },
      {
        name: "state_content",
        selector: { ui_state_content: { allow_name: true } },
        context: { filter_entity: "entity" },
      },
    ];
    if (stateContentHasTimestamp(this._config.state_content)) {
      contentSchema.push({
        name: "time_format",
        selector: { ui_time_format: {} },
      });
    }

    const usesNativeHoldAction =
      this._config.hold_action && this._config.hold_action.action !== "arm_or_disarm";
    const alarmSchema = [
      {
        name: "hold_to_arm_or_disarm",
        selector: { boolean: {} },
      },
    ];
    if (!usesNativeHoldAction) {
      const features =
        this._hass?.states?.[this._config.entity]?.attributes?.supported_features || 0;
      const { supported, filtered } = _filteredArmActions(features, this._config.states);
      const options = filtered.length ? filtered : supported;
      if (options.length) {
        alarmSchema.push({
          name: "arm_state",
          selector: {
            select: {
              mode: "dropdown",
              options: options.map((action) => ({
                value: action.key,
                label: _t(this._hass?.language || "en", action.labelKey),
              })),
            },
          },
        });
      }
    }

    return [
      {
        name: "entity",
        selector: { entity: { domain: "alarm_control_panel" } },
      },
      {
        name: "content",
        type: "expandable",
        flatten: true,
        schema: contentSchema,
      },
      {
        name: "interactions",
        type: "expandable",
        flatten: true,
        schema: [
          {
            name: "tap_action",
            selector: { ui_action: { default_action: "more-info" } },
            context: { entity_id: "entity", area_id: "area" },
          },
          {
            name: "",
            type: "optional_actions",
            flatten: true,
            schema: [...(usesNativeHoldAction ? ["hold_action"] : []), "double_tap_action"].map(
              (name) => ({
                name,
                selector: { ui_action: { default_action: "none" } },
                context: { entity_id: "entity", area_id: "area" },
              }),
            ),
          },
        ],
      },
      {
        name: "alarm_behavior",
        type: "expandable",
        flatten: true,
        schema: alarmSchema,
      },
    ];
  }

  _formData() {
    const data = {
      ...this._config,
      displayed_elements: displayedElements(this._config),
      hold_to_arm_or_disarm:
        !this._config.hold_action || this._config.hold_action.action === "arm_or_disarm",
    };
    if (data.hold_to_arm_or_disarm) {
      data.arm_state =
        this._config.hold_action?.arm_state ||
        defaultArmState(this._hass, this._config.entity, this._config.states);
    }
    delete data.type;
    for (const key of LEGACY_KEYS) delete data[key];
    // arm_or_disarm is an integration runtime extension, not a native HA
    // action. Preserve it in config, but do not feed an unsupported value to
    // the stock ui_action selector.
    for (const key of ACTION_KEYS) {
      if (data[key]?.action === "arm_or_disarm") delete data[key];
    }
    return data;
  }

  _render() {
    if (!this._hass || !this._config) return;
    this._form.hass = this._hass;
    this._form.data = this._formData();
    this._form.schema = this._schema();
    this._form.computeLabel = (schema) => this._computeLabel(schema);
    this._form.computeHelper = (schema) => this._computeHelper(schema);
  }

  _computeLabel(schema) {
    const localize = (key, fallback) => this._hass?.localize?.(key) || fallback;
    if (schema.name === "alarm_behavior") {
      return _t(this._hass?.language || "en", "editor_alarm_behavior");
    }
    if (schema.name === "hold_to_arm_or_disarm") {
      return _t(this._hass?.language || "en", "editor_hold_to_arm_or_disarm");
    }
    if (schema.name === "arm_state") {
      return _t(this._hass?.language || "en", "editor_arm_state");
    }
    if (
      ["color", "state_content", "show_entity_picture", "displayed_elements"].includes(schema.name)
    ) {
      return localize(
        `ui.panel.lovelace.editor.badge.entity.${schema.name}`,
        schema.name.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase()),
      );
    }
    return localize(
      `ui.panel.lovelace.editor.card.generic.${schema.name}`,
      schema.name.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase()),
    );
  }

  _computeHelper(schema) {
    if (schema.name !== "color") return undefined;
    return this._hass?.localize?.("ui.panel.lovelace.editor.badge.entity.color_helper");
  }

  _valueChanged(value) {
    const previous = this._config;
    const next = { ...value, type: previous.type };
    if (!next.type) delete next.type;

    if (!next.state_content) delete next.state_content;
    if (!next.time_format) delete next.time_format;
    if (!next.color) delete next.color;
    if (!next.icon) delete next.icon;
    if (!next.name) delete next.name;

    const holdToArmOrDisarm = value.hold_to_arm_or_disarm !== false;
    const armState = value.arm_state || previous.hold_action?.arm_state;
    delete next.hold_to_arm_or_disarm;
    delete next.arm_state;
    if (holdToArmOrDisarm) {
      next.hold_action = {
        action: "arm_or_disarm",
        ...(armState ? { arm_state: armState } : {}),
      };
    } else if (!next.hold_action) {
      // The Badge runtime intentionally keeps its historic arm/disarm hold
      // default. Save an explicit native no-op when the user switches it off.
      next.hold_action = { action: "none" };
    }

    const shown = Array.isArray(next.displayed_elements)
      ? next.displayed_elements
      : displayedElements(previous);
    next.show_name = shown.includes("name");
    next.show_state = shown.includes("state");
    next.show_icon = shown.includes("icon");
    delete next.displayed_elements;

    for (const key of LEGACY_KEYS) {
      if (previous[key] !== undefined) next[key] = previous[key];
    }
    for (const key of ACTION_KEYS) {
      if (
        key !== "hold_action" &&
        previous[key]?.action === "arm_or_disarm" &&
        value[key] === undefined
      ) {
        next[key] = previous[key];
      }
    }

    this._config = next;
    this._render();
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: next },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

/* v8 ignore start -- defensive duplicate-registration guard. */
if (!customElements.get("verisure-owa-alarm-badge-editor")) {
  customElements.define("verisure-owa-alarm-badge-editor", VerisureOwaAlarmBadgeEditor);
}
/* v8 ignore stop */

export { VerisureOwaAlarmBadgeEditor };
