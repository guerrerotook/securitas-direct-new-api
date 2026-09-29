import { describe, it, expect } from "vitest";
import { TRANSLATIONS as ALARM } from "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { TRANSLATIONS as CAMERA } from "../../custom_components/securitas/www/verisure-owa-camera-card.js";
import { TRANSLATIONS as ACTIVITY } from "../../custom_components/securitas/www/verisure-owa-activity-log-card.js";
import { ARM_EXCEPTION_TRANSLATIONS as ARM_EXCEPTION } from "../../custom_components/securitas/www/verisure-owa-arm-exception.js";

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
  ["arm-exception", ARM_EXCEPTION],
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

// Names as Home Assistant 2026.9's own translations spell them
// (ui.panel.lovelace.editor.card.tile.name, card.alarm-panel.name, the Entity
// badge, and the alarm_control_panel "triggered" state), so a user can find the
// replacement in the card picker and the card agrees with More Info.
describe("the alarm card names Home Assistant's cards and states as HA does", () => {
  const HA_NAMES = {
    en: { tile: "Tile", alarmPanel: "Alarm panel", badge: "Entity badge", triggered: "TRIGGERED" },
    ca: {
      tile: "Peça",
      alarmPanel: "Panell d'alarma",
      badge: "insígnia Entitat",
      triggered: "DISPARADA",
    },
    es: {
      tile: "Mosaico",
      alarmPanel: "Panel de alarma",
      badge: "insignia Entidad",
      triggered: "DISPARADA",
    },
    fr: {
      tile: "Tuile",
      alarmPanel: "Panneau d'alarme",
      badge: "badge Entité",
      triggered: "DÉCLENCHÉE",
    },
    it: {
      tile: "Mosaico",
      alarmPanel: "Pannello degli Allarmi",
      badge: "distintivo Entità",
      triggered: "INNESCATO",
    },
    pt: {
      tile: "Mosaico",
      alarmPanel: "Painel de alarme",
      badge: "crachá Entidade",
      triggered: "DISPARADO",
    },
    "pt-BR": {
      tile: "Bloco",
      alarmPanel: "Painel de alarme",
      badge: "emblema Entidade",
      triggered: "ACIONADO",
    },
  };

  it.each(Object.keys(HA_NAMES))("%s", (lang) => {
    const { tile, alarmPanel, badge, triggered } = HA_NAMES[lang];
    expect(ALARM[lang].deprecated_card).toContain(`${tile} `);
    expect(ALARM[lang].deprecated_card).toContain(alarmPanel);
    expect(ALARM[lang].deprecated_badge).toContain(badge);
    expect(ALARM[lang].triggered).toBe(triggered);
  });
});

// Home Assistant's Catalan UI labels buttons in the command form ("Cancel·la",
// "Tanca", "Activa, a fora"). The PIN prompt embeds a button label, so it must
// not read "per Arma fora".
describe("Catalan buttons use Home Assistant's command form", () => {
  it.each(["arm_away", "disarm", "cancel", "close", "confirm", "force_arm", "deprecated_dismiss"])(
    "%s",
    (key) => {
      expect(ALARM.ca[key]).not.toMatch(/^\S+(ar|ir|er|re)\b/u);
    },
  );

  it("puts the button label first in the PIN and code prompts", () => {
    expect(ALARM.ca.enter_pin.startsWith("{action}")).toBe(true);
    expect(ALARM.ca.enter_code.startsWith("{action}")).toBe(true);
  });
});
