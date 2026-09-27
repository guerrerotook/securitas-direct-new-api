import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";
import {
  addAlarmModes,
  autoForceCalls,
  autoForceCheckbox as checkbox,
  autoForceToggle as toggle,
  buildTile,
  closePinPrompt,
  makeModesControl,
  openPinPrompt,
  pressMode,
  submitPin,
  wrapFeature,
} from "../fixtures/ha-alarm-dom.js";

const ENTITY = "alarm_control_panel.test";

function mountFeature({ entity = makeAlarmEntity(), hass, context = true } = {}) {
  const feature = document.createElement("verisure-owa-arm-exception");
  feature.setConfig({ type: "custom:verisure-owa-arm-exception" });
  if (context) feature.context = { entity_id: ENTITY };
  feature.hass = hass || makeHass({ states: { [ENTITY]: entity } });
  document.body.appendChild(feature);
  return feature;
}

function exceptionRoot(feature) {
  return feature.shadowRoot.querySelector("verisure-owa-arm-exception-alert").shadowRoot;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("Verisure OWA Tile Card open-sensor feature", () => {
  it("registers the custom feature and its visual-editor metadata", () => {
    const Feature = customElements.get("verisure-owa-arm-exception");
    expect(Feature).toBeDefined();
    expect(Feature.getStubConfig()).toEqual({
      type: "custom:verisure-owa-arm-exception",
    });

    const entry = window.customCardFeatures.find(
      (item) => item.type === "verisure-owa-arm-exception",
    );
    expect(entry).toMatchObject({
      name: "Verisure OWA Open Sensors",
      configurable: false,
    });
    expect(
      entry.isSupported(makeHass({ entities: { [ENTITY]: { platform: "securitas" } } }), {
        entity_id: ENTITY,
      }),
    ).toBe(true);
    expect(entry.isSupported(makeHass(), { entity_id: "sensor.temperature" })).toBe(false);
    expect(
      entry.isSupported(makeHass({ entities: { [ENTITY]: { platform: "other" } } }), {
        entity_id: ENTITY,
      }),
    ).toBe(false);
    // An alarm_control_panel.* entity that is absent from the registry map
    // (a YAML or other-integration panel) must NOT offer this Verisure-specific
    // feature. Securitas panels are config-entry entities, so they are always
    // in hass.entities and still match via the securitas-platform check above.
    expect(entry.isSupported(makeHass(), { entity_id: ENTITY })).toBe(false);
    expect(entry.supported({ entity_id: ENTITY })).toBe(true);
    expect(entry.supported({ entity_id: "sensor.temperature" })).toBe(false);
  });

  it("stays hidden while there is no arming exception", () => {
    const feature = mountFeature();
    expect(feature.hidden).toBe(true);
    expect(feature.shadowRoot.querySelector("verisure-owa-arm-exception-alert").hidden).toBe(true);
  });

  it("lists all non-forceable sensors inline and escapes their names", () => {
    const feature = mountFeature({
      entity: makeAlarmEntity({
        armExceptionActive: true,
        armExceptions: ["Kitchen window", "Bedroom <script>"],
      }),
    });

    expect(feature.hidden).toBe(false);
    const root = exceptionRoot(feature);
    expect(root.textContent).toContain("Open sensor(s) — close them before arming");
    expect(root.textContent).toContain("Kitchen window");
    expect(root.textContent).toContain("Bedroom <script>");
    expect(root.innerHTML).not.toContain("Bedroom <script>");
    expect(root.querySelector(".force").hidden).toBe(true);
  });

  it("uses the HA locale fallback and tolerates a malformed sensor list", () => {
    const entity = makeAlarmEntity({ armExceptionActive: true });
    entity.attributes.arm_exceptions = "not-an-array";
    const feature = mountFeature({
      entity,
      hass: makeHass({
        language: undefined,
        locale: { language: "es" },
        states: { [ENTITY]: entity },
      }),
    });

    expect(exceptionRoot(feature).textContent).toContain(
      "Sensor(es) abierto(s) — ciérrelos antes de armar",
    );
    expect(exceptionRoot(feature).querySelector(".sensors").hidden).toBe(true);
  });

  it("offers Force Arm only when allowed and calls both feature services", async () => {
    const parentClick = vi.fn();
    const parent = document.createElement("div");
    parent.addEventListener("click", parentClick);
    document.body.appendChild(parent);

    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          forceArmAvailable: true,
          armExceptions: ["Office"],
        }),
      },
    });
    const feature = document.createElement("verisure-owa-arm-exception");
    feature.setConfig({ type: "custom:verisure-owa-arm-exception" });
    feature.context = { entity_id: ENTITY };
    feature.hass = hass;
    parent.appendChild(feature);

    exceptionRoot(feature).querySelector(".force").click();
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
    await Promise.resolve();
    await Promise.resolve();

    exceptionRoot(feature).querySelector(".dismiss").click();
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm_cancel", {
      entity_id: ENTITY,
    });
    expect(parentClick).not.toHaveBeenCalled();
  });

  it("hides the HA feature wrapper until the warning becomes active", () => {
    const wrapper = document.createElement("hui-card-feature");
    const root = wrapper.attachShadow({ mode: "open" });
    const feature = document.createElement("verisure-owa-arm-exception");
    feature.setConfig(null);
    feature.context = { entity_id: ENTITY };
    feature.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    root.appendChild(feature);
    document.body.appendChild(wrapper);

    expect(wrapper.hidden).toBe(true);

    feature.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          armExceptionActive: true,
          armExceptions: ["Patio"],
        }),
      },
    });
    expect(wrapper.hidden).toBe(false);
    expect(exceptionRoot(feature).textContent).toContain("Patio");

    feature.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    expect(wrapper.hidden).toBe(true);
  });

  it("supports the legacy stateObj-only custom-feature contract", () => {
    const entity = {
      ...makeAlarmEntity({
        armExceptionActive: true,
        armExceptions: ["Garage"],
      }),
      entity_id: ENTITY,
    };
    const hass = makeHass();
    const feature = mountFeature({ hass, context: false });
    feature.stateObj = entity;

    expect(exceptionRoot(feature).textContent).toContain("Garage");
    exceptionRoot(feature).querySelector(".dismiss").click();
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm_cancel", {
      entity_id: ENTITY,
    });
  });

  it("re-renders when the sensor snapshot changes", () => {
    const feature = mountFeature({
      entity: makeAlarmEntity({
        armExceptionActive: true,
        armExceptions: ["Window 1"],
      }),
    });
    expect(exceptionRoot(feature).textContent).toContain("Window 1");

    feature.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          armExceptionActive: true,
          armExceptions: ["Window 2", "Window 3"],
        }),
      },
    });
    expect(exceptionRoot(feature).textContent).not.toContain("Window 1");
    expect(exceptionRoot(feature).textContent).toContain("Window 2Window 3");
  });

  it("uses native HA buttons and recovers from rejected services", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({ forceArmAvailable: true, armExceptions: ["Office"] }),
      },
    });
    hass.callService.mockRejectedValueOnce(new Error("unavailable"));
    const feature = mountFeature({ hass });
    const notification = vi.fn();
    feature.addEventListener("hass-notification", notification);
    const root = exceptionRoot(feature);
    const force = root.querySelector("ha-button.force");

    expect(force.textContent).toBe("Force Arm");
    expect(root.querySelector("ha-button.cancel ha-icon")).not.toBeNull();
    expect(root.querySelector("ha-button.cancel .visually-hidden").textContent).toBe("Cancel");
    force.click();
    await Promise.resolve();
    await Promise.resolve();

    expect(notification).toHaveBeenCalledOnce();
    expect(force.disabled).toBe(false);
  });
});

