import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeHass } from "../fixtures/hass.js";

const ENTITY = "alarm_control_panel.test";
const LS_KEY = `verisure-owa:auto-force-arm:${ENTITY}`;

await import("../../custom_components/securitas/www/verisure-owa-more-info.js");

function makeState({
  state = "disarmed",
  armExceptionActive = false,
  forceArmAvailable = false,
  armExceptions = [],
  autoForceArmEnabled = true,
  entityId = ENTITY,
} = {}) {
  return {
    entity_id: entityId,
    state,
    attributes: {
      arm_exception_active: armExceptionActive,
      force_arm_available: forceArmAvailable,
      arm_exceptions: armExceptions,
      auto_force_arm_enabled: autoForceArmEnabled,
    },
  };
}

// Drive the element the way Home Assistant does: a fresh hass whose
// `states` map carries the current entity, plus the recomputed stateObj.
function push(element, stateOverrides, { callService } = {}) {
  const stateObj = makeState(stateOverrides);
  const hass = makeHass({
    ...(callService ? { callService } : {}),
    states: { [stateObj.entity_id]: stateObj },
  });
  element.hass = hass;
  element.stateObj = stateObj;
  return hass;
}

function mountMoreInfo(stateOverrides = {}, { callService } = {}) {
  const element = document.createElement("more-info-verisure-owa-alarm");
  const callServiceFn = callService || vi.fn(async () => {});
  push(element, stateOverrides, { callService: callServiceFn });
  document.body.appendChild(element);
  return { element, callService: callServiceFn };
}

function toggle(element) {
  // The tick box is a persistent element toggled via `hidden` (matching the
  // force-extension pattern in this file), so treat hidden as not shown.
  const el = element.shadowRoot.querySelector(".auto-force-toggle");
  return el && !el.hidden ? el : null;
}

function checkbox(element) {
  return element.shadowRoot.querySelector(".auto-force-checkbox");
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  document.body.innerHTML = "";
  localStorage.clear();
  vi.clearAllMocks();
});

describe("More Info auto-force tick box visibility (capability gate)", () => {
  it("shows the tick box when auto_force_arm_enabled is true and disarmed", () => {
    const { element } = mountMoreInfo();
    expect(toggle(element)).not.toBeNull();
    expect(checkbox(element)).not.toBeNull();
  });

  it("hides the tick box when auto_force_arm_enabled is false", () => {
    const { element } = mountMoreInfo({ autoForceArmEnabled: false });
    expect(toggle(element)).toBeNull();
  });

  it("hides the tick box when the alarm is already armed", () => {
    const { element } = mountMoreInfo({ state: "armed_away" });
    expect(toggle(element)).toBeNull();
  });

  it("re-renders to show the tick box when the capability gate turns on", () => {
    const { element } = mountMoreInfo({ autoForceArmEnabled: false });
    expect(toggle(element)).toBeNull();

    push(element, { autoForceArmEnabled: true });
    expect(toggle(element)).not.toBeNull();
  });
});

describe("More Info auto-force tick box persistence (localStorage)", () => {
  it("checking the box writes the choice to the shared per-device key", () => {
    const { element } = mountMoreInfo();
    const cb = checkbox(element);
    cb.checked = true;
    cb.dispatchEvent(new Event("change"));
    expect(localStorage.getItem(LS_KEY)).toBe("true");
  });

  it("unchecking the box records the off choice", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element } = mountMoreInfo();
    const cb = checkbox(element);
    cb.checked = false;
    cb.dispatchEvent(new Event("change"));
    expect(localStorage.getItem(LS_KEY)).toBe("false");
  });

  it("renders the box pre-checked from a stored true choice (set via the card)", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element } = mountMoreInfo();
    expect(checkbox(element).checked).toBe(true);
  });
});

