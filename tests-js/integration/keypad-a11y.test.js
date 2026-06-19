import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

// End-to-end a11y: the PIN keypad's icon-only ✕/⌫ buttons must carry an
// accessible name, AND it must be localized. The i18n guard proves the source
// uses _t (not hardcoded) and that the keys exist in every language; this test
// proves the aria-labels are actually PRESENT in the rendered DOM and resolve
// to the active language (the guard can't see a missing/removed attribute).

const ENTITY = "alarm_control_panel.test";

const esArmedNumeric = () =>
  makeHass({
    language: "es",
    states: {
      [ENTITY]: makeAlarmEntity({
        state: "armed_away",
        codeArmRequired: true,
        codeFormat: "number",
      }),
    },
  });

describe("PIN keypad accessible names are present and localized", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("badge keypad ✕/⌫ expose Spanish aria-labels", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY, hold_action: { action: "arm_or_disarm" } });
    badge.hass = esArmedNumeric();
    document.body.appendChild(badge);

    const badgeEl = badge.shadowRoot.getElementById("badge");
    badgeEl.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    vi.advanceTimersByTime(501); // long-press → arm_or_disarm → PIN entry

    const cancel = document.querySelector('[data-badge-key="cancel"]');
    const del = document.querySelector('[data-badge-key="del"]');
    expect(cancel?.getAttribute("aria-label")).toBe("Cancelar");
    expect(del?.getAttribute("aria-label")).toBe("Borrar");
  });

  it("card keypad ✕/⌫ expose Spanish aria-labels", () => {
    const card = document.createElement("verisure-owa-alarm-card");
    card.setConfig({ entity: ENTITY });
    card.hass = esArmedNumeric();
    document.body.appendChild(card);

    // Disarm requires a code → opens the numeric keypad.
    Array.from(card.shadowRoot.querySelectorAll("button"))
      .find((b) => /Desarmar/i.test(b.textContent.trim()))
      .click();

    const cancel = card.shadowRoot.querySelector('[data-key="cancel"]');
    const del = card.shadowRoot.querySelector('[data-key="del"]');
    expect(cancel?.getAttribute("aria-label")).toBe("Cancelar");
    expect(del?.getAttribute("aria-label")).toBe("Borrar");
  });

  it("badge popup close (✕) button exposes a Spanish aria-label", () => {
    const badge = document.createElement("verisure-owa-alarm-badge");
    badge.setConfig({ entity: ENTITY });
    badge.hass = makeHass({
      language: "es",
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    document.body.appendChild(badge);

    badge._openDialog(); // tap → more-info opens this popup

    const closeBtn = [...document.querySelectorAll("button")].find(
      (b) => b.getAttribute("aria-label") === "Cerrar",
    );
    expect(closeBtn).toBeTruthy();
    expect(closeBtn.title).toBe("Cerrar");
  });
});
