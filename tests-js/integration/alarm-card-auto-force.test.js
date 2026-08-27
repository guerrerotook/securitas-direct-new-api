import { describe, it, expect, beforeEach, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

const ENTITY = "alarm_control_panel.test";
const LS_KEY = `verisure-owa:auto-force-arm:${ENTITY}`;

function mountAlarmCard({ config = {}, hass = makeHass() } = {}) {
  const el = document.createElement("verisure-owa-alarm-card");
  el.setConfig({ type: "custom:verisure-owa-alarm-card", entity: ENTITY, ...config });
  el.hass = hass;
  document.body.appendChild(el);
  return el;
}

function disarmed(overrides = {}) {
  return makeAlarmEntity({ state: "disarmed", autoForceArmEnabled: true, ...overrides });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("auto-force tick box visibility (capability gate)", () => {
  it("shows the tick box when auto_force_arm_enabled is true and disarmed", () => {
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: disarmed() } }),
    });
    expect(card.shadowRoot.querySelector(".auto-force-toggle")).not.toBeNull();
    expect(card.shadowRoot.querySelector(".auto-force-checkbox")).not.toBeNull();
  });

  it("hides the tick box when auto_force_arm_enabled is false", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed", autoForceArmEnabled: false }) },
      }),
    });
    expect(card.shadowRoot.querySelector(".auto-force-toggle")).toBeNull();
  });

  it("re-renders to show the tick box when the capability gate turns on", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed", autoForceArmEnabled: false }) },
      }),
    });
    expect(card.shadowRoot.querySelector(".auto-force-toggle")).toBeNull();

    // User enables the option; HA updates only the attribute.
    card.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed", autoForceArmEnabled: true }) },
    });
    expect(card.shadowRoot.querySelector(".auto-force-toggle")).not.toBeNull();
  });

  it("hides the tick box when the alarm is already armed", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "armed_away", autoForceArmEnabled: true }) },
      }),
    });
    expect(card.shadowRoot.querySelector(".auto-force-toggle")).toBeNull();
  });
});

describe("auto-force tick box persistence (localStorage)", () => {
  it("checking the box writes the choice to localStorage", () => {
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: disarmed() } }),
    });
    const cb = card.shadowRoot.querySelector(".auto-force-checkbox");
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));
    expect(localStorage.getItem(LS_KEY)).toBe("true");
  });

  it("unchecking the box clears the stored choice", () => {
    localStorage.setItem(LS_KEY, "true");
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: disarmed() } }),
    });
    const cb = card.shadowRoot.querySelector(".auto-force-checkbox");
    cb.checked = false;
    cb.dispatchEvent(new Event("change"));
    expect(localStorage.getItem(LS_KEY)).toBe("false");
  });

  it("renders the box pre-checked from a stored true choice", () => {
    localStorage.setItem(LS_KEY, "true");
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: disarmed() } }),
    });
    expect(card.shadowRoot.querySelector(".auto-force-checkbox").checked).toBe(true);
  });
});

describe("auto-force behaviour", () => {
  it("auto-forces after a card-initiated arm when the box is on", () => {
    localStorage.setItem(LS_KEY, "true");
    const hass = makeHass({ states: { [ENTITY]: disarmed() } });
    const card = mountAlarmCard({ hass });

    // User arms from the card.
    card.shadowRoot.querySelector('[data-action="arm_away"]').click();
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_arm_away", {
      entity_id: ENTITY,
    });

    // Backend rejects with a forceable exception.
    card.hass = makeHass({
      callService: hass.callService,
      states: {
        [ENTITY]: disarmed({ forceArmAvailable: true, armExceptions: ["Kitchen Door"] }),
      },
    });

    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force a stale exception present on load (no card arm)", () => {
    localStorage.setItem(LS_KEY, "true");
    const hass = makeHass({
      states: {
        [ENTITY]: disarmed({ forceArmAvailable: true, armExceptions: ["Kitchen Door"] }),
      },
    });
    mountAlarmCard({ hass });
    expect(hass.callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force when the box is off (manual buttons instead)", () => {
    localStorage.setItem(LS_KEY, "false");
    const hass = makeHass({ states: { [ENTITY]: disarmed() } });
    const card = mountAlarmCard({ hass });

    card.shadowRoot.querySelector('[data-action="arm_away"]').click();
    card.hass = makeHass({
      callService: hass.callService,
      states: {
        [ENTITY]: disarmed({ forceArmAvailable: true, armExceptions: ["Kitchen Door"] }),
      },
    });

    expect(hass.callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
    // Manual force section is still offered.
    expect(card.shadowRoot.querySelector('[data-action="force_arm"]')).not.toBeNull();
  });

  it("drops the intent after a non-forceable rejection bounces back to disarmed", () => {
    localStorage.setItem(LS_KEY, "true");
    const hass = makeHass({ states: { [ENTITY]: disarmed() } });
    const card = mountAlarmCard({ hass });

    card.shadowRoot.querySelector('[data-action="arm_away"]').click();

    // Arm goes in-flight, then bounces back to disarmed with NO forceable
    // exception (a non-forceable panel rejection / other arm error).
    card.hass = makeHass({
      callService: hass.callService,
      states: { [ENTITY]: makeAlarmEntity({ state: "arming", autoForceArmEnabled: true }) },
    });
    card.hass = makeHass({
      callService: hass.callService,
      states: { [ENTITY]: disarmed() },
    });

    // A later, unrelated exception on this entity (not from this card) must
    // not auto-force.
    card.hass = makeHass({
      callService: hass.callService,
      states: {
        [ENTITY]: disarmed({ forceArmAvailable: true, armExceptions: ["Kitchen Door"] }),
      },
    });

    expect(hass.callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("clears the pending intent once the arm commits without exceptions", () => {
    localStorage.setItem(LS_KEY, "true");
    const hass = makeHass({ states: { [ENTITY]: disarmed() } });
    const card = mountAlarmCard({ hass });

    card.shadowRoot.querySelector('[data-action="arm_away"]').click();

    // Arm succeeds outright.
    card.hass = makeHass({
      callService: hass.callService,
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away", autoForceArmEnabled: true }) },
    });
    // A later, unrelated exception (e.g. a sibling device) must not auto-force.
    card.hass = makeHass({
      callService: hass.callService,
      states: {
        [ENTITY]: disarmed({ forceArmAvailable: true, armExceptions: ["Kitchen Door"] }),
      },
    });

    expect(hass.callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });
});