describe("More Info auto-force behaviour", () => {
  it("auto-forces after a user arm when the box is on", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    // HA's stock control dispatches the arm; the panel optimistically moves to
    // `arming` before the forceable exception lands.
    push(element, { state: "arming" }, { callService });
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });

    expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("contains rejections from the best-effort auto-force service calls", async () => {
    // Both auto-force calls (suppress + force-arm) are fire-and-forget, so a
    // backend rejection must resolve rather than escape as an unhandled promise
    // rejection in the browser console.
    const callService = vi.fn(() => Promise.reject(new Error("panel offline")));
    const { element } = mountMoreInfo({}, { callService });

    await expect(element._bestEffortCall("force_arm", ENTITY)).resolves.toBeUndefined();
    await expect(
      element._bestEffortCall("suppress_arm_exception_prompt", ENTITY),
    ).resolves.toBeUndefined();
  });

  it("suppresses the arm-exception prompt when a user arm starts", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    // Best-effort pre-suppress fired as soon as the arm goes in-flight, so the
    // transient prompt can be skipped and only the "force-armed" confirmation
    // is shown.
    push(element, { state: "arming" }, { callService });

    expect(callService).toHaveBeenCalledWith("verisure_owa", "suppress_arm_exception_prompt", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force when the box is off (manual Force Arm instead)", () => {
    localStorage.setItem(LS_KEY, "false");
    const { element, callService } = mountMoreInfo();

    push(element, { state: "arming" }, { callService });
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
    // The manual Force Arm prompt is still offered.
    expect(
      element.shadowRoot.getElementById("force-extension").shadowRoot.querySelector(".force")
        .hidden,
    ).toBe(false);
  });

  it("does NOT suppress the prompt when the box is off", () => {
    const { element, callService } = mountMoreInfo();

    push(element, { state: "arming" }, { callService });

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "suppress_arm_exception_prompt", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force when the capability gate is off, even if remembered on", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo({ autoForceArmEnabled: false });

    push(element, { state: "arming", autoForceArmEnabled: false }, { callService });
    push(
      element,
      { forceArmAvailable: true, armExceptions: ["Kitchen Door"], autoForceArmEnabled: false },
      { callService },
    );

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force if the gate is turned off between arm and exception", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    push(element, { state: "arming" }, { callService });
    push(
      element,
      { forceArmAvailable: true, armExceptions: ["Kitchen Door"], autoForceArmEnabled: false },
      { callService },
    );

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force a stale exception present when the dialog opens", () => {
    localStorage.setItem(LS_KEY, "true");
    // The dialog opens straight onto a pending force context (an earlier arm
    // attempt elsewhere) — no arm started from this dialog, so do not force.
    const { callService } = mountMoreInfo({
      forceArmAvailable: true,
      armExceptions: ["Kitchen Door"],
    });

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("drops the intent after a non-forceable rejection bounces back to disarmed", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    push(element, { state: "arming" }, { callService });
    // Bounces back to disarmed with no forceable exception (non-forceable
    // rejection / other arm error).
    push(element, { state: "disarmed" }, { callService });
    // A later, unrelated forceable exception must not auto-force.
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("clears the pending intent once the arm commits without exceptions", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    push(element, { state: "arming" }, { callService });
    push(element, { state: "armed_away" }, { callService });
    // A later, unrelated forceable exception must not auto-force.
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("does not carry a pending intent across an entity swap on the same instance", () => {
    // Both devices have auto-force enabled, so only the per-entity reset (not
    // the gate re-check) can stop the swapped-in entity being force-armed.
    const OTHER = "alarm_control_panel.other";
    localStorage.setItem(LS_KEY, "true");
    localStorage.setItem(`verisure-owa:auto-force-arm:${OTHER}`, "true");
    const { element, callService } = mountMoreInfo();

    // An arm on the first entity goes in-flight (intent armed), then HA reuses
    // the same element for a different entity that already has a live forceable
    // context — the first entity's intent must not fire for the second.
    push(element, { state: "arming" }, { callService });
    push(
      element,
      { entityId: OTHER, forceArmAvailable: true, armExceptions: ["Kitchen Door"] },
      { callService },
    );

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: OTHER,
    });
  });
});
