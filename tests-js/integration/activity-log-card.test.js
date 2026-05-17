import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-activity-log-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeActivityLogEntity } from "../fixtures/entities.js";

const ENTITY = "sensor.test_activity_log";

function mountActivityCard({ config = {}, hass = makeHass() } = {}) {
  const el = document.createElement("verisure-owa-activity-log-card");
  el.setConfig({
    type: "custom:verisure-owa-activity-log-card",
    entity: ENTITY,
    ...config,
  });
  el.hass = hass;
  document.body.appendChild(el);
  return el;
}

describe("verisure-owa-activity-log-card render", () => {
  it("registers", () => {
    expect(customElements.get("verisure-owa-activity-log-card")).toBeDefined();
  });

  it("renders empty state when events list is empty", () => {
    const card = mountActivityCard({
      hass: makeHass({ states: { [ENTITY]: makeActivityLogEntity({ events: [] }) } }),
    });
    // The card emits a `.empty` div with the localised "no events" string
    // (English fixture: "No events recorded yet"). Assert on that real
    // marker rather than the toBeDefined placeholder from the plan.
    const empty = card.shadowRoot.querySelector(".empty");
    expect(empty).not.toBeNull();
    expect(empty.textContent).toMatch(/No events recorded yet/);
  });

  it("renders one row per event", () => {
    const card = mountActivityCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeActivityLogEntity({
            events: [
              {
                id_signal: "1",
                time: "2026-05-17 11:30:00",
                category: "armed",
                alias: "ArmedAlias",
              },
              {
                id_signal: "2",
                time: "2026-05-17 11:00:00",
                category: "disarmed",
                alias: "DisarmedAlias",
              },
            ],
          }),
        },
      }),
    });
    // The card renders one .event row per visible event — count them.
    // This catches a buggy zero-row render that toContain("arm") would miss.
    const rows = card.shadowRoot.querySelectorAll(".event");
    expect(rows.length).toBe(2);
    // Each row should carry the event's id_signal as data-id.
    const ids = Array.from(rows).map((r) => r.getAttribute("data-id"));
    expect(ids).toEqual(["1", "2"]);
    // The category-label strings are rendered into the row meta.
    const html = card.shadowRoot.innerHTML;
    expect(html).toContain("Armed");
    expect(html).toContain("Disarmed");
    // The alias is rendered in .line2 — assert it is present too.
    expect(html).toContain("ArmedAlias");
    expect(html).toContain("DisarmedAlias");
  });

  it("renders entity-not-found when state is missing", () => {
    const card = mountActivityCard({ hass: makeHass() });
    expect(card.shadowRoot.innerHTML).toMatch(/Entity not found/);
  });
});

describe("verisure-owa-activity-log-card refresh service", () => {
  it("clicking Refresh calls verisure_owa.refresh_activity_log", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [] }) },
    });
    const card = mountActivityCard({ hass });

    // The refresh trigger is an icon-only button in the top-right corner
    // (mdi:refresh icon, no text content) — identified by its id, same
    // pattern as the camera card.
    const refreshBtn = card.shadowRoot.getElementById("refresh-btn");
    expect(refreshBtn).not.toBeNull();
    refreshBtn.click();
    // _handleRefresh is async — give the microtask queue a chance to settle.
    await Promise.resolve();
    expect(hass.callService).toHaveBeenCalledWith(
      "verisure_owa",
      "refresh_activity_log",
      expect.objectContaining({ entity_id: ENTITY }),
    );
  });
});

