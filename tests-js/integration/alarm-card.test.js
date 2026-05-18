import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
    ).not.toBeNull();
  });
});

describe("verisure-owa-alarm-card error paths", () => {
  it("does not throw when callService rejects on Arm Away", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    hass.callService.mockRejectedValueOnce(new Error("boom"));
    const card = mountAlarmCard({ hass });

    const armBtn = Array.from(card.shadowRoot.querySelectorAll("button")).find((b) =>
      /Arm Away/i.test(b.textContent.trim()),
    );
    expect(armBtn).not.toBeUndefined();
    expect(() => armBtn.click()).not.toThrow();

    // Let any async work settle before asserting on the spy.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_arm_away", {
      entity_id: ENTITY,
    });
  });
});

describe("verisure-owa-alarm-card banners and force-arm", () => {
  it("renders the refresh_failed banner when the attribute is true", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({ state: "disarmed", refreshFailed: true }),
        },
      }),
    });
    const banner = card.shadowRoot.querySelector(".stale-banner");
    expect(banner).not.toBeNull();
    expect(banner.textContent).toMatch(/Refresh/);
  });

  it("renders each arm_exception entry as a list item in the force section", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "disarmed",
            forceArmAvailable: true,
            armExceptions: ["Front Door", "Garage"],
          }),
        },
      }),
    });
    const items = card.shadowRoot.querySelectorAll(".sensor-list li");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe("Front Door");
    expect(items[1].textContent).toBe("Garage");
  });

  it("disarm button next to force-arm calls alarm_disarm when armed", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({ state: "armed_away", forceArmAvailable: true }),
      },
    });
    const card = mountAlarmCard({ hass });
    const disarmBtn = Array.from(card.shadowRoot.querySelectorAll("button")).find((b) =>
      /Disarm/i.test(b.textContent.trim()),
    );
    expect(disarmBtn).not.toBeUndefined();
    disarmBtn.click();
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
    });
  });
});

describe("verisure-owa-alarm-card refresh button", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("clicking refresh calls verisure_owa.refresh_alarm and toggles spinning class", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    hass.callService.mockResolvedValueOnce(undefined);
    const card = mountAlarmCard({ hass });
    const refreshBtn = card.shadowRoot.querySelector(".refresh-btn");
    refreshBtn.click();
    // Spinner is added synchronously
    expect(card.shadowRoot.querySelector(".refresh-btn").classList.contains("spinning")).toBe(true);
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "refresh_alarm", {
      entity_id: ENTITY,
    });
    // Drain microtasks + advance past the 2s clear timer
    await Promise.resolve();
    await Promise.resolve();
    vi.advanceTimersByTime(2001);
    expect(card.shadowRoot.querySelector(".refresh-btn")?.classList.contains("spinning")).toBe(
      false,
    );
  });
});

