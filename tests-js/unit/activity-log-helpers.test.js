import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  hassLang,
  relativeTime,
  formatActor,
  renderExceptions,
  renderRows,
  DETAIL_FIELDS,
} from "../../custom_components/securitas/www/verisure-owa-activity-log-card.js";

describe("hassLang", () => {
  it("prefers hass.locale.language", () => {
    expect(hassLang({ locale: { language: "fr" }, language: "en" })).toBe("fr");
  });

  it("falls back to hass.language", () => {
    expect(hassLang({ language: "it" })).toBe("it");
  });

  it("returns 'en' for null hass", () => {
    expect(hassLang(null)).toBe("en");
  });
});

describe("relativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-17T12:00:00"));
  });
  afterEach(() => vi.useRealTimers());

  it("returns empty string for falsy / short input", () => {
    expect(relativeTime("", "en")).toBe("");
    expect(relativeTime("2026-05", "en")).toBe("");
    expect(relativeTime(null, "en")).toBe("");
  });

  it("returns empty string for unparseable date", () => {
    expect(relativeTime("not-a-date-string-XXX", "en")).toBe("");
  });

  it("formats a recent time in seconds", () => {
    expect(relativeTime("2026-05-17 11:59:50", "en")).toMatch(/second/i);
  });

  it("formats minutes-ago", () => {
    expect(relativeTime("2026-05-17 11:45:00", "en")).toMatch(/minute/i);
  });

  it("formats hours-ago", () => {
    expect(relativeTime("2026-05-17 09:00:00", "en")).toMatch(/hour/i);
  });

  it("formats days-ago", () => {
    expect(relativeTime("2026-05-10 12:00:00", "en")).toMatch(/day/i);
  });
});

describe("formatActor", () => {
  it("prefers verisure_user with 'by' label", () => {
    expect(formatActor({ verisure_user: "Luci" }, "en")).toContain("Luci");
  });

  it("falls back to device_name in parentheses", () => {
    expect(formatActor({ device_name: "Kitchen" }, "en")).toBe("(Kitchen)");
  });

  it("returns empty string when neither is present", () => {
    expect(formatActor({}, "en")).toBe("");
  });

  it("escapes HTML in actor names", () => {
    expect(formatActor({ device_name: "<x>" }, "en")).toBe("(&lt;x&gt;)");
  });
});

describe("renderExceptions", () => {
  it("returns empty string for empty / non-array input", () => {
    expect(renderExceptions([], "en")).toBe("");
    expect(renderExceptions(null, "en")).toBe("");
  });

  it("renders a list with alias and status", () => {
    const html = renderExceptions([{ alias: "Door", status_key: "open" }], "en");
    expect(html).toContain("<ul");
    expect(html).toContain("Door");
  });

  it("escapes HTML in alias", () => {
    const html = renderExceptions([{ alias: "<x>", status_key: "open" }], "en");
    expect(html).toContain("&lt;x&gt;");
    expect(html).not.toContain("<x>");
  });
});

describe("renderRows", () => {
  it("emits one <tr> per non-empty DETAIL_FIELDS entry", () => {
    const html = renderRows({ time: "12:00", alias: "Door", type: "open" }, "en");
    expect(html.match(/<tr>/g)?.length).toBe(3);
  });

  it("skips empty / null / 0 values", () => {
    const html = renderRows({ time: "12:00", alias: "", type: null, device: 0 }, "en");
    expect(html.match(/<tr>/g)?.length).toBe(1);
  });

  it("renders exceptions through renderExceptions", () => {
    const html = renderRows({ exceptions: [{ alias: "Door", status_key: "open" }] }, "en");
    expect(html).toContain("<ul");
  });

  it("stringifies objects/arrays as pretty JSON in <pre>", () => {
    const html = renderRows({ media_platform: { kind: "snapshot" } }, "en");
    expect(html).toContain("<pre>");
    expect(html).toContain("snapshot");
  });
});

describe("DETAIL_FIELDS", () => {
  it("is a non-empty list of strings", () => {
    expect(Array.isArray(DETAIL_FIELDS)).toBe(true);
    expect(DETAIL_FIELDS.length).toBeGreaterThan(0);
    DETAIL_FIELDS.forEach((f) => expect(typeof f).toBe("string"));
  });
});
