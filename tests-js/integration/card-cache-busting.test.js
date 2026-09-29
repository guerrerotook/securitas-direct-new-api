import { describe, it, expect } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// /verisure-owa-panel is served with a long max-age, so every URL a card
// module imports must change whenever the imported file's bytes change. Python
// stamps the registered entry points (const.py::_card_url); the relative
// imports between modules are stamped in the JS source as
// ?v=<first 8 hex of sha256(imported file)>-<manifest version>.
//
// Fix a failure with:  python3 scripts/stamp_card_imports.py

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "../..");
const wwwDir = join(root, "custom_components/securitas/www");
const manifest = JSON.parse(
  readFileSync(join(root, "custom_components/securitas/manifest.json"), "utf8"),
);
const VERSION = manifest.version;

// Static `from "./x.js…"`, side-effect `import "./x.js…"` and dynamic
// `import("./x.js…")`.
const IMPORT_RE = /\b(?:from\s+|import\s*\(?\s*)"\.\/([A-Za-z0-9._-]+\.js)([^"]*)"/g;

const wwwFiles = readdirSync(wwwDir).filter((f) => f.endsWith(".js"));

const expectedQueries = new Map();
const expectedQuery = (name) => {
  if (!expectedQueries.has(name)) {
    const hash = createHash("sha256")
      .update(readFileSync(join(wwwDir, name)))
      .digest("hex")
      .slice(0, 8);
    expectedQueries.set(name, `?v=${hash}-${VERSION}`);
  }
  return expectedQueries.get(name);
};

describe("card module relative imports are stamped with the imported file's content hash", () => {
  it("has a sane manifest version to stamp against", () => {
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });

  for (const file of wwwFiles) {
    it(`${file}: every relative import carries ?v=<hash8>-${VERSION}`, () => {
      const src = readFileSync(join(wwwDir, file), "utf8");
      const offenders = [];
      for (const [, name, query] of src.matchAll(IMPORT_RE)) {
        const want = expectedQuery(name);
        if (query !== want) offenders.push(`./${name}${query} (want ${want})`);
      }
      expect({ file, staleImports: offenders }).toEqual({
        file,
        staleImports: [],
      });
    });
  }

  it("the lazy Badge editor is imported with its own content stamp", () => {
    const src = readFileSync(join(wwwDir, "verisure-owa-alarm-chip.js"), "utf8");

    const query = src.match(/\bimport\("\.\/verisure-owa-alarm-badge-editor\.js([^"]*)"\)/)?.[1];

    expect(query).toBe(expectedQuery("verisure-owa-alarm-badge-editor.js"));
  });
});
