import { describe, it, expect } from "vitest";
import { alarmEntitySuggestion } from "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { makeHass } from "../fixtures/hass.js";

const ours = (entityId, platform = "securitas") =>
  makeHass({ entities: { [entityId]: { platform } } });

describe("alarmEntitySuggestion", () => {
  it("suggests the full card and the chip for one of our alarm panels", () => {
    const hass = ours("alarm_control_panel.home");
    expect(alarmEntitySuggestion(hass, "alarm_control_panel.home")).toEqual([
      { config: { type: "custom:verisure-owa-alarm-card", entity: "alarm_control_panel.home" } },
      { config: { type: "custom:verisure-owa-alarm-chip", entity: "alarm_control_panel.home" } },
    ]);
  });

  it("does not match the never-released verisure_owa domain", () => {
    const hass = ours("alarm_control_panel.home", "verisure_owa");
    expect(alarmEntitySuggestion(hass, "alarm_control_panel.home")).toBeNull();
  });

  it("returns null for an alarm panel from another integration", () => {
    const hass = ours("alarm_control_panel.other", "manual");
    expect(alarmEntitySuggestion(hass, "alarm_control_panel.other")).toBeNull();
  });

  it("returns null for non-alarm domains", () => {
    const hass = ours("sensor.temperature");
    expect(alarmEntitySuggestion(hass, "sensor.temperature")).toBeNull();
  });

  it("returns null when the entity is not in the registry", () => {
    expect(alarmEntitySuggestion(makeHass(), "alarm_control_panel.unknown")).toBeNull();
  });
});
