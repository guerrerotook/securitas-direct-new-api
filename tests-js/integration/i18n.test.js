import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// i18n a11y guard — runs in the pre-push hook (npm test) and the JS CI on every
// card change. It scans the card render code for user-facing aria-label / title
// values that are hardcoded English literals instead of localized (`${_t(...)}`)
// or dynamic (`${...}`). Adding a hardcoded English aria-label/title fails here.
//
// Translation-table completeness — every language defines every `en` key with a
// non-empty value ("never English-fallback") — is enforced separately, and more
// thoroughly (nested keys), by tests-js/unit/translations.test.js. The PIN
// keypad keeps a dedicated rendered-aria check in keypad-a11y.test.js.
//
// Known limits (deliberately NOT covered here): an icon-only element with no
// aria-label at all, hardcoded English in placeholder / textContent / visible
// text, or a non-en value left equal to English.

const wwwDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../custom_components/securitas/www",
);
// Rendering card modules only; skip the legacy shims, the pure-util module, and
// the translation-only shared module (no render code).
const files = readdirSync(wwwDir).filter(
  (f) =>
    f.endsWith(".js") &&
    !f.startsWith("securitas-") &&
    f !== "verisure-owa-card-utils.js" &&
    f !== "verisure-owa-alarm-shared.js",
);

// Matches aria-label="..." or title='...' in either quote style.
const ATTR_RE = /\b(aria-label|title)=(["'])(.*?)\2/g;

describe("card aria-label/title are localized, not English literals", () => {
  for (const file of files) {
    it(`${file}`, () => {
      const src = readFileSync(join(wwwDir, file), "utf8");
      const hardcoded = [];
      let m;
      while ((m = ATTR_RE.exec(src)) !== null) {
        const value = m[3];
        if (value.includes("${")) continue; // localized/dynamic interpolation
        if (!/[A-Za-z]/.test(value)) continue; // symbols only (e.g. dots)
        hardcoded.push(`${m[1]}=${m[2]}${value}${m[2]}`);
      }
      expect({ file, hardcoded }).toEqual({ file, hardcoded: [] });
    });
  }
});
