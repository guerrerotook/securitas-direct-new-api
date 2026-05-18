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

describe("verisure-owa-alarm-card-editor per-variant gesture defaults", () => {
  // PR #475: editor's gesture defaults mirror each variant's runtime
  // fallbacks. card: tap=none, hold=none. badge: tap=more-info,
  // hold=arm_or_disarm. chip: tap=more-info, hold=none. Otherwise the editor
  // would display an action the runtime would never actually invoke.

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

  it("badge variant: tap default is 'more-info', hold default is 'arm_or_disarm'", () => {
    const editor = mountEditorForType("custom:verisure-owa-alarm-badge");
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    expect(sections[0].querySelector("ha-form").data.action).toBe("more-info");
    expect(sections[1].querySelector("ha-form").data.action).toBe("arm_or_disarm");
  });

  it("chip variant: tap default is 'more-info', hold default is 'none'", () => {
    // The chip's runtime defaults are tap=more-info, hold=none (chips have
    // no PIN-overlay-on-long-press fallback like the badge does).
    const editor = mountEditorForType("custom:verisure-owa-alarm-chip");
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    expect(sections[0].querySelector("ha-form").data.action).toBe("more-info");
    expect(sections[1].querySelector("ha-form").data.action).toBe("none");
  });

  it("mushroom chip variant resolves to chip defaults via the -alarm-chip suffix match", () => {
    const editor = mountEditorForType("custom:mushroom-verisure-owa-alarm-chip");
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    expect(sections[0].querySelector("ha-form").data.action).toBe("more-info");
  });

  it("legacy securitas-alarm-badge type alias still resolves to badge defaults", () => {
    const editor = mountEditorForType("custom:securitas-alarm-badge");
    const sections = editor.shadowRoot.querySelectorAll(".gesture-section");
    expect(sections[0].querySelector("ha-form").data.action).toBe("more-info");
    expect(sections[1].querySelector("ha-form").data.action).toBe("arm_or_disarm");
  });
});
