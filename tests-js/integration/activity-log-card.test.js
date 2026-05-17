import { describe, it, expect, vi } from "vitest";
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
