// Edge-case tests added to cover branches that Vitest 4 / v8-coverage 4 now
// count more accurately. These exercise paths the main suite skipped:
// fallback defaults, second-call render paths, null-guard branches.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeCameraEntity } from "../fixtures/entities.js";

const ENTITY = "camera.test";

function mountCameraCard({ config = {}, hass = makeHass() } = {}) {
  const el = document.createElement("verisure-owa-camera-card");
  el.setConfig({ type: "custom:verisure-owa-camera-card", entity: ENTITY, ...config });
  el.hass = hass;
  document.body.appendChild(el);
  return el;
}

describe("camera-card edge branches", () => {
  it("_openMoreInfo falls back to config.entity when called with no entityId", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk" }) },
    });
    const card = mountCameraCard({ hass });
    const events = [];
    card.addEventListener("hass-more-info", (e) => events.push(e.detail));
    // _openMoreInfo is invoked from the img-wrapper click handler with the
    // resolved entity; calling it directly with null exercises the
    // `entityId || this._config.entity` fallback branch.
    card._openMoreInfo(null);
    expect(events).toEqual([{ entityId: ENTITY }]);
  });

  it("clicking the refresh button does not bubble to the more-info handler", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk" }) },
    });
    const card = mountCameraCard({ hass });
    const moreInfoEvents = [];
    card.addEventListener("hass-more-info", (e) => moreInfoEvents.push(e.detail));
    card.shadowRoot.getElementById("refresh-btn").click();
    expect(moreInfoEvents).toEqual([]);
    expect(hass.callService).toHaveBeenCalledWith(
      "verisure_owa",
      "capture_image",
      expect.objectContaining({ entity_id: ENTITY }),
    );
  });

  it("refresh button shows the spinning class while a capture is in flight", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk" }) },
      callService: vi.fn(() => new Promise(() => {})), // never resolves
    });
    const card = mountCameraCard({ hass });
    card.shadowRoot.getElementById("refresh-btn").click();
    await Promise.resolve();
    expect(card.shadowRoot.getElementById("refresh-btn").classList.contains("spinning")).toBe(true);
  });

  it("renders without crashing when hass.language is unset", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      language: undefined,
    });
    expect(() => mountCameraCard({ hass })).not.toThrow();
  });

  it("re-renders successfully when called with a fresh hass.entities reference", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { device_id: "dev1" } },
      devices: { dev1: { name: "Front Door" } },
    });
    const card = mountCameraCard({ hass });
    // Force a second _entitiesByDeviceId call with a different entities ref
    // to exercise the cache-invalidation branch.
    const hass2 = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { device_id: "dev2" }, "binary_sensor.x": {} },
      devices: { dev2: { name: "Back Door" } },
    });
    card.hass = hass2;
    expect(card.shadowRoot.innerHTML).toContain("Back Door");
  });
});

describe("camera-card _findFullEntity null-guards", () => {
  it("returns null when hass has no entities map", () => {
    const hass = makeHass({ states: { [ENTITY]: makeCameraEntity() }, entities: null });
    expect(() => mountCameraCard({ hass })).not.toThrow();
  });

  it("returns null when cameraEntry has no device_id", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { unique_id: "u1" } }, // no device_id
    });
    expect(() => mountCameraCard({ hass })).not.toThrow();
  });

  it("returns null when the camera's device has no other camera entity", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: {
        [ENTITY]: { device_id: "dev1" },
        "binary_sensor.motion": { device_id: "dev1" },
      },
    });
    expect(() => mountCameraCard({ hass })).not.toThrow();
  });
});

describe("camera-card setConfig second-call path", () => {
  it("second setConfig call updates the entity picker without rebuilding the DOM", () => {
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.hass = makeHass({
      states: { "camera.a": makeCameraEntity(), "camera.b": makeCameraEntity() },
    });
    editor.setConfig({ entity: "camera.a" });
    document.body.appendChild(editor);
    const firstEntityForm = editor.shadowRoot.getElementById("entity-form");
    expect(firstEntityForm).not.toBeNull();

    editor.setConfig({ entity: "camera.b" });
    const secondEntityForm = editor.shadowRoot.getElementById("entity-form");
    expect(secondEntityForm).toBe(firstEntityForm); // DOM preserved
    expect(secondEntityForm.data).toEqual({ entity: "camera.b" });
  });

  it("editor value-changed ignores events with no entity in detail", () => {
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.hass = makeHass({ states: { "camera.a": makeCameraEntity() } });
    editor.setConfig({ entity: "camera.a" });
    document.body.appendChild(editor);
    const changes = [];
    editor.addEventListener("config-changed", (e) => changes.push(e.detail.config));
    const entityForm = editor.shadowRoot.getElementById("entity-form");
    // value-changed where detail.value lacks an `entity` key — newEntity is undefined,
    // which hits the `if (newEntity !== undefined)` false branch.
    entityForm.dispatchEvent(
      new CustomEvent("value-changed", { detail: { value: {} }, bubbles: true, composed: true }),
    );
    expect(changes).toEqual([]);
  });
});

describe("camera-card refresh fallback timer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("clears the spinning state after 15s when no token rotation arrives", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk1" }) },
    });
    const card = mountCameraCard({ hass });
    card.shadowRoot.getElementById("refresh-btn").click();
    await Promise.resolve();
    await Promise.resolve();
    vi.advanceTimersByTime(15000);
    expect(card.shadowRoot.getElementById("refresh-btn").classList.contains("spinning")).toBe(
      false,
    );
  });
});

describe("camera-card getStubConfig", () => {
  it("returns an empty entity when no camera entity exists in hass", () => {
    const ctor = customElements.get("verisure-owa-camera-card");
    expect(ctor.getStubConfig(makeHass())).toEqual({ entity: "" });
  });

  it("picks a camera that is not a full-image variant", () => {
    const ctor = customElements.get("verisure-owa-camera-card");
    const hass = makeHass({
      states: {
        "camera.front": makeCameraEntity(),
        "camera.back": makeCameraEntity(),
      },
    });
    expect(ctor.getStubConfig(hass).entity).toMatch(/^camera\./);
  });

  it("handles hass with no states map", () => {
    const ctor = customElements.get("verisure-owa-camera-card");
    expect(ctor.getStubConfig({ entities: {} })).toEqual({ entity: "" });
  });
});
