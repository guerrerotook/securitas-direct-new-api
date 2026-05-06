/**
 * Securitas Events Card
 *
 * Renders the alarm panel's activity timeline (xSActV2) as a clickable list.
 *
 * Reads from a sensor.<...>_activity_log entity created by the Securitas
 * integration.  Each row shows:
 *   - icon for the event category (armed / alarm / power_cut / ...)
 *   - localised category label (e.g. "Armed") + actor ("by Luci" or "(Cucina)")
 *   - panel-language alias as a description
 *   - relative time ("5 minutes ago") in the user's HA locale
 *   - click to expand and show every populated field
 *
 * Card config:
 *   type: custom:securitas-events-card
 *   entity: sensor.home_activity_log    # required
 *   limit: 10                           # default 10, max 30
 *   title: "Recent activity"            # optional
 */

// ── Translations ─────────────────────────────────────────────────────────────

const TRANSLATIONS = {
  en: {
    category: {
      armed: "Armed",
      armed_with_exceptions: "Armed with exceptions",
      arming_failed: "Arming failed",
      disarmed: "Disarmed",
      alarm: "Alarm",
      alarm_resolved: "Alarm resolved",
      tampering: "Tampering",
      sabotage: "Sabotage",
      image_request: "Image request",
      power_cut: "Power cut",
      power_restored: "Power restored",
      status_check: "Status check",
      unknown: "Unknown event",
    },
    exception_status: {
      open: "Open",
      battery_low: "Low battery",
      unknown: "Unknown",
    },
    by: "by",
    no_events: "No events recorded yet",
    entity_not_found: "Entity not found: {entity}",
    not_an_activity_log: "Entity is not an activity log: {entity}",
    details: "Details",
    from_home_assistant: "Issued by Home Assistant",
    refresh: "Refresh",
    unknown_event_prompt: "Unknown event type — please report at https://github.com/clintongormley/securitas-direct-new-api/issues so we can add it.",
  },
  es: {
    category: {
      armed: "Armado",
      armed_with_exceptions: "Armado con excepciones",
      arming_failed: "Armado fallido",
      disarmed: "Desarmado",
      alarm: "Alarma",
      alarm_resolved: "Alarma resuelta",
      tampering: "Manipulación",
      sabotage: "Sabotaje",
      image_request: "Petición de imagen",
      power_cut: "Corte de energía",
      power_restored: "Energía restablecida",
      status_check: "Comprobación de estado",
      unknown: "Evento desconocido",
    },
    exception_status: {
      open: "Abierto",
      battery_low: "Batería baja",
      unknown: "Desconocido",
    },
    by: "por",
    no_events: "Sin eventos registrados",
    entity_not_found: "Entidad no encontrada: {entity}",
    not_an_activity_log: "La entidad no es un registro de actividad: {entity}",
    details: "Detalles",
    from_home_assistant: "Emitido por Home Assistant",
    refresh: "Actualizar",
    unknown_event_prompt: "Tipo de evento desconocido — por favor, repórtalo en https://github.com/clintongormley/securitas-direct-new-api/issues para que podamos añadirlo.",
  },
  it: {
    category: {
      armed: "Armato",
      armed_with_exceptions: "Armato con eccezioni",
      arming_failed: "Armamento fallito",
      disarmed: "Disarmato",
      alarm: "Allarme",
      alarm_resolved: "Allarme risolto",
      tampering: "Manomissione",
      sabotage: "Sabotaggio",
      image_request: "Richiesta immagine",
      power_cut: "Interruzione di corrente",
      power_restored: "Corrente ripristinata",
      status_check: "Verifica di stato",
      unknown: "Evento sconosciuto",
    },
    exception_status: {
      open: "Aperto",
      battery_low: "Batteria scarica",
      unknown: "Sconosciuto",
    },
    by: "da",
    no_events: "Nessun evento registrato",
    entity_not_found: "Entità non trovata: {entity}",
    not_an_activity_log: "L'entità non è un registro attività: {entity}",
    details: "Dettagli",
    from_home_assistant: "Emesso da Home Assistant",
    refresh: "Aggiorna",
    unknown_event_prompt: "Tipo di evento sconosciuto — segnalalo su https://github.com/clintongormley/securitas-direct-new-api/issues così possiamo aggiungerlo.",
  },
  fr: {
    category: {
      armed: "Armé",
      armed_with_exceptions: "Armé avec exceptions",
      arming_failed: "Échec de l'armement",
      disarmed: "Désarmé",
      alarm: "Alarme",
      alarm_resolved: "Alarme résolue",
      tampering: "Manipulation",
      sabotage: "Sabotage",
      image_request: "Demande d'image",
      power_cut: "Coupure de courant",
      power_restored: "Courant rétabli",
      status_check: "Vérification de l'état",
      unknown: "Événement inconnu",
    },
    exception_status: {
      open: "Ouvert",
      battery_low: "Batterie faible",
      unknown: "Inconnu",
    },
    by: "par",
    no_events: "Aucun événement enregistré",
    entity_not_found: "Entité introuvable : {entity}",
    not_an_activity_log: "L'entité n'est pas un journal d'activité : {entity}",
    details: "Détails",
    from_home_assistant: "Émis par Home Assistant",
    refresh: "Actualiser",
    unknown_event_prompt: "Type d'événement inconnu — merci de le signaler sur https://github.com/clintongormley/securitas-direct-new-api/issues afin que nous puissions l'ajouter.",
  },
  pt: {
    category: {
      armed: "Armado",
      armed_with_exceptions: "Armado com exceções",
      arming_failed: "Falha ao armar",
      disarmed: "Desarmado",
      alarm: "Alarme",
      alarm_resolved: "Alarme resolvido",
      tampering: "Adulteração",
      sabotage: "Sabotagem",
      image_request: "Pedido de imagem",
      power_cut: "Corte de energia",
      power_restored: "Energia restaurada",
      status_check: "Verificação de estado",
      unknown: "Evento desconhecido",
    },
    exception_status: {
      open: "Aberto",
      battery_low: "Bateria fraca",
      unknown: "Desconhecido",
    },
    by: "por",
    no_events: "Sem eventos registados",
    entity_not_found: "Entidade não encontrada: {entity}",
    not_an_activity_log: "A entidade não é um registo de atividade: {entity}",
    details: "Detalhes",
    from_home_assistant: "Emitido pelo Home Assistant",
    refresh: "Atualizar",
    unknown_event_prompt: "Tipo de evento desconhecido — por favor reporte em https://github.com/clintongormley/securitas-direct-new-api/issues para o podermos adicionar.",
  },
  "pt-BR": {
    category: {
      armed: "Armado",
      armed_with_exceptions: "Armado com exceções",
      arming_failed: "Falha ao armar",
      disarmed: "Desarmado",
      alarm: "Alarme",
      alarm_resolved: "Alarme resolvido",
      tampering: "Adulteração",
      sabotage: "Sabotagem",
      image_request: "Solicitação de imagem",
      power_cut: "Corte de energia",
      power_restored: "Energia restaurada",
      status_check: "Verificação de status",
      unknown: "Evento desconhecido",
    },
    exception_status: {
      open: "Aberto",
      battery_low: "Bateria fraca",
      unknown: "Desconhecido",
    },
    by: "por",
    no_events: "Sem eventos registrados",
    entity_not_found: "Entidade não encontrada: {entity}",
    not_an_activity_log: "A entidade não é um registro de atividade: {entity}",
    details: "Detalhes",
    from_home_assistant: "Emitido pelo Home Assistant",
    refresh: "Atualizar",
    unknown_event_prompt: "Tipo de evento desconhecido — por favor reporte em https://github.com/clintongormley/securitas-direct-new-api/issues para podermos adicioná-lo.",
  },
  ca: {
    category: {
      armed: "Armat",
      armed_with_exceptions: "Armat amb excepcions",
      arming_failed: "Armament fallit",
      disarmed: "Desarmat",
      alarm: "Alarma",
      alarm_resolved: "Alarma resolta",
      tampering: "Manipulació",
      sabotage: "Sabotatge",
      image_request: "Petició d'imatge",
      power_cut: "Tall de corrent",
      power_restored: "Corrent restablert",
      status_check: "Comprovació d'estat",
      unknown: "Esdeveniment desconegut",
    },
    exception_status: {
      open: "Obert",
      battery_low: "Bateria baixa",
      unknown: "Desconegut",
    },
    by: "per",
    no_events: "Sense esdeveniments enregistrats",
    entity_not_found: "Entitat no trobada: {entity}",
    not_an_activity_log: "L'entitat no és un registre d'activitat: {entity}",
    details: "Detalls",
    from_home_assistant: "Emès per Home Assistant",
    refresh: "Actualitza",
    unknown_event_prompt: "Tipus d'esdeveniment desconegut — informeu-ho a https://github.com/clintongormley/securitas-direct-new-api/issues perquè el puguem afegir.",
  },
};