describe("verisure-owa-alarm-card PIN keypad", () => {
  function showPin(card) {
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Arm Away/i.test(b.textContent.trim()))
      .click();
  }

  it("typing digits then cancel-pin resets back to normal UI", () => {
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
    showPin(card);
    // Click the "1" key
    const oneKey = card.shadowRoot.querySelector('[data-key="1"]');
    oneKey.click();

    expect(card._pin).toBe("1");
    // Click backspace
    card.shadowRoot.querySelector('[data-key="del"]').click();

    expect(card._pin).toBe("");
    // Click cancel key
    card.shadowRoot.querySelector('[data-key="cancel"]').click();
    // After cancel, the keypad should be gone — normal arm buttons return.
    expect(card.shadowRoot.querySelector('[data-key="1"]')).toBeNull();
  });

  it("confirm-pin submits alarm_disarm with the entered code and resets state", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const card = mountAlarmCard({ hass });
    // Open PIN entry by clicking Disarm
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Disarm/i.test(b.textContent.trim()))
      .click();
    // Type "1234"
    ["1", "2", "3", "4"].forEach((n) => card.shadowRoot.querySelector(`[data-key="${n}"]`).click());
    // Click confirm
    card.shadowRoot.querySelector('[data-action="confirm-pin"]').click();
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "1234",
    });

    expect(card._pin).toBe("");

    expect(card._uiState).toBe("normal");
  });

  it("PIN input strips non-digits on input event", () => {
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
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Arm Away/i.test(b.textContent.trim()))
      .click();
    const pinInput = card.shadowRoot.getElementById("pin-keyboard-input");
    pinInput.value = "12a3";
    pinInput.dispatchEvent(new Event("input", { bubbles: true }));
    expect(pinInput.value).toBe("123");

    expect(card._pin).toBe("123");
  });

  it("Enter on the PIN input submits the pending action", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const card = mountAlarmCard({ hass });
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Disarm/i.test(b.textContent.trim()))
      .click();
    const pinInput = card.shadowRoot.getElementById("pin-keyboard-input");
    pinInput.value = "9999";
    pinInput.dispatchEvent(new Event("input", { bubbles: true }));
    pinInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "9999",
    });
  });

  it("Escape on the PIN input resets back to normal UI", () => {
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
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Arm Away/i.test(b.textContent.trim()))
      .click();
    const pinInput = card.shadowRoot.getElementById("pin-keyboard-input");
    pinInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    expect(card._uiState).toBe("normal");
  });

  it("text-code input Enter submits the pending action and cancel-pin resets", () => {
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
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Disarm/i.test(b.textContent.trim()))
      .click();
    const codeInput = card.shadowRoot.getElementById("code-input");
    codeInput.value = "letmein";
    codeInput.dispatchEvent(new Event("input", { bubbles: true }));
    codeInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "letmein",
    });
  });

  it("clicking cancel button in the text-code section resets UI", () => {
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
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Disarm/i.test(b.textContent.trim()))
      .click();
    const cancelBtn = card.shadowRoot.querySelector('[data-action="cancel-pin"]');
    cancelBtn.click();

    expect(card._uiState).toBe("normal");
  });
});

describe("verisure-owa-alarm-card gesture (icon-wrap pointer events)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("a single tap on the icon-wrap dispatches hass-more-info via the default tap_action", () => {
    const card = mountAlarmCard({
      config: { tap_action: { action: "more-info" } },
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    let captured = null;
    card.addEventListener("hass-more-info", (e) => {
      captured = e.detail.entityId;
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(captured).toBe(ENTITY);
  });

  it("a hold (>500ms) on the icon-wrap fires hold_action (navigate)", () => {
    const card = mountAlarmCard({
      config: {
        hold_action: { action: "navigate", navigation_path: "/lovelace/0" },
      },
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    const pushSpy = vi.spyOn(window.history, "pushState");
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    expect(pushSpy).toHaveBeenCalledWith({}, "", "/lovelace/0");
    pushSpy.mockRestore();
  });

  it("a double-tap on the icon-wrap fires double_tap_action (perform-action)", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: {
        double_tap_action: {
          action: "perform-action",
          perform_action: "light.turn_on",
          data: { entity_id: "light.kitchen" },
        },
      },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    // Double-tap fires immediately on the second pointerup — no timer needed.
    expect(hass.callService).toHaveBeenCalledWith("light", "turn_on", {
      entity_id: "light.kitchen",
    });
  });

  it("pointermove beyond 10 px cancels the long-press timer", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { hold_action: { action: "more-info" } },
      hass,
    });
    let captured = false;
    card.addEventListener("hass-more-info", () => {
      captured = true;
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(
      new PointerEvent("pointermove", { bubbles: true, clientX: 20, clientY: 0 }),
    );
    vi.advanceTimersByTime(600);
    expect(captured).toBe(false);
  });

  it("pointercancel after pointerdown clears the long-press timer", () => {
    const card = mountAlarmCard({
      config: { hold_action: { action: "more-info" } },
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    let captured = false;
    card.addEventListener("hass-more-info", () => {
      captured = true;
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true }));
    vi.advanceTimersByTime(600);
    expect(captured).toBe(false);
  });

  it("hold-fired click is swallowed via stopImmediatePropagation", () => {
    const card = mountAlarmCard({
      config: { hold_action: { action: "more-info" } },
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(600);
    // Hold fired — subsequent click event must be swallowed (no exception).
    expect(() => iconWrap.dispatchEvent(new MouseEvent("click", { bubbles: true }))).not.toThrow();
  });

  it("arm_or_disarm gesture on a disarmed entity calls the default arm service", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "arm_or_disarm" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_arm_away", {
      entity_id: ENTITY,
    });
  });

  it("arm_or_disarm gesture on an armed entity calls alarm_disarm", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "arm_or_disarm" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
    });
  });

  it("arm_or_disarm gesture on disarmed with code_arm_required starts PIN entry for arm", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "disarmed",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "arm_or_disarm", arm_state: "arm_away" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(hass.callService).not.toHaveBeenCalled();

    expect(card._uiState).toBe("pin");
  });

  it("perform-action with no perform_action string is a no-op (no service call)", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "perform-action" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("navigate without a path is a no-op", () => {
    const card = mountAlarmCard({
      config: { tap_action: { action: "navigate" } },
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    const pushSpy = vi.spyOn(window.history, "pushState");
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(pushSpy).not.toHaveBeenCalled();
    pushSpy.mockRestore();
  });

  it("arm_or_disarm gesture with a configured code starts PIN entry instead of calling the service", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "arm_or_disarm" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    // No callService — PIN entry is shown instead.
    expect(hass.callService).not.toHaveBeenCalled();

    expect(card._uiState).toBe("pin");
  });
});

