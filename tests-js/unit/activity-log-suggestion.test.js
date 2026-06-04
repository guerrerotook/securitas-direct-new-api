import { describe, it, expect } from "vitest";
import { activityLogEntitySuggestion } from "../../custom_components/securitas/www/verisure-owa-activity-log-card.js";
import { makeHass } from "../fixtures/hass.js";

const ours = (entityId, { platform = "securitas", events = [] } = {}) =>
  makeHass({
    entities: { [entityId]: { platform } },
    states: { [entityId]: { attributes: { events } } },
  });

describe("activityLogEntitySuggestion", () => {
  it("suggests the activity-log card for one of our activity-log sensors", () => {
    const hass = ours("sensor.installation_activity_log");
    expect(activityLogEntitySuggestion(hass, "sensor.installation_activity_log")).toEqual({
      config: {
        type: "custom:verisure-owa-activity-log-card",
        entity: "sensor.installation_activity_log",
      },
    });
  });

  it("does not match the never-released verisure_owa domain", () => {
    const hass = ours("sensor.activity", { platform: "verisure_owa" });
    expect(activityLogEntitySuggestion(hass, "sensor.activity")).toBeNull();
  });

  it("returns null for a sensor from another integration", () => {
    const hass = ours("sensor.activity", { platform: "template" });
    expect(activityLogEntitySuggestion(hass, "sensor.activity")).toBeNull();
  });

  it("returns null for one of our sensors that has no events array", () => {
    const hass = makeHass({
      entities: { "sensor.battery": { platform: "securitas" } },
      states: { "sensor.battery": { attributes: {} } },
    });
    expect(activityLogEntitySuggestion(hass, "sensor.battery")).toBeNull();
  });

  it("returns null for non-sensor domains", () => {
    const hass = ours("binary_sensor.door");
    expect(activityLogEntitySuggestion(hass, "binary_sensor.door")).toBeNull();
  });

  it("returns null when the entity is not in the registry", () => {
    expect(activityLogEntitySuggestion(makeHass(), "sensor.unknown")).toBeNull();
  });
});
