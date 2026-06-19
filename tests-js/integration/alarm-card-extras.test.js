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

  it("renders a shield-lock icon when armed_away", () => {
    // The badge intentionally renders only an icon — not state text — so we
    // assert on the per-state icon mapping from STATE_CFG (armed_away ->
    // mdi:shield-lock) instead of the original "Armed Away" text assertion.
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    document.body.appendChild(badge);
    const html = badge.shadowRoot.innerHTML;
    expect(html).toContain("mdi:shield-lock");
    expect(html).toContain("<ha-icon");
  });

  it("renders the shield-off-outline icon for unavailable state", () => {
    // Same reasoning as above: badge has no text rendering. The STATE_CFG
    // entry for unavailable maps to mdi:shield-off-outline.
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "unavailable" }) },
    });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-off-outline");
  });

  it("renders the error shield-alert icon when the entity is missing", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({ states: {} });
    document.body.appendChild(badge);
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-alert");
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

  it("a tap opens the dialog (default tap_action=more-info)", () => {
    const badge = mountBadge();
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    // The dialog mounts a verisure-owa-alarm-card under document.body, inside
    // an overlay div.
    const dialogCard = document.body.querySelector("securitas-alarm-card");
    expect(dialogCard).not.toBeNull();
  });

  it("clicking the alarm-card icon inside the popup must NOT open HA's more-info dialog (default-tap config)", () => {
    // User bug report: when our badge's popup is open and the user clicks the
    // big shield icon in the embedded alarm-card, HA's standard more-info
    // dialog appears. The embedded card's tap_action default is `none`, so
    // tapping the icon should be a no-op. Listen on document for hass-more-info
    // (the event HA's <home-assistant> root would catch to open the dialog).
    const badge = mountBadge();
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);

    const popupCard = document.body.querySelector("securitas-alarm-card");
    expect(popupCard).not.toBeNull();

    const moreInfoCalls = vi.fn();
    document.addEventListener("hass-more-info", moreInfoCalls);

    const iconWrap = popupCard.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    iconWrap.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    vi.advanceTimersByTime(301);

    document.removeEventListener("hass-more-info", moreInfoCalls);
    expect(moreInfoCalls).not.toHaveBeenCalled();
  });

  it("clicking the alarm-card icon inside the popup must NOT open HA's dialog when badge tap_action is more-info", () => {
    // The badge's editor defaults tap_action to `more-info` (which means
    // "open our popup" in badge context). That same config is passed
    // wholesale to the popup's inner alarm-card via setConfig(this._config) —
    // but in the alarm-card context, `more-info` means "open HA's dialog".
    // So a user who configures their badge with the default tap action
    // and then clicks the icon inside the popup gets HA's dialog. Bug.
    const badge = mountBadge({ config: { tap_action: { action: "more-info" } } });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);

    const popupCard = document.body.querySelector("securitas-alarm-card");
    expect(popupCard).not.toBeNull();

    const moreInfoCalls = vi.fn();
    document.addEventListener("hass-more-info", moreInfoCalls);

    const iconWrap = popupCard.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    iconWrap.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    vi.advanceTimersByTime(301);

    document.removeEventListener("hass-more-info", moreInfoCalls);
    expect(moreInfoCalls).not.toHaveBeenCalled();
  });

  it("a tap on the badge stops the native click event from bubbling to parents", () => {
    // When the badge sits inside a parent (e.g. an HA tile-card wrapper or a
    // dashboard view that has its own tap_action default of `more-info`), the
    // browser's native click event must NOT bubble past the badge — otherwise
    // the user sees BOTH our custom popup AND the standard HA more-info dialog.
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

  it("closing the dialog via the close button removes the overlay", () => {
    const badge = mountBadge();
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    const dialogCard = document.body.querySelector("securitas-alarm-card");
    expect(dialogCard).not.toBeNull();
    // The close button is the first button inside the overlay's content wrapper.
    const closeBtn = dialogCard.parentElement.querySelector("button");
    closeBtn.click();
    expect(document.body.querySelector("securitas-alarm-card")).toBeNull();
  });

  it("re-entering the dialog is a no-op while one is already open", () => {
    const badge = mountBadge();
    const badgeEl = badge.shadowRoot.getElementById("badge");
    // Open dialog
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    // Try to open again — handler should bail out due to _dialogOpen guard.
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(document.body.querySelectorAll("securitas-alarm-card").length).toBe(1);
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

  it("badge dialog wires up a connection 'disconnected' listener and unsubscribes on close", () => {
    let unsubCalled = false;
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      connection: {
        addEventListener: vi.fn(() => () => {
          unsubCalled = true;
        }),
      },
    });
    const badge = mountBadge({ hass });
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(hass.connection.addEventListener).toHaveBeenCalledWith(
      "disconnected",
      expect.any(Function),
    );
    // Closing via the close button should call the unsub fn.
    const dialogCard = document.body.querySelector("securitas-alarm-card");
    const closeBtn = dialogCard.parentElement.querySelector("button");
    closeBtn.click();
    expect(unsubCalled).toBe(true);
  });

  it("badge skips re-render when neither state nor force_arm_available change", () => {
    const badge = mountBadge();
    const firstHtml = badge.shadowRoot.innerHTML;
    // Same hass — identity key matches, no rerender.
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    expect(badge.shadowRoot.innerHTML).toBe(firstHtml);
  });

  it("clicking outside the dialog overlay closes it (transparent-area dismissal)", () => {
    const badge = mountBadge();
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    const dialogCard = document.body.querySelector("securitas-alarm-card");
    expect(dialogCard).not.toBeNull();
    // The overlay is the dialogCard's grandparent (overlay → content → card).
    const overlay = dialogCard.parentElement.parentElement;
    // Click event targets the overlay itself (not its children).
    overlay.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(document.body.querySelector("securitas-alarm-card")).toBeNull();
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

  it("badge forwards subsequent hass updates to the open dialog card", () => {
    const badge = mountBadge();
    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    badgeEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    const dialogCard = document.body.querySelector("securitas-alarm-card");
    badge.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_home" }) },
    });
    expect(dialogCard.shadowRoot.innerHTML).toContain("Armed Home");
  });

  it("badge getCardSize returns 1; getConfigElement returns the editor", () => {
    const badge = mountBadge();
    expect(badge.getCardSize()).toBe(1);
    const ctor = customElements.get("verisure-owa-alarm-badge");
    const editor = ctor.getConfigElement();
    expect(editor.tagName.toLowerCase()).toBe("verisure-owa-alarm-card-editor");
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

  it("a tap on the chip opens the dialog", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(chip);
    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    chipEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    expect(document.body.querySelector("securitas-alarm-card")).not.toBeNull();
  });

  it("clicking the alarm-card icon inside the chip's popup must NOT open HA's dialog", () => {
    // Same bug as the badge: the chip's tap_action (default `more-info`) is
    // passed wholesale to the embedded alarm-card via _openDialog. In the
    // alarm-card context, `more-info` dispatches `hass-more-info` and opens
    // HA's standard dialog on top of our popup. The chip delegates to the
    // badge's _openDialog so the same gesture-stripping fix protects it.
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY, tap_action: { action: "more-info" } });
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(chip);
    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    chipEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);

    const popupCard = document.body.querySelector("securitas-alarm-card");
    expect(popupCard).not.toBeNull();

    const moreInfoCalls = vi.fn();
    document.addEventListener("hass-more-info", moreInfoCalls);

    const iconWrap = popupCard.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    iconWrap.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    vi.advanceTimersByTime(301);

    document.removeEventListener("hass-more-info", moreInfoCalls);
    expect(moreInfoCalls).not.toHaveBeenCalled();
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

  it("chip forwards subsequent hass updates to the open dialog card", () => {
    const chip = document.createElement("verisure-owa-alarm-chip");
    chip.setConfig({ entity: ENTITY });
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(chip);
    const chipEl = chip.shadowRoot.getElementById("chip");
    chipEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    chipEl.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    vi.advanceTimersByTime(301);
    const dialogCard = document.body.querySelector("securitas-alarm-card");
    expect(dialogCard).not.toBeNull();
    // Push a new hass with armed state — the dialog card should re-render to armed.
    chip.hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) },
    });
    expect(dialogCard.shadowRoot.innerHTML).toContain("Armed Away");
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
