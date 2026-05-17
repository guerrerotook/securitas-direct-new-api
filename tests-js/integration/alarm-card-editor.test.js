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

describe("verisure-owa-alarm-card-editor name field", () => {
  function mountEditor() {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x" });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    return editor;
  }

  it("setting a non-empty name in the textfield merges it into the config", () => {
    const editor = mountEditor();
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const nameTf = editor.shadowRoot.querySelector("#name-slot ha-textfield");
    expect(nameTf).not.toBeNull();
    nameTf.value = "My Panel";
    nameTf.dispatchEvent(new Event("input", { bubbles: true }));
    expect(captured?.name).toBe("My Panel");
  });

  it("clearing the name field removes the name key from the config", () => {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x", name: "Old" });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const nameTf = editor.shadowRoot.querySelector("#name-slot ha-textfield");
    nameTf.value = "";
    nameTf.dispatchEvent(new Event("input", { bubbles: true }));
    expect(captured).not.toHaveProperty("name");
  });
});

describe("verisure-owa-alarm-card-editor color pickers", () => {
  function mountEditor(config = {}) {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x", ...config });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    return editor;
  }

  it("changing a color picker merges colors.<state> into the config and unhides reset", () => {
    const editor = mountEditor();
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const picker = editor.shadowRoot.querySelector('input[type="color"][data-state="disarmed"]');
    picker.value = "#123456";
    picker.dispatchEvent(new Event("change", { bubbles: true }));
    expect(captured.colors.disarmed).toBe("#123456");
    const resetBtn = editor.shadowRoot.querySelector('.reset-btn[data-reset="disarmed"]');
    expect(resetBtn.hasAttribute("hidden")).toBe(false);
  });

  it("clicking reset on the only override removes the colors key entirely", () => {
    const editor = mountEditor({ colors: { disarmed: "#123456" } });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const resetBtn = editor.shadowRoot.querySelector('.reset-btn[data-reset="disarmed"]');
    resetBtn.click();
    expect(captured).not.toHaveProperty("colors");
    expect(resetBtn.hasAttribute("hidden")).toBe(true);
  });

  it("clicking reset on one of two overrides keeps the other", () => {
    const editor = mountEditor({
      colors: { disarmed: "#111111", armed_away: "#222222" },
    });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const resetBtn = editor.shadowRoot.querySelector('.reset-btn[data-reset="disarmed"]');
    resetBtn.click();
    expect(captured.colors).toEqual({ armed_away: "#222222" });
  });
});