describe("verisure-owa-activity-log-card callWS wiring", () => {
  // Note: the activity-log card has no pagination UI. The plan's "load
  // more / older / previous" button does not exist. The card's only
  // callWS usage is _callServiceWithResponse, invoked by _fetchEventImage
  // when an event with img: 1 (and a non-ha- id_signal) is expanded.
  // We exercise that path here as the realistic callWS trigger.
  it("expanding an image-request row calls hass.callWS with fetch_activity_image", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "9001",
              time: "2026-05-17 11:30:00",
              category: "image_request",
              alias: "Camera",
              img: 1,
              type: 14,
            },
          ],
        }),
      },
    });
    // Resolve with a valid base64 payload so _fetchEventImage takes the
    // "loaded" branch and doesn't emit a benign console.warn that would
    // clutter test output.
    hass.callWS.mockResolvedValueOnce({
      response: { [ENTITY]: { image_b64: "AAAA", mime_type: "image/jpeg" } },
    });
    // Suppress any other unforeseen console.warn from the card during
    // this scenario — we only care about asserting the callWS arguments.
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const card = mountActivityCard({ hass });

    const row = card.shadowRoot.querySelector('.event[data-id="9001"]');
    expect(row).not.toBeNull();
    // Bypass the pointerdown drag-threshold check by issuing a click with
    // matching coordinates. Without a prior pointerdown, downX/downY are 0,
    // so a click at clientX/Y=0 falls under the 4-px drag threshold.
    row.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 0, clientY: 0 }));
    await Promise.resolve();
    expect(hass.callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "call_service",
        domain: "verisure_owa",
        service: "fetch_activity_image",
        service_data: expect.objectContaining({
          entity_id: ENTITY,
          id_signal: "9001",
        }),
      }),
    );
    warnSpy.mockRestore();
  });
});

describe("verisure-owa-activity-log-card not-an-activity-log branch", () => {
  it("renders 'not_an_activity_log' message when state has no events array", () => {
    // When the configured entity exists but its attributes lack an
    // `events` array, _render() takes the not_an_activity_log branch.
    const card = mountActivityCard({
      hass: makeHass({
        states: {
          [ENTITY]: { state: "0", attributes: { friendly_name: "Bogus" } },
        },
      }),
    });
    expect(card.shadowRoot.innerHTML).toMatch(/not an activity log/i);
  });
});