describe("Verisure OWA Tile feature auto-force-arm tick box", () => {
  const LS_KEY = `verisure-owa:auto-force-arm:${ENTITY}`;

  function alarmEntity(overrides = {}) {
    return { ...makeAlarmEntity({ autoForceArmEnabled: true, ...overrides }), entity_id: ENTITY };
  }

  function hassWith(entity, callService) {
    return makeHass({
      states: { [ENTITY]: entity },
      ...(callService ? { callService } : {}),
    });
  }

  function addOurFeature(tileParts, hass) {
    const feature = document.createElement("verisure-owa-arm-exception");
    feature.setConfig({ type: "custom:verisure-owa-arm-exception" });
    // HA assigns hass and context before the feature is connected.
    feature.hass = hass;
    feature.context = { entity_id: ENTITY };
    const wrapper = wrapFeature(feature);
    tileParts.group("features").appendChild(wrapper);
    return { feature, wrapper };
  }

  function mountTile({ entity = alarmEntity(), modes = "before", callService } = {}) {
    const hass = hassWith(entity, callService || vi.fn(async () => {}));
    const tileParts = buildTile();
    let modesFeature = null;
    if (modes === "before") modesFeature = addAlarmModes(tileParts);
    if (modes === "inline") modesFeature = addAlarmModes(tileParts, "features-inline");
    const ours = addOurFeature(tileParts, hass);
    if (modes === "after") modesFeature = addAlarmModes(tileParts);
    return { ...tileParts, ...ours, modes: modesFeature, hass, callService: hass.callService };
  }

  function push(feature, entity, callService) {
    const hass = hassWith(entity, callService);
    feature.hass = hass;
    feature.stateObj = entity;
    return hass;
  }

  function armWithException(feature, callService) {
    push(feature, alarmEntity({ state: "arming" }), callService);
    push(feature, alarmEntity({ forceArmAvailable: true, armExceptions: ["Door"] }), callService);
  }

  beforeEach(() => {
    localStorage.clear();
  });

  describe("visibility", () => {
    it("shows the labelled tick box below the Alarm modes feature while disarmed", () => {
      const { feature, wrapper } = mountTile();

      expect(toggle(feature)).not.toBeNull();
      expect(toggle(feature).getAttribute("label")).toBe(
        "Automatically force-arm past open sensors",
      );
      expect(checkbox(feature).localName).toBe("ha-checkbox");
      expect(feature.hidden).toBe(false);
      expect(wrapper.hidden).toBe(false);
    });

    it("finds an Alarm modes feature in the Tile's inline feature slot", () => {
      const { feature } = mountTile({ modes: "inline" });
      expect(toggle(feature)).not.toBeNull();
    });

    it("finds an Alarm modes feature that HA renders after this one", async () => {
      const { feature } = mountTile({ modes: "after" });

      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(toggle(feature)).not.toBeNull();
    });

    it("hides the tick box and the feature row on a Tile without Alarm modes", () => {
      const { feature, wrapper } = mountTile({ modes: "none" });

      expect(toggle(feature)).toBeNull();
      expect(wrapper.hidden).toBe(true);
    });

    it("hides the tick box when the Alarm modes feature is removed from the Tile", () => {
      const { feature, modes, wrapper } = mountTile();

      modes.wrapper.remove();
      push(feature, alarmEntity());

      expect(toggle(feature)).toBeNull();
      expect(wrapper.hidden).toBe(true);
    });

    it("does not search the Tile again for Alarm modes once it has found them", () => {
      const { feature, tileRoot } = mountTile();
      const search = vi.spyOn(tileRoot, "querySelectorAll");

      push(feature, alarmEntity());
      push(feature, alarmEntity({ state: "armed_away" }));
      push(feature, alarmEntity());

      expect(search).not.toHaveBeenCalled();
      expect(toggle(feature)).not.toBeNull();
    });

    it("hides the tick box when the capability gate is off", () => {
      const { feature, wrapper } = mountTile({
        entity: alarmEntity({ autoForceArmEnabled: false }),
      });

      expect(toggle(feature)).toBeNull();
      expect(wrapper.hidden).toBe(true);
    });

    it("hides the tick box while the alarm is not disarmed", () => {
      const { feature, wrapper } = mountTile({ entity: alarmEntity({ state: "armed_away" }) });

      expect(toggle(feature)).toBeNull();
      expect(wrapper.hidden).toBe(true);
    });

    it("replaces the tick box with the open-sensor warning while one is active", () => {
      const { feature, wrapper } = mountTile({
        entity: alarmEntity({ armExceptionActive: true, armExceptions: ["Patio"] }),
      });

      expect(toggle(feature)).toBeNull();
      expect(exceptionRoot(feature).textContent).toContain("Patio");
      expect(wrapper.hidden).toBe(false);
    });

    it("uses the Home Assistant language for the label", () => {
      const { feature } = mountTile();
      feature.hass = makeHass({ language: "es", states: { [ENTITY]: alarmEntity() } });

      expect(toggle(feature).getAttribute("label")).toBe(
        "Forzar armado automáticamente con sensores abiertos",
      );
    });

    it("uses Catalan for the label when Home Assistant is in Catalan", () => {
      const { feature } = mountTile();
      feature.hass = makeHass({ language: "ca", states: { [ENTITY]: alarmEntity() } });

      expect(toggle(feature).getAttribute("label")).toBe(
        "Forçar l’armat automàticament amb sensors oberts",
      );
    });
  });

  describe("tick persistence", () => {
    it("writes the tick to the per-device key shared with More Info", () => {
      const { feature } = mountTile();
      const outer = vi.fn();
      document.body.addEventListener("change", outer);

      const cb = checkbox(feature);
      cb.checked = true;
      cb.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
      document.body.removeEventListener("change", outer);

      expect(localStorage.getItem(LS_KEY)).toBe("true");
      expect(outer).not.toHaveBeenCalled();

      cb.checked = false;
      cb.dispatchEvent(new Event("change"));
      expect(localStorage.getItem(LS_KEY)).toBe("false");
    });

    it("reflects a tick made in the More Info dialog", async () => {
      await import("../../custom_components/securitas/www/verisure-owa-more-info.js");
      const { feature } = mountTile();
      expect(checkbox(feature).checked).toBe(false);

      const moreInfo = document.createElement("more-info-verisure-owa-alarm");
      moreInfo.hass = hassWith(alarmEntity());
      moreInfo.stateObj = alarmEntity();
      document.body.appendChild(moreInfo);
      const moreInfoBox = moreInfo.shadowRoot.querySelector(".auto-force-checkbox");
      moreInfoBox.checked = true;
      moreInfoBox.dispatchEvent(new Event("change"));

      expect(checkbox(feature).checked).toBe(true);
    });

    it("redraws once per click on the tick box", () => {
      const { feature } = mountTile();
      const render = vi.spyOn(feature, "_render");

      const cb = checkbox(feature);
      cb.checked = true;
      cb.dispatchEvent(new Event("change"));

      expect(render).toHaveBeenCalledOnce();
      expect(checkbox(feature).checked).toBe(true);
    });

    it("reads the saved tick when the alarm is set, not on every update", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature } = mountTile();
      const read = vi.spyOn(globalThis.localStorage, "getItem");

      push(feature, alarmEntity());
      push(feature, alarmEntity());
      const reads = read.mock.calls.length;
      read.mockRestore();

      expect(reads).toBe(0);
      expect(checkbox(feature).checked).toBe(true);
    });

    it("reads the saved tick of a different alarm when the Tile switches to it", () => {
      const OTHER = "alarm_control_panel.other";
      localStorage.setItem(`verisure-owa:auto-force-arm:${OTHER}`, "true");
      const { feature } = mountTile();
      expect(checkbox(feature).checked).toBe(false);

      const other = { ...alarmEntity(), entity_id: OTHER };
      feature.hass = makeHass({ states: { [ENTITY]: alarmEntity(), [OTHER]: other } });
      feature.context = { entity_id: OTHER };

      expect(checkbox(feature).checked).toBe(true);
    });

    it("picks up a tick saved while it was removed", () => {
      const { feature, wrapper, group } = mountTile();
      wrapper.remove();

      localStorage.setItem(LS_KEY, "true");
      group("features").appendChild(wrapper);

      expect(checkbox(feature).checked).toBe(true);
    });

    it("picks up a tick saved after an update while it was removed", () => {
      const { feature, wrapper, group } = mountTile();
      wrapper.remove();
      push(feature, alarmEntity());

      localStorage.setItem(LS_KEY, "true");
      group("features").appendChild(wrapper);

      expect(checkbox(feature).checked).toBe(true);
    });

    it("stops following ticks once removed", () => {
      const { feature, wrapper, group } = mountTile();
      const other = mountTile();
      wrapper.remove();

      const cb = checkbox(other.feature);
      cb.checked = true;
      cb.dispatchEvent(new Event("change"));
      const render = vi.spyOn(feature, "_render");
      cb.checked = false;
      cb.dispatchEvent(new Event("change"));
      expect(render).not.toHaveBeenCalled();

      group("features").appendChild(wrapper);
      cb.checked = true;
      cb.dispatchEvent(new Event("change"));
      expect(checkbox(feature).checked).toBe(true);
    });
  });

  describe("auto-force acts only on this Tile's Alarm modes buttons", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it("force-arms an arm started from the Tile's Alarm modes feature", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, modes, callService } = mountTile();

      pressMode(modes.select);
      armWithException(feature, callService);

      expect(callService).toHaveBeenCalledWith("verisure_owa", "suppress_arm_exception_prompt", {
        entity_id: ENTITY,
      });
      expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
        entity_id: ENTITY,
      });
    });

    it("force-arms an arm started from an inline Alarm modes feature", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, modes, callService } = mountTile({ modes: "inline" });

      pressMode(modes.select);
      armWithException(feature, callService);

      expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
        entity_id: ENTITY,
      });
    });

    it("does NOT force an arm started elsewhere", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, callService } = mountTile();

      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("does NOT force an arm started from another Tile's Alarm modes", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, callService } = mountTile();
      const otherTile = buildTile();
      const otherModes = addAlarmModes(otherTile);

      pressMode(otherModes.select);
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("ignores mode events from other features and disarm presses", () => {
      localStorage.setItem(LS_KEY, "true");
      const tileParts = buildTile();
      const modes = addAlarmModes(tileParts);
      const { control: other, select: otherSelect } = makeModesControl(
        "hui-select-options-card-feature",
      );
      tileParts.group("features").appendChild(wrapFeature(other));
      const callService = vi.fn(async () => {});
      const { feature } = addOurFeature(tileParts, hassWith(alarmEntity(), callService));

      pressMode(otherSelect);
      pressMode(modes.select, "disarmed");
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("does NOT force an arm from elsewhere after the PIN prompt is cancelled", () => {
      vi.useFakeTimers();
      localStorage.setItem(LS_KEY, "true");
      const { feature, modes, callService } = mountTile();

      pressMode(modes.select);
      openPinPrompt(modes.select);
      vi.advanceTimersByTime(3_000);
      closePinPrompt();
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("does NOT force an arm from another PIN prompt submitted after this one was cancelled", () => {
      vi.useFakeTimers();
      localStorage.setItem(LS_KEY, "true");
      const { feature, modes, callService } = mountTile();

      pressMode(modes.select);
      openPinPrompt(modes.select);
      vi.advanceTimersByTime(3_000);
      closePinPrompt();
      vi.advanceTimersByTime(3_000);
      submitPin();
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("still forces an arm made after typing a PIN", () => {
      vi.useFakeTimers();
      localStorage.setItem(LS_KEY, "true");
      const { feature, modes, callService } = mountTile();

      pressMode(modes.select);
      openPinPrompt(modes.select);
      vi.advanceTimersByTime(30_000);
      submitPin();
      armWithException(feature, callService);
      closePinPrompt();

      expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
        entity_id: ENTITY,
      });
    });

    it("does NOT force an arm from elsewhere while the PIN prompt is still open", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, modes, callService } = mountTile();

      pressMode(modes.select);
      openPinPrompt(modes.select);
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("does NOT force when the tick box is off", () => {
      const { feature, modes, callService } = mountTile();

      pressMode(modes.select);
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("does not stop the mode event, so HA's own handler still arms", () => {
      const { modes } = mountTile();
      const outer = vi.fn();
      document.body.addEventListener("value-changed", outer);

      pressMode(modes.select);
      document.body.removeEventListener("value-changed", outer);

      expect(outer).toHaveBeenCalledOnce();
    });

    it("stops listening once disconnected and listens again on reconnect", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, wrapper, modes, group, callService } = mountTile();

      wrapper.remove();
      pressMode(modes.select);
      armWithException(feature, callService);
      expect(autoForceCalls(callService)).toEqual([]);

      push(feature, alarmEntity(), callService);
      group("features").appendChild(wrapper);
      pressMode(modes.select);
      armWithException(feature, callService);
      expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
        entity_id: ENTITY,
      });
    });

    it("forgets a button press when the Tile is removed and put back", () => {
      localStorage.setItem(LS_KEY, "true");
      const { feature, wrapper, modes, group, callService } = mountTile();

      pressMode(modes.select);
      wrapper.remove();
      group("features").appendChild(wrapper);
      armWithException(feature, callService);

      expect(autoForceCalls(callService)).toEqual([]);
    });

    it("does not re-render after a disconnect that beats the deferred check", async () => {
      const { feature, wrapper } = mountTile({ modes: "after" });
      const render = vi.spyOn(feature, "_render");

      wrapper.remove();
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(render).not.toHaveBeenCalled();
    });
  });
});
