import { describe, it, expect } from "vitest";
import { cameraEntitySuggestion } from "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { makeHass } from "../fixtures/hass.js";

const ours = (entityId, platform = "securitas") =>
  makeHass({ entities: { [entityId]: { platform } } });

describe("cameraEntitySuggestion", () => {
  it("suggests the camera card for one of our camera entities", () => {
    const hass = ours("camera.front_door");
    expect(cameraEntitySuggestion(hass, "camera.front_door")).toEqual({
      config: { type: "custom:verisure-owa-camera-card", entity: "camera.front_door" },
    });
  });

  it("does not match the never-released verisure_owa domain", () => {
    const hass = ours("camera.garden", "verisure_owa");
    expect(cameraEntitySuggestion(hass, "camera.garden")).toBeNull();
  });

  it("returns null for a camera from another integration", () => {
    const hass = ours("camera.generic_cam", "generic");
    expect(cameraEntitySuggestion(hass, "camera.generic_cam")).toBeNull();
  });

  it("returns null for non-camera domains", () => {
    const hass = ours("light.kitchen");
    expect(cameraEntitySuggestion(hass, "light.kitchen")).toBeNull();
  });

  it("returns null for the internal full-image camera entity", () => {
    const hass = ours("camera.front_door_full_image");
    expect(cameraEntitySuggestion(hass, "camera.front_door_full_image")).toBeNull();
  });

  it("returns null when the entity is not in the registry", () => {
    expect(cameraEntitySuggestion(makeHass(), "camera.unknown")).toBeNull();
  });
});