describe("verisure-owa-activity-log-card row interactions", () => {
  it("ignores click after pointerdown moved more than the drag threshold", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "55",
              time: "2026-05-17 11:30:00",
              category: "armed",
              alias: "Drag",
            },
          ],
        }),
      },
    });
    const card = mountActivityCard({ hass });
    const row = card.shadowRoot.querySelector('.event[data-id="55"]');
    expect(row.classList.contains("expanded")).toBe(false);

    row.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 0, clientY: 0 }));
    row.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 20, clientY: 0 }));

    // The row should NOT have been toggled because the cursor moved > 4 px.
    const after = card.shadowRoot.querySelector('.event[data-id="55"]');
    expect(after.classList.contains("expanded")).toBe(false);
  });

  it("toggles row open then closed via Enter keypress, updating aria-expanded", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "kbd-1",
              time: "2026-05-17 11:30:00",
              category: "armed",
              alias: "Keyboard",
            },
          ],
        }),
      },
    });
    const card = mountActivityCard({ hass });
    const row = card.shadowRoot.querySelector('.event[data-id="kbd-1"]');
    expect(row.getAttribute("aria-expanded")).toBe("false");

    // Open with Enter
    row.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
    expect(
      card.shadowRoot.querySelector('.event[data-id="kbd-1"]').getAttribute("aria-expanded"),
    ).toBe("true");
    expect(
      card.shadowRoot.querySelector('.details-row[data-id="kbd-1"]').classList.contains("expanded"),
    ).toBe(true);

    // Close with Space
    card.shadowRoot
      .querySelector('.event[data-id="kbd-1"]')
      .dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: " " }));
    expect(
      card.shadowRoot.querySelector('.event[data-id="kbd-1"]').getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("does not fetch image when expanded id starts with 'ha-' (synthetic)", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "ha-injected-1",
              time: "2026-05-17 11:30:00",
              category: "image_request",
              alias: "Synthetic",
              img: 1,
              type: 14,
              injected: true,
            },
          ],
        }),
      },
    });
    const card = mountActivityCard({ hass });
    const row = card.shadowRoot.querySelector('.event[data-id="ha-injected-1"]');
    row.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 0, clientY: 0 }));
    await Promise.resolve();
    // callWS is the wire used by _fetchEventImage — synthetic ids must not trigger it.
    expect(hass.callWS).not.toHaveBeenCalled();
    // Injected event's badge icon is rendered.
    expect(card.shadowRoot.innerHTML).toContain("mdi:home-assistant");
  });

  it("falls back to an error placeholder when fetch_activity_image returns no image_b64", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "no-img",
              time: "2026-05-17 11:30:00",
              category: "image_request",
              alias: "NoImage",
              img: 1,
              type: 14,
            },
          ],
        }),
      },
    });
    hass.callWS.mockResolvedValueOnce({ response: { [ENTITY]: {} } });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const card = mountActivityCard({ hass });

    const row = card.shadowRoot.querySelector('.event[data-id="no-img"]');
    row.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 0, clientY: 0 }));
    // Two microtask ticks: one for callWS resolution, one for the post-fetch re-render.
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(card.shadowRoot.innerHTML).toMatch(/Image not available/i);
    warnSpy.mockRestore();
  });

  it("falls back to an error placeholder when callWS rejects", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "throw-1",
              time: "2026-05-17 11:30:00",
              category: "image_request",
              alias: "Boom",
              img: 1,
              type: 14,
            },
          ],
        }),
      },
    });
    hass.callWS.mockRejectedValueOnce(new Error("network"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const card = mountActivityCard({ hass });

    const row = card.shadowRoot.querySelector('.event[data-id="throw-1"]');
    row.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 0, clientY: 0 }));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(card.shadowRoot.innerHTML).toMatch(/Image not available/i);
    warnSpy.mockRestore();
  });

  it("renders a loaded image when fetch returns image_b64", async () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "img-loaded",
              time: "2026-05-17 11:30:00",
              category: "image_request",
              alias: "Cam",
              img: 1,
              type: 14,
            },
          ],
        }),
      },
    });
    hass.callWS.mockResolvedValueOnce({
      response: { [ENTITY]: { image_b64: "AAAA", mime_type: "image/png" } },
    });
    const card = mountActivityCard({ hass });

    const row = card.shadowRoot.querySelector('.event[data-id="img-loaded"]');
    row.dispatchEvent(new MouseEvent("click", { bubbles: true, clientX: 0, clientY: 0 }));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    const img = card.shadowRoot.querySelector("img.event-image");
    expect(img).not.toBeNull();
    expect(img.getAttribute("src")).toContain("data:image/png;base64,AAAA");
  });

  it("renders the unknown-event prompt for events with category=unknown", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            {
              id_signal: "u-1",
              time: "2026-05-17 11:30:00",
              category: "unknown",
              alias: "Mystery",
            },
          ],
        }),
      },
    });
    const card = mountActivityCard({ hass });
    const row = card.shadowRoot.querySelector('.event[data-id="u-1"]');
    row.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
    expect(card.shadowRoot.querySelector(".unknown-prompt")).not.toBeNull();
  });
});

describe("verisure-owa-activity-log-card lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("installs a tick timer on connect and clears it on disconnect", () => {
    const card = mountActivityCard({
      hass: makeHass({ states: { [ENTITY]: makeActivityLogEntity({ events: [] }) } }),
    });
    // connectedCallback runs synchronously when appended.

    expect(card._tickTimer).not.toBeNull();
    card.remove();

    expect(card._tickTimer).toBeNull();
  });

  it("re-renders on the periodic tick to refresh relative timestamps", () => {
    const renderSpy = vi.fn();
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [{ id_signal: "1", time: "2026-05-17 11:30:00", category: "armed", alias: "A" }],
        }),
      },
    });
    const card = mountActivityCard({ hass });
    // Patch _render to count re-renders triggered by the timer
    const originalRender = card._render.bind(card);
    card._render = (...args) => {
      renderSpy();
      return originalRender(...args);
    };
    vi.advanceTimersByTime(60_001);
    expect(renderSpy).toHaveBeenCalled();
  });
});

