// Edge-case tests added to cover branches that Vitest 4 / v8-coverage 4 now
// count more accurately. Focuses on default/fallback branches the main suite
// always satisfied with explicit values (gesture defaults, language/name
// fallbacks, optional config keys, empty stub data, etc.).

import { describe, it, expect } from "vitest";
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

describe("alarm-card gesture defaults (no actions configured)", () => {
  it("renders + handles a pointerdown/up cycle when no gesture actions are set", () => {
    // Card has no tap_action / hold_action / double_tap_action — exercises the
    // `|| { action: "none" }` defaults in _render's gestureConfig and the
    // attachGesture(`|| { action: ... }`) defaults at the top of the helper.
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({ hass });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    expect(iconWrap).not.toBeNull();
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    // No service call should fire — defaults are { action: "none" }.
    expect(hass.callService).not.toHaveBeenCalled();
  });

  it("pointermove beyond 10px cancels a held press", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { hold_action: { action: "perform-action", perform_action: "x.y" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    // Move 20px — exceeds MOVE_PX (10) — cancels the hold timer.
    iconWrap.dispatchEvent(
      new PointerEvent("pointermove", { bubbles: true, clientX: 20, clientY: 0 }),
    );
    iconWrap.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, clientX: 20, clientY: 0 }),
    );
    // Hold was cancelled before its 500ms fire, so the hold_action's
    // perform-action service call must not have run.
    expect(hass.callService).not.toHaveBeenCalled();
  });
});

describe("alarm-card name + language fallbacks", () => {
  it("falls back to attributes.friendly_name when config.name is unset", () => {
    const card = mountAlarmCard({
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ state: "disarmed", friendlyName: "Front Door" }) },
      }),
    });
    expect(card.shadowRoot.innerHTML).toContain("Front Door");
  });

  it("falls back to entity_id when neither config.name nor friendly_name is set", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          state: "disarmed",
          attributes: { supported_features: 2 }, // no friendly_name
        },
      },
    });
    const card = mountAlarmCard({ hass });
    expect(card.shadowRoot.innerHTML).toContain(ENTITY);
  });

  it("renders without crashing when hass.language is unset", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
      language: undefined,
    });
    expect(() => mountAlarmCard({ hass })).not.toThrow();
  });

  it("falls back to STATE_CFG default when state is an unknown string", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          state: "weird_unknown_state",
          attributes: { supported_features: 2, friendly_name: "X" },
        },
      },
    });
    const card = mountAlarmCard({ hass });
    // No crash — the `STATE_CFG[state] || { icon, color }` fallback is what
    // we're exercising. The state label key falls through to the raw key.
    expect(card.shadowRoot.innerHTML).toContain("X");
  });
});

