import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";

// The chip/badge are what sit on an always-visible dashboard. They must be
// defined by their OWN lightweight module so they render without downloading
// the heavy alarm-card + editor bundle — that coupling is what made the alarm
// chip render 5-10s late on a cold dashboard open over a slow network.
describe("verisure-owa-alarm-chip standalone module", () => {
  it("defines the chip and badge elements", () => {
    expect(customElements.get("verisure-owa-alarm-chip")).toBeDefined();
    expect(customElements.get("verisure-owa-alarm-badge")).toBeDefined();
  });

  it("defines the mushroom + securitas chip/badge aliases", () => {
    expect(customElements.get("mushroom-verisure-owa-alarm-chip")).toBeDefined();
    expect(customElements.get("securitas-alarm-chip")).toBeDefined();
    expect(customElements.get("securitas-alarm-badge")).toBeDefined();
  });

  it("does NOT pull in the heavy alarm-card or editor at load time", () => {
    expect(customElements.get("verisure-owa-alarm-card")).toBeUndefined();
    expect(customElements.get("verisure-owa-alarm-card-editor")).toBeUndefined();
  });

  it("registers the chip in customCards and the badge in customBadges", () => {
    expect(window.customCards?.some((c) => c.type === "verisure-owa-alarm-chip")).toBe(true);
    expect(window.customBadges?.some((b) => b.type === "verisure-owa-alarm-badge")).toBe(true);
  });

  it("opening the popup before the card module loads falls back to native more-info", () => {
    // Slow cold load: the chip can be tapped before the separate
    // verisure-owa-alarm-card.js resource has loaded (securitas-alarm-card is
    // undefined here). The popup must not throw — it should fall back to HA's
    // native more-info dialog so the user can still arm/disarm.
    expect(customElements.get("securitas-alarm-card")).toBeUndefined();

    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: "alarm_control_panel.test" });
    chip.hass = {
      states: {
        "alarm_control_panel.test": { state: "armed_away", attributes: {} },
      },
      language: "en",
    };
    document.body.appendChild(chip);

    let moreInfoEntity = null;
    chip.addEventListener("hass-more-info", (e) => {
      moreInfoEntity = e.detail.entityId;
    });

    expect(() => chip._openDialog()).not.toThrow();
    expect(moreInfoEntity).toBe("alarm_control_panel.test");
    expect(chip._dialogOpen).toBe(false);
  });
});
