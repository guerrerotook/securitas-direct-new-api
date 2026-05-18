import { describe, it, expect } from "vitest";
import "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeCameraEntity } from "../fixtures/entities.js";

describe("verisure-owa-camera-card-editor", () => {
  it("registers as a custom element", () => {
    expect(customElements.get("verisure-owa-camera-card-editor")).toBeDefined();
  });

  it("excludes full-image cameras from the entity picker via ha-form schema", () => {
    // The editor delegates entity selection to HA's <ha-form> with an entity
    // selector — the camera dropdown is resolved lazily by HA at runtime, not
    // embedded in the editor's shadow DOM. We assert on the ha-form schema
    // instead: the selector must scope to the camera domain and carry an
    // exclude_entities list of the full-image variants from findFullImageEntityIds.
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.setConfig({ entity: "camera.front_door" });
    editor.hass = makeHass({
      states: {
        "camera.front_door": makeCameraEntity(),
        "camera.front_door_full_image": makeCameraEntity(),
        "camera.back_yard": makeCameraEntity(),
        "camera.back_yard_full_image_2": makeCameraEntity(),
      },
      entities: {
        "camera.front_door": { platform: "verisure_owa" },
        "camera.front_door_full_image": { platform: "verisure_owa" },
        "camera.back_yard": { platform: "securitas" },
        "camera.back_yard_full_image_2": { platform: "securitas" },
      },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm).not.toBeNull();
    expect(entityForm.tagName.toLowerCase()).toBe("ha-form");
    expect(entityForm.schema).toHaveLength(1);
    const [field] = entityForm.schema;
    expect(field.name).toBe("entity");
    expect(field.selector.entity.domain).toBe("camera");
    // Both full-image variants (one per supported platform alias) must be excluded.
    expect(field.selector.entity.exclude_entities).toEqual(
      expect.arrayContaining(["camera.front_door_full_image", "camera.back_yard_full_image_2"]),
    );
    expect(field.selector.entity.exclude_entities).toHaveLength(2);
    expect(entityForm.data).toEqual({ entity: "camera.front_door" });
  });

  it("omits exclude_entities when no full-image cameras exist", () => {
    // findFullImageEntityIds returns []; the editor must NOT add an empty
    // exclude_entities key (would over-constrain HA's entity selector).
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "camera.front_door": makeCameraEntity() },
      entities: { "camera.front_door": { platform: "verisure_owa" } },
    });
    document.body.appendChild(editor);

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    expect(entityForm.schema).toEqual([
      { name: "entity", selector: { entity: { domain: "camera" } } },
    ]);
  });

  it("dispatches config-changed when the entity ha-form emits value-changed", () => {
    // The editor wires to ha-form's "value-changed" event (HA convention).
    // happy-dom renders <ha-form> as a generic HTMLElement so we dispatch the
    // event the editor actually listens for.
    const editor = document.createElement("verisure-owa-camera-card-editor");
    editor.setConfig({});
    editor.hass = makeHass({
      states: { "camera.front_door": makeCameraEntity() },
      entities: { "camera.front_door": { platform: "verisure_owa" } },
    });
    document.body.appendChild(editor);

    let captured = null;
    editor.addEventListener("config-changed", (e) => {
      captured = e.detail.config;
    });

    const entityForm = editor.shadowRoot.getElementById("entity-form");
    entityForm.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { entity: "camera.front_door" } },
        bubbles: true,
        composed: true,
      }),
    );

    expect(captured?.entity).toBe("camera.front_door");
  });
});
