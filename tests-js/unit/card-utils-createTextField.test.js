import { afterEach, describe, expect, it, vi } from "vitest";
import { createTextField } from "../../custom_components/securitas/www/verisure-owa-card-utils.js";

function registerOnly(...tags) {
  vi.spyOn(customElements, "get").mockImplementation((tag) =>
    tags.includes(tag) ? class extends HTMLElement {} : undefined,
  );
}

describe("createTextField", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses ha-input when Home Assistant has it", () => {
    registerOnly("ha-input");
    expect(createTextField("Name", "", "").localName).toBe("ha-input");
  });

  it("prefers ha-input when both are registered", () => {
    registerOnly("ha-input", "ha-textfield");
    expect(createTextField("Name", "", "").localName).toBe("ha-input");
  });

  it("falls back to ha-textfield on an older Home Assistant", () => {
    registerOnly("ha-textfield");
    expect(createTextField("Name", "", "").localName).toBe("ha-textfield");
  });

  it.each(["ha-input", "ha-textfield"])("sets label, value and placeholder on %s", (tag) => {
    registerOnly(tag);
    const field = createTextField("Name", "Front door", "Type a name");
    expect(field.label).toBe("Name");
    expect(field.value).toBe("Front door");
    expect(field.placeholder).toBe("Type a name");
  });

  it.each(["ha-input", "ha-textfield"])("exposes the typed value on %s's input event", (tag) => {
    registerOnly(tag);
    const field = createTextField("Name", "", "");
    let seen;
    field.addEventListener("input", (event) => {
      seen = event.target.value;
    });
    field.value = "Typed";
    field.dispatchEvent(new Event("input", { bubbles: true }));
    expect(seen).toBe("Typed");
  });
});
