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
