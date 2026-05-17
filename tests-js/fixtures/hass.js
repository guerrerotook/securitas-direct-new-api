import { vi } from "vitest";

export function makeHass(overrides = {}) {
  return {
    language: "en",
    locale: { language: overrides.language || "en" },
    states: {},
    entities: {},
    devices: {},
    callService: vi.fn(async () => {}),
    callWS: vi.fn(async () => ({})),
    ...overrides,
  };
}
