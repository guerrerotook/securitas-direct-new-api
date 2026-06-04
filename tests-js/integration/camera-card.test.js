import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { TRANSLATIONS as CAMERA_TRANSLATIONS } from "../../custom_components/securitas/www/verisure-owa-camera-card.js";
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

describe("verisure-owa-camera-card", () => {
  it("registers", () => {
    expect(customElements.get("verisure-owa-camera-card")).toBeDefined();
  });

  it("renders the camera image using entity_picture", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk1" }) },
    });
    const card = mountCameraCard({ hass });
    const img = card.shadowRoot.querySelector("img");
    expect(img).not.toBeNull();
    expect(img.src).toContain("token=tk1");
  });

  it("re-renders when access_token rotates", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk1" }) },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector("img").src).toContain("token=tk1");

    card.hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk2" }) },
    });
    expect(card.shadowRoot.querySelector("img").src).toContain("token=tk2");
  });

  it("renders entity-not-found when state is missing", () => {
    const card = mountCameraCard({ hass: makeHass() });
    expect(card.shadowRoot.innerHTML).toMatch(/Entity not found/);
  });

  it("clicking the capture button calls verisure_owa.capture_image", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
    });
    const card = mountCameraCard({ hass });

    // The capture trigger is the refresh button in the top-right corner
    // (mdi:refresh icon, no text/aria-label) — identified by its id.
    const captureBtn = card.shadowRoot.getElementById("refresh-btn");
    expect(captureBtn).not.toBeNull();
    captureBtn.click();
    // capture_image is async — give the promise microtask a chance to settle
    await Promise.resolve();
    expect(hass.callService).toHaveBeenCalledWith(
      "verisure_owa",
      "capture_image",
      expect.objectContaining({ entity_id: ENTITY }),
    );
  });

  it("uses Spanish strings when hass.language is es", () => {
    // The main card's _render path only emits translated strings on the
    // entity-not-found branch and inside the relative-timestamp tooltip.
    // The entity-not-found branch is the most reliable place to assert the
    // locale is honoured, so render that branch with hass.language=es.
    const card = mountCameraCard({ hass: makeHass({ language: "es" }) });
    const esEntityNotFound = CAMERA_TRANSLATIONS.es.entity_not_found.split("{")[0];
    expect(card.shadowRoot.innerHTML).toContain(esEntityNotFound);
  });
});

describe("verisure-owa-camera-card setConfig", () => {
  it("throws when entity is missing", () => {
    const el = document.createElement("verisure-owa-camera-card");
    expect(() => el.setConfig({})).toThrow(/entity/i);
  });
});

describe("verisure-owa-camera-card overlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-17T12:00:00"));
  });
  afterEach(() => vi.useRealTimers());

  it("renders the relative-time pill in the overlay when image_timestamp is recent", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          ...makeCameraEntity({ accessToken: "tk" }),
          attributes: {
            ...makeCameraEntity({ accessToken: "tk" }).attributes,
            image_timestamp: "2026-05-17T11:55:00",
          },
        },
      },
    });
    const card = mountCameraCard({ hass });
    const ts = card.shadowRoot.querySelector(".timestamp");
    expect(ts).not.toBeNull();
    // 5 minutes ago — must render the localized minute string.
    expect(ts.textContent).toMatch(/min/);
    // The absolute tooltip is the locale-formatted string.
    expect(ts.getAttribute("title")).toContain("2026");
  });

  it("formats timestamps in hours when an hour or more old", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          ...makeCameraEntity({ accessToken: "tk" }),
          attributes: {
            ...makeCameraEntity({ accessToken: "tk" }).attributes,
            image_timestamp: "2026-05-17T09:00:00",
          },
        },
      },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector(".timestamp").textContent).toMatch(/h/);
  });

  it("formats timestamps in days when older than a day", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          ...makeCameraEntity({ accessToken: "tk" }),
          attributes: {
            ...makeCameraEntity({ accessToken: "tk" }).attributes,
            image_timestamp: "2026-05-10T12:00:00",
          },
        },
      },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector(".timestamp").textContent).toMatch(/d/);
  });

  it("formats timestamps in seconds when very recent", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          ...makeCameraEntity({ accessToken: "tk" }),
          attributes: {
            ...makeCameraEntity({ accessToken: "tk" }).attributes,
            image_timestamp: "2026-05-17T11:59:50",
          },
        },
      },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector(".timestamp").textContent).toMatch(/s/);
  });

  it("renders the raw timestamp when it cannot be parsed as a date", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: {
          ...makeCameraEntity({ accessToken: "tk" }),
          attributes: {
            ...makeCameraEntity({ accessToken: "tk" }).attributes,
            image_timestamp: "not-a-date",
          },
        },
      },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector(".timestamp").textContent).toBe("not-a-date");
  });
});

