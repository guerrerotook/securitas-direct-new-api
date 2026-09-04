// Native-style visual editor for the Verisure OWA alarm Badge.
//
// This intentionally uses Home Assistant's ha-form selector API without Lit.
// Keeping it in a separate, dynamically imported module prevents the compact
// Badge from depending on the much larger Alarm Card editor at runtime.

import {
  GESTURE_KEYS,
  migrateCompactAlarmConfig,
} from "./verisure-owa-alarm-shared.js?v=5.8.0-rc.1";

const DEFAULT_CONFIG = {
  show_name: false,
  show_state: true,
  show_icon: true,
};

const PRESERVED_CUSTOM_KEYS = ["colors"];
// Keep the stock HA action editor, but only advertise actions that this
// dependency-free custom Badge can faithfully execute. `toggle` is not valid
// for alarm_control_panel entities (they have explicit alarm_arm_* / disarm
// services), while URL and Assist require private frontend helpers that are
// not part of the custom-card API.
const BADGE_ACTIONS = ["more-info", "navigate", "perform-action", "none"];

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
    this._config = {
      ...DEFAULT_CONFIG,
      ...migrateCompactAlarmConfig(config),
    };
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
            selector: {
              ui_action: { default_action: "more-info", actions: BADGE_ACTIONS },
            },
            context: { entity_id: "entity", area_id: "area" },
          },
          {
            name: "",
            type: "optional_actions",
            flatten: true,
            schema: GESTURE_KEYS.slice(1).map((name) => ({
              name,
              selector: {
                ui_action: { default_action: "none", actions: BADGE_ACTIONS },
              },
              context: { entity_id: "entity", area_id: "area" },
            })),
          },
        ],
      },
    ];
  }

  _formData() {
    const data = {
      ...this._config,
      displayed_elements: displayedElements(this._config),
    };
    delete data.type;
    delete data.states;
    for (const key of PRESERVED_CUSTOM_KEYS) delete data[key];
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

    const shown = Array.isArray(next.displayed_elements)
      ? next.displayed_elements
      : displayedElements(previous);
    next.show_name = shown.includes("name");
    next.show_state = shown.includes("state");
    next.show_icon = shown.includes("icon");
    delete next.displayed_elements;

    for (const key of PRESERVED_CUSTOM_KEYS) {
      if (previous[key] !== undefined) next[key] = previous[key];
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
