import { describe, it, expect, vi } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";
import { makeHass } from "../fixtures/hass.js";

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
      name: "Verisure OWA Alarm Badge",
    });
  });

  it("keeps the badge picker preview disabled so it survives no alarm entity", () => {
    // F5: with preview:true the badge picker calls setConfig(getStubConfig(hass)).
    // On a system with no alarm_control_panel.* entity, getStubConfig returns
    // { entity: "" } and setConfig throws "Please define an entity" — which
    // breaks the picker preview. We deliberately KEEP setConfig throwing on an
    // empty entity (real misconfiguration feedback) and instead disable the
    // live preview so the picker never drives it into that path.
    const badgeCtor = customElements.get("verisure-owa-alarm-badge");
    const stub = badgeCtor.getStubConfig(makeHass());
    expect(stub).toEqual({ entity: "" });

    const badge = document.createElement("verisure-owa-alarm-badge");
    expect(() => badge.setConfig(stub)).toThrow(/entity/i);

    const descriptor = window.customBadges.find((b) => b.type === "verisure-owa-alarm-badge");
    expect(descriptor.preview).toBe(false);
  });

  it("tolerates hass being assigned before setConfig", () => {
    // Some HA custom-element lifecycles (and test harnesses) assign `hass`
    // before calling setConfig(). set hass() must not read this._config.entity
    // before config exists, or the badge throws and never renders.
    const badge = document.createElement("verisure-owa-alarm-badge");
    expect(() => {
      badge.hass = makeHass();
    }).not.toThrow();
    // Once configured it renders without error.
    expect(() => {
      badge.setConfig({ entity: "alarm_control_panel.home" });
    }).not.toThrow();
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

    vi.useFakeTimers();
    const chipElement = chip.shadowRoot.getElementById("chip");
    chipElement.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    chipElement.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    vi.useRealTimers();

    expect(moreInfoEntity).toBe("alarm_control_panel.test");
  });
});
