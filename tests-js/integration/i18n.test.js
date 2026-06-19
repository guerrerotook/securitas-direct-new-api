import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { TRANSLATIONS as ALARM } from "../../custom_components/securitas/www/verisure-owa-alarm-shared.js?v=5.4.0";
import { TRANSLATIONS as CAMERA } from "../../custom_components/securitas/www/verisure-owa-camera-card.js?v=5.4.0";
import { TRANSLATIONS as ACTIVITY } from "../../custom_components/securitas/www/verisure-owa-activity-log-card.js?v=5.4.0";

// i18n guard — runs in the pre-push hook (npm test) and the JS CI on every
// card change, so untranslated/partial strings can't reach a PR.
//
// (1) Translation-table parity: every language in each card's TRANSLATIONS must
//     define exactly the same keys as `en`, with non-empty values. This enforces
//     "always translate all languages — never English-fallback" structurally:
//     adding an `en` key without translating it in every language fails here.
// (2) No hardcoded user-facing attribute literals: aria-label / title in the
//     card render code must be localized (`${_t(...)}`) or dynamic (`${...}`),
//     not English string literals.

const CARDS = { alarm: ALARM, camera: CAMERA, activity: ACTIVITY };

describe("i18n translation-table parity", () => {
  for (const [name, T] of Object.entries(CARDS)) {
    const langs = Object.keys(T);
    const enKeys = Object.keys(T.en);
    describe(`${name}`, () => {
      it("defines more than one language", () => {
        expect(langs.length).toBeGreaterThan(1);
      });
      for (const lang of langs) {
        it(`${lang}: same keys as en, all non-empty`, () => {
          const table = T[lang];
          const result = {
            missing: enKeys.filter((k) => !(k in table)),
            extra: Object.keys(table).filter((k) => !(k in T.en)),
            empty: Object.keys(table).filter((k) => !String(table[k] ?? "").trim()),
          };
          expect(result).toEqual({ missing: [], extra: [], empty: [] });
        });
      }
    });
  }
});

describe("no hardcoded user-facing attribute strings in card render code", () => {
  const wwwDir = join(
    dirname(fileURLToPath(import.meta.url)),
    "../../custom_components/securitas/www",
  );
  // Only the rendering card modules; skip the legacy shims and the pure-util module.
  const files = readdirSync(wwwDir).filter(
    (f) =>
      f.endsWith(".js") &&
      !f.startsWith("securitas-") &&
      f !== "verisure-owa-card-utils.js" &&
      f !== "verisure-owa-alarm-shared.js",
  );
  const ATTR_RE = /\b(aria-label|title)="([^"]*)"/g;
  for (const file of files) {
    it(`${file}: aria-label/title are localized, not English literals`, () => {
      const src = readFileSync(join(wwwDir, file), "utf8");
      const hardcoded = [];
      let m;
      while ((m = ATTR_RE.exec(src)) !== null) {
        const value = m[2];
        if (value.includes("${")) continue; // localized/dynamic interpolation
        if (!/[A-Za-z]/.test(value)) continue; // symbols only (e.g. dots)
        hardcoded.push(`${m[1]}="${value}"`);
      }
      expect({ file, hardcoded }).toEqual({ file, hardcoded: [] });
    });
  }
});
