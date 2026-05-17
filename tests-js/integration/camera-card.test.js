import { describe, it, expect } from "vitest";
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
