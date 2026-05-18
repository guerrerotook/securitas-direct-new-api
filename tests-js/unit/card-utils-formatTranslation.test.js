import { describe, it, expect } from "vitest";
import { formatTranslation } from "../../custom_components/securitas/www/verisure-owa-card-utils.js";

const T = {
  en: {
    hello: "Hello",
    nested: { deep: "Deep EN" },
    welcome: "Hi {name}, you have {count} items",
  },
  es: {
    hello: "Hola",
    nested: { deep: "Deep ES" },
    // welcome intentionally missing — should fall back to EN
  },
};

describe("formatTranslation", () => {
  it("returns the requested locale string for a flat key", () => {
    expect(formatTranslation("es", T, "hello")).toBe("Hola");
  });

  it("resolves dot-path keys", () => {
    expect(formatTranslation("es", T, "nested.deep")).toBe("Deep ES");
  });

  it("falls back to English when the locale lacks the key", () => {
    expect(formatTranslation("es", T, "welcome", { name: "Luci", count: 3 })).toBe(
      "Hi Luci, you have 3 items",
    );
  });

  it("falls back to language root when locale is a region tag", () => {
    expect(formatTranslation("es-AR", T, "hello")).toBe("Hola");
  });

  it("returns the key itself when missing in both target and English", () => {
    expect(formatTranslation("es", T, "missing.key")).toBe("missing.key");
  });

  it("interpolates {var} placeholders", () => {
    expect(formatTranslation("en", T, "welcome", { name: "A", count: 7 })).toBe(
      "Hi A, you have 7 items",
    );
  });

  it("does not treat $& / $1 in interpolated values as regex back-refs", () => {
    const T2 = { en: { msg: "Value: {v}" } };
    expect(formatTranslation("en", T2, "msg", { v: "$&" })).toBe("Value: $&");
    expect(formatTranslation("en", T2, "msg", { v: "$1$2" })).toBe("Value: $1$2");
  });

  it("handles null/undefined language by falling back to English", () => {
    expect(formatTranslation(null, T, "hello")).toBe("Hello");
    expect(formatTranslation(undefined, T, "hello")).toBe("Hello");
  });
});