describe("verisure-owa-camera-card click → more-info", () => {
  it("clicking the image dispatches hass-more-info for the thumbnail entity", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
    });
    const card = mountCameraCard({ hass });
    let captured = null;
    card.addEventListener("hass-more-info", (e) => {
      captured = e.detail.entityId;
    });
    card.shadowRoot.getElementById("img-wrapper").click();
    expect(captured).toBe(ENTITY);
  });

  it("clicking the image dispatches hass-more-info for the full entity when configured and timestamped", () => {
    const FULL = "camera.test_full_image";
    const hass = makeHass({
      states: {
        [ENTITY]: makeCameraEntity(),
        [FULL]: {
          state: "idle",
          attributes: { image_timestamp: "2026-05-17T11:59:50", access_token: "tk" },
        },
      },
      entities: {
        [ENTITY]: { device_id: "dev1", platform: "securitas" },
        [FULL]: { device_id: "dev1", platform: "securitas" },
      },
    });
    const card = mountCameraCard({ hass });
    let captured = null;
    card.addEventListener("hass-more-info", (e) => {
      captured = e.detail.entityId;
    });
    card.shadowRoot.getElementById("img-wrapper").click();
    expect(captured).toBe(FULL);
  });

  it("uses the device's name_by_user as display name when no config.name", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { device_id: "dev1", platform: "securitas" } },
      devices: { dev1: { name: "Camera", name_by_user: "Front Hall" } },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector(".name").textContent).toBe("Front Hall");
  });

  it("falls back to device.name when name_by_user is unset", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { device_id: "dev1", platform: "securitas" } },
      devices: { dev1: { name: "Hallway" } },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector(".name").textContent).toBe("Hallway");
  });
});

describe("verisure-owa-camera-card refresh spinner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("clears the spinner when the access_token rotates to a new value", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk-old" }) },
    });
    const card = mountCameraCard({ hass });
    card.shadowRoot.getElementById("refresh-btn").click();

    expect(card._refreshing).toBe(true);
    // New token via fresh hass push (and capturing=false to take the clear branch).
    const newHass = makeHass({
      states: {
        [ENTITY]: {
          state: "idle",
          attributes: { access_token: "tk-new", capturing: false },
        },
      },
    });
    card.hass = newHass;

    expect(card._refreshing).toBe(false);
  });

  it("the 15s fallback timer clears the spinner if no token rotation arrives", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk1" }) },
    });
    hass.callService.mockResolvedValueOnce(undefined);
    const card = mountCameraCard({ hass });
    card.shadowRoot.getElementById("refresh-btn").click();
    // Let the awaited callService resolve so the finally-block schedules the timer.
    await Promise.resolve();
    await Promise.resolve();
    vi.advanceTimersByTime(15001);

    expect(card._refreshing).toBe(false);
  });

  it("guards against re-entrant clicks on the refresh button", async () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity({ accessToken: "tk1" }) },
    });
    let calls = 0;
    hass.callService.mockImplementation(async () => {
      calls += 1;
    });
    const card = mountCameraCard({ hass });
    card.shadowRoot.getElementById("refresh-btn").click();
    card.shadowRoot.getElementById("refresh-btn").click();
    await Promise.resolve();
    await Promise.resolve();
    expect(calls).toBe(1);
  });
});

