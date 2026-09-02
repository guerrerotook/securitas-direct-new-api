import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
// The chip/badge live in their own module (a separate Lovelace resource in
// production); import it so those elements are defined under test.
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

const ENTITY = "alarm_control_panel.test";

describe("verisure-owa-alarm-badge", () => {
  it("registers", () => {
    expect(customElements.get("verisure-owa-alarm-badge")).toBeDefined();
  });

  it("renders a standard HA badge with the default state content and icon", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    document.body.appendChild(badge);
    const html = badge.shadowRoot.innerHTML;
    expect(html).toContain("mdi:shield-lock");
    expect(html).toContain("<ha-icon");
    expect(badge.shadowRoot.querySelector("ha-badge").getAttribute("label")).toBeNull();
    const stateDisplay = badge.shadowRoot.getElementById("badge-state");
    expect(stateDisplay.stateObj.state).toBe("armed_away");
    expect(stateDisplay.name).toBe("Test Alarm");
  });

  it("renders the shield-off-outline icon and native state content for unavailable", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "unavailable" }) },
    });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-off-outline");
    expect(badge.shadowRoot.getElementById("badge-state").stateObj.state).toBe("unavailable");
  });

  it("renders an error badge when the entity is missing", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({ states: {} });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-alert");
    expect(badge.shadowRoot.querySelector("ha-badge").getAttribute("label")).toBe(ENTITY);
    expect(badge.shadowRoot.textContent).toContain("Unavailable");
  });

  it("keeps the state text and switches to an alert icon for an arming exception", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY, name: "Entrance", show_name: true });
    badge.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "disarmed",
          armExceptionActive: true,
          armExceptions: ["Kitchen"],
        }),
      },
    });
    document.body.appendChild(badge);

    expect(badge.shadowRoot.innerHTML).toContain("mdi:alert");
    expect(badge.shadowRoot.querySelector("ha-badge").getAttribute("label")).toBe("Entrance");
    expect(badge.shadowRoot.getElementById("badge-state").stateObj.state).toBe("disarmed");
  });

  it("escapes a configured badge name", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({
      entity: ENTITY,
      name: 'Alarm <img src=x onerror="bad">',
      show_name: true,
    });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    const rendered = badge.shadowRoot.querySelector("ha-badge").getAttribute("label");
    expect(rendered).toBe('Alarm <img src=x onerror="bad">');
    expect(badge.shadowRoot.querySelector("img")).toBeNull();
  });

  it("supports the standard name, state and icon visibility options", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({
      entity: ENTITY,
      name: "Entrance",
      show_name: true,
      show_state: false,
      show_icon: false,
    });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    expect(badge.shadowRoot.querySelector("ha-icon")).toBeNull();
    expect(badge.shadowRoot.getElementById("badge-state")).toBeNull();
    expect(badge.shadowRoot.textContent).toContain("Entrance");
  });

  it("uses a configured icon without allowing attribute injection", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY, icon: 'mdi:shield" data-bad="true' });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    const icon = badge.shadowRoot.querySelector("ha-icon");
    expect(icon.getAttribute("icon")).toBe('mdi:shield" data-bad="true');
    expect(icon.hasAttribute("data-bad")).toBe(false);
  });

  it("forwards configured state content and time format to state-display", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({
      entity: ENTITY,
      state_content: ["state", "arm_exceptions"],
      time_format: "24",
    });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    const stateDisplay = badge.shadowRoot.getElementById("badge-state");
    expect(stateDisplay.content).toEqual(["state", "arm_exceptions"]);
    expect(stateDisplay.timeFormat).toBe("24");
  });

  it("resolves structured entity-name content through Home Assistant", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    const formatEntityName = vi.fn(() => "Front Door Alarm");
    badge.setConfig({
      entity: ENTITY,
      name: [{ type: "area" }, { type: "entity" }],
      show_name: true,
    });
    badge.hass = makeHass({
      formatEntityName,
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    expect(formatEntityName).toHaveBeenCalled();
    expect(badge.shadowRoot.querySelector("ha-badge").getAttribute("label")).toBe(
      "Front Door Alarm",
    );
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

  it("renders the warning alert icon for a non-forceable arming exception", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "disarmed",
          armExceptionActive: true,
          forceArmAvailable: false,
        }),
      },
    });
    document.body.appendChild(chip);
    expect(chip.shadowRoot.innerHTML).toContain("mdi:alert");
  });

  it("throws when setConfig is called without an entity", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    expect(() => chip.setConfig({})).toThrow(/entity/i);
  });

  it("renders the shield-alert icon when the entity is missing", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({ states: {} });
    document.body.appendChild(chip);
    expect(chip.shadowRoot.innerHTML).toContain("mdi:shield-alert");
  });

  it("supports the `set config` alias for setConfig", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.config = { entity: ENTITY };
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(chip);
    expect(chip.shadowRoot.innerHTML).toContain("mdi:shield-off-outline");
  });

  it("getCardSize returns 1", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    expect(chip.getCardSize()).toBe(1);
  });
});

