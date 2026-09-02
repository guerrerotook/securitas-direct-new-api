import { afterEach, describe, expect, it, vi } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

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
