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

  it("loading securitas-alarm-card.js also registers the chip/badge (split modules)", () => {
    // The chip/badge now live in a separate module; the shim imports it too so
    // a single legacy resource still defines every element, as before the split.
    expect(customElements.get("securitas-alarm-chip")).toBeDefined();
    expect(customElements.get("securitas-alarm-badge")).toBeDefined();
    expect(customElements.get("verisure-owa-alarm-chip")).toBeDefined();
    expect(customElements.get("verisure-owa-alarm-badge")).toBeDefined();
  });
});
