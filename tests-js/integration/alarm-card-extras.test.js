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
    const stateIcon = badge.shadowRoot.querySelector("ha-state-icon");
    expect(stateIcon.icon).toBe("mdi:shield-lock");
    expect(badge.shadowRoot.querySelector("ha-badge").label).toBeUndefined();
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
    expect(badge.shadowRoot.querySelector("ha-state-icon").icon).toBe("mdi:shield-off-outline");
    expect(badge.shadowRoot.getElementById("badge-state").stateObj.state).toBe("unavailable");
  });

  it("renders an error badge when the entity is missing", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({ states: {} });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-alert");
    expect(badge.shadowRoot.querySelector("ha-badge").label).toBe(ENTITY);
    expect(badge.shadowRoot.textContent).toContain("Unavailable");
  });

  it("re-renders locale-fallback text when hass.language is unset", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({ language: undefined, locale: { language: "en" }, states: {} });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.textContent).toContain("Unavailable");

    badge.hass = makeHass({ language: undefined, locale: { language: "es" }, states: {} });

    expect(badge.shadowRoot.textContent).toContain("No disponible");
    expect(badge.shadowRoot.textContent).not.toContain("Unavailable");
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
    expect(badge.shadowRoot.querySelector("ha-badge").label).toBe("Entrance");
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

    const rendered = badge.shadowRoot.querySelector("ha-badge").label;
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

    const icon = badge.shadowRoot.querySelector("ha-state-icon");
    expect(icon.icon).toBe('mdi:shield" data-bad="true');
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

  it("supports the native badge color setting", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY, color: "amber" });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    expect(badge.shadowRoot.querySelector("ha-badge").style.getPropertyValue("--badge-color")).toBe(
      "var(--amber-color)",
    );
  });

  it("applies editor config updates without waiting for another HA state update", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity() },
    });
    document.body.appendChild(badge);

    badge.setConfig({ entity: ENTITY, color: "amber", show_icon: false });

    expect(badge.shadowRoot.querySelector("ha-state-icon")).toBeNull();
    expect(badge.shadowRoot.querySelector("ha-badge").style.getPropertyValue("--badge-color")).toBe(
      "var(--amber-color)",
    );
  });

  it("supports the native show_entity_picture setting", () => {
    const entity = makeAlarmEntity();
    entity.attributes.entity_picture = "/local/alarm.png";
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY, show_entity_picture: true });
    badge.hass = makeHass({
      hassUrl: (path) => `https://example.test${path}`,
      states: { [ENTITY]: entity },
    });
    document.body.appendChild(badge);

    const picture = badge.shadowRoot.querySelector('img[slot="icon"]');
    expect(picture.src).toBe("https://example.test/local/alarm.png");
    expect(badge.shadowRoot.querySelector("ha-state-icon")).toBeNull();
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
    expect(badge.shadowRoot.querySelector("ha-badge").label).toBe("Front Door Alarm");
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

  it("does nothing on hold by default", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const badge = mountBadge({ hass });
    const moreInfoCalls = vi.fn();
    badge.addEventListener("hass-more-info", moreInfoCalls);
    const badgeEl = badge.shadowRoot.getElementById("badge");

    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);

    expect(moreInfoCalls).not.toHaveBeenCalled();
    expect(hass.callService).not.toHaveBeenCalled();
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });

  it("passes native Perform action data and target through Home Assistant", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const badge = mountBadge({
      hass,
      config: {
        hold_action: {
          action: "perform-action",
          perform_action: "alarm_control_panel.alarm_arm_home",
          data: { code: "1234" },
          target: { entity_id: ENTITY },
        },
      },
    });
    const badgeEl = badge.shadowRoot.getElementById("badge");

    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);

    expect(hass.callService).toHaveBeenCalledWith(
      "alarm_control_panel",
      "alarm_arm_home",
      { code: "1234" },
      { entity_id: ENTITY },
    );
  });

  it("reports a rejected native Perform action through Home Assistant", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    hass.callService.mockRejectedValueOnce(new Error("panel offline"));
    const badge = mountBadge({
      hass,
      config: {
        hold_action: {
          action: "perform-action",
          perform_action: "alarm_control_panel.alarm_arm_away",
          target: { entity_id: ENTITY },
        },
      },
    });
    const notification = vi.fn();
    badge.addEventListener("hass-notification", notification);
    const badgeEl = badge.shadowRoot.getElementById("badge");

    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);
    await Promise.resolve();
    await Promise.resolve();

    expect(notification).toHaveBeenCalledOnce();
    expect(notification.mock.calls[0][0].detail.message).toContain("panel offline");
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

  it("migrates Badge arm_or_disarm gestures to native More Info", () => {
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
      config: {
        hold_action: { action: "arm_or_disarm", arm_state: "arm_away" },
      },
    });
    const moreInfoCalls = vi.fn();
    badge.addEventListener("hass-more-info", moreInfoCalls);

    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);

    expect(badge._config.hold_action).toEqual({ action: "more-info" });
    expect(moreInfoCalls).toHaveBeenCalledOnce();
    expect(moreInfoCalls.mock.calls[0][0].detail).toEqual({ entityId: ENTITY });
    expect(hass.callService).not.toHaveBeenCalled();
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

  it("badge exposes the standard defaults, stub config and visual editor", async () => {
    const badge = mountBadge();
    expect(badge.getCardSize()).toBe(1);
    const ctor = customElements.get("verisure-owa-alarm-badge");
    const editor = await ctor.getConfigElement();
    expect(editor.tagName.toLowerCase()).toBe("verisure-owa-alarm-badge-editor");
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

  it("migrates Chip arm_or_disarm gestures to native More Info", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({
      entity: ENTITY,
      hold_action: { action: "arm_or_disarm", arm_state: "arm_away" },
    });
    const hass = makeHass({
      states: {
        [ENTITY]: makeAlarmEntity({
          state: "armed_away",
          codeArmRequired: true,
          codeFormat: "number",
        }),
      },
    });
    chip.hass = hass;
    document.body.appendChild(chip);
    const moreInfoCalls = vi.fn();
    chip.addEventListener("hass-more-info", moreInfoCalls);

    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501);

    expect(chip._config.hold_action).toEqual({ action: "more-info" });
    expect(moreInfoCalls).toHaveBeenCalledOnce();
    expect(moreInfoCalls.mock.calls[0][0].detail).toEqual({ entityId: ENTITY });
    expect(hass.callService).not.toHaveBeenCalled();
    expect(document.querySelector("#badge-pin-input")).toBeNull();
  });
});
