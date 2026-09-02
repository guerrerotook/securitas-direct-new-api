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
    expect(window.customBadges?.find((b) => b.type === "verisure-owa-alarm-badge")).toMatchObject({
      preview: true,
      name: "Verisure OWA Alarm Badge",
    });
  });

  it("opens native More Info without loading the custom alarm card", () => {
    // The compact module never needs to wait for the separate heavy card:
    // Home Assistant owns the dialog and loads our global More Info extension.
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
  });
});