describe("verisure-owa-alarm-card-editor gesture sections", () => {
  function mountEditor(config = {}) {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x", ...config });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    return editor;
  }

  it("renders three gesture sections (tap / hold / double-tap)", () => {
    const editor = mountEditor();
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    expect(sections.length).toBe(3);
  });

  it("badge-type editor uses more-info as the default tap action", () => {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({
      type: "custom:securitas-alarm-badge",
      entity: "alarm_control_panel.x",
    });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    // First section is tap_action — its ha-form.data.action should be more-info.
    const tapForm = sections[0].querySelector("ha-form");
    expect(tapForm.data.action).toBe("more-info");
  });

  it("transitioning action through perform-action and arm_or_disarm toggles each sub-field block", () => {
    const editor = mountEditor();
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const actionForm = tapSection.querySelector("ha-form");
    const [navFields, perfFields, armFields] = tapSection.querySelectorAll(".conditional-fields");

    actionForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { action: "perform-action" } },
        bubbles: true,
      }),
    );
    expect(perfFields.style.display).toBe("");
    expect(navFields.style.display).toBe("none");
    expect(armFields.style.display).toBe("none");

    actionForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { action: "arm_or_disarm" } },
        bubbles: true,
      }),
    );
    expect(armFields.style.display).toBe("");
    expect(perfFields.style.display).toBe("none");
  });

  it("changing the action selector to navigate reveals the navigation_path field", () => {
    const editor = mountEditor();
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const actionForm = tapSection.querySelector("ha-form");
    actionForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { action: "navigate" } },
        bubbles: true,
      }),
    );
    expect(captured.tap_action.action).toBe("navigate");
    const navFields = tapSection.querySelectorAll(".conditional-fields")[0];
    expect(navFields.style.display).toBe("");
  });

  it("setting a navigation_path round-trips into the config", () => {
    const editor = mountEditor({ tap_action: { action: "navigate" } });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const navForm = tapSection.querySelectorAll(".conditional-fields ha-form")[0];
    navForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { navigation_path: "/lovelace/0" } },
        bubbles: true,
      }),
    );
    expect(captured.tap_action.navigation_path).toBe("/lovelace/0");
  });

  it("changing perform-action service field writes perform_action into the config", () => {
    const editor = mountEditor({ tap_action: { action: "perform-action" } });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const perfFields = tapSection.querySelectorAll(".conditional-fields")[1];
    const [perfInput, perfDataInput] = perfFields.querySelectorAll("ha-textfield");
    perfInput.value = "light.turn_on";
    perfInput.dispatchEvent(new Event("input", { bubbles: true }));
    expect(captured.tap_action.perform_action).toBe("light.turn_on");
    // Valid JSON in the data field becomes a parsed object.
    perfDataInput.value = '{"entity_id":"light.kitchen"}';
    perfDataInput.dispatchEvent(new Event("input", { bubbles: true }));
    expect(captured.tap_action.data).toEqual({ entity_id: "light.kitchen" });
    // Invalid JSON silently leaves data unset (the catch is empty).
    perfDataInput.value = "{not json";
    perfDataInput.dispatchEvent(new Event("input", { bubbles: true }));
    // captured will be re-merged — data should not be present anymore.
    expect(captured.tap_action).not.toHaveProperty("data");
  });

  it("changing arm_state in arm_or_disarm round-trips into the config", () => {
    const editor = mountEditor({ tap_action: { action: "arm_or_disarm" } });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const armFields = tapSection.querySelectorAll(".conditional-fields")[2];
    const armForm = armFields.querySelector("ha-form");
    armForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { arm_state: "arm_home" } },
        bubbles: true,
      }),
    );
    expect(captured.tap_action.arm_state).toBe("arm_home");
  });
});

describe("verisure-owa-alarm-card-editor seeds gesture sections from existing config", () => {
  it("perform-action data is pre-populated as JSON in the Data textfield", () => {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({
      entity: "alarm_control_panel.x",
      tap_action: {
        action: "perform-action",
        perform_action: "light.turn_on",
        data: { entity_id: "light.kitchen" },
      },
    });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const perfFields = tapSection.querySelectorAll(".conditional-fields")[1];
    const [, perfDataInput] = perfFields.querySelectorAll("ha-textfield");
    expect(perfDataInput.value).toBe('{"entity_id":"light.kitchen"}');
    // The conditional perform-action block should be visible.
    expect(perfFields.style.display).toBe("");
  });
});

describe("verisure-owa-alarm-card-editor defensive defaults", () => {
  it("renders without throwing when hass.language is undefined", () => {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x" });
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    // Force language to be a falsy value to take the `|| "en"` branch.
    delete hass.language;
    editor.hass = hass;
    document.body.appendChild(editor);
    expect(editor.shadowRoot.getElementById("entity-form")).not.toBeNull();
  });
});

describe("verisure-owa-alarm-card-editor reuse on subsequent setConfig", () => {
  it("does not rebuild the DOM when only non-structural keys change", () => {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x" });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    const firstEditor = editor.shadowRoot.querySelector(".editor");
    editor.setConfig({ entity: "alarm_control_panel.x", name: "Renamed" });
    const secondEditor = editor.shadowRoot.querySelector(".editor");
    expect(secondEditor).toBe(firstEditor);
  });
});