describe("alarm-card setConfig states fingerprint", () => {
  it("non-array states value collapses to empty fingerprint", () => {
    const card = mountAlarmCard({
      config: { states: "arm_away" }, // string, not array
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    expect(card._statesFP).toBe("");
  });

  it("array states value is joined into a comma fingerprint", () => {
    const card = mountAlarmCard({
      config: { states: ["arm_away", "arm_night"] },
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    expect(card._statesFP).toBe("arm_away,arm_night");
  });

  it("undefined states yields wildcard fingerprint '*'", () => {
    const card = mountAlarmCard({
      hass: makeHass({ states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) } }),
    });
    expect(card._statesFP).toBe("*");
  });
});

describe("alarm-card _render guards", () => {
  it("early-returns when hass is missing", () => {
    const el = document.createElement("verisure-owa-alarm-card");
    el.setConfig({ type: "custom:verisure-owa-alarm-card", entity: ENTITY });
    document.body.appendChild(el);
    // No hass set — setConfig's `if (this._hass)` guard skips _render(), and
    // _render itself short-circuits on the `!this._hass || !this._config` line.
    expect(el.shadowRoot.innerHTML).toBe("");
  });
});

describe("alarm-card badge fallbacks", () => {
  function mountBadge({ config = {}, hass = makeHass() } = {}) {
    const el = document.createElement("verisure-owa-alarm-badge");
    el.setConfig({ type: "custom:verisure-owa-alarm-badge", entity: ENTITY, ...config });
    el.hass = hass;
    document.body.appendChild(el);
    return el;
  }

  it("renders an error icon when the entity state is missing", () => {
    const badge = mountBadge({ hass: makeHass() });
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield-alert");
  });

  it("renders force-arm icon when force_arm_available is true", () => {
    const badge = mountBadge({
      hass: makeHass({
        states: { [ENTITY]: makeAlarmEntity({ forceArmAvailable: true }) },
      }),
    });
    expect(badge.shadowRoot.innerHTML).toContain("mdi:alert");
  });

  it("falls back to STATE_CFG default icon when state is unknown", () => {
    const badge = mountBadge({
      hass: makeHass({
        states: {
          [ENTITY]: {
            state: "weird",
            attributes: { supported_features: 2, force_arm_available: false },
          },
        },
      }),
    });
    expect(badge.shadowRoot.innerHTML).toContain("mdi:shield");
  });

  it("renders without crashing when hass.language is unset", () => {
    expect(() =>
      mountBadge({
        hass: makeHass({
          states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
          language: undefined,
        }),
      }),
    ).not.toThrow();
  });
});

describe("alarm-card chip fallbacks", () => {
  function mountChip({ config = {}, hass = makeHass() } = {}) {
    const el = document.createElement("verisure-owa-alarm-chip");
    el.setConfig({ type: "custom:verisure-owa-alarm-chip", entity: ENTITY, ...config });
    el.hass = hass;
    document.body.appendChild(el);
    return el;
  }

  it("falls back to STATE_CFG default icon when state is unknown", () => {
    const chip = mountChip({
      hass: makeHass({
        states: {
          [ENTITY]: {
            state: "weird",
            attributes: { supported_features: 2 },
          },
        },
      }),
    });
    expect(chip.shadowRoot.innerHTML).toContain("mdi:shield");
  });
});

describe("alarm-card executeAction null-guards", () => {
  it("tap_action: arm_or_disarm with no stateObj is a no-op (executeAction !stateObj guard)", () => {
    // Card mounted with a state, gesture wired. Then the entity state vanishes
    // mid-session before the tap fires — executeAction must early-return.
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "arm_or_disarm" } },
      hass,
    });
    // Remove the entity from hass.states *without* re-rendering the card
    // (assigning a new hass would re-render and re-attach gestures).
    delete hass.states[ENTITY];
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    return new Promise((r) => setTimeout(r, 350)).then(() => {
      expect(hass.callService).not.toHaveBeenCalled();
    });
  });

  it("arm_or_disarm with an unknown arm_state is a no-op (armDef not found guard)", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "arm_or_disarm", arm_state: "arm_unknown_xyz" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    return new Promise((r) => setTimeout(r, 350)).then(() => {
      expect(hass.callService).not.toHaveBeenCalled();
    });
  });

  it("perform-action with no dot in perform_action string is silently dropped", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    });
    const card = mountAlarmCard({
      config: { tap_action: { action: "perform-action", perform_action: "no_dot_here" } },
      hass,
    });
    const iconWrap = card.shadowRoot.querySelector(".icon-wrap");
    iconWrap.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    iconWrap.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, clientX: 0, clientY: 0 }),
    );
    return new Promise((r) => setTimeout(r, 350)).then(() => {
      expect(hass.callService).not.toHaveBeenCalled();
    });
  });
});

describe("alarm-card editor default-action coverage", () => {
  function mountEditor({ config = {}, hass = makeHass() } = {}) {
    const el = document.createElement("verisure-owa-alarm-card-editor");
    el.setConfig({ type: "custom:verisure-owa-alarm-card", entity: ENTITY, ...config });
    el.hass = hass;
    document.body.appendChild(el);
    return el;
  }

  it("editor handles an entity without arm_actions supported_features = 0", () => {
    // Forces `supported.length > 0` to be false → the empty-supported fallback
    // branch in _filteredArmActions / the editor's dropdown calculation.
    const hass = makeHass({
      states: { [ENTITY]: makeAlarmEntity({ supportedFeatures: 0 }) },
    });
    const editor = mountEditor({ hass });
    expect(editor.shadowRoot.innerHTML).not.toBe("");
  });
});
