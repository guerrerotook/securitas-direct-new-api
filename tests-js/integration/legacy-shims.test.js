import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/securitas-alarm-card.js";
import "../../custom_components/securitas/www/securitas-camera-card.js";

describe("legacy shim re-exports", () => {
  it("loading securitas-alarm-card.js registers the verisure-owa custom elements", () => {
    expect(customElements.get("verisure-owa-alarm-card")).toBeDefined();
  });

  it("loading securitas-camera-card.js registers the verisure-owa-camera-card element", () => {
    expect(customElements.get("verisure-owa-camera-card")).toBeDefined();
  });

  it("legacy securitas-* aliases are also registered", () => {
    expect(customElements.get("securitas-alarm-card")).toBeDefined();
    expect(customElements.get("securitas-camera-card")).toBeDefined();
  });
});
