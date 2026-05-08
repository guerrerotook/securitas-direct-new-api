// Shared utilities for the Verisure OWA Lovelace cards.
//
// Loaded as an ES module (the cards' static path is served with
// cache_headers=False, so updates here propagate alongside card updates).

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
      v = v.replace(new RegExp(`\\{${name}\\}`, "g"), val);
    }
  }
  return v;
}