describe("verisure-owa-camera-card-editor name field", () => {
  it("emits config-changed with name when the name textfield is typed into", () => {
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.setConfig({ entity: "camera.front_door" });
    editor.hass = makeHass({
      states: { "camera.front_door": makeCameraEntity() },
      entities: { "camera.front_door": { platform: "securitas" } },
    });
    document.body.appendChild(editor);

    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });

    const nameTf = editor.shadowRoot.querySelector("ha-textfield");
    expect(nameTf).not.toBeNull();
    nameTf.value = "Main Door";
    nameTf.dispatchEvent(new Event("input", { bubbles: true }));

    expect(captured?.name).toBe("Main Door");
  });

  it("removes the name key when the textfield is cleared", () => {
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.setConfig({ entity: "camera.front_door", name: "Old" });
    editor.hass = makeHass({
      states: { "camera.front_door": makeCameraEntity() },
      entities: { "camera.front_door": { platform: "securitas" } },
    });
    document.body.appendChild(editor);

    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });

    const nameTf = editor.shadowRoot.querySelector("ha-textfield");
    nameTf.value = "   ";
    nameTf.dispatchEvent(new Event("input", { bubbles: true }));

    expect(captured).not.toHaveProperty("name");
  });

  it("updates ha-form data on a second setConfig call without rebuilding the DOM", () => {
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.setConfig({ entity: "camera.front_door" });
    editor.hass = makeHass({
      states: { "camera.front_door": makeCameraEntity() },
      entities: { "camera.front_door": { platform: "securitas" } },
    });
    document.body.appendChild(editor);

    const firstForm = editor.shadowRoot.getElementById("entity-form");
    editor.setConfig({ entity: "camera.back_yard" });
    const secondForm = editor.shadowRoot.getElementById("entity-form");

    expect(secondForm).toBe(firstForm);
    expect(secondForm.data).toEqual({ entity: "camera.back_yard" });
  });
});

describe("verisure-owa-camera-card defensive defaults", () => {
  it("uses empty token when access_token is missing", () => {
    const hass = makeHass({
      states: {
        [ENTITY]: { state: "idle", attributes: { friendly_name: "C" } },
      },
    });
    const card = mountCameraCard({ hass });
    expect(card.shadowRoot.querySelector("img").getAttribute("src")).toBe(
      `/api/camera_proxy/${ENTITY}?token=`,
    );
  });

  it("renders without a .timestamp overlay when image_timestamp is missing", () => {
    const card = mountCameraCard({
      hass: makeHass({ states: { [ENTITY]: makeCameraEntity() } }),
    });
    expect(card.shadowRoot.querySelector(".timestamp")).toBeNull();
  });

  it("uses config.name when both name and device entry are present", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { device_id: "dev1", platform: "securitas" } },
      devices: { dev1: { name: "Device" } },
    });
    const card = mountCameraCard({ config: { name: "Override" }, hass });
    expect(card.shadowRoot.querySelector(".name").textContent).toBe("Override");
  });

  it("_findFullEntity returns null when the camera entry has no device_id", () => {
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities: { [ENTITY]: { platform: "securitas" } },
    });
    const card = mountCameraCard({ hass });
    // Without a device_id the lookup returns null and the click goes to the thumbnail.
    let captured = null;
    card.addEventListener("hass-more-info", (e) => {
      captured = e.detail.entityId;
    });
    card.shadowRoot.getElementById("img-wrapper").click();
    expect(captured).toBe(ENTITY);
  });

  it("_entitiesByDeviceId reuses its cache when hass.entities is unchanged", () => {
    const entities = {
      [ENTITY]: { device_id: "dev1", platform: "securitas" },
      "camera.test_full_image": { device_id: "dev1", platform: "securitas" },
    };
    const hass = makeHass({
      states: { [ENTITY]: makeCameraEntity() },
      entities,
    });
    const card = mountCameraCard({ hass });
    // Force a re-render with the same hass.entities reference.
    card.hass = hass;

    expect(card._entitiesRef).toBe(entities);
  });
});

describe("verisure-owa-camera-card static helpers", () => {
  it("getCardSize returns 3", () => {
    const card = mountCameraCard({
      hass: makeHass({ states: { [ENTITY]: makeCameraEntity() } }),
    });
    expect(card.getCardSize()).toBe(3);
  });

  it("getConfigElement returns the matching editor element", () => {
    const ctor = customElements.get("verisure-owa-camera-card");
    const el = ctor.getConfigElement();
    expect(el.tagName.toLowerCase()).toBe("verisure-owa-camera-card-editor");
  });

  it("getStubConfig picks the first non-full-image camera entity", () => {
    const ctor = customElements.get("verisure-owa-camera-card");
    const hass = makeHass({
      states: {
        "camera.x_full_image": makeCameraEntity(),
        "camera.front_door": makeCameraEntity(),
        "light.kitchen": { state: "on", attributes: {} },
      },
      entities: {
        "camera.x_full_image": { platform: "securitas" },
        "camera.front_door": { platform: "securitas" },
      },
    });
    const stub = ctor.getStubConfig(hass);
    expect(stub.entity).toBe("camera.front_door");
  });

  it("getStubConfig returns empty entity when no eligible cameras exist", () => {
    const ctor = customElements.get("verisure-owa-camera-card");
    expect(ctor.getStubConfig(makeHass()).entity).toBe("");
  });
});
