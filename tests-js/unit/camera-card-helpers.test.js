import { describe, it, expect } from "vitest";
import { findFullImageEntityIds } from "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { makeHass } from "../fixtures/hass.js";

describe("findFullImageEntityIds", () => {
  it("returns empty array when hass has no entities", () => {
    expect(findFullImageEntityIds(makeHass())).toEqual([]);
  });

  it("returns matching full-image cameras from our platform", () => {
    const hass = makeHass({
      entities: {
        "camera.front_door_full_image": { platform: "securitas" },
        "camera.garden_full_image_2": { platform: "securitas" },
        "camera.kitchen": { platform: "securitas" },
        "camera.other_full_image": { platform: "generic" },
      },
    });
    const ids = findFullImageEntityIds(hass);
    expect(ids.sort()).toEqual(
      ["camera.front_door_full_image", "camera.garden_full_image_2"].sort(),
    );
  });

  it("ignores full-image cameras from the never-released verisure_owa domain", () => {
    // The integration domain was briefly going to be renamed securitas →
    // verisure_owa, but that was reversed before release, so no install ever
    // registers entities under the verisure_owa platform.
    const hass = makeHass({
      entities: { "camera.front_door_full_image": { platform: "verisure_owa" } },
    });
    expect(findFullImageEntityIds(hass)).toEqual([]);
  });

  it("ignores entries without a platform field", () => {
    const hass = makeHass({
      entities: { "camera.x_full_image": {} },
    });
    expect(findFullImageEntityIds(hass)).toEqual([]);
  });

  it("handles undefined hass.entities", () => {
    expect(findFullImageEntityIds({ entities: undefined })).toEqual([]);
  });
});
