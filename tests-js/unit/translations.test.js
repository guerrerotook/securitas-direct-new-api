import { describe, it, expect } from "vitest";
import { TRANSLATIONS as ALARM } from "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { TRANSLATIONS as CAMERA } from "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { TRANSLATIONS as ACTIVITY } from "../../custom_components/securitas/www/verisure-owa-activity-log-card.js";

function flatKeys(obj, prefix = "") {
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      out.push(...flatKeys(v, path));
    } else {
      out.push(path);
    }
  }
  return out;
}

function lookup(table, path) {
  return path
    .split(".")
    .reduce((acc, k) => (acc != null && acc[k] !== undefined ? acc[k] : undefined), table);
}

describe.each([
  ["alarm card", ALARM],
  ["camera card", CAMERA],
  ["activity-log card", ACTIVITY],
])("%s translations", (_label, table) => {
  const enKeys = flatKeys(table.en);
  const locales = Object.keys(table).filter((l) => l !== "en");

  it("English table is non-empty", () => {
    expect(enKeys.length).toBeGreaterThan(0);
  });

  it.each(locales)("locale %s provides every English key as a non-empty string", (locale) => {
    const missing = [];
    for (const key of enKeys) {
      const v = lookup(table[locale], key);
      if (typeof v !== "string" || v.length === 0) missing.push(key);
    }
    // Compare a labelled string so failures surface the precise list of
    // missing keys (e.g. "missing in es: foo, bar.baz").
    expect(`missing in ${locale}: ${missing.join(", ")}`).toBe(`missing in ${locale}: `);
  });
});
