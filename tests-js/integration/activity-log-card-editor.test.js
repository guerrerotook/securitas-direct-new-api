import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-activity-log-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeActivityLogEntity } from "../fixtures/entities.js";

describe("verisure-owa-activity-log-card-editor", () => {
  it("registers as a custom element", () => {
    expect(customElements.get("verisure-owa-activity-log-card-editor")).toBeDefined();
  });

  it("restricts the entity picker to detected activity-log sensors via include_entities", () => {
    // The editor delegates entity selection to HA's <ha-form> with an entity
    // selector — the dropdown contents are resolved lazily by HA at runtime,
    // not embedded in the editor's shadow DOM. Activity-log sensors are
    // detected by their attribute shape (an `events` array) rather than by
    // name or platform, so we assert on the ha-form schema: when at least
    // one sensor has an `events` attribute, the selector must carry an
    // include_entities list of those sensor entity IDs.
    // hass MUST be assigned before setConfig: the editor builds the entity
    // schema inside _render(), and _render() is invoked synchronously by
    // setConfig — so any include_entities list is captured at that moment
    // from this._hass.states, with no later schema recompute on hass updates.
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.hass = makeHass({
      states: {
        "sensor.house_activity_log": makeActivityLogEntity(),
        "sensor.cabin_activity_log": makeActivityLogEntity(),
        "sensor.unrelated": { state: "1", attributes: {} },
        "light.kitchen": { state: "on", attributes: {} },
      },
    });
    editor.setConfig({ entity: "sensor.house_activity_log" });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm).not.toBeNull();
    expect(entityForm.tagName.toLowerCase()).toBe("ha-form");
    const [entityField] = entityForm.schema;
    expect(entityField.name).toBe("entity");
    // Only the two sensors with an `events` array attribute should be included.
    expect(entityField.selector.entity.include_entities).toEqual(
      expect.arrayContaining(["sensor.house_activity_log", "sensor.cabin_activity_log"]),
    );
    expect(entityField.selector.entity.include_entities).toHaveLength(2);
    expect(entityField.selector.entity.domain).toBeUndefined();
  });

  it("falls back to a sensor-domain selector when no activity-log sensors are loaded", () => {
    // If hass.states has no sensors carrying an `events` array, the editor
    // must fall back to a domain-scoped selector (sensor) instead of emitting
    // an empty include_entities list (which would render an empty dropdown).
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "light.kitchen": { state: "on", attributes: {} } },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    const [entityField] = entityForm.schema;
    expect(entityField).toEqual({
      name: "entity",
      selector: { entity: { domain: "sensor" } },
    });
  });

  it("exposes the full editor schema (entity, limit, title, max_height, hide_categories)", () => {
    // The editor manages five fields beyond the entity picker: number-slider
    // limit, free-text title and max_height, and a multi-select category
    // filter. The category options list is built from CATEGORY_ICONS — we
    // can't import it from the card module, so we sanity-check the multi-
    // select shape and confirm a known category ("armed") is present.
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "sensor.house_activity_log": makeActivityLogEntity() },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    const names = entityForm.schema.map((s) => s.name);
    expect(names).toEqual(["entity", "limit", "title", "max_height", "hide_categories"]);

    const limit = entityForm.schema.find((s) => s.name === "limit");
    expect(limit.selector).toEqual({
      number: { min: 1, max: 30, step: 1, mode: "slider" },
    });

    const title = entityForm.schema.find((s) => s.name === "title");
    expect(title.selector).toEqual({ text: {} });

    const maxHeight = entityForm.schema.find((s) => s.name === "max_height");
    expect(maxHeight.selector).toEqual({ text: {} });

    const hideCategories = entityForm.schema.find((s) => s.name === "hide_categories");
    expect(hideCategories.selector.select.multiple).toBe(true);
    expect(hideCategories.selector.select.mode).toBe("list");
    const optionValues = hideCategories.selector.select.options.map((o) => o.value);
    expect(optionValues).toContain("armed");
    expect(optionValues).toContain("alarm");
    expect(optionValues).toContain("unknown");
    // Every option must carry both a value and a (localized) label.
    for (const opt of hideCategories.selector.select.options) {
      expect(typeof opt.value).toBe("string");
      expect(typeof opt.label).toBe("string");
    }
  });

  it("seeds ha-form data with config defaults (limit 10, max_height 400px, empty arrays)", () => {
    // _formData() applies defaults for unset fields so that the form renders
    // sensible values on first open. We assert the defaults reach ha-form.data
    // unmodified for an empty config.
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "sensor.house_activity_log": makeActivityLogEntity() },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm.data).toEqual({
      entity: "",
      limit: 10,
      title: "",
      max_height: "400px",
      hide_categories: [],
    });
  });

  it("propagates an existing config (entity, limit, hide_categories) to ha-form data", () => {
    // When opening the editor on an already-configured card, every field set
    // in the user's config must round-trip into ha-form.data without being
    // overwritten by defaults.
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({
      entity: "sensor.house_activity_log",
      limit: 25,
      title: "Recent",
      max_height: "50vh",
      hide_categories: ["status_check", "unknown"],
    });
    editor.hass = makeHass({
      states: { "sensor.house_activity_log": makeActivityLogEntity() },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm.data).toEqual({
      entity: "sensor.house_activity_log",
      limit: 25,
      title: "Recent",
      max_height: "50vh",
      hide_categories: ["status_check", "unknown"],
    });
  });

  it("dispatches config-changed merging updates when ha-form emits value-changed", () => {
    // The editor wires to ha-form's "value-changed" event (HA convention).
    // happy-dom renders <ha-form> as a generic HTMLElement so we dispatch the
    // event directly. The dispatched config-changed must carry a merged config
    // (previous + new values) on detail.config, matching HA's editor contract.
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({ entity: "sensor.house_activity_log", limit: 10 });
    editor.hass = makeHass({
      states: { "sensor.house_activity_log": makeActivityLogEntity() },
    });
    document.body.appendChild(editor);

    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    entityForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { limit: 5, hide_categories: ["unknown"] } },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured).toEqual({
      entity: "sensor.house_activity_log",
      limit: 5,
      hide_categories: ["unknown"],
    });
  });

  it("reuses the same ha-form on subsequent setConfig calls and refreshes data", () => {
    // setConfig is called whenever the user edits in the lovelace editor.
    // The editor should NOT re-render (which would discard ha-form state) and
    // should instead push the new defaults into the existing entity-form.data.
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "sensor.house_activity_log": makeActivityLogEntity() },
    });
    document.body.appendChild(editor);

    const firstForm = editor.shadowRoot.getElementById("entity-form");
    editor.setConfig({ entity: "sensor.house_activity_log", limit: 7 });
    const secondForm = editor.shadowRoot.getElementById("entity-form");

    expect(secondForm).toBe(firstForm);
    expect(secondForm.data).toEqual({
      entity: "sensor.house_activity_log",
      limit: 7,
      title: "",
      max_height: "400px",
      hide_categories: [],
    });
  });
});
