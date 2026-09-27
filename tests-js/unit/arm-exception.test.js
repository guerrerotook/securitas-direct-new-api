import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AUTO_FORCE_ARM_START_MS,
  AUTO_FORCE_CHANGED_EVENT,
  AUTO_FORCE_INTENT_TTL_MS,
  AutoForceArmTracker,
  AutoForceTickBox,
  writeAutoForce,
  armExceptionState,
  armExceptionTranslation,
} from "../../custom_components/securitas/www/verisure-owa-arm-exception.js";
import { makeHass } from "../fixtures/hass.js";
import { makeModesControl, pressMode } from "../fixtures/ha-alarm-dom.js";

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
    for (const lang of ["en", "es", "fr", "it", "pt", "pt-BR", "ca"]) {
      const value = armExceptionTranslation(lang, "auto_force_arm");
      expect(value).not.toBe("auto_force_arm");
      expect(value.length).toBeGreaterThan(0);
    }
  });

  it("speaks Catalan rather than falling back to English", () => {
    expect(armExceptionTranslation("ca", "force_arm")).toBe("Força l’armat");
    expect(armExceptionTranslation("ca", "cancel")).toBe("Cancel·la");
    expect(armExceptionTranslation("ca", "open_sensors")).toBe(
      "Sensor(s) obert(s) — armar igualment?",
    );
    expect(armExceptionTranslation("ca", "auto_force_arm")).toBe(
      "Força l’armat automàticament amb sensors oberts",
    );
    expect(armExceptionTranslation("ca", "action_failed_detail", { error: "x" })).toBe(
      "L’acció de l’alarma ha fallat: x",
    );
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

  // HA's PIN prompt, as dialog-enter-code renders it: a keypad whose tick
  // button submits, the PIN box (Enter submits), and for text PINs a footer
  // Submit button.
  function pinPromptElement() {
    const dialog = document.createElement("dialog-enter-code");
    const root = dialog.attachShadow({ mode: "open" });
    const input = document.createElement("ha-input");
    input.id = "code";
    const inner = input.attachShadow({ mode: "open" }).appendChild(document.createElement("input"));
    const digit = document.createElement("ha-control-button");
    digit.textContent = "8";
    const clear = document.createElement("ha-control-button");
    clear.className = "clear";
    const tick = document.createElement("ha-control-button");
    tick.className = "submit";
    const textSubmit = document.createElement("ha-button");
    textSubmit.slot = "primaryAction";
    const textCancel = document.createElement("ha-button");
    textCancel.slot = "secondaryAction";
    root.append(input, digit, clear, tick, textSubmit, textCancel);
    document.body.appendChild(dialog);
    return { dialog, inner, digit, clear, tick, textSubmit, textCancel };
  }

  // Dispatch as the browser would, with the tracker listening where connect()
  // listens (window, capture), so composedPath() is real.
  function inPrompt(tracker, dispatch) {
    const listener = (event) => tracker.noteSubmit(event);
    window.addEventListener("click", listener, true);
    window.addEventListener("keydown", listener, true);
    dispatch();
    window.removeEventListener("click", listener, true);
    window.removeEventListener("keydown", listener, true);
  }

  function clickIn(tracker, element) {
    inPrompt(tracker, () =>
      element.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true })),
    );
  }

  function pressKeyIn(tracker, element, key) {
    inPrompt(tracker, () =>
      element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, composed: true })),
    );
  }

  function submitPin(tracker) {
    clickIn(tracker, pinPromptElement().tick);
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
    submitPin(tracker);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);

    const late = setup();
    fire(late.select, "armed_away", late.tracker, late.disarmed);
    openPinPrompt(late.tracker);
    vi.advanceTimersByTime(AUTO_FORCE_INTENT_TTL_MS + 1);
    submitPin(late.tracker);
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

  it("forgets the press as soon as the PIN prompt closes without a Submit", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    closePinPrompt(tracker);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("does not let a Submit in a later PIN prompt revive a press whose prompt was cancelled", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    closePinPrompt(tracker);
    // Any PIN prompt on the page counts as a Submit, e.g. one opened elsewhere.
    submitPin(tracker);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("does not force an arm that starts while the PIN prompt is open and nothing was submitted", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("forces the arm that lands after a Submit but before the prompt reports closing", () => {
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    submitPin(tracker);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    closePinPrompt(tracker);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
  });

  it("counts the keypad tick, Enter in the PIN box and a text-PIN Submit button as a Submit", () => {
    const submits = [
      (tracker) => clickIn(tracker, pinPromptElement().tick),
      (tracker) => pressKeyIn(tracker, pinPromptElement().inner, "Enter"),
      (tracker) => clickIn(tracker, pinPromptElement().textSubmit),
    ];
    for (const submit of submits) {
      const { tracker, hass, disarmed, select } = setup();
      fire(select, "armed_away", tracker, disarmed);
      openPinPrompt(tracker);
      submit(tracker);
      tracker.update(stateOf({ state: "arming" }), true, hass);
      expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
    }
  });

  it("ignores other prompt keys and buttons, and submit-like buttons outside the prompt", () => {
    const { tracker, hass, disarmed, select } = setup();
    const prompt = pinPromptElement();
    const outside = document.createElement("ha-control-button");
    outside.className = "submit";
    document.body.appendChild(outside);

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    clickIn(tracker, prompt.digit);
    clickIn(tracker, prompt.clear);
    clickIn(tracker, prompt.textCancel);
    pressKeyIn(tracker, prompt.inner, "8");
    clickIn(tracker, outside);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("ignores a Submit when its own PIN prompt is not open", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    vi.advanceTimersByTime(AUTO_FORCE_ARM_START_MS - 1_000);
    openPinPrompt(tracker, "another-modes-control");
    // Counted, this Submit would restart the start window.
    submitPin(tracker);
    vi.advanceTimersByTime(2_000);
    tracker.update(stateOf({ state: "arming" }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("forces the arm that follows a submitted PIN prompt", () => {
    vi.useFakeTimers();
    const { tracker, hass, disarmed, select } = setup();

    fire(select, "armed_away", tracker, disarmed);
    openPinPrompt(tracker);
    vi.advanceTimersByTime(30_000);
    submitPin(tracker);
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
    submitPin(other.tracker);
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
    tracker.connect(scope);
    // A press before the first update has no state to be judged against.
    press();
    tracker.update(stateOf(), true, hass);
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(hass.callService).not.toHaveBeenCalled();

    tracker.update(stateOf(), true, hass);

    press();
    prompt();
    vi.advanceTimersByTime(30_000);
    pinPromptElement().tick.dispatchEvent(
      new MouseEvent("click", { bubbles: true, composed: true }),
    );
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

  // happy-dom removes a capture listener even when the remove omits the
  // capture flag, where a browser would leave it attached, so check the flags.
  it("removes each listener with the same capture flag it was added with", () => {
    const tracker = new AutoForceArmTracker(CONTROL);
    const scope = document.createElement("div");
    const record = (target) => {
      const added = [];
      const removed = [];
      vi.spyOn(target, "addEventListener").mockImplementation((type, fn, capture) =>
        added.push([type, fn, capture === true]),
      );
      vi.spyOn(target, "removeEventListener").mockImplementation((type, fn, capture) =>
        removed.push([type, fn, capture === true]),
      );
      return { added, removed };
    };
    const onScope = record(scope);
    const onWindow = record(globalThis);

    tracker.connect(scope);
    tracker.disconnect();
    vi.restoreAllMocks();

    expect(onScope.added.find(([type]) => type === "value-changed")[2]).toBe(true);
    expect(onScope.removed).toEqual(onScope.added);
    expect(onWindow.removed).toEqual(onWindow.added);
  });

  // A modes control whose own handler on its inner select opens the PIN prompt
  // straight away, before the press has bubbled out to the tracker's scope.
  function connectedControlThatPromptsAtOnce() {
    const tracker = new AutoForceArmTracker(CONTROL);
    const hass = makeHass();
    const scope = document.createElement("div");
    document.body.appendChild(scope);
    const control = document.createElement(CONTROL);
    const select = document.createElement("ha-control-select");
    control.attachShadow({ mode: "open" }).appendChild(select);
    scope.appendChild(control);
    select.addEventListener("value-changed", () =>
      select.dispatchEvent(
        new CustomEvent("show-dialog", {
          detail: { dialogTag: "dialog-enter-code" },
          bubbles: true,
          composed: true,
        }),
      ),
    );
    tracker.connect(scope);
    tracker.update(stateOf(), true, hass);
    const press = () =>
      select.dispatchEvent(
        new CustomEvent("value-changed", {
          detail: { value: "armed_away" },
          bubbles: true,
          composed: true,
        }),
      );
    return { tracker, hass, press };
  }

  it("does not force an arm from elsewhere while a PIN prompt opened at once by the press is unsubmitted", () => {
    const { tracker, hass, press } = connectedControlThatPromptsAtOnce();

    press();
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(hass.callService).not.toHaveBeenCalled();
    tracker.disconnect();
  });

  it("forces the arm after a Submit in a PIN prompt opened at once by the press", () => {
    const { tracker, hass, press } = connectedControlThatPromptsAtOnce();

    press();
    pinPromptElement().tick.dispatchEvent(
      new MouseEvent("click", { bubbles: true, composed: true }),
    );
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.update(stateOf({ forceArmAvailable: true }), true, hass);

    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt", "force_arm"]);
    tracker.disconnect();
  });

  it("judges a press by the tick and state from the latest update", () => {
    const tracker = new AutoForceArmTracker(CONTROL);
    const hass = makeHass();
    const select = nestedSelect(CONTROL);
    const press = () =>
      select.dispatchEvent(
        new CustomEvent("value-changed", {
          detail: { value: "armed_away" },
          bubbles: true,
          composed: true,
        }),
      );
    tracker.connect(document.body);

    tracker.update(stateOf(), false, hass);
    press();
    tracker.update(stateOf({ state: "arming" }), true, hass);
    expect(hass.callService).not.toHaveBeenCalled();

    tracker.update(stateOf(), true, hass);
    press();
    tracker.update(stateOf({ state: "arming" }), true, hass);
    tracker.disconnect();
    expect(calls(hass)).toEqual(["suppress_arm_exception_prompt"]);
  });

  it("announces a saved tick so More Info and the Tile can follow it", () => {
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

  it("contains a service call that throws before returning a promise", () => {
    const { tracker, disarmed, select } = setup();
    const services = [];
    const hass = makeHass({
      callService: (_domain, service) => {
        services.push(service);
        throw new Error("disconnected");
      },
    });

    fire(select, "armed_away", tracker, disarmed);
    expect(() => tracker.update(stateOf({ state: "arming" }), true, hass)).not.toThrow();
    expect(() => tracker.update(stateOf({ forceArmAvailable: true }), true, hass)).not.toThrow();

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

describe("AutoForceTickBox (the tick box shared by More Info and the Tile)", () => {
  const OTHER = "alarm_control_panel.other";

  function tickBoxFor(entityId, onChange = vi.fn()) {
    const box = new AutoForceTickBox(CONTROL, { onChange });
    box.connect(null);
    box.setEntity(entityId);
    box.render(stateOf(), makeHass());
    return box;
  }

  function tick(box, on) {
    box.checkbox.checked = on;
    box.checkbox.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  }

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("reflects the stored preference for its entity", () => {
    localStorage.setItem(`verisure-owa:auto-force-arm:${ENTITY}`, "true");

    const box = tickBoxFor(ENTITY);
    const other = tickBoxFor(OTHER);

    expect(box.ticked).toBe(true);
    expect(box.field.hidden).toBe(false);
    expect(box.field.getAttribute("label")).toBe("Automatically force-arm past open sensors");
    expect(box.checkbox.checked).toBe(true);
    expect(other.ticked).toBe(false);
    expect(other.checkbox.checked).toBe(false);
    box.disconnect();
    other.disconnect();
  });

  it("is offered only while disarmed with the capability gate on", () => {
    const box = tickBoxFor(ENTITY);
    const hass = makeHass();

    expect(box.render(stateOf({ autoForceArmEnabled: false }), hass)).toBe(false);
    expect(box.field.hidden).toBe(true);
    expect(box.render(stateOf({ state: "armed_away" }), hass)).toBe(false);
    expect(box.render(stateOf(), hass, () => false)).toBe(false);
    expect(box.field.hidden).toBe(true);
    expect(box.render(stateOf(), hass)).toBe(true);
    expect(box.field.hidden).toBe(false);
    box.disconnect();
  });

  it("a tick writes the preference and notifies other surfaces", () => {
    const box = tickBoxFor(ENTITY);
    const heard = vi.fn();
    const outer = vi.fn();
    window.addEventListener(AUTO_FORCE_CHANGED_EVENT, heard);
    document.body.appendChild(box.field);
    document.body.addEventListener("change", outer);

    tick(box, true);
    window.removeEventListener(AUTO_FORCE_CHANGED_EVENT, heard);
    document.body.removeEventListener("change", outer);
    box.field.remove();

    expect(localStorage.getItem(`verisure-owa:auto-force-arm:${ENTITY}`)).toBe("true");
    expect(heard).toHaveBeenCalledOnce();
    expect(heard.mock.calls[0][0].detail).toEqual({ entityId: ENTITY, on: true });
    expect(outer).not.toHaveBeenCalled();
    box.disconnect();
  });

  it("saves nothing for a tick made before it knows its alarm", () => {
    const box = new AutoForceTickBox(CONTROL);
    const heard = vi.fn();
    window.addEventListener(AUTO_FORCE_CHANGED_EVENT, heard);

    tick(box, true);
    window.removeEventListener(AUTO_FORCE_CHANGED_EVENT, heard);

    expect(heard).not.toHaveBeenCalled();
    expect(localStorage.getItem(`verisure-owa:auto-force-arm:${ENTITY}`)).toBeNull();
  });

  it("follows a tick made elsewhere for the same entity and ignores other entities", () => {
    const onChange = vi.fn();
    const box = tickBoxFor(ENTITY, onChange);

    writeAutoForce(OTHER, true);
    expect(onChange).not.toHaveBeenCalled();
    expect(box.ticked).toBe(false);

    writeAutoForce(ENTITY, true);
    expect(onChange).toHaveBeenCalledOnce();
    expect(box.ticked).toBe(true);
    box.render(stateOf(), makeHass());
    expect(box.checkbox.checked).toBe(true);
    box.disconnect();
  });

  it("stops following after disconnect()", () => {
    const onChange = vi.fn();
    const box = tickBoxFor(ENTITY, onChange);

    box.disconnect();
    writeAutoForce(ENTITY, true);

    expect(onChange).not.toHaveBeenCalled();
    expect(box.ticked).toBe(false);
  });

  it("reads storage only when its entity changes, and again after reconnecting", () => {
    const box = tickBoxFor(ENTITY);
    box.disconnect();
    localStorage.setItem(`verisure-owa:auto-force-arm:${ENTITY}`, "true");

    box.setEntity(ENTITY);
    expect(box.ticked).toBe(false);

    box.connect(null);
    box.setEntity(ENTITY);
    expect(box.ticked).toBe(true);
    box.setEntity(null);
    expect(box.ticked).toBe(false);
    expect(box.entityId).toBe(null);
    box.disconnect();
  });

  it("forces an arm started from its own control once connected", () => {
    localStorage.setItem(`verisure-owa:auto-force-arm:${ENTITY}`, "true");
    const hass = makeHass();
    const scope = document.createElement("div");
    const { control, select } = makeModesControl(CONTROL);
    scope.appendChild(control);
    document.body.appendChild(scope);
    const box = new AutoForceTickBox(CONTROL);
    box.connect(scope);
    box.setEntity(ENTITY);
    box.track(stateOf(), hass);

    pressMode(select, "armed_away");
    box.track(stateOf({ state: "arming" }), hass);
    box.track(stateOf({ forceArmAvailable: true }), hass);
    box.disconnect();

    expect(hass.callService.mock.calls.map((call) => call[1])).toEqual([
      "suppress_arm_exception_prompt",
      "force_arm",
    ]);
  });
});