describe("verisure-owa-alarm-card color overrides", () => {
  it("config.colors override is reflected in the top-bar accent color", () => {
    const card = mountAlarmCard({
      config: { colors: { disarmed: "#abcdef" } },
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      }),
    });
    // The accent color is interpolated into the inline <style> block.
    expect(card.shadowRoot.innerHTML).toContain("#abcdef");
  });

  it("falls back to the default disabled color when state is not in STATE_CFG", () => {
    // happy-dom allows arbitrary state strings — the card's STATE_CFG fallback
    // path uses `var(--disabled-color,#9E9E9E)`.
    const card = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: {
            state: "totally-bogus",
            attributes: { friendly_name: "X", supported_features: 0 },
          },
        },
      }),
    });
    expect(card.shadowRoot.innerHTML).toContain("--disabled-color");
  });
});

describe("verisure-owa-alarm-card lifecycle and statics", () => {
  it("getCardSize returns 6 during PIN entry, 5 for force-arm, 3 by default", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({ hass });
    expect(card.getCardSize()).toBe(3);

    const forceCard = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({ state: "disarmed", forceArmAvailable: true }),
        },
      }),
    });
    expect(forceCard.getCardSize()).toBe(5);

    const pinCard = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "disarmed",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
    });
    Array.from(pinCard.shadowRoot.querySelectorAll("button"))
      .find((b) => /Arm Away/i.test(b.textContent.trim()))
      .click();
    expect(pinCard.getCardSize()).toBe(6);
  });

  it("getConfigElement returns the matching editor element", () => {
    const ctor = customElements.get("verisure-owa-alarm-card");
    const el = ctor.getConfigElement();
    expect(el.tagName.toLowerCase()).toBe("verisure-owa-alarm-card-editor");
  });

  it("getStubConfig picks the first alarm_control_panel entity", () => {
    const ctor = customElements.get("verisure-owa-alarm-card");
    const hass = makeHass({
      states: {
        "light.x": { state: "on", attributes: {} },
        "alarm_control_panel.a": makeAlarmEntity(),
      },
    });
    expect(ctor.getStubConfig(hass).entity).toBe("alarm_control_panel.a");
  });

  it("getStubConfig returns empty entity when no alarm panels are loaded", () => {
    const ctor = customElements.get("verisure-owa-alarm-card");
    expect(ctor.getStubConfig(makeHass()).entity).toBe("");
  });

  it("disconnectedCallback zeroes pending PIN state and removes gesture listeners", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "disarmed",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
    });
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Arm Away/i.test(b.textContent.trim()))
      .click();

    expect(card._uiState).toBe("pin");
    card.remove();

    expect(card._uiState).toBe("normal");

    expect(card._pin).toBe("");

    expect(card._gestureCleanup).toBeNull();
  });

  it("reconnecting the card after detach re-attaches gesture listeners on next hass update", () => {
    // PR #475 (b77986f): when the dashboard tears the card off the DOM and
    // re-mounts it, gesture listeners must come back. disconnectedCallback
    // wipes _lastKey so the next `set hass` after re-mount sees a changed
    // key and runs _render() — which calls attachGesture again.
    vi.useFakeTimers();
    try {
      const hass = makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      });
      const card = mountAlarmCard({
        config: { hold_action: { action: "more-info" } },
        hass,
      });
      // Detach (e.g. dashboard tab switch / editor open).
      document.body.removeChild(card);

      expect(card._gestureCleanup).toBeNull();
      // Re-attach and push fresh hass — the card must re-render gestures.
      document.body.appendChild(card);
      card.hass = hass;
      let captured = false;
      card.addEventListener("hass-more-info", () => {
        captured = true;
      });
      const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
      iconWrap.dispatchEvent(
        new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
      );
      vi.advanceTimersByTime(600);
      expect(captured).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("re-rendering during PIN entry returns to normal UI when entity arms", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "disarmed",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
    });
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Arm Away/i.test(b.textContent.trim()))
      .click();

    expect(card._uiState).toBe("pin");
    card.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });

    expect(card._uiState).toBe("normal");
  });
});