describe("verisure-owa-alarm-badge dialog and overlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  function mountBadge({ config = {}, hass } = {}) {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY, ...config });
    badge.hass =
      hass ||
      makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      });
    document.body.appendChild(badge);
    return badge;
  }

  it("a tap asks Home Assistant to open the native More Info dialog", () => {
    const badge = mountBadge();
    const moreInfoCalls = vi.fn();
    badge.addEventListener("hass-more-info", moreInfoCalls);
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(moreInfoCalls).toHaveBeenCalledOnce();
    expect(moreInfoCalls.mock.calls[0][0].detail).toEqual({ entityId: ENTITY });
    expect(document.body.querySelector("securitas-alarm-card")).toBeNull();
  });

  it("a tap on the badge stops the native click event from bubbling to parents", () => {
    // When the badge sits inside a parent (e.g. an HA tile-card wrapper or a
    // dashboard view that has its own tap_action default of `more-info`), the
    // browser's native click event must NOT bubble past the badge — otherwise
    // a parent action can open a second More Info dialog.
    const parent = document.createElement("div");
    document.body.appendChild(parent);
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    parent.appendChild(badge);
    const parentClicks = vi.fn();
    parent.addEventListener("click", parentClicks);

    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    // Native click event follows pointerup in a real browser; jsdom doesn't
    // synthesise it, so dispatch one explicitly.
    badgeEl.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    vi.advanceTimersByTime(301);

    expect(parentClicks).not.toHaveBeenCalled();
  });

  it("a long-press with arm_or_disarm + code opens the PIN overlay", () => {
    const badge = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "armed_away",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    // The badge PIN overlay is attached to document.body with #badge-pin-input.
    const overlayInput = document.querySelector("#badge-pin-input");
    expect(overlayInput).not.toBeNull();
  });

  it("the PIN overlay submits alarm_disarm when Confirm is clicked", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const badge = mountBadge({
      hass,
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    // Type "1" via keypad
    document.querySelector('[data-badge-key="1"]').click();
    document.querySelector('[data-badge-key="2"]').click();
    document.querySelector('[data-badge-key="3"]').click();
    document.querySelector("#badge-pin-confirm").click();
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "123",
    });
    // Overlay should be torn down
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("PIN overlay del key removes the last digit; cancel key closes", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const badge = mountBadge({
      hass,
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    document.querySelector('[data-badge-key="9"]').click();
    document.querySelector('[data-badge-key="9"]').click();
    document.querySelector('[data-badge-key="del"]').click();
    document.querySelector("#badge-pin-confirm").click();
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "9",
    });
    // Reopen and dismiss via cancel key — overlay must close, no service call.
    const newBadge = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "armed_away",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const newBadgeEl = newBadge.shadowRoot.getElementById("badge");
    newBadgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    document.querySelector('[data-badge-key="cancel"]').click();
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("PIN overlay text input event updates _pin and submit calls service with code", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "text",
        }),
      },
    });
    const badge = mountBadge({
      hass,
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    const input = document.querySelector("#badge-pin-input");
    input.value = "abc!";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    document.querySelector("#badge-pin-confirm").click();
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "abc!",
    });
  });

  it("PIN confirm with empty PIN is a no-op (early-return guard)", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const badge = mountBadge({
      hass,
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    document.querySelector("#badge-pin-confirm").click();
    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("PIN overlay text-format renders a text input (no keypad)", () => {
    const badge = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "armed_away",
            codeArmRequired: true,
            codeFormat: "text",
          }),
        },
      }),
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    expect(document.querySelector('[data-badge-key="1"]')).toBeNull();
    expect(document.querySelector("#badge-pin-input")).not.toBeNull();
  });

  it("PIN overlay Enter on the input submits; Escape closes", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "text",
        }),
      },
    });
    const badge = mountBadge({
      hass,
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    const input = document.querySelector("#badge-pin-input");
    input.value = "secret";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(hass.callService).toHaveBeenCalledWith("alarm_control_panel", "alarm_disarm", {
      entity_id: ENTITY,
      code: "secret",
    });
    // Now open a fresh overlay and dismiss with Escape.
    const badge2 = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "armed_away",
            codeArmRequired: true,
            codeFormat: "text",
          }),
        },
      }),
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl2 = badge2.shadowRoot.getElementById("badge");
    badgeEl2.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    const input2 = document.querySelector("#badge-pin-input");
    input2.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("PIN overlay Cancel button closes without a service call", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    const badge = mountBadge({
      hass,
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    document.querySelector("#badge-pin-cancel").click();
    expect(hass.callService).not.toHaveBeenCalled();
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("badge disconnect tears down the PIN overlay if one is open", () => {
    const badge = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "armed_away",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    expect(document.querySelector("#badge-pin-input")).not.toBeNull();
    badge.remove();
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("badge skips re-render when neither state nor force_arm_available change", () => {
    const badge = mountBadge();
    const firstHtml = badge.shadowRoot.innerHTML;
    const firstStateDisplay = badge.shadowRoot.getElementById("badge-state");
    const updatedEntity = makeAlarmEntity({ state: "disarmed" });
    updatedEntity.attributes.arm_exceptions = ["Kitchen"];
    // Same hass — identity key matches, no rerender.
    badge.hass = makeHass({
      states: { [ENTITY]: updatedEntity },
    });
    expect(badge.shadowRoot.innerHTML).toBe(firstHtml);
    expect(badge.shadowRoot.getElementById("badge-state")).toBe(firstStateDisplay);
    expect(firstStateDisplay.stateObj.attributes.arm_exceptions).toEqual(["Kitchen"]);
  });

  it("clicking outside the PIN overlay closes it (transparent-area dismissal)", () => {
    const badge = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: makeAlarmEntity({
            state: "armed_away",
            codeArmRequired: true,
            codeFormat: "number",
          }),
        },
      }),
      config: { hold_action: { action: "arm_or_disarm" } },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    const pinInput = document.querySelector("#badge-pin-input");
    expect(pinInput).not.toBeNull();
    // Walk up to the outer overlay div.
    const overlay = pinInput.closest("div").parentElement;
    overlay.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("badge exposes the standard defaults, stub config and visual editor", () => {
    const badge = mountBadge();
    expect(badge.getCardSize()).toBe(1);
    const ctor = customElements.get("verisure-owa-alarm-badge");
    const editor = ctor.getConfigElement();
    expect(editor.tagName.toLowerCase()).toBe("verisure-owa-alarm-card-editor");
    expect(ctor.getDefaultConfig()).toEqual({
      show_name: false,
      show_state: true,
      show_icon: true,
    });
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    expect(ctor.getStubConfig(hass).entity).toBe(ENTITY);
    expect(ctor.getStubConfig(makeHass()).entity).toBe("");
  });
});

describe("verisure-owa-alarm-chip dialog wiring", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("a tap on the chip asks HA to open native More Info", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(chip);
    const moreInfoCalls = vi.fn();
    chip.addEventListener("hass-more-info", moreInfoCalls);
    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    chipEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(moreInfoCalls).toHaveBeenCalledOnce();
    expect(moreInfoCalls.mock.calls[0][0].detail).toEqual({ entityId: ENTITY });
  });

  it("a tap on the chip stops the native click event from bubbling to parents", () => {
    // Same concern as the badge: when the chip is placed inside a wrapper
    // (mushroom chips card, generic container with its own tap handler, etc.),
    // the native click must not escape and trigger the parent's tap_action.
    const parent = document.createElement("div");
    document.body.appendChild(parent);
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    parent.appendChild(chip);
    const parentClicks = vi.fn();
    parent.addEventListener("click", parentClicks);

    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    chipEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    chipEl.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    vi.advanceTimersByTime(301);

    expect(parentClicks).not.toHaveBeenCalled();
  });

  it("setting hass before setConfig is a no-op (renders only after config arrives)", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    expect(chip.shadowRoot.innerHTML).toBe("");
    chip.setConfig({ entity: ENTITY });
    document.body.appendChild(chip);
    expect(chip.shadowRoot.querySelector(".chip")).not.toBeNull();
  });

  it("re-rendering the chip is skipped when state hasn't changed (identity-key cache)", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    chip.hass = hass;
    document.body.appendChild(chip);
    const firstChipEl = chip.shadowRoot.getElementById("chip");
    // Same key — should NOT re-render.
    chip.hass = hass;
    const secondChipEl = chip.shadowRoot.getElementById("chip");
    expect(secondChipEl).toBe(firstChipEl);
  });

  it("chip with force_arm_available renders the warning alert icon and re-renders on change", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({ state: "disarmed", forceArmAvailable: true }),
      },
    });
    document.body.appendChild(chip);
    expect(chip.shadowRoot.innerHTML).toContain("mdi:alert");
    // Toggle force_arm_available off — chip should re-render to the regular icon.
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    expect(chip.shadowRoot.innerHTML).toContain("mdi:shield-off-outline");
  });

  it("a long-press on the chip with arm_or_disarm + code opens the PIN overlay", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({
      entity: ENTITY,
      hold_action: { action: "arm_or_disarm" },
    });
    chip.hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    document.body.appendChild(chip);
    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    expect(document.querySelector("#badge-pin-input")).not.toBeNull();
  });
});