describe("verisure-owa-activity-log-card refresh paths", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("the 8s fallback clears the spinner if no state update arrives", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [] }) },
    });
    // Make callService settle (so finally completes) but no state update
    // is delivered to the card from outside.
    hass.callService.mockResolvedValueOnce(undefined);
    const card = mountActivityCard({ hass });
    const refreshBtn = card.shadowRoot.getElementById("refresh-btn");
    refreshBtn.click();
    // Spinner should be active immediately.

    expect(card._refreshing).toBe(true);
    // Advance past the 8000ms fallback.
    vi.advanceTimersByTime(8001);

    expect(card._refreshing).toBe(false);
  });

  it("a subsequent hass state change clears the refreshing flag", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [] }) },
    });
    const card = mountActivityCard({ hass });
    const refreshBtn = card.shadowRoot.getElementById("refresh-btn");
    refreshBtn.click();

    expect(card._refreshing).toBe(true);
    // Push a new hass with a fresh state object — triggers _clearRefreshing path.
    card.hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [{ id_signal: "x" }] }) },
    });

    expect(card._refreshing).toBe(false);
  });

  it("swallows callService rejections without throwing (sync click is safe)", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [] }) },
    });
    hass.callService.mockRejectedValueOnce(new Error("boom"));
    const card = mountActivityCard({ hass });
    expect(() => card.shadowRoot.getElementById("refresh-btn").click()).not.toThrow();
    // Let the rejected promise propagate through finally.
    await Promise.resolve();
    await Promise.resolve();
    expect(hass.callService).toHaveBeenCalled();
  });
});

describe("verisure-owa-activity-log-card static helpers", () => {
  it("getConfigElement returns the matching editor element", () => {
    const ctor = customElements.get("verisure-owa-activity-log-card");
    const el = ctor.getConfigElement();
    expect(el.tagName.toLowerCase()).toBe("verisure-owa-activity-log-card-editor");
  });

  it("getStubConfig picks the first sensor with an events array", () => {
    const ctor = customElements.get("verisure-owa-activity-log-card");
    const hass = makeHass({
      states: {
        "sensor.other": { state: "1", attributes: {} },
        "sensor.activity_a": makeActivityLogEntity(),
        "sensor.activity_b": makeActivityLogEntity(),
      },
    });
    const stub = ctor.getStubConfig(hass);
    expect(stub.entity).toBe("sensor.activity_a");
    expect(stub.limit).toBe(10);
  });

  it("getStubConfig returns empty entity when no activity log sensors exist", () => {
    const ctor = customElements.get("verisure-owa-activity-log-card");
    const stub = ctor.getStubConfig(makeHass());
    expect(stub.entity).toBe("");
  });

  it("getCardSize scales with the configured limit, capped at 8", () => {
    const card = mountActivityCard({
      config: { limit: 30 },
      hass: makeHass({ states: { [ENTITY]: makeActivityLogEntity({ events: [] }) } }),
    });
    expect(card.getCardSize()).toBe(8);
  });
});

describe("verisure-owa-activity-log-card setConfig validation", () => {
  it("throws when entity is missing", () => {
    const el = document.createElement("verisure-owa-activity-log-card");
    expect(() => el.setConfig({})).toThrow(/entity is required/i);
  });

  it("filters out events whose category is listed in hide_categories", () => {
    const card = mountActivityCard({
      config: { hide_categories: ["status_check"] },
      hass: makeHass({
        states: {
          [ENTITY]: makeActivityLogEntity({
            events: [
              { id_signal: "1", time: "2026-05-17 11:30:00", category: "armed", alias: "A" },
              { id_signal: "2", time: "2026-05-17 11:00:00", category: "status_check", alias: "S" },
            ],
          }),
        },
      }),
    });
    const rows = card.shadowRoot.querySelectorAll(".event");
    expect(rows.length).toBe(1);
    expect(rows[0].getAttribute("data-id")).toBe("1");
  });
});

