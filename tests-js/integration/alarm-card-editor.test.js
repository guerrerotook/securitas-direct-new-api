import { describe, it, expect, vi } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import "../../custom_components/securitas/www/verisure-owa-alarm-badge-editor.js";
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

describe("verisure-owa-alarm-badge-editor", () => {
  function mountBadgeEditor(config = {}) {
    const editor = document.createElement("verisure-owa-alarm-badge-editor");
    editor.setConfig({
      type: "custom:verisure-owa-alarm-badge",
      entity: "alarm_control_panel.x",
      ...config,
    });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    return editor;
  }

  function flattenSchema(schema) {
    return schema.flatMap((entry) => [entry, ...(entry.schema ? flattenSchema(entry.schema) : [])]);
  }

  it("uses one native ha-form for standard Content and Interactions options", () => {
    const editor = mountBadgeEditor();
    const form = editor.shadowRoot.getElementById("badge-form");
    const schema = flattenSchema(form.schema);

    expect(form).not.toBeNull();
    expect(form.data.displayed_elements).toEqual(["state", "icon"]);
    expect(schema).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "name", selector: { entity_name: {} } }),
        expect.objectContaining({ name: "icon", selector: { icon: {} } }),
        expect.objectContaining({
          name: "color",
          selector: {
            ui_color: { default_color: "state", include_state: true },
          },
        }),
        expect.objectContaining({
          name: "show_entity_picture",
          selector: { boolean: {} },
        }),
        expect.objectContaining({
          name: "state_content",
          selector: { ui_state_content: { allow_name: true } },
        }),
        expect.objectContaining({
          name: "tap_action",
          selector: {
            ui_action: {
              default_action: "more-info",
              actions: ["more-info", "navigate", "perform-action", "none"],
            },
          },
        }),
        expect.objectContaining({
          name: "hold_action",
          selector: {
            ui_action: {
              default_action: "none",
              actions: ["more-info", "navigate", "perform-action", "none"],
            },
          },
        }),
        expect.objectContaining({
          name: "double_tap_action",
          selector: {
            ui_action: {
              default_action: "none",
              actions: ["more-info", "navigate", "perform-action", "none"],
            },
          },
        }),
      ]),
    );
    expect(schema).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "alarm_behavior" })]),
    );
  });

  it("maps Displayed elements and Content values to the badge config", () => {
    const editor = mountBadgeEditor();
    let captured = null;
    editor.addEventListener("config-changed", (event) => {
      captured = event.detail.config;
    });
    const form = editor.shadowRoot.getElementById("badge-form");
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: {
          value: {
            entity: "alarm_control_panel.x",
            name: "Entrance",
            icon: "mdi:shield-home",
            color: "amber",
            show_entity_picture: true,
            displayed_elements: ["name", "state"],
            state_content: ["state", "arm_exceptions"],
            time_format: "24",
            tap_action: { action: "more-info" },
          },
        },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured).toMatchObject({
      name: "Entrance",
      icon: "mdi:shield-home",
      color: "amber",
      show_entity_picture: true,
      show_name: true,
      show_state: true,
      show_icon: false,
      state_content: ["state", "arm_exceptions"],
      time_format: "24",
    });
  });

  it("removes optional Content keys when they are cleared", () => {
    const editor = mountBadgeEditor({
      name: "Old",
      icon: "mdi:shield",
      state_content: "state",
      time_format: "12",
    });
    let captured = null;
    editor.addEventListener("config-changed", (event) => {
      captured = event.detail.config;
    });
    editor.shadowRoot.getElementById("badge-form").dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { displayed_elements: ["icon"] } },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured).not.toHaveProperty("name");
    expect(captured).not.toHaveProperty("state_content");
    expect(captured).not.toHaveProperty("time_format");
    expect(captured).toMatchObject({
      show_name: false,
      show_state: false,
      show_icon: true,
    });
  });

  it("shows time format only for timestamp content", () => {
    const regular = mountBadgeEditor({ state_content: "state" });
    expect(flattenSchema(regular.shadowRoot.getElementById("badge-form").schema)).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "time_format" })]),
    );

    const timestamp = mountBadgeEditor({ state_content: "last_triggered" });
    expect(flattenSchema(timestamp.shadowRoot.getElementById("badge-form").schema)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "time_format",
          selector: { ui_time_format: {} },
        }),
      ]),
    );
  });

  it("migrates Badge arm_or_disarm actions to native More Info", () => {
    const editor = mountBadgeEditor({
      colors: { disarmed: "#123456" },
      states: ["arm_home"],
      tap_action: { action: "arm_or_disarm", arm_state: "arm_home" },
      hold_action: { action: "arm_or_disarm", arm_state: "arm_home" },
      double_tap_action: { action: "arm_or_disarm", arm_state: "arm_night" },
    });
    let captured = null;
    editor.addEventListener("config-changed", (event) => {
      captured = event.detail.config;
    });

    const form = editor.shadowRoot.getElementById("badge-form");
    expect(form.data).not.toHaveProperty("colors");
    expect(form.data).not.toHaveProperty("states");
    expect(form.data.tap_action).toEqual({ action: "more-info" });
    expect(form.data.hold_action).toEqual({ action: "more-info" });
    expect(form.data.double_tap_action).toEqual({ action: "more-info" });
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: {
          value: {
            ...form.data,
            displayed_elements: ["state", "icon"],
          },
        },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured.colors).toEqual({ disarmed: "#123456" });
    expect(captured).not.toHaveProperty("states");
    expect(captured.tap_action).toEqual({ action: "more-info" });
    expect(captured.hold_action).toEqual({ action: "more-info" });
    expect(captured.double_tap_action).toEqual({ action: "more-info" });
  });

  it("uses only native HA actions and has no implicit hold action", () => {
    const editor = mountBadgeEditor();
    const form = editor.shadowRoot.getElementById("badge-form");
    expect(form.data).not.toHaveProperty("hold_action");
    expect(form.data).not.toHaveProperty("arm_state");
    expect(flattenSchema(form.schema)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "hold_action",
          selector: {
            ui_action: {
              default_action: "none",
              actions: ["more-info", "navigate", "perform-action", "none"],
            },
          },
        }),
      ]),
    );

    let captured = null;
    editor.addEventListener("config-changed", (event) => {
      captured = event.detail.config;
    });
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: {
          value: {
            entity: "alarm_control_panel.x",
            displayed_elements: ["state", "icon"],
            hold_action: {
              action: "perform-action",
              perform_action: "alarm_control_panel.alarm_arm_home",
              target: { entity_id: "alarm_control_panel.x" },
            },
          },
        },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured.hold_action).toEqual({
      action: "perform-action",
      perform_action: "alarm_control_panel.alarm_arm_home",
      target: { entity_id: "alarm_control_panel.x" },
    });
  });

  it("provides native labels/helpers and handles an empty form update", () => {
    const localize = vi.fn((key) =>
      key === "ui.panel.lovelace.editor.badge.entity.color" ? "Colour" : undefined,
    );
    const editor = document.createElement("verisure-owa-alarm-badge-editor");
    editor.setConfig({ entity: "alarm_control_panel.x", show_name: true });
    editor.hass = makeHass({ localize });
    document.body.appendChild(editor);
    const form = editor.shadowRoot.getElementById("badge-form");

    expect(form.computeLabel({ name: "color" })).toBe("Colour");
    expect(form.computeLabel({ name: "entity" })).toBe("Entity");
    expect(form.computeHelper({ name: "icon" })).toBeUndefined();
    expect(form.computeHelper({ name: "color" })).toBeUndefined();

    let captured = null;
    editor.addEventListener("config-changed", (event) => {
      captured = event.detail.config;
    });
    form.dispatchEvent(new CustomEvent("value-changed", { bubbles: true, composed: true }));

    expect(captured).not.toHaveProperty("type");
    expect(captured).toMatchObject({
      show_name: true,
      show_state: true,
      show_icon: true,
    });
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

describe("verisure-owa-alarm-card-editor setConfig re-render behavior", () => {
  // PR #475 made the editor re-render on every external setConfig (YAML edits,
  // initial mount, parent resets), and re-render on internal structural
  // changes (entity / type). Internal non-structural writes (name, colors,
  // gestures) routed through _fireChanged are suppressed for one tick by the
  // _internalWriteInFlight flag so the parent's round-trip doesn't tear down
  // the editor while the user is still editing.

  it("external setConfig (YAML edit) rebuilds the editor DOM", () => {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x" });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    const firstEditor = editor.shadowRoot.querySelector(".editor");
    // Simulate an external YAML edit — the parent calls setConfig with a fresh
    // config object and no _internalWriteInFlight flag pending.
    editor.setConfig({ entity: "alarm_control_panel.x", name: "Renamed" });
    const secondEditor = editor.shadowRoot.querySelector(".editor");
    expect(secondEditor).not.toBe(firstEditor);
    // The new name flows into the rebuilt textfield.
    const nameTf = editor.shadowRoot.querySelector("#name-slot ha-textfield");
    expect(nameTf.value).toBe("Renamed");
  });

  it("internal non-structural write (name typed into textfield) does NOT rebuild the DOM", () => {
    // After _fireChanged the parent re-calls setConfig with the same entity
    // and type, but _internalWriteInFlight is set — the suppression branch
    // skips _render so the user's typing cursor isn't lost.
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x" });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    const firstEditor = editor.shadowRoot.querySelector(".editor");
    const nameTf = editor.shadowRoot.querySelector("#name-slot ha-textfield");
    nameTf.value = "Typed";
    nameTf.dispatchEvent(new Event("input", { bubbles: true }));
    // Simulate the parent's round-trip (same entity/type → not structural).
    editor.setConfig({ entity: "alarm_control_panel.x", name: "Typed" });
    const secondEditor = editor.shadowRoot.querySelector(".editor");
    expect(secondEditor).toBe(firstEditor);
  });

  it("structural change (entity) rebuilds the DOM even when _internalWriteInFlight is set", () => {
    // Copilot-caught regression from PR #475: setConfig must NOT short-circuit
    // when entity (or type) changes, even mid-flight, because the Arm modes
    // checkboxes + each gesture's arm_state dropdown are derived from the new
    // entity's supported_features. Without this safeguard the editor showed
    // the previous entity's modes until close/reopen.
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x" });
    editor.hass = makeHass({
      states: {
        "alarm_control_panel.x": makeAlarmEntity(),
        "alarm_control_panel.y": makeAlarmEntity(),
      },
    });
    document.body.appendChild(editor);
    const firstEditor = editor.shadowRoot.querySelector(".editor");
    // Simulate the race: an internal write set the flag, and now a structural
    // setConfig arrives before the queueMicrotask has cleared it.
    editor._internalWriteInFlight = true;
    editor.setConfig({ entity: "alarm_control_panel.y" });
    const secondEditor = editor.shadowRoot.querySelector(".editor");
    expect(secondEditor).not.toBe(firstEditor);
  });

  it("structural change (type — card → badge) rebuilds the DOM", () => {
    // The gesture defaults differ per variant; a card→badge swap must rebuild
    // the gesture sections so the new defaults (hold=arm_or_disarm, etc.)
    // surface immediately.
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({
      type: "custom:verisure-owa-alarm-card",
      entity: "alarm_control_panel.x",
    });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    const firstEditor = editor.shadowRoot.querySelector(".editor");
    editor.setConfig({
      type: "custom:verisure-owa-alarm-badge",
      entity: "alarm_control_panel.x",
    });
    const secondEditor = editor.shadowRoot.querySelector(".editor");
    expect(secondEditor).not.toBe(firstEditor);
  });
});

describe("verisure-owa-alarm-card-editor arm modes checkbox section", () => {
  // PR #475 added a checkbox group listing every mode the entity advertises
  // via `supported_features`. Toggling rewrites `config.states`; when every
  // supported box is checked the editor drops the key so the YAML stays
  // minimal and naturally tracks future `supported_features` expansions.

  function mountEditor(config = {}, hassOverrides = {}) {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ entity: "alarm_control_panel.x", ...config });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity(hassOverrides) },
    });
    document.body.appendChild(editor);
    return editor;
  }

  it("renders a checkbox per supported arm mode", () => {
    // makeAlarmEntity defaults to all 5 features supported.
    const editor = mountEditor();
    const checkboxes = editor.shadowRoot.querySelectorAll(".arm-modes-list input[type='checkbox']");
    expect(checkboxes.length).toBe(5);
    const keys = Array.from(checkboxes).map((cb) => cb.dataset.armKey);
    expect(keys).toEqual([
      "arm_away",
      "arm_home",
      "arm_night",
      "arm_vacation",
      "arm_custom_bypass",
    ]);
  });

  it("all checkboxes checked by default when config.states is unset", () => {
    const editor = mountEditor();
    const checkboxes = editor.shadowRoot.querySelectorAll(".arm-modes-list input[type='checkbox']");
    Array.from(checkboxes).forEach((cb) => expect(cb.checked).toBe(true));
  });

  it("only configured modes are checked when config.states is set", () => {
    const editor = mountEditor({ states: ["arm_away", "arm_night"] });
    const checked = Array.from(
      editor.shadowRoot.querySelectorAll(".arm-modes-list input[type='checkbox']"),
    )
      .filter((cb) => cb.checked)
      .map((cb) => cb.dataset.armKey);
    expect(checked).toEqual(["arm_away", "arm_night"]);
  });

  it("unchecking a checkbox writes config.states with only the still-checked modes", () => {
    const editor = mountEditor();
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    // Uncheck arm_home.
    const homeCb = editor.shadowRoot.querySelector(
      ".arm-modes-list input[type='checkbox'][data-arm-key='arm_home']",
    );
    homeCb.checked = false;
    homeCb.dispatchEvent(new Event("change", { bubbles: true }));
    expect(captured.states).toEqual(["arm_away", "arm_night", "arm_vacation", "arm_custom_bypass"]);
  });

  it("re-checking the last hidden mode (all supported again) drops the states key", () => {
    const editor = mountEditor({
      states: ["arm_away", "arm_home", "arm_night", "arm_vacation"],
    });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    // Re-check arm_custom_bypass — now all 5 are on again.
    const customCb = editor.shadowRoot.querySelector(
      ".arm-modes-list input[type='checkbox'][data-arm-key='arm_custom_bypass']",
    );
    customCb.checked = true;
    customCb.dispatchEvent(new Event("change", { bubbles: true }));
    expect(captured).not.toHaveProperty("states");
  });

  it("renders the all-hidden hint when every checkbox is unchecked", () => {
    const editor = mountEditor({ states: [] });
    // The arm_or_disarm section inside each gesture should show the
    // editor_arm_state_no_modes hint when filtered = [].
    // First switch a gesture to arm_or_disarm to trigger the conditional
    // rendering of the hint.
    const tapSection = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const tapActionForm = tapSection.querySelector("ha-form");
    tapActionForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { action: "arm_or_disarm" } },
        bubbles: true,
      }),
    );
    // The arm-fields block should now hold the hint and NO arm-state ha-form.
    const tapSectionAfter = editor.shadowRoot.querySelectorAll(".gesture-section")[0];
    const armFields = tapSectionAfter.querySelectorAll(".conditional-fields")[2];
    expect(armFields.querySelector(".arm-modes-empty")).not.toBeNull();
    expect(armFields.querySelector(".arm-modes-empty").textContent).toMatch(
      /at least one arm mode/i,
    );
  });

  it("renders the no-supported-modes message when the entity has zero features", () => {
    const editor = mountEditor({}, { supportedFeatures: 0 });
    // The arm-modes section appends a `.arm-modes-empty` div instead of the
    // `.arm-modes-list`.
    const armModesSection = editor.shadowRoot.querySelector(".arm-modes-section");
    expect(armModesSection.querySelector(".arm-modes-list")).toBeNull();
    const emptyMsg = armModesSection.querySelector(".arm-modes-empty");
    expect(emptyMsg).not.toBeNull();
    expect(emptyMsg.textContent).toMatch(/no supported arm modes/i);
  });

  it("toggling a checkbox refreshes each gesture's arm_state dropdown options live", () => {
    // Seed with the hold gesture set to arm_or_disarm — its dropdown options
    // should match all 5 supported modes initially.
    const editor = mountEditor({ hold_action: { action: "arm_or_disarm" } });
    let armFields = editor.shadowRoot
      .querySelectorAll(".gesture-section")[1] // hold section
      .querySelectorAll(".conditional-fields")[2];
    let armForm = armFields.querySelector("ha-form");
    const initialOpts = armForm.schema[0].selector.select.options.map((o) => o.value);
    expect(initialOpts.length).toBe(5);
    // Uncheck arm_night — gesture dropdowns should rebuild without it.
    const nightCb = editor.shadowRoot.querySelector(
      ".arm-modes-list input[type='checkbox'][data-arm-key='arm_night']",
    );
    nightCb.checked = false;
    nightCb.dispatchEvent(new Event("change", { bubbles: true }));
    // The gesture slot is rebuilt — re-query for the new form.
    armFields = editor.shadowRoot
      .querySelectorAll(".gesture-section")[1]
      .querySelectorAll(".conditional-fields")[2];
    armForm = armFields.querySelector("ha-form");
    const newOpts = armForm.schema[0].selector.select.options.map((o) => o.value);
    expect(newOpts).not.toContain("arm_night");
    expect(newOpts.length).toBe(4);
  });

  it("scrubs a gesture's arm_state when its referenced mode is hidden", () => {
    const editor = mountEditor({
      hold_action: { action: "arm_or_disarm", arm_state: "arm_home" },
    });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    // Uncheck arm_home — the gesture's arm_state references it; it must be
    // rewritten to the new default.
    const homeCb = editor.shadowRoot.querySelector(
      ".arm-modes-list input[type='checkbox'][data-arm-key='arm_home']",
    );
    homeCb.checked = false;
    homeCb.dispatchEvent(new Event("change", { bubbles: true }));
    // hold_action.arm_state must NOT still be "arm_home" — it should fall back
    // to the first remaining supported mode (arm_away).
    expect(captured.hold_action.arm_state).not.toBe("arm_home");
    expect(captured.hold_action.arm_state).toBe("arm_away");
  });

  it("leaves an unrelated (non-arm_or_disarm) gesture's arm_state untouched", () => {
    // Only arm_or_disarm gestures should be scrubbed — a navigate gesture
    // with a stale arm_state should not be modified.
    const editor = mountEditor({
      hold_action: { action: "navigate", navigation_path: "/lovelace/0" },
    });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    const homeCb = editor.shadowRoot.querySelector(
      ".arm-modes-list input[type='checkbox'][data-arm-key='arm_home']",
    );
    homeCb.checked = false;
    homeCb.dispatchEvent(new Event("change", { bubbles: true }));
    expect(captured.hold_action.action).toBe("navigate");
    expect(captured.hold_action.navigation_path).toBe("/lovelace/0");
  });

  it("does not scrub gesture arm_state when the resulting states list is empty (falls back to all supported)", () => {
    // Edge case: when the user unchecks every mode, the editor leaves the
    // gesture's saved arm_state alone — the dropdown's empty-list branch is
    // already handled by the userHiddenAll hint.
    const editor = mountEditor({
      states: ["arm_home"],
      hold_action: { action: "arm_or_disarm", arm_state: "arm_home" },
    });
    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });
    // Uncheck the only remaining mode (arm_home) — now states becomes [].
    const homeCb = editor.shadowRoot.querySelector(
      ".arm-modes-list input[type='checkbox'][data-arm-key='arm_home']",
    );
    homeCb.checked = false;
    homeCb.dispatchEvent(new Event("change", { bubbles: true }));
    expect(captured.states).toEqual([]);
    // Per code: scrub only runs when nextStates.length > 0, so arm_home
    // stays in the saved config (the gesture section will show the hint
    // instead of the dropdown).
    expect(captured.hold_action.arm_state).toBe("arm_home");
  });
});

describe("verisure-owa-alarm-card-editor gesture defaults", () => {
  function mountEditorForType(type) {
    const editor = document.createElement("verisure-owa-alarm-card-editor");
    editor.setConfig({ type, entity: "alarm_control_panel.x" });
    editor.hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    document.body.appendChild(editor);
    return editor;
  }

  it("card variant: tap default is 'none', hold default is 'none'", () => {
    const editor = mountEditorForType("custom:verisure-owa-alarm-card");
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    expect(sections[0].querySelector("ha-form").data.action).toBe("none");
    expect(sections[1].querySelector("ha-form").data.action).toBe("none");
  });
});