function _t(lang, key, vars) {
  const l = TRANSLATIONS[lang] || TRANSLATIONS[lang?.split("-")[0]] || TRANSLATIONS.en;
  let v = key.split(".").reduce((acc, k) => (acc && acc[k] !== undefined ? acc[k] : null), l);
  if (v == null) {
    // Fallback to English for missing keys
    v = key.split(".").reduce((acc, k) => (acc && acc[k] !== undefined ? acc[k] : null), TRANSLATIONS.en) || key;
  }
  if (vars) {
    for (const [name, val] of Object.entries(vars)) {
      v = v.replace(new RegExp(`\\{${name}\\}`, "g"), val);
    }
  }
  return v;
}

// ── Per-category icon and color ──────────────────────────────────────────────

const CATEGORY_ICONS = {
  armed: "mdi:shield-lock",
  armed_with_exceptions: "mdi:shield-alert",
  arming_failed: "mdi:shield-remove",
  disarmed: "mdi:shield-off",
  alarm: "mdi:alarm-light",
  alarm_resolved: "mdi:check-circle",
  tampering: "mdi:shield-edit",
  sabotage: "mdi:shield-bug",
  image_request: "mdi:camera",
  power_cut: "mdi:power-plug-off",
  power_restored: "mdi:power-plug",
  status_check: "mdi:lan-check",
  unknown: "mdi:help-circle",
};

