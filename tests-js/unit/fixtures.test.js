import { describe, it, expect, vi } from "vitest";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity, makeCameraEntity, makeActivityLogEntity } from "../fixtures/entities.js";
import {
  addAlarmModes,
  autoForceCalls,
  autoForceCheckbox,
  autoForceToggle,
  buildTile,
  closePinPrompt,
  makeModesControl,
  openPinPrompt,
  pressMode,
  submitPin,
} from "../fixtures/ha-alarm-dom.js";

describe("makeHass", () => {
  it("returns a default English hass with empty registries and vi.fn spies", () => {
    const hass = makeHass();
    expect(hass.language).toBe("en");
    expect(hass.states).toEqual({});
    expect(hass.entities).toEqual({});
    expect(hass.devices).toEqual({});
    expect(vi.isMockFunction(hass.callService)).toBe(true);
    expect(vi.isMockFunction(hass.callWS)).toBe(true);
  });

  it("merges overrides shallowly per top-level key", () => {
    const hass = makeHass({
      language: "es",
      states: { "alarm_control_panel.x": { state: "armed_away", attributes: {} } },
    });
    expect(hass.language).toBe("es");
    expect(hass.states["alarm_control_panel.x"].state).toBe("armed_away");
    expect(hass.entities).toEqual({});
  });

  it("callService resolves by default", async () => {
    const hass = makeHass();
    await expect(hass.callService("x", "y", {})).resolves.toBeUndefined();
  });
});

describe("makeAlarmEntity", () => {
  it("returns a disarmed alarm with all supported features by default", () => {
    const ent = makeAlarmEntity();
    expect(ent.state).toBe("disarmed");
    expect(ent.attributes.supported_features).toBe(1 | 2 | 4 | 16 | 32);
    expect(ent.attributes.code_arm_required).toBe(false);
    expect(ent.attributes.force_arm_available).toBe(false);
    expect(ent.attributes.arm_exceptions).toEqual([]);
  });

  it("accepts overrides", () => {
    const ent = makeAlarmEntity({
      state: "armed_away",
      supportedFeatures: 2,
      codeArmRequired: true,
      forceArmAvailable: true,
      armExceptions: [{ alias: "Door", status_key: "open" }],
    });
    expect(ent.state).toBe("armed_away");
    expect(ent.attributes.supported_features).toBe(2);
    expect(ent.attributes.code_arm_required).toBe(true);
    expect(ent.attributes.force_arm_available).toBe(true);
    expect(ent.attributes.arm_exceptions).toHaveLength(1);
  });
});

describe("makeCameraEntity", () => {
  it("provides access_token + entity_picture defaults", () => {
    const ent = makeCameraEntity();
    expect(ent.state).toBe("idle");
    expect(ent.attributes.access_token).toMatch(/^token-/);
    expect(ent.attributes.entity_picture).toContain("token-");
  });
});

describe("makeActivityLogEntity", () => {
  it("defaults to empty events list", () => {
    const ent = makeActivityLogEntity();
    expect(ent.state).toBe("0");
    expect(ent.attributes.events).toEqual([]);
  });

  it("uses events.length as state", () => {
    const ent = makeActivityLogEntity({ events: [{ id_signal: "1" }, { id_signal: "2" }] });
    expect(ent.state).toBe("2");
    expect(ent.attributes.events).toHaveLength(2);
  });
});

describe("ha-alarm-dom", () => {
  // The cards identify where an event came from by the element names on its
  // composed path, so that is what these helpers must reproduce.
  function pathAtWindow(type, dispatch) {
    let seen = null;
    const listener = (event) => {
      const nodes = event.composedPath();
      seen = { event, nodes, path: nodes.map((node) => node.localName).filter(Boolean) };
    };
    window.addEventListener(type, listener);
    dispatch();
    window.removeEventListener(type, listener);
    return seen;
  }

  it("pressMode fires a composed value-changed from inside the modes control", () => {
    const { control, select } = makeModesControl("fake-alarm-modes");
    document.body.appendChild(control);

    const seen = pathAtWindow("value-changed", () => pressMode(select, "armed_home"));

    expect(select.getRootNode().host).toBe(control);
    expect(seen.event.detail).toEqual({ value: "armed_home" });
    expect(seen.path.slice(0, 2)).toEqual(["ha-control-select", "fake-alarm-modes"]);
  });

  it("pressMode defaults to armed_away", () => {
    const { select } = makeModesControl("fake-alarm-modes");

    expect(pressMode(select).detail).toEqual({ value: "armed_away" });
  });

  it("openPinPrompt asks for the PIN prompt from the modes control", () => {
    const { control, select } = makeModesControl("fake-alarm-modes");
    document.body.appendChild(control);

    const seen = pathAtWindow("show-dialog", () => openPinPrompt(select));

    expect(seen.event.detail).toEqual({ dialogTag: "dialog-enter-code" });
    expect(seen.path[0]).toBe("fake-alarm-modes");
  });

  it("submitPin clicks the keypad's submit button inside the prompt, then removes it", () => {
    const seen = pathAtWindow("click", () => submitPin());

    expect(seen.path.slice(0, 2)).toEqual(["ha-control-button", "dialog-enter-code"]);
    expect(seen.nodes[0].classList.contains("submit")).toBe(true);
    expect(document.querySelector("dialog-enter-code")).toBeNull();
  });

  it("closePinPrompt fires dialog-closed that reaches window, then removes the prompt", () => {
    const seen = pathAtWindow("dialog-closed", () => closePinPrompt());

    expect(seen.event.detail).toEqual({ dialog: "dialog-enter-code" });
    expect(seen.path[0]).toBe("dialog-enter-code");
    expect(document.querySelector("dialog-enter-code")).toBeNull();
  });

  it("addAlarmModes nests the modes control in a Tile the way HA does", () => {
    const tile = buildTile();
    const { select } = addAlarmModes(tile, "features-inline");

    const seen = pathAtWindow("value-changed", () => pressMode(select));

    expect(seen.nodes).toContain(tile.tile);
    expect(seen.path.slice(0, 7)).toEqual([
      "ha-control-select",
      "hui-alarm-modes-card-feature",
      "hui-card-feature",
      "hui-card-features",
      "ha-tile-container",
      "ha-card",
      "hui-tile-card",
    ]);
    const group = seen.nodes.find((node) => node.localName === "hui-card-features");
    expect(group.slot).toBe("features-inline");
    expect(addAlarmModes(tile, "features-inline").wrapper.parentNode).toBe(group.shadowRoot);
  });

  it("autoForceToggle counts a hidden tick box as not shown", () => {
    const host = document.createElement("div");
    const root = host.attachShadow({ mode: "open" });
    expect(autoForceToggle(host)).toBeNull();

    const toggle = document.createElement("label");
    toggle.className = "auto-force-toggle";
    const checkbox = document.createElement("input");
    checkbox.className = "auto-force-checkbox";
    toggle.appendChild(checkbox);
    root.appendChild(toggle);

    expect(autoForceToggle(host)).toBe(toggle);
    expect(autoForceCheckbox(host)).toBe(checkbox);
    toggle.hidden = true;
    expect(autoForceToggle(host)).toBeNull();
  });

  it("autoForceCalls keeps only the auto-force services, in order", () => {
    const callService = vi.fn();
    callService("alarm_control_panel", "alarm_arm_away", {});
    callService("securitas", "suppress_arm_exception_prompt", {});
    callService("securitas", "refresh", {});
    callService("securitas", "force_arm", {});

    expect(autoForceCalls(callService)).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
  });
});
