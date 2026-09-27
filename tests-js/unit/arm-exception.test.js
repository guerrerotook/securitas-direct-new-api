import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AUTO_FORCE_ARM_START_MS,
  AUTO_FORCE_CHANGED_EVENT,
  AUTO_FORCE_INTENT_TTL_MS,
  AutoForceArmTracker,
  writeAutoForce,
  armExceptionState,
  armExceptionTranslation,
} from "../../custom_components/securitas/www/verisure-owa-arm-exception.js";
import { makeHass } from "../fixtures/hass.js";

describe("arming-exception shared helpers", () => {
  it("resolves regional, English and key fallbacks", () => {
    expect(armExceptionTranslation("es-MX", "cancel")).toBe("Cancelar");
    expect(armExceptionTranslation("unknown", "cancel")).toBe("Cancel");
    expect(armExceptionTranslation("unknown", "missing_key")).toBe("missing_key");
    expect(armExceptionTranslation(undefined, "action_failed_detail", { error: "$&" })).toBe(
      "The alarm action failed: $&",
    );
  });

  it("provides the auto-force label in every supported locale", () => {
    // More Info imports only this lightweight module, so the auto-force tick
    // box label must live here rather than in the dashboard bundle.
    for (const lang of ["en", "es", "fr", "it", "pt", "pt-BR"]) {
      const value = armExceptionTranslation(lang, "auto_force_arm");
      expect(value).not.toBe("auto_force_arm");
      expect(value.length).toBeGreaterThan(0);
    }
  });

  it("normalizes missing, malformed and forceable entity state", () => {
    expect(armExceptionState()).toEqual({
      active: false,
      forceArmAvailable: false,
      sensors: [],
    });
    expect(
      armExceptionState({
        attributes: { force_arm_available: true, arm_exceptions: [1, "Window"] },
      }),
    ).toEqual({
      active: true,
      forceArmAvailable: true,
      sensors: ["1", "Window"],
    });
  });
});

describe("verisure-owa-arm-exception-alert public API", () => {
  it("updates all presentation state through one method", () => {
    const alert = document.createElement("verisure-owa-arm-exception-alert");
    const stateObj = {
      entity_id: "alarm_control_panel.test",
      attributes: { arm_exception_active: true, arm_exceptions: ["Patio"] },
    };
    const hass = makeHass({ language: undefined, locale: { language: "es" } });

    alert.update({
      hass,
      stateObj,
      entityId: "alarm_control_panel.test",
      presentation: "compact",
    });
    document.body.appendChild(alert);

    expect(alert.active).toBe(true);
    expect(alert.getAttribute("presentation")).toBe("compact");
    expect(alert.shadowRoot.textContent).toContain("Patio");

    alert.update({
      hass,
      stateObj,
      entityId: "alarm_control_panel.test",
      presentation: null,
    });
    expect(alert.getAttribute("presentation")).toBe("full");
    expect(alert.shadowRoot.querySelector("ha-button.cancel").textContent).toBe("Cancelar");
    expect(alert.shadowRoot.querySelector("style").textContent).toContain("grid-column: 2");
  });

  it("uses the generic notification for non-Error service rejections", async () => {
    const hass = makeHass();
    hass.callService = vi.fn().mockRejectedValue("offline");
    const alert = document.createElement("verisure-owa-arm-exception-alert");
    alert.update({
      hass,
      entityId: "alarm_control_panel.test",
      stateObj: {
        attributes: { arm_exception_active: true, force_arm_available: true },
      },
    });
    document.body.appendChild(alert);
    const notification = vi.fn();
    alert.addEventListener("hass-notification", notification);

    alert.shadowRoot.querySelector(".force").click();
    alert.shadowRoot.querySelector(".cancel").click();
    await Promise.resolve();
    await Promise.resolve();

    expect(hass.callService).toHaveBeenCalledOnce();
    expect(notification.mock.calls[0][0].detail.message).toBe(
      "The alarm action failed. Please try again.",
    );
  });
});