const CATEGORY_COLORS = {
  armed: "var(--info-color, #039be5)",
  armed_with_exceptions: "var(--warning-color, #ff9800)",
  arming_failed: "var(--error-color, #db4437)",
  disarmed: "var(--success-color, #43a047)",
  alarm: "var(--error-color, #db4437)",
  alarm_resolved: "var(--success-color, #43a047)",
  tampering: "var(--warning-color, #ff9800)",
  sabotage: "var(--error-color, #db4437)",
  image_request: "var(--secondary-text-color)",
  power_cut: "var(--warning-color, #ff9800)",
  power_restored: "var(--success-color, #43a047)",
  status_check: "var(--secondary-text-color)",
  unknown: "var(--secondary-text-color)",
};

// ── Utilities ─────────────────────────────────────────────────────────────────

function _escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _hassLang(hass) {
  return hass?.locale?.language || hass?.language || "en";
}

const _RTF_CACHE = new Map();
function _rtf(lang) {
  let f = _RTF_CACHE.get(lang);
  if (!f) {
    f = new Intl.RelativeTimeFormat(lang || "en", { numeric: "auto" });
    _RTF_CACHE.set(lang, f);
  }
  return f;
}

/**
 * Render "X seconds/minutes/hours/days ago" using Intl.RelativeTimeFormat.
 * Treats the panel-local "YYYY-MM-DD HH:MM:SS" string as the user's local
 * timezone — correct in the common case where HA runs near the panel.
 */
function _relativeTime(timeStr, lang) {
  if (!timeStr || timeStr.length < 16) return "";
  // "2026-05-05 15:00:00" → "2026-05-05T15:00:00" → local Date
  const date = new Date(timeStr.replace(" ", "T"));
  if (isNaN(date.getTime())) return "";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = _rtf(lang);
  if (abs < 60) return rtf.format(seconds, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(seconds / 86400), "day");
  if (abs < 86400 * 365) return rtf.format(Math.round(seconds / (86400 * 30)), "month");
  return rtf.format(Math.round(seconds / (86400 * 365)), "year");
}

/** Format an event's actor as "by Luci" or "(Cucina)" or "" */
function _formatActor(event, lang) {
  if (event.verisure_user) return `${_t(lang, "by")} ${_escHtml(event.verisure_user)}`;
  if (event.device_name) return `(${_escHtml(event.device_name)})`;
  return "";
}

