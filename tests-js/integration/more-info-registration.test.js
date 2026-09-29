import { afterEach, describe, expect, it, vi } from "vitest";

// The module loads on every page via add_extra_js_url, which can run before
// Home Assistant's app script installs its own custom-element registry.
// Defined before that swap, the element is missing from the registry HA reads.

const ELEMENT = "more-info-verisure-owa-alarm";
const nativeRegistry = globalThis.customElements;

afterEach(() => {
  globalThis.customElements = nativeRegistry;
});

describe("More Info element registration", () => {
  it("defines the element in the registry HA's app script installs", async () => {
    await import("../../custom_components/securitas/www/verisure-owa-more-info.js");
    expect(nativeRegistry.get(ELEMENT)).toBeUndefined();

    const appRegistry = { get: vi.fn(() => undefined), define: vi.fn() };
    globalThis.customElements = appRegistry;
    nativeRegistry.define("home-assistant", class extends HTMLElement {});
    await vi.waitFor(() => expect(appRegistry.define).toHaveBeenCalled());

    expect(appRegistry.define).toHaveBeenCalledWith(ELEMENT, expect.any(Function));
    expect(nativeRegistry.get(ELEMENT)).toBeUndefined();
  });
});
