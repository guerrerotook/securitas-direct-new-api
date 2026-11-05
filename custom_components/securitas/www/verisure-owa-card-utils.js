// Shared utilities for the Verisure OWA Lovelace cards.

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

// Home Assistant 2026.11 removed ha-textfield in favour of ha-input. Both report
// what was typed as `value` on the target of their `input` event.
export function createTextField(label, value, placeholder) {
  const tag = customElements.get("ha-input") ? "ha-input" : "ha-textfield";
  const field = document.createElement(tag);
  field.label = label;
  field.value = value;
  field.placeholder = placeholder;
  return field;
}

export function resolveEntityName(hass, stateObj, configName) {
  if (typeof hass?.formatEntityName === "function") {
    try {
      return hass.formatEntityName(stateObj, configName);
    } catch (_) {
      // Older/minimal HA clients may not expose all entity registries needed
      // by structured entity-name configs. Fall back to the friendly name.
    }
  }
  if (typeof configName === "string") return configName;
  const nameItems = Array.isArray(configName) ? configName : configName ? [configName] : [];
  if (nameItems.length && nameItems.every((item) => item?.type === "text")) {
    return nameItems.map((item) => item.text || "").join(" ");
  }
  return stateObj.attributes.friendly_name || stateObj.entity_id;
}