describe("verisure-owa-activity-log-card extra branches", () => {
  it("renders the configured title in the card header", () => {
    const card = mountActivityCard({
      config: { title: "Recent" },
      hass: makeHass({ states: { [ENTITY]: makeActivityLogEntity({ events: [] }) } }),
    });
    expect(card.shadowRoot.querySelector(".card-header").textContent).toBe("Recent");
  });

  it("renders an event whose category is not in CATEGORY_ICONS with the unknown icon", () => {
    const card = mountActivityCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeActivityLogEntity({
            events: [
              {
                id_signal: "u-2",
                time: "2026-05-17 11:30:00",
                // Deliberately unmapped category to take the `|| unknown` branch.
                category: "made-up-category",
                alias: "Mystery",
              },
            ],
          }),
        },
      }),
    });
    expect(card.shadowRoot.innerHTML).toContain("mdi:help-circle");
  });

  it("renders an injected event with the ha-badge marker", () => {
    const card = mountActivityCard({
      hass: makeHass({
        states: {
          [ENTITY]: makeActivityLogEntity({
            events: [
              {
                id_signal: "inj-1",
                time: "2026-05-17 11:30:00",
                category: "armed",
                alias: "Inj",
                injected: true,
              },
            ],
          }),
        },
      }),
    });
    expect(card.shadowRoot.querySelector(".injected-badge")).not.toBeNull();
    expect(card.shadowRoot.querySelector(".event.injected")).not.toBeNull();
  });

  it("_handleRefresh early-returns while already refreshing (re-entrant click ignored)", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [] }) },
    });
    let calls = 0;
    hass.callService.mockImplementation(async () => {
      calls += 1;
    });
    const card = mountActivityCard({ hass });
    const btn = card.shadowRoot.getElementById("refresh-btn");
    btn.click();
    btn.click();
    await Promise.resolve();
    expect(calls).toBe(1);
  });

  it("_callServiceWithResponse returns the service_response key when present, else null", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeActivityLogEntity({ events: [] }) },
    });
    const card = mountActivityCard({ hass });
    // service_response key (alternate shape supported by HA frontends).
    hass.callWS.mockResolvedValueOnce({ service_response: { ok: true } });

    let result = await card._callServiceWithResponse("d", "s", {});
    expect(result).toEqual({ ok: true });
    // Null when neither response nor service_response is present.
    hass.callWS.mockResolvedValueOnce(null);

    result = await card._callServiceWithResponse("d", "s", {});
    expect(result).toBeNull();
    // Null when callWS rejects.
    hass.callWS.mockRejectedValueOnce(new Error("net"));

    result = await card._callServiceWithResponse("d", "s", {});
    expect(result).toBeNull();
  });

  it("prunes _expanded entries for events that scroll out of view", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [
            { id_signal: "1", time: "2026-05-17 11:30:00", category: "armed", alias: "A" },
            { id_signal: "2", time: "2026-05-17 11:00:00", category: "armed", alias: "B" },
          ],
        }),
      },
    });
    const card = mountActivityCard({ config: { limit: 2 }, hass });
    // Expand row 1 via Enter.
    card.shadowRoot
      .querySelector('.event[data-id="1"]')
      .dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));

    expect(card._expanded.has("1")).toBe(true);
    // Push a new state with only row 2 — row 1 falls out and should be pruned.
    card.hass = makeHass({
      states: {
        [ENTITY]: makeActivityLogEntity({
          events: [{ id_signal: "2", time: "2026-05-17 11:00:00", category: "armed", alias: "B" }],
        }),
      },
    });

    expect(card._expanded.has("1")).toBe(false);
  });
});

describe("verisure-owa-activity-log-card-editor change events", () => {
  it("computeLabel returns localized strings for each known schema field", () => {
    const editor = document.createElement("verisure-owa-activity-log-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "sensor.house_activity_log": makeActivityLogEntity() },
    });
    document.body.appendChild(editor);
    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm.computeLabel({ name: "entity" })).toBe("Activity log entity");
    expect(entityForm.computeLabel({ name: "limit" })).toBe("Number of events to show");
    expect(entityForm.computeLabel({ name: "title" })).toBe("Card title (optional)");
    expect(entityForm.computeLabel({ name: "max_height" })).toBe(
      "Max card height (e.g. 400px, 60vh)",
    );
    expect(entityForm.computeLabel({ name: "hide_categories" })).toBe("Categories to hide");
    // Unknown fields fall through to the raw name (defensive default).
    expect(entityForm.computeLabel({ name: "unknown" })).toBe("unknown");
  });
});
