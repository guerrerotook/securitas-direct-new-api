import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

const ENTITY = "alarm_control_panel.test";

describe("verisure-owa-alarm-badge", () => {
  it("registers", () => {
    expect(customElements.get("verisure-owa-alarm-badge")).toBeDefined();
  });

  it("renders a shield-lock icon when armed_away", () => {
    // The badge intentionally renders only an icon — not state text — so we
    // assert on the per-state icon mapping from STATE_CFG (armed_away ->
    // mdi:shield-lock) instead of the original "Armed Away" text assertion.
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    document.body.appendChild(badge);
    const html = badge.shadowRoot.innerHTML;
    expect(html).toContain("mdi:shield-lock");
    expect(html).toContain("<ha-icon");
  });

  it("renders the shield-off-outline icon for unavailable state", () => {
    // Same reasoning as above: badge has no text rendering. The STATE_CFG
    // entry for unavailable maps to mdi:shield-off-outline.
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "unavailable" }) },
    });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-off-outline");
  });

  it("renders the error shield-alert icon when the entity is missing", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({ states: {} });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-alert");
  });

  it("throws when setConfig is called without an entity", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    expect(() => badge.setConfig({})).toThrow(/entity/i);
  });
});

describe("verisure-owa-alarm-chip", () => {
  it("registers", () => {
    expect(customElements.get("verisure-owa-alarm-chip")).toBeDefined();
  });

  it("renders the shield-off-outline icon when disarmed", () => {
    // The chip, like the badge, renders only an icon (no state text). The
    // disarmed state maps to mdi:shield-off-outline in STATE_CFG.
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(chip);
    const html = chip.shadowRoot.innerHTML;
    expect(html).toContain("mdi:shield-off-outline");
    expect(html).toContain('class="chip"');
  });

  it("renders the warning alert icon when force_arm_available is true", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({ state: "disarmed", forceArmAvailable: true }),
      },
    });
    document.body.appendChild(chip);
    expect(chip.shadowRoot.innerHTML).toContain("mdi:alert");
  });

  it("throws when setConfig is called without an entity", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    expect(() => chip.setConfig({})).toThrow(/entity/i);
  });
});
