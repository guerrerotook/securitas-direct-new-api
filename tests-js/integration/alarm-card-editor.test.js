import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

describe("verisure-owa-alarm-card-editor", () => {
  it("registers as a custom element", () => {
    expect(customElements.get("verisure-owa-alarm-card-editor")).toBeDefined();
  });

  it("renders an entity picker scoped to alarm_control_panel via ha-form", () => {
    // The editor delegates entity selection to HA's <ha-form> with an entity
    // selector — the list of alarm panels is resolved lazily by HA at runtime,
    // not embedded in the editor's shadow DOM. We instead assert that the
    // editor wires up the entity ha-form with the alarm_control_panel domain
    // restriction, and that the current entity flows into ha-form.data.
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.panel_a" });
    editor.hass = makeHass({
      states: {
        "alarm_control_panel.panel_a": makeAlarmEntity(),
        "alarm_control_panel.panel_b": makeAlarmEntity(),
        "light.kitchen": { state: "on", attributes: {} },
      },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm).not.toBeNull();
    expect(entityForm.tagName.toLowerCase()).toBe("ha-form");
    expect(entityForm.schema).toEqual([
      { name: "entity", selector: { entity: { domain: "alarm_control_panel" } } },
    ]);
    expect(entityForm.data).toEqual({ entity: "alarm_control_panel.panel_a" });
  });

  it("dispatches config-changed when the entity ha-form emits value-changed", () => {
    // The editor wires to ha-form's "value-changed" event (HA convention),
    // not a native <select> change. happy-dom renders <ha-form> as a generic
    // HTMLElement so we dispatch the event the editor actually listens for.
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "alarm_control_panel.panel_a": makeAlarmEntity() },
    });
    document.body.appendChild(editor);

    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm).not.toBeNull();
    entityForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { entity: "alarm_control_panel.panel_a" } },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured?.entity).toBe("alarm_control_panel.panel_a");
  });
});
