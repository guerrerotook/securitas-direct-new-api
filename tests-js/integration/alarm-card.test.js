import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

const ENTITY = "alarm_control_panel.test";

function mountAlarmCard({ config = {}, hass = makeHass() } = {}) {
  const el = document.createElement("verisure-owa-alarm-card");
  el.setConfig({ type: "custom:verisure-owa-alarm-card", entity: ENTITY, ...config });
  el.hass = hass;
  document.body.appendChild(el);
  return el;
}

describe("verisure-owa-alarm-card render", () => {
  it("registers the custom element", () => {
    expect(customElements.get("verisure-owa-alarm-card")).toBeDefined();
  });

  it("renders disarmed state with arm-away button visible", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({ hass });
    const html = card.shadowRoot.innerHTML;
    expect(html).toContain("Disarmed");
    expect(html).toMatch(/arm[- _]?away/i);
  });

  it("renders armed_away state with disarm button visible", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    const card = mountAlarmCard({ hass });
    const html = card.shadowRoot.innerHTML;
    expect(html).toContain("Armed Away");
    expect(html.toLowerCase()).toContain("disarm");
  });

  it("renders unavailable state", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "unavailable" }) },
    });
    const card = mountAlarmCard({ hass });
    expect(card.shadowRoot.innerHTML).toContain("Unavailable");
  });

  it("renders entity-not-found message when state is missing", () => {
    const card = mountAlarmCard({ hass: makeHass() });
    expect(card.shadowRoot.innerHTML).toMatch(/Entity not found/);
  });
});

describe("verisure-owa-alarm-card state transitions", () => {
  it("re-renders when hass updates", () => {
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    expect(card.shadowRoot.innerHTML).toContain("Disarmed");

    card.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    expect(card.shadowRoot.innerHTML).toContain("Armed Away");
  });

  it("renders triggered state with warning emphasis", () => {
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "triggered" }) } }),
    });
    expect(card.shadowRoot.innerHTML).toContain("TRIGGERED");
  });

  it("renders arming and pending intermediate states", () => {
    const cardArming = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "arming" }) } }),
    });
    expect(cardArming.shadowRoot.innerHTML).toMatch(/Arming/);

    document.body.innerHTML = "";

    const cardPending = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "pending" }) } }),
    });
    expect(cardPending.shadowRoot.innerHTML).toMatch(/Pending/);
  });

  it("shows WAF rate-limit message when waf_blocked attribute is true", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({ state: "disarmed", wafBlocked: true }),
        },
      }),
    });
    expect(card.shadowRoot.innerHTML).toMatch(/Rate limited|Verisure servers/);
  });

  it("uses the Spanish locale when hass.language is es", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        language: "es",
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      }),
    });
    expect(card.shadowRoot.innerHTML).toContain("Desarmado");
  });
});

describe("verisure-owa-alarm-card service calls", () => {
  function findButton(card, labelMatcher) {
    const buttons = Array.from(card.shadowRoot.querySelectorAll("button"));
    return buttons.find((b) =>
      typeof labelMatcher === "string"
        ? b.textContent.trim() === labelMatcher
        : labelMatcher.test(b.textContent.trim()),
    );
  }

  it("clicking Arm Away calls alarm_arm_away", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({ hass });

    const armBtn = findButton(card, /Arm Away/i);
    expect(armBtn).toBeDefined();
    armBtn.click();

    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_arm_away", {
      entity_id: ENTITY,
    });
  });

  it("clicking Disarm when no code configured calls alarm_disarm immediately", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    const card = mountAlarmCard({ hass });

    const disarmBtn = findButton(card, /Disarm/i);
    disarmBtn.click();

    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
    });
  });

  it("Force Arm button calls verisure_owa.force_arm when force_arm_available", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "disarmed",
          forceArmAvailable: true,
          armExceptions: [{ alias: "Front Door", status_key: "open" }],
        }),
      },
    });
    const card = mountAlarmCard({ hass });

    const forceBtn = findButton(card, /Force Arm/i);
    expect(forceBtn).toBeDefined();
    forceBtn.click();

    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("Cancel button next to Force Arm calls verisure_owa.force_arm_cancel", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({ state: "disarmed", forceArmAvailable: true }),
      },
    });
    const card = mountAlarmCard({ hass });

    const cancelBtn = findButton(card, /Cancel/i);
    cancelBtn.click();

    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm_cancel", {
      entity_id: ENTITY,
    });
  });

  it("shows PIN keypad when code_arm_required and arm button clicked", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "disarmed",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const card = mountAlarmCard({ hass });

    findButton(card, /Arm Away/i).click();

    const html = card.shadowRoot.innerHTML;
    expect(html).toMatch(/Enter PIN/);
    expect(card.shadowRoot.querySelectorAll("button").length).toBeGreaterThan(5);
  });

  it("shows alphanumeric input when code_format is text", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "text",
        }),
      },
    });
    const card = mountAlarmCard({ hass });

    findButton(card, /Disarm/i).click();

    expect(
      card.shadowRoot.querySelector("input[type='password'], input[type='text']"),
    ).toBeDefined();
  });
});

describe("verisure-owa-alarm-card error paths", () => {
  it("logs and does not throw when callService rejects", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    hass.callService.mockRejectedValueOnce(new Error("boom"));
    const card = mountAlarmCard({ hass });

    const armBtn = card.shadowRoot.querySelector("button");
    expect(() => armBtn.click()).not.toThrow();
  });
});
