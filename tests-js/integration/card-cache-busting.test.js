import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// The card static path is served with cache_headers=True (long max-age), so
// every served URL must be cache-busted or an update is pinned stale. The
// registered entry points are hash+version busted by Python (_card_url); their
// bare cross-module imports (`./verisure-owa-alarm-shared.js`,
// `./verisure-owa-card-utils.js`, the legacy shims' entry imports) are NOT seen
// by Python, so they must carry an explicit `?v=<version>` query in the JS
// source. This test fails the build if any relative import is missing the
// stamp or is out of sync with the integration version — so bumping the
// version can't silently leave a stale-serving import behind.
//
// On a version bump, re-stamp with:
//   sed -i '' -E 's#(("|/)[A-Za-z0-9._-]+\.js)\?v=[^"]*"#\1?v=<new-version>"#g' \
//     custom_components/securitas/www/*.js
// (or just set the `?v=` on each relative import to the new manifest version).

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "../..");
const wwwDir = join(root, "custom_components/securitas/www");
const manifest = JSON.parse(
  readFileSync(join(root, "custom_components/securitas/manifest.json"), "utf8"),
);
const VERSION = manifest.version;

// Matches `from "./x.js<query>"` and `import "./x.js<query>"` (side-effect).
const IMPORT_RE = /\b(?:from|import)\s+"(\.\/[A-Za-z0-9._-]+\.js)([^"]*)"/g;

const wwwFiles = readdirSync(wwwDir).filter((f) => f.endsWith(".js"));

describe("card module bare imports are cache-busted to the manifest version", () => {
  it("has a sane manifest version to stamp against", () => {
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });

  for (const file of wwwFiles) {
    it(`${file}: every relative import carries ?v=${VERSION}`, () => {
      const src = readFileSync(join(wwwDir, file), "utf8");
      const offenders = [];
      let m;
      while ((m = IMPORT_RE.exec(src)) !== null) {
        if (m[2] !== `?v=${VERSION}`) offenders.push(`${m[1]}${m[2]}`);
      }
      // On failure vitest prints this object, naming the file and the
      // un-stamped imports that need ?v=${VERSION}.
      expect({ file, unstampedImports: offenders }).toEqual({
        file,
        unstampedImports: [],
      });
    });
  }
});
