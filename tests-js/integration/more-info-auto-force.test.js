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

// HA renders its mode buttons several shadow roots deep inside the wrapped
// native control: more-info-content > more-info-alarm_control_panel >
// ha-state-control-alarm_control_panel-modes > ha-control-select.
function nativeModeSelect(element, controlTag = "ha-state-control-alarm_control_panel-modes") {
  const native = element.shadowRoot.getElementById("native-control");
  const moreInfo = document.createElement("more-info-alarm_control_panel");
  const control = document.createElement(controlTag);
  const select = document.createElement("ha-control-select");
  control.attachShadow({ mode: "open" }).appendChild(select);
  moreInfo.attachShadow({ mode: "open" }).appendChild(control);
  native.replaceChildren(moreInfo);
  return select;
}

// What HA's ha-control-select fires when a mode button is pressed
// (fireEvent defaults: bubbles + composed).
function pressMode(element, value = "armed_away", controlTag) {
  const event = new CustomEvent("value-changed", {
    detail: { value },
    bubbles: true,
    composed: true,
  });
  nativeModeSelect(element, controlTag).dispatchEvent(event);
  return event;
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
  it("auto-forces an arm started from the dialog's own buttons when the box is on", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    // HA's stock control dispatches the arm; the panel optimistically moves to
    // `arming` before the forceable exception lands.
    pressMode(element);
    push(element, { state: "arming" }, { callService });
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });

    expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
  });

  it("contains rejections from the best-effort auto-force service calls", async () => {
    // Both auto-force calls (suppress + force-arm) are fire-and-forget, so a
    // backend rejection must not escape as an unhandled promise rejection in
    // the browser console (vitest fails the run on one). A plain function, not
    // vi.fn, because a spy observes returned promises and marks them handled.
    localStorage.setItem(LS_KEY, "true");
    const services = [];
    const callService = (_domain, service) => {
      services.push(service);
      return Promise.reject(new Error("panel offline"));
    };
    const { element } = mountMoreInfo({}, { callService });

    pressMode(element);
    push(element, { state: "arming" }, { callService });
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(services).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
  });

  it("suppresses the arm-exception prompt when a user arm starts", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    // Best-effort pre-suppress fired as soon as the arm goes in-flight, so the
    // transient prompt can be skipped and only the "force-armed" confirmation
    // is shown.
    pressMode(element);
    push(element, { state: "arming" }, { callService });

    expect(callService).toHaveBeenCalledWith("verisure_owa", "suppress_arm_exception_prompt", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force when the box is off (manual Force Arm instead)", () => {
    localStorage.setItem(LS_KEY, "false");
    const { element, callService } = mountMoreInfo();

    pressMode(element);
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

    pressMode(element);
    push(element, { state: "arming" }, { callService });

    expect(callService).not.toHaveBeenCalledWith("verisure_owa", "suppress_arm_exception_prompt", {
      entity_id: ENTITY,
    });
  });

  it("does NOT auto-force when the capability gate is off, even if remembered on", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo({ autoForceArmEnabled: false });

    pressMode(element);
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

    pressMode(element);
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

    pressMode(element);
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

    pressMode(element);
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
    pressMode(element);
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

describe("More Info auto-force acts only on the dialog's own arm buttons", () => {
  function autoForceCalls(callService) {
    return callService.mock.calls
      .map((call) => call[1])
      .filter((service) => ["suppress_arm_exception_prompt", "force_arm"].includes(service));
  }

  function armWithException(element, callService) {
    push(element, { state: "arming" }, { callService });
    push(element, { forceArmAvailable: true, armExceptions: ["Kitchen Door"] }, { callService });
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does NOT auto-force an arm started elsewhere (automation, other screen, app)", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    armWithException(element, callService);

    expect(autoForceCalls(callService)).toEqual([]);
  });

  it("does NOT auto-force when the arm starts more than 60 s after the button press", () => {
    vi.useFakeTimers();
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    pressMode(element);
    vi.advanceTimersByTime(60_001);
    armWithException(element, callService);

    expect(autoForceCalls(callService)).toEqual([]);
  });

  it("still auto-forces when the arm starts within 60 s (PIN entry)", () => {
    vi.useFakeTimers();
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    pressMode(element);
    vi.advanceTimersByTime(59_000);
    armWithException(element, callService);

    expect(callService).toHaveBeenCalledWith("verisure_owa", "force_arm", { entity_id: ENTITY });
  });

  it("does NOT treat a disarm press as an arm intent", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    pressMode(element, "disarmed");
    armWithException(element, callService);

    expect(autoForceCalls(callService)).toEqual([]);
  });

  it("ignores value-changed events from other controls", () => {
    localStorage.setItem(LS_KEY, "true");
    const { element, callService } = mountMoreInfo();

    pressMode(element, "armed_away", "ha-more-info-settings");
    armWithException(element, callService);

    expect(autoForceCalls(callService)).toEqual([]);
  });

  it("does not stop the mode event, so HA's own handler still arms", () => {
    const { element } = mountMoreInfo();
    const outer = vi.fn();
    document.body.addEventListener("value-changed", outer);

    const event = pressMode(element);
    document.body.removeEventListener("value-changed", outer);

    expect(outer).toHaveBeenCalledWith(event);
  });

  it("keeps the tick box's change event inside the dialog and never counts it as an arm", () => {
    const { element, callService } = mountMoreInfo();
    const outer = vi.fn();
    document.body.addEventListener("change", outer);

    const cb = checkbox(element);
    cb.checked = true;
    cb.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    document.body.removeEventListener("change", outer);
    armWithException(element, callService);

    expect(outer).not.toHaveBeenCalled();
    expect(autoForceCalls(callService)).toEqual([]);
  });
});
