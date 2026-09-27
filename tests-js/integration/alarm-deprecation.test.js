import { describe, it, expect, vi } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import "../../custom_components/securitas/www/verisure-owa-alarm-chip.js";
import "../../custom_components/securitas/www/verisure-owa-alarm-badge-editor.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

const ENTITY = "alarm_control_panel.test";

function hassWithAlarm(overrides = {}) {
  return makeHass({
    states: { [ENTITY]: makeAlarmEntity({ state: "disarmed" }) },
    ...overrides,
  });
}

function mount(tag, hass = hassWithAlarm()) {
  const el = document.createElement(tag);
  el.setConfig({ type: `custom:${tag}`, entity: ENTITY });
  el.hass = hass;
  document.body.appendChild(el);
  return el;
}

function deprecationCalls(hass) {
  return hass.callWS.mock.calls
    .map(([msg]) => msg)
    .filter((msg) => msg.type === "verisure_owa/deprecated_element");
}

describe("alarm card deprecation notice", () => {
  it("shows a notice pointing to the native replacement", () => {
    const card = mount("verisure-owa-alarm-card");
    const notice = card.shadowRoot.querySelector(".deprecation-notice");
    expect(notice).not.toBeNull();
    expect(notice.textContent).toContain("deprecated");
    expect(notice.querySelector("a").href).toContain(
      "#replacing-the-deprecated-alarm-card-badge-and-chip",
    );
  });

  it("shows the notice in the user's language", () => {
    const card = mount("verisure-owa-alarm-card", hassWithAlarm({ language: "es" }));
    const notice = card.shadowRoot.querySelector(".deprecation-notice");
    expect(notice.textContent).toContain("obsoleta");
  });

  it("shows the notice in Catalan, naming Home Assistant's Catalan card names", () => {
    const card = mount("verisure-owa-alarm-card", hassWithAlarm({ language: "ca" }));
    const notice = card.shadowRoot.querySelector(".deprecation-notice");
    expect(notice.textContent).toContain("Aquesta targeta està obsoleta");
    expect(notice.textContent).toContain("Mosaic");
  });

  it("stays hidden after it is dismissed, including on a new card", () => {
    const card = mount("verisure-owa-alarm-card");
    card.shadowRoot.querySelector(".deprecation-dismiss").click();
    expect(card.shadowRoot.querySelector(".deprecation-notice")).toBeNull();

    const again = mount("verisure-owa-alarm-card");
    expect(again.shadowRoot.querySelector(".deprecation-notice")).toBeNull();
  });

  it("still renders the card and notice when browser storage throws", () => {
    const getItem = vi.spyOn(globalThis.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(globalThis.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      const card = mount("verisure-owa-alarm-card");
      expect(card.shadowRoot.querySelector(".deprecation-notice")).not.toBeNull();
      card.shadowRoot.querySelector(".deprecation-dismiss").click();
      expect(card.shadowRoot.querySelector(".deprecation-notice")).toBeNull();
      expect(card.shadowRoot.innerHTML).toContain("Disarmed");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("remembers the dismissal under the verisure-owa: storage prefix", () => {
    const card = mount("verisure-owa-alarm-card");
    card.shadowRoot.querySelector(".deprecation-dismiss").click();
    expect(globalThis.localStorage.getItem("verisure-owa:deprecation-dismissed")).toBe("true");
  });

  it("hides the notice on every other mounted card, legacy alias included", () => {
    const hass = hassWithAlarm();
    const first = mount("verisure-owa-alarm-card", hass);
    const second = mount("verisure-owa-alarm-card", hass);
    const legacy = mount("securitas-alarm-card", hass);
    first.shadowRoot.querySelector(".deprecation-dismiss").click();
    // An ordinary update with the alarm state unchanged must not be needed.
    second.hass = { ...hass, states: { ...hass.states } };
    expect(second.shadowRoot.querySelector(".deprecation-notice")).toBeNull();
    expect(legacy.shadowRoot.querySelector(".deprecation-notice")).toBeNull();
  });

  it("hides the notice on other mounted cards even when storage is blocked", () => {
    const getItem = vi.spyOn(globalThis.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(globalThis.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      const first = mount("verisure-owa-alarm-card");
      const second = mount("verisure-owa-alarm-card");
      first.shadowRoot.querySelector(".deprecation-dismiss").click();
      expect(second.shadowRoot.querySelector(".deprecation-notice")).toBeNull();
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("stops listening for dismissals once removed from the page", () => {
    const first = mount("verisure-owa-alarm-card");
    const removed = mount("verisure-owa-alarm-card");
    removed.remove();
    const render = vi.spyOn(removed, "_render");
    expect(() => first.shadowRoot.querySelector(".deprecation-dismiss").click()).not.toThrow();
    expect(render).not.toHaveBeenCalled();
  });

  it("appears on the legacy securitas-alarm-card alias too", () => {
    const card = mount("securitas-alarm-card");
    expect(card.shadowRoot.querySelector(".deprecation-notice")).not.toBeNull();
  });
});

describe("picker entries are labelled deprecated", () => {
  it.each([
    ["customCards", "verisure-owa-alarm-card"],
    ["customCards", "verisure-owa-alarm-chip"],
    ["customBadges", "verisure-owa-alarm-badge"],
  ])("%s entry %s", (registry, type) => {
    const entry = window[registry].find((e) => e.type === type);
    expect(entry.name).toMatch(/\(deprecated\)$/);
  });

  it("leaves the cards that are not deprecated alone", () => {
    const tile = window.customCardFeatures.find((f) => f.type === "verisure-owa-arm-exception");
    expect(tile.name).not.toMatch(/deprecated/i);
  });
});

describe("badge editor deprecation notice", () => {
  it("shows a notice above the form", () => {
    const editor = document.createElement("verisure-owa-alarm-badge-editor");
    editor.hass = hassWithAlarm();
    editor.setConfig({ type: "custom:verisure-owa-alarm-badge", entity: ENTITY });
    document.body.appendChild(editor);
    const notice = editor.shadowRoot.querySelector(".deprecation-notice");
    expect(notice).not.toBeNull();
    expect(notice.textContent).toContain("badge");
    expect(notice.querySelector("a").href).toContain(
      "#replacing-the-deprecated-alarm-card-badge-and-chip",
    );
  });
});

describe("deprecated elements report themselves to the Home Assistant log", () => {
  it.each([
    ["verisure-owa-alarm-card", "card"],
    ["securitas-alarm-card", "card"],
    ["verisure-owa-alarm-badge", "badge"],
    ["securitas-alarm-badge", "badge"],
    ["verisure-owa-alarm-chip", "chip"],
    ["mushroom-verisure-owa-alarm-chip", "chip"],
    ["securitas-alarm-chip", "chip"],
    ["mushroom-securitas-alarm-chip", "chip"],
  ])("%s reports itself once as %s with its dashboard", (tag, element) => {
    window.history.replaceState(null, "", "/dashboard-security/alarm");
    const hass = hassWithAlarm();
    const el = mount(tag, hass);
    el.hass = { ...hass, states: { ...hass.states } };
    el.hass = { ...hass, states: { [ENTITY]: makeAlarmEntity({ state: "armed_away" }) } };
    expect(deprecationCalls(hass)).toEqual([
      { type: "verisure_owa/deprecated_element", element, dashboard: "dashboard-security" },
    ]);
  });

  it("keeps working when the report is rejected", async () => {
    const hass = hassWithAlarm({
      callWS: vi.fn(async () => {
        throw new Error("unknown command");
      }),
    });
    const card = mount("verisure-owa-alarm-card", hass);
    await Promise.resolve();
    expect(card.shadowRoot.innerHTML).toContain("Disarmed");
  });

  it("keeps working when callWS is missing", () => {
    const hass = hassWithAlarm();
    delete hass.callWS;
    const card = mount("verisure-owa-alarm-card", hass);
    expect(card.shadowRoot.innerHTML).toContain("Disarmed");
  });
});
