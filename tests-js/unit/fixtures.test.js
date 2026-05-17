import { describe, it, expect, vi } from "vitest";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity, makeCameraEntity, makeActivityLogEntity } from "../fixtures/entities.js";

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