describe("verisure-owa-alarm-card config.states arm-button filter", () => {
  // PR #475 (4085f1c): when the user adds `states: [...]` to their card
  // config, only those arm buttons render. The filter is intersected with
  // `supported_features` — the card never offers a button the entity hasn't
  // advertised, even if the user lists it.

  function armButtonKeys(card) {
    return Array.from(card.shadowRoot.querySelectorAll(".btn-arm[data-action]")).map(
      (b) => b.dataset.action,
    );
  }

  it("renders only the listed arm modes when config.states is set", () => {
    const card = mountAlarmCard({
      config: { states: ["arm_away", "arm_night"] },
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      }),
    });
    expect(armButtonKeys(card)).toEqual(["arm_away", "arm_night"]);
  });

  it("renders all supported modes when config.states is omitted (default behavior)", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      }),
    });
    // All 5 features are supported by the default fixture entity.
    expect(armButtonKeys(card)).toEqual([
      "arm_away",
      "arm_home",
      "arm_night",
      "arm_vacation",
      "arm_custom_bypass",
    ]);
  });

  it("renders no arm buttons when config.states intersects empty with supported_features", () => {
    // Entity only supports ARM_AWAY (feature 2); user listed only arm_night.
    const card = mountAlarmCard({
      config: { states: ["arm_night"] },
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({ state: "disarmed", supportedFeatures: 2 }),
        },
      }),
    });
    expect(armButtonKeys(card)).toEqual([]);
  });

  it("renders no arm buttons when config.states is the empty array", () => {
    const card = mountAlarmCard({
      config: { states: [] },
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      }),
    });
    expect(armButtonKeys(card)).toEqual([]);
  });

  it("updates the visible buttons when a fresh setConfig narrows the states list", () => {
    // setConfig resets _lastKey so the next state push triggers a fresh
    // render with the new states filter.
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({ hass });
    expect(armButtonKeys(card).length).toBe(5);
    card.setConfig({
      type: "custom:verisure-owa-alarm-card",
      entity: ENTITY,
      states: ["arm_home"],
    });
    expect(armButtonKeys(card)).toEqual(["arm_home"]);
  });
});

describe("verisure-owa-alarm-card arm_or_disarm gesture respects config.states", () => {
  // PR #475 (6be6983): when the user hides arm_away via states: [...], the
  // hold gesture's arm_or_disarm fallback default must come from the
  // visible subset — not the global ARM_ACTIONS[0] (arm_away). Otherwise
  // the hold gesture calls a service for a button the user can't see.

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("hold gesture with arm_or_disarm and states=['arm_night'] calls alarm_arm_night", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: {
        states: ["arm_night"],
        hold_action: { action: "arm_or_disarm" },
      },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_arm_night", {
      entity_id: ENTITY,
    });
  });

  it("explicit arm_state in the gesture wins over the states-derived default", () => {
    // The user's explicit arm_state must be honored even if it isn't in the
    // states filter — that's the same UX as setting it in the editor.
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: {
        states: ["arm_night"],
        hold_action: { action: "arm_or_disarm", arm_state: "arm_home" },
      },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_arm_home", {
      entity_id: ENTITY,
    });
  });
});