// Fields shown in the expanded details block, in display order.
// Skipped: __typename (internal), category (already shown), the redundant
// signal_type (always equal to type in observed data).
const DETAIL_FIELDS = [
  "time",
  "alias",
  "type",
  "device",
  "device_name",
  "source",
  "verisure_user",
  "interface",
  "id_signal",
  "incidence_id",
  "img",
  "scheduler_type",
  "keyname",
  "tag_id",
  "user_auth",
  "exceptions",
  "media_platform",
];

/** Render `exceptions[]` as a small list — "Pfincameret — Low battery" */
function _renderExceptions(exceptions, lang) {
  if (!Array.isArray(exceptions) || exceptions.length === 0) return "";
  const items = exceptions.map((exc) => {
    const aliasText = exc.alias ? _escHtml(exc.alias) : "";
    const statusText = _escHtml(_t(lang, `exception_status.${exc.status_key || "unknown"}`));
    const dt = exc.device_type ? ` <span class="device-type">[${_escHtml(exc.device_type)}]</span>` : "";
    return `<li>${aliasText} — <em>${statusText}</em>${dt}</li>`;
  });
  return `<ul class="exceptions">${items.join("")}</ul>`;
}

function _renderDetails(event, lang) {
  const rows = [];
  for (const key of DETAIL_FIELDS) {
    const val = event[key];
    if (val == null || val === "" || val === 0) continue;
    let display;
    if (key === "exceptions") {
      display = _renderExceptions(val, lang);
    } else if (Array.isArray(val) || (typeof val === "object" && val !== null)) {
      display = `<pre>${_escHtml(JSON.stringify(val, null, 2))}</pre>`;
    } else {
      display = _escHtml(String(val));
    }
    rows.push(`<tr><th>${_escHtml(key)}</th><td>${display}</td></tr>`);
  }
  const prompt =
    event.category === "unknown"
      ? `<div class="unknown-prompt">${_escHtml(_t(lang, "unknown_event_prompt"))}</div>`
      : "";
  return `${prompt}<table class="details">${rows.join("")}</table>`;
}

// ── Card ─────────────────────────────────────────────────────────────────────

class SecuritasEventsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    // Track which idSignals are currently expanded so we don't lose state
    // every time _render() rebuilds the DOM (each poll triggers a re-render).
    this._expanded = new Set();
    this._tickTimer = null;
    // The last `state` object identity we rendered against — HA replaces
    // the state object whenever a state changes, so identity-equality is
    // enough to skip rebuilds when nothing relevant has changed.
    this._lastRenderedState = null;
    this._refreshing = false;
    this._refreshFallbackTimer = null;
  }

  setConfig(config) {
    if (!config?.entity) {
      throw new Error("entity is required");
    }
    this._config = {
      entity: config.entity,
      limit: Math.max(1, Math.min(30, Number(config.limit) || 10)),
      title: config.title || "",
      // Max card height in CSS units; defaults to 400px when omitted.
      // Anything taller than this scrolls inside the card rather than
      // expanding the dashboard column.
      max_height: config.max_height || "400px",
      hide_categories: Array.isArray(config.hide_categories)
        ? config.hide_categories
        : [],
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // hass setter fires on EVERY state change in HA (every entity).
    // Skip the rebuild if our entity's state object hasn't changed —
    // HA replaces the state object on change, so identity equality
    // is sufficient.
    const stateObj = hass?.states?.[this._config?.entity];
    if (stateObj !== this._lastRenderedState) {
      // A state change after a manual refresh request — clear spin.
      if (this._refreshing) this._clearRefreshing();
      this._render();
    }
  }

  _clearRefreshing() {
    this._refreshing = false;
    if (this._refreshFallbackTimer) {
      clearTimeout(this._refreshFallbackTimer);
      this._refreshFallbackTimer = null;
    }
  }

  async _handleRefresh() {
    if (this._refreshing || !this._hass || !this._config?.entity) return;
    this._refreshing = true;
    this._lastRenderedState = null;
    this._render();
    // Fallback — clear spin even if no state update arrives (e.g. service
    // call rejected, or coordinator's data was unchanged).
    this._refreshFallbackTimer = setTimeout(() => {
      if (this._refreshing) {
        this._clearRefreshing();
        this._lastRenderedState = null;
        this._render();
      }
    }, 8000);
    try {
      // Routes through the integration's API queue at FOREGROUND priority,
      // ahead of the next scheduled 60s poll.
      await this._hass.callService("securitas", "refresh_activity_log", {
        entity_id: this._config.entity,
      });
    } catch (e) {
      // Ignore — fallback timer will clear the spinner.
    }
  }

  connectedCallback() {
    // Re-render every minute so relative times ("3 minutes ago") stay current.
    if (!this._tickTimer) {
      this._tickTimer = setInterval(() => {
        // Force a render even if state didn't change — clock advanced.
        this._lastRenderedState = null;
        this._render();
      }, 60_000);
    }
  }

  disconnectedCallback() {
    if (this._tickTimer) {
      clearInterval(this._tickTimer);
      this._tickTimer = null;
    }
  }

  getCardSize() {
    return Math.min(8, 1 + (this._config?.limit || 10));
  }

  static getConfigElement() {
    return document.createElement("securitas-events-card-editor");
  }

  static getStubConfig(hass) {
    // Auto-pick the first activity-log sensor by its attribute shape.
    const candidates = Object.entries(hass?.states || {})
      .filter(
        ([eid, state]) =>
          eid.startsWith("sensor.") && Array.isArray(state.attributes?.events)
      )
      .map(([eid]) => eid);
    return { entity: candidates[0] || "", limit: 10 };
  }

  _render() {
    if (!this._config || !this._hass) return;
    const lang = _hassLang(this._hass);
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];
    this._lastRenderedState = stateObj;
    if (!stateObj) {
      this._writeShell(`<div class="missing">${_escHtml(_t(lang, "entity_not_found", { entity: entityId }))}</div>`);
      return;
    }
    const events = stateObj.attributes?.events;
    if (!Array.isArray(events)) {
      this._writeShell(`<div class="missing">${_escHtml(_t(lang, "not_an_activity_log", { entity: entityId }))}</div>`);
      return;
    }

    const hidden = new Set(this._config.hide_categories || []);
    const visible = events.filter((ev) => !hidden.has(ev.category || "unknown"));
    const limited = visible.slice(0, this._config.limit);
    const body = limited.length
      ? limited.map((ev) => this._renderRow(ev, lang)).join("")
      : `<div class="empty">${_escHtml(_t(lang, "no_events"))}</div>`;

    this._writeShell(body);
    // Wire refresh button
    const refreshBtn = this.shadowRoot.getElementById("refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._handleRefresh();
      });
    }
    // Wire row clicks
    this.shadowRoot.querySelectorAll(".event").forEach((row) => {
      row.addEventListener("click", () => {
        const id = row.dataset.id;
        if (!id) return;
        const details = this.shadowRoot.querySelector(`.details-row[data-id="${CSS.escape(id)}"]`);
        if (this._expanded.has(id)) {
          this._expanded.delete(id);
          row.classList.remove("expanded");
          if (details) details.classList.remove("expanded");
        } else {
          this._expanded.add(id);
          row.classList.add("expanded");
          if (details) details.classList.add("expanded");
        }
      });
    });
  }

  _renderRow(event, lang) {
    const cat = event.category || "unknown";
    const icon = CATEGORY_ICONS[cat] || CATEGORY_ICONS.unknown;
    const color = CATEGORY_COLORS[cat] || CATEGORY_COLORS.unknown;
    const label = _t(lang, `category.${cat}`);
    const actor = _formatActor(event, lang);
    const rel = _relativeTime(event.time, lang);
    const id = String(event.id_signal || "");
    const isExpanded = this._expanded.has(id);
    const isInjected = event.injected === true;
    const injectedBadge = isInjected
      ? `<ha-icon class="injected-badge" icon="mdi:home-assistant" title="${_escHtml(_t(lang, "from_home_assistant"))}"></ha-icon>`
      : "";
    return `
      <div class="event${isExpanded ? " expanded" : ""}${isInjected ? " injected" : ""}" data-id="${_escHtml(id)}">
        <ha-icon icon="${_escHtml(icon)}" style="color:${color}"></ha-icon>
        <div class="meta">
          <div class="line1">
            <span class="category" style="color:${color}">${_escHtml(label)}</span>${actor ? ` <span class="actor">${actor}</span>` : ""}${injectedBadge}
          </div>
          <div class="line2">${_escHtml(event.alias || "")}</div>
        </div>
        <div class="time" title="${_escHtml(event.time || "")}">${_escHtml(rel)}</div>
      </div>
      <div class="details-row ${isExpanded ? "expanded" : ""}" data-id="${_escHtml(id)}">
        ${_renderDetails(event, lang)}
      </div>
    `;
  }

  _writeShell(bodyHtml) {
    const lang = _hassLang(this._hass);
    const titleHtml = this._config.title
      ? `<div class="card-header">${_escHtml(this._config.title)}</div>`
      : "";
    const refreshLabel = _escHtml(_t(lang, "refresh"));
    const refreshBtn = `
      <button class="refresh-btn${this._refreshing ? " spinning" : ""}" id="refresh-btn"
              type="button" title="${refreshLabel}" aria-label="${refreshLabel}">
        <ha-icon icon="mdi:refresh"></ha-icon>
      </button>`;
    const maxHeight = this._config.max_height || "400px";
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 8px 0; position: relative; }
        .scroll {
          max-height: ${maxHeight};
          overflow-y: auto;
        }
        .refresh-btn {
          position: absolute;
          top: 6px;
          right: 6px;
          width: 32px;
          height: 32px;
          padding: 0;
          border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
          border-radius: 50%;
          background: var(--card-background-color, #fff);
          color: var(--secondary-text-color);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 2;
          --mdc-icon-size: 18px;
        }
        .refresh-btn:hover { background: var(--secondary-background-color, rgba(0,0,0,.04)); }
        @keyframes spin { to { transform: rotate(360deg); } }
        .refresh-btn.spinning ha-icon { animation: spin 1s linear infinite; }
        .card-header {
          padding: 8px 48px 4px 16px;
          font-weight: 500;
          font-size: 1.1em;
        }
        .missing, .empty {
          padding: 24px 16px;
          color: var(--secondary-text-color);
          text-align: center;
        }
        .event {
          display: grid;
          grid-template-columns: 32px 1fr auto;
          align-items: center;
          gap: 12px;
          padding: 8px 16px;
          cursor: pointer;
          border-top: 1px solid var(--divider-color, rgba(0,0,0,.06));
        }
        .event:first-of-type { border-top: 0; }
        .event:hover { background: var(--secondary-background-color, rgba(0,0,0,.03)); }
        .event ha-icon { --mdc-icon-size: 24px; }
        .meta { min-width: 0; }
        .line1 {
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .actor { color: var(--secondary-text-color); font-weight: 400; }
        .event.injected { box-shadow: inset 3px 0 0 var(--info-color, #039be5); }
        .injected-badge {
          --mdc-icon-size: 14px;
          color: var(--info-color, #039be5);
          margin-left: 6px;
          vertical-align: middle;
          opacity: 0.75;
        }
        .line2 {
          color: var(--secondary-text-color);
          font-size: 0.9em;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .time {
          color: var(--secondary-text-color);
          font-size: 0.85em;
          white-space: nowrap;
        }
        .event.expanded { background: var(--secondary-background-color, rgba(0,0,0,.04)); }
        .details-row {
          display: none;
          padding: 4px 16px 12px 60px;
          background: var(--secondary-background-color, rgba(0,0,0,.04));
        }
        .details-row.expanded { display: block; }
        table.details {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.85em;
        }
        table.details th {
          text-align: left;
          padding: 2px 12px 2px 0;
          color: var(--secondary-text-color);
          font-weight: 400;
          width: 30%;
          vertical-align: top;
        }
        table.details td {
          padding: 2px 0;
          vertical-align: top;
          word-break: break-word;
        }
        table.details pre {
          margin: 0;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          font-size: 0.85em;
          white-space: pre-wrap;
        }
        ul.exceptions {
          margin: 0;
          padding-left: 16px;
        }
        ul.exceptions li { padding: 1px 0; }
        ul.exceptions em {
          font-style: normal;
          color: var(--warning-color, #ff9800);
        }
        ul.exceptions .device-type {
          color: var(--secondary-text-color);
          font-size: 0.85em;
        }
        .unknown-prompt {
          margin-bottom: 8px;
          padding: 6px 8px;
          font-size: 0.85em;
          color: var(--primary-text-color);
          background: var(--warning-color, #ff9800);
          border-radius: 4px;
          opacity: 0.85;
        }
        .unknown-prompt a { color: inherit; text-decoration: underline; }
      </style>
      <ha-card>
        ${refreshBtn}
        ${titleHtml}
        <div class="scroll">${bodyHtml}</div>
      </ha-card>
    `;
  }
}

// ── Editor ────────────────────────────────────────────────────────────────────

class SecuritasEventsCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
  }

  set hass(hass) {
    this._hass = hass;
    const entityForm = this.shadowRoot.getElementById("entity-form");
    if (entityForm) entityForm.hass = hass;
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this.shadowRoot.getElementById("entity-form")) {
      this._render();
    } else {
      const entityForm = this.shadowRoot.getElementById("entity-form");
      if (entityForm) {
        entityForm.data = this._formData();
      }
    }
  }

  _formData() {
    return {
      entity: this._config.entity || "",
      limit: this._config.limit || 10,
      title: this._config.title || "",
      max_height: this._config.max_height || "400px",
      hide_categories: Array.isArray(this._config.hide_categories)
        ? this._config.hide_categories
        : [],
    };
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; display: flex; flex-direction: column; gap: 8px; }
      </style>
      <div class="editor">
        <ha-form id="entity-form"></ha-form>
      </div>`;
    const entityForm = this.shadowRoot.getElementById("entity-form");
    entityForm.hass = this._hass;
    entityForm.data = this._formData();
    const lang = _hassLang(this._hass);
    const categoryOptions = Object.keys(CATEGORY_ICONS).map((c) => ({
      value: c,
      label: _t(lang, `category.${c}`),
    }));
    // Detect activity-log sensors by their attribute shape (an `events` array)
    // rather than by name.  Falls back to all sensors if none are loaded yet.
    const activityLogEntities = Object.entries(this._hass?.states || {})
      .filter(
        ([eid, state]) =>
          eid.startsWith("sensor.") && Array.isArray(state.attributes?.events)
      )
      .map(([eid]) => eid);
    const entitySelector = activityLogEntities.length
      ? { entity: { include_entities: activityLogEntities } }
      : { entity: { domain: "sensor" } };
    entityForm.schema = [
      {
        name: "entity",
        selector: entitySelector,
      },
      {
        name: "limit",
        selector: { number: { min: 1, max: 30, step: 1, mode: "slider" } },
      },
      { name: "title", selector: { text: {} } },
      { name: "max_height", selector: { text: {} } },
      {
        name: "hide_categories",
        selector: {
          select: { multiple: true, options: categoryOptions, mode: "list" },
        },
      },
    ];
    entityForm.computeLabel = (s) => {
      if (s.name === "entity") return "Activity log entity";
      if (s.name === "limit") return "Number of events to show";
      if (s.name === "title") return "Card title (optional)";
      if (s.name === "max_height") return "Max card height (e.g. 400px, 60vh)";
      if (s.name === "hide_categories") return "Categories to hide";
      return s.name;
    };
    entityForm.addEventListener("value-changed", (e) => {
      this._config = { ...this._config, ...e.detail.value };
      this.dispatchEvent(
        new CustomEvent("config-changed", { detail: { config: this._config } })
      );
    });
  }
}

// ── Registration ──────────────────────────────────────────────────────────────

if (!customElements.get("securitas-events-card"))
  customElements.define("securitas-events-card", SecuritasEventsCard);
if (!customElements.get("securitas-events-card-editor"))
  customElements.define("securitas-events-card-editor", SecuritasEventsCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "securitas-events-card")) {
  window.customCards.push({
    type: "securitas-events-card",
    name: "Securitas Events Card",
    description: "Shows recent alarm-panel events from a Securitas activity log entity.",
    preview: false,
    documentationURL:
      "https://github.com/Cebeerre/securitas-direct-new-api",
  });
}