describe("AutoForceArmTracker (own-buttons-only auto-force)", () => {
  const ENTITY = "alarm_control_panel.test";
  const CONTROL = "fake-alarm-modes";

  function stateOf({
    state = "disarmed",
    forceArmAvailable = false,
    autoForceArmEnabled = true,
    entityId = ENTITY,
  } = {}) {
    return {
      entity_id: entityId,
      state,
      attributes: {
        force_arm_available: forceArmAvailable,
        auto_force_arm_enabled: autoForceArmEnabled,
      },
    };
  }

  // A control nested in a shadow root, as HA's alarm-modes controls are: the
  // event leaves through the host, so only composedPath() can name the control.
  function nestedSelect(tag) {
    const host = document.createElement(tag);
    const root = host.attachShadow({ mode: "open" });
    const select = document.createElement("ha-control-select");
    root.appendChild(select);
    document.body.appendChild(host);
    return select;
  }

  function fire(target, value, tracker, stateObj, ticked = true) {
    const listener = (event) => tracker.noteValueChanged(event, stateObj, ticked);
    document.body.addEventListener("value-changed", listener);
    target.dispatchEvent(
      new CustomEvent("value-changed", { detail: { value }, bubbles: true, composed: true }),
    );
    document.body.removeEventListener("value-changed", listener);
  }

  // HA's setProtectedAlarmControlPanelMode fires show-dialog from the modes
  // control itself (bubbles + composed) to open its PIN prompt.
  function openPinPrompt(tracker, from = CONTROL, dialogTag = "dialog-enter-code") {
    const control = document.querySelector(from) || nestedSelect(from).getRootNode().host;
    const listener = (event) => tracker.noteShowDialog(event);
    document.body.addEventListener("show-dialog", listener);
    control.dispatchEvent(
      new CustomEvent("show-dialog", { detail: { dialogTag }, bubbles: true, composed: true }),
    );
    document.body.removeEventListener("show-dialog", listener);
  }

  // The prompt lives elsewhere in HA's shell and fires dialog-closed on
  // Submit and Cancel alike; it reaches window.
  function closePinPrompt(tracker, dialog = "dialog-enter-code") {
    tracker.noteDialogClosed(new CustomEvent("dialog-closed", { detail: { dialog } }));
  }

  function setup() {
    const tracker = new AutoForceArmTracker(CONTROL);
    const hass = makeHass();
    const disarmed = stateOf();
    tracker.update(disarmed, true, hass);
    return { tracker, hass, disarmed, select: nestedSelect(CONTROL) };
  }

  function calls(hass) {
    return hass.callService.mock.calls.map((call) => call[1]);
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it("forces an arm started from its own control", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "suppress_arm_exception_prompt", {
      entity_id: ENTITY,
    });
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
  });

  it("also consumes the intent on a disarmed→pending transition", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_home", tracker, disarmed);
    tracker.update(stateOf({ state: "pending" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
  });

  it("does not force an arm with no intent (automation, other screen)", () => {
    const { tracker, hass } = setup();

    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("ignores value-changed events from other controls", () => {
    const { tracker, hass, disarmed } = setup();

    fire(nestedSelect("some-other-control"), "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("ignores disarm and non-alarm values", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "disarmed", tracker, disarmed);
    fire(select, "on", tracker, disarmed);
    fire(select, undefined, tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("ignores an intent while the panel is not disarmed", () => {
    const { tracker, hass, select } = setup();
    const armedHome = stateOf({ state: "armed_home" });
    tracker.update(armedHome, true, hass);

    fire(select, "armed_away", tracker, armedHome);
    tracker.update(stateOf(), true, hass);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("ignores an intent when the box is unticked or the gate is off", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed, false);
    fire(select, "armed_away", tracker, stateOf({ autoForceArmEnabled: false }), true);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("keeps the intent while the PIN prompt is open, up to the cap, then discards it", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    vi.advanceTimersByTime(AUTO_FORCE_INTENT_TTL_MS);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);

    const late = setup();
    fire(late.select, "armed_away", late.tracker, late.disarmed);
    openPinPrompt(late.tracker);
    vi.advanceTimersByTime(AUTO_FORCE_INTENT_TTL_MS + 1);
    late.tracker.update(stateOf({ state: "arming" }), true, late.hass);
    late.tracker.update(stateOf({ forceArmAvailable: true }), true, late.hass);
    expect(late.hass.callService).not.toHaveBeenCalled();
  });

  it("discards a press that no arm follows within the start window when no PIN prompt opens", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS + 1);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("still forces an arm that starts within the start window with no PIN prompt", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("discards the press shortly after the PIN prompt is cancelled", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    vi.advanceTimersByTime(5_000);
    closePinPrompt(tracker);
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS + 1);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("forces the arm that follows a submitted PIN prompt", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    vi.advanceTimersByTime(30_000);
    closePinPrompt(tracker);
    vi.advanceTimersByTime(1_000);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("ignores other dialogs and a PIN prompt opened by another control", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker, CONTROL, "some-other-dialog");
    openPinPrompt(tracker, "another-modes-control");
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS + 1);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(hass.callService).not.toHaveBeenCalled();

    const other = setup();
    fire(other.select, "armed_away", other.tracker, other.disarmed);
    openPinPrompt(other.tracker);
    closePinPrompt(other.tracker, "some-other-dialog");
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS + 1);
    other.tracker.update(stateOf({ state: "arming" }), true, other.hass);
    expect(calls(other.hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("listens on the scope and window once connected, and stops once disconnected", () => {
    vi.useFakeTimers();
    const tracker = new AutoForceArmTracker(CONTROL);
    const hass = makeHass();
    const scope = document.createElement("div");
    document.body.appendChild(scope);
    const control = document.createElement(CONTROL);
    const select = document.createElement("ha-control-select");
    control.attachShadow({ mode: "open" }).appendChild(select);
    scope.appendChild(control);
    const press = () =>
      select.dispatchEvent(
        new CustomEvent("value-changed", {
          detail: { value: "armed_away" },
          bubbles: true,
          composed: true,
        }),
      );
    const prompt = () =>
      control.dispatchEvent(
        new CustomEvent("show-dialog", {
          detail: { dialogTag: "dialog-enter-code" },
          bubbles: true,
          composed: true,
        }),
      );
    const closed = () =>
      window.dispatchEvent(
        new CustomEvent("dialog-closed", { detail: { dialog: "dialog-enter-code" } }),
      );
    tracker.connect(scope, { stateObj: () => stateOf(), ticked: () => true });
    tracker.update(stateOf(), true, hass);

    press();
    prompt();
    vi.advanceTimersByTime(30_000);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);

    tracker.update(stateOf({ state: "armed_away" }), true, hass);
    tracker.update(stateOf(), true, hass);
    press();
    prompt();
    closed();
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS + 1);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);

    tracker.update(stateOf(), true, hass);
    press();
    tracker.disconnect();
    tracker.update(stateOf(), true, hass);
    press();
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("announces a saved tick so every mounted surface can follow it", () => {
    const heard = vi.fn();
    window.addEventListener(AUTO_FORCE_CHANGED_EVENT, heard);

    writeAutoForce(ENTITY, true);
    window.removeEventListener(AUTO_FORCE_CHANGED_EVENT, heard);

    expect(heard).toHaveBeenCalledOnce();
    expect(heard.mock.calls[0][0].detail).toEqual({ entityId: ENTITY, on: true });
  });

  it("uses an intent once: a later arm from elsewhere is not forced", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ state: "armed_away" }), true, hass);
    tracker.update(stateOf(), true, hass);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("drops the intent when the panel leaves disarmed without arming", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "triggered" }), true, hass);
    tracker.update(stateOf(), true, hass);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("re-checks the gate and tick when the exception lands", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), false, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("drops the pending force once the arm settles without an exception", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf(), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("does not carry an intent across an entity swap", () => {
    const OTHER = "alarm_control_panel.other";
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ entityId: OTHER }), true, hass);
    tracker.update(stateOf({ entityId: OTHER, state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("does not carry a pending force across an entity swap", () => {
    const OTHER = "alarm_control_panel.other";
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ entityId: OTHER, forceArmAvailable: true }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("contains rejections from its best-effort service calls", async () => {
    const { tracker, disarmed, select } = setup();
    // A plain function, not vi.fn: a spy observes the promises it returns,
    // which would mark the rejection handled and hide a missing catch.
    const services = [];
    const hass = makeHass({
      callService: (_domain, service) => {
        services.push(service);
        return Promise.reject(new Error("offline"));
      },
    });

    fire(select, "armed_away", tracker, disarmed);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);
    // An uncaught rejection here would fail the run as an unhandled rejection.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(services).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
  });

  it("tolerates a missing state object or hass", () => {
    const tracker = new AutoForceArmTracker(CONTROL);
    const select = nestedSelect(CONTROL);

    expect(() => tracker.update(null, true, null)).not.toThrow();
    fire(select, "armed_away", tracker, null);
    tracker.update(stateOf(), true, null);
    fire(select, "armed_away", tracker, stateOf());
    expect(() => tracker.update(stateOf({ state: "arming" }), true, null)).not.toThrow();
  });
});
