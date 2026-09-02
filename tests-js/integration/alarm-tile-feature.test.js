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
    expect(feature.shadowRoot.querySelector(".warning")).toBeNull();
  });

  it("lists all non-forceable sensors inline and escapes their names", () => {
    const feature = mountFeature({
      entity: makeAlarmEntity({
        armExceptionActive: true,
        armExceptions: ["Kitchen window", "Bedroom <script>"],
      }),
    });

    expect(feature.hidden).toBe(false);
    expect(feature.shadowRoot.textContent).toContain("Open sensor(s) — close them before arming");
    expect(feature.shadowRoot.textContent).toContain("Kitchen window");
    expect(feature.shadowRoot.textContent).toContain("Bedroom <script>");
    expect(feature.shadowRoot.innerHTML).not.toContain("Bedroom <script>");
    expect(feature.shadowRoot.querySelector(".force")).toBeNull();
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

    expect(feature.shadowRoot.textContent).toContain(
      "Sensor(es) abierto(s) — ciérrelos antes de armar",
    );
    expect(feature.shadowRoot.querySelector(".sensors")).toBeNull();
  });

  it("offers Force Arm only when allowed and calls both feature services", () => {
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

    feature.shadowRoot.querySelector(".force").click();
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });

    feature.shadowRoot.querySelector(".dismiss").click();
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
    expect(feature.shadowRoot.textContent).toContain("Patio");

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

    expect(feature.shadowRoot.textContent).toContain("Garage");
    feature.shadowRoot.querySelector(".dismiss").click();
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
    expect(feature.shadowRoot.textContent).toContain("Window 1");

    feature.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          armExceptionActive: true,
          armExceptions: ["Window 2", "Window 3"],
        }),
      },
    });
    expect(feature.shadowRoot.textContent).not.toContain("Window 1");
    expect(feature.shadowRoot.textContent).toContain("Window 2, Window 3");
  });
});
