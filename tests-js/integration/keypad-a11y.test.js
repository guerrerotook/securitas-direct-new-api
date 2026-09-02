import { describe, it, expect, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
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
  afterEach(() => {
    document.body.innerHTML = "";
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
});
