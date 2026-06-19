// Shared utilities for the Verisure OWA Lovelace cards.
//
// Imported by the other card modules with a ?v=<version> cache-bust query, so
// the static path can be served with cache_headers=True (long max-age) without
// pinning a stale copy: each release changes the query and the browser
// re-fetches. Keep the ?v= in sync with the integration version — enforced by
// tests-js/integration/card-cache-busting.test.js.

export function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Lookup a translation table entry by flat or dot-path key, with English fallback
// and {var} interpolation. Each card passes its own TRANSLATIONS table.
export function formatTranslation(lang, translations, key, vars) {
  const enTable = translations.en || {};
  const langTable =
    translations[lang] ||
    translations[lang?.split("-")[0]] ||
    enTable;
  const lookup = (table) =>
    key.split(".").reduce(
      (acc, k) => (acc != null && acc[k] !== undefined ? acc[k] : null),
      table,
    );
  let v = lookup(langTable);
  if (v == null) v = lookup(enTable) || key;
  if (vars) {
    for (const [name, val] of Object.entries(vars)) {
      // Use a function replacement so "$" sequences in the value (e.g. "$&", "$1")
      // aren't interpreted as special replacement patterns by String.replace.
      const safe = String(val);
      v = v.replace(new RegExp(`\\{${name}\\}`, "g"), () => safe);
    }
  }
  return v;
}
