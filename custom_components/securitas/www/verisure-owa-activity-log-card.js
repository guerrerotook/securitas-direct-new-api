/**
 * Verisure OWA Activity Log Card
 *
 * Renders the alarm panel's activity timeline (xSActV2) as a clickable list.
 *
 * Reads from a sensor.<...>_activity_log entity created by the Verisure OWA
 * integration.  Each row shows:
 *   - icon for the event category (armed / alarm / power_cut / ...)
 *   - localised category label (e.g. "Armed") + actor ("by Luci" or "(Cucina)")
 *   - panel-language alias as a description
 *   - relative time ("5 minutes ago") in the user's HA locale
 *   - click to expand and show every populated field
 *
 * Card config:
 *   type: custom:verisure-owa-activity-log-card
 *   entity: sensor.home_activity_log    # required
 *   limit: 10                           # default 10, max 30
 *   title: "Recent activity"            # optional
 */

import { escHtml, formatTranslation } from "./verisure-owa-card-utils.js";

// ── Translations ─────────────────────────────────────────────────────────────

export const TRANSLATIONS = {
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
      communication_failed: "Communication failed",
      communication_restored: "Communication restored",
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
    verisure_record: "Verisure record",
    refresh: "Refresh",
    unknown_event_prompt: "Please screenshot this event and create an issue at https://github.com/guerrerotook/securitas-direct-new-api/issues so that we can document this unknown event type.",
    image_loading: "Loading image…",
    image_unavailable: "Image not available",
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
      communication_failed: "Fallo de comunicación",
      communication_restored: "Comunicación restablecida",
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
    verisure_record: "Registro de Verisure",
    refresh: "Actualizar",
    unknown_event_prompt: "Captura una imagen de este evento y abre una incidencia en https://github.com/guerrerotook/securitas-direct-new-api/issues para que podamos documentar este tipo de evento desconocido.",
    image_loading: "Cargando imagen…",
    image_unavailable: "Imagen no disponible",
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
      communication_failed: "Errore di comunicazione",
      communication_restored: "Comunicazione ripristinata",
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
    verisure_record: "Record di Verisure",
    refresh: "Aggiorna",
    unknown_event_prompt: "Fai uno screenshot di questo evento e apri una segnalazione su https://github.com/guerrerotook/securitas-direct-new-api/issues così possiamo documentare questo tipo di evento sconosciuto.",
    image_loading: "Caricamento immagine…",
    image_unavailable: "Immagine non disponibile",
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
      communication_failed: "Échec de communication",
      communication_restored: "Communication rétablie",
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
    verisure_record: "Enregistrement Verisure",
    refresh: "Actualiser",
    unknown_event_prompt: "Prenez une capture d'écran de cet événement et créez un ticket sur https://github.com/guerrerotook/securitas-direct-new-api/issues afin que nous puissions documenter ce type d'événement inconnu.",
    image_loading: "Chargement de l'image…",
    image_unavailable: "Image indisponible",
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
      communication_failed: "Falha de comunicação",
      communication_restored: "Comunicação restaurada",
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
    unknown_event_prompt: "Capture uma imagem deste evento e crie um problema em https://github.com/guerrerotook/securitas-direct-new-api/issues para podermos documentar este tipo de evento desconhecido.",
    image_loading: "A carregar imagem…",
    verisure_record: "Registo Verisure",
    image_unavailable: "Imagem não disponível",
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
      communication_failed: "Falha de comunicação",
      communication_restored: "Comunicação restaurada",
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
    unknown_event_prompt: "Faça uma captura de tela deste evento e crie uma issue em https://github.com/guerrerotook/securitas-direct-new-api/issues para podermos documentar este tipo de evento desconhecido.",
    image_loading: "Carregando imagem…",
    verisure_record: "Registro Verisure",
    image_unavailable: "Imagem indisponível",
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
      communication_failed: "Error de comunicació",
      communication_restored: "Comunicació restablerta",
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
    verisure_record: "Registre de Verisure",
    refresh: "Actualitza",
    unknown_event_prompt: "Feu una captura de pantalla d'aquest esdeveniment i obriu una incidència a https://github.com/guerrerotook/securitas-direct-new-api/issues perquè puguem documentar aquest tipus d'esdeveniment desconegut.",
    image_loading: "Carregant imatge…",
    image_unavailable: "Imatge no disponible",
  },
};

const _t = (lang, key, vars) => formatTranslation(lang, TRANSLATIONS, key, vars);

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
  communication_failed: "mdi:lan-disconnect",
  communication_restored: "mdi:lan-connect",
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
  communication_failed: "var(--error-color, #db4437)",
  communication_restored: "var(--success-color, #43a047)",
  unknown: "var(--secondary-text-color)",
};

// ── Utilities ─────────────────────────────────────────────────────────────────

export function hassLang(hass) {
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
export function relativeTime(timeStr, lang) {
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
export function formatActor(event, lang) {
  if (event.verisure_user) return `${_t(lang, "by")} ${escHtml(event.verisure_user)}`;
  if (event.device_name) return `(${escHtml(event.device_name)})`;
  return "";
}

// Fields shown in the expanded details block, in display order.
// Skipped: __typename (internal), category (already shown), the redundant
// signal_type (always equal to type in observed data).
export const DETAIL_FIELDS = [
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
export function renderExceptions(exceptions, lang) {
  if (!Array.isArray(exceptions) || exceptions.length === 0) return "";
  const items = exceptions.map((exc) => {
    const aliasText = exc.alias ? escHtml(exc.alias) : "";
    const statusText = escHtml(_t(lang, `exception_status.${exc.status_key || "unknown"}`));
    const dt = exc.device_type ? ` <span class="device-type">[${escHtml(exc.device_type)}]</span>` : "";
    return `<li>${aliasText} — <em>${statusText}</em>${dt}</li>`;
  });
  return `<ul class="exceptions">${items.join("")}</ul>`;
}

export function renderRows(event, lang) {
  const rows = [];
  for (const key of DETAIL_FIELDS) {
    const val = event[key];
    if (val == null || val === "" || val === 0) continue;
    let display;
    if (key === "exceptions") {
      display = renderExceptions(val, lang);
    } else if (Array.isArray(val) || (typeof val === "object" && val !== null)) {
      display = `<pre>${escHtml(JSON.stringify(val, null, 2))}</pre>`;
    } else {
      display = escHtml(String(val));
    }
    rows.push(`<tr><th>${escHtml(key)}</th><td>${display}</td></tr>`);
  }
  return rows.join("");
}

// ── Card ─────────────────────────────────────────────────────────────────────

class VerisureOwaActivityLogCard extends HTMLElement {
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
    // Lazy-fetch cache for image-request events.
    // Map<id_signal, { state: 'loading' | 'loaded' | 'error', dataUrl?: string }>
    this._imageCache = new Map();
    // Latest events list, kept so click handlers can resolve the event by id.
    this._latestEvents = [];
    // parent id_signal → [echo events], built each render to nest panel
    // echoes of HA actions inside their injected event's detail.
    this._duplicatesByParent = new Map();
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
      await this._hass.callService("verisure_owa", "refresh_activity_log", {
        entity_id: this._config.entity,
      });
    } catch (e) {
      // Ignore — fallback timer will clear the spinner.
    }
  }

  async _callServiceWithResponse(domain, service, data) {
    // Use callWS directly: hass.callService on older frontends silently
    // ignores the returnResponse arg (executes the service but returns
    // undefined), and a try/callService-then-fallback pattern would end
    // up calling the rate-limited service twice.  callWS has had a
    // stable return_response contract for years.
    try {
      const resp = await this._hass.callWS({
        type: "call_service",
        domain,
        service,
        service_data: data,
        return_response: true,
      });
      return resp?.response || resp?.service_response || null;
    } catch (e) {
      return null;
    }
  }

  connectedCallback() {
    // Pull fresh data as soon as the card is shown — when background polling
    // is off the coordinator only refreshes on demand, so a freshly-opened
    // dashboard would otherwise show stale data until the first tick.
    // _handleRefresh shows the spinner while the fetch is in flight.
    this._handleRefresh();
    // Every minute while mounted: pull again (so the log keeps updating while
    // viewed) and re-render so relative times ("3 minutes ago") stay current.
    // disconnectedCallback clears this, so refreshes stop when the card leaves
    // the screen — no per-minute API calls when nobody's looking.
    if (!this._tickTimer) {
      // _handleRefresh pulls fresh data and re-renders (so relative times
      // also advance). It's a no-op while a refresh is already in flight.
      this._tickTimer = setInterval(() => this._handleRefresh(), 60_000);
    }
  }

  disconnectedCallback() {
    if (this._tickTimer) {
      clearInterval(this._tickTimer);
      this._tickTimer = null;
    }
    // Cancel any in-flight refresh's fallback timer (and spinner) so a removed
    // card does no further work — connectedCallback/the tick start a refresh,
    // each of which arms an 8s fallback timeout that would otherwise survive
    // removal and fire a stray re-render.
    this._clearRefreshing();
  }

  getCardSize() {
    return Math.min(8, 1 + (this._config?.limit || 10));
  }

  static getConfigElement() {
    return document.createElement("verisure-owa-activity-log-card-editor");
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
    const lang = hassLang(this._hass);
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];
    this._lastRenderedState = stateObj;
    if (!stateObj) {
      this._writeShell(`<div class="missing">${escHtml(_t(lang, "entity_not_found", { entity: entityId }))}</div>`);
      return;
    }
    const events = stateObj.attributes?.events;
    if (!Array.isArray(events)) {
      this._writeShell(`<div class="missing">${escHtml(_t(lang, "not_an_activity_log", { entity: entityId }))}</div>`);
      return;
    }

    // Echoes of HA actions (duplicate_of set) are folded into their parent
    // injected event's detail, not shown as their own row.
    const duplicatesByParent = new Map();
    for (const ev of events) {
      const parent = ev.duplicate_of;
      if (!parent) continue;
      const arr = duplicatesByParent.get(parent) || [];
      arr.push(ev);
      duplicatesByParent.set(parent, arr);
    }
    this._duplicatesByParent = duplicatesByParent;

    const hidden = new Set(this._config.hide_categories || []);
    const visible = events.filter(
      (ev) => !ev.duplicate_of && !hidden.has(ev.category || "unknown"),
    );
    const limited = visible.slice(0, this._config.limit);
    this._latestEvents = limited;

    // Prune per-row state for events that have scrolled out of view —
    // otherwise _expanded and _imageCache grow unboundedly across days
    // (image cache entries hold the full data URL, not just a flag).
    const visibleIds = new Set(limited.map((ev) => String(ev.id_signal || "")));
    for (const id of this._expanded) {
      if (!visibleIds.has(id)) this._expanded.delete(id);
    }
    for (const id of this._imageCache.keys()) {
      if (!visibleIds.has(id)) this._imageCache.delete(id);
    }
    const body = limited.length
      ? limited.map((ev) => this._renderRow(ev, lang)).join("")
      : `<div class="empty">${escHtml(_t(lang, "no_events"))}</div>`;

    this._writeShell(body);
    // Wire refresh button
    const refreshBtn = this.shadowRoot.getElementById("refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._handleRefresh();
      });
    }
    // Wire row activation — click for mouse, Enter/Space for keyboard.
    const toggleRow = (row) => {
      const id = row.dataset.id;
      if (!id) return;
      const details = this.shadowRoot.querySelector(`.details-row[data-id="${CSS.escape(id)}"]`);
      if (this._expanded.has(id)) {
        this._expanded.delete(id);
        row.classList.remove("expanded");
        row.setAttribute("aria-expanded", "false");
        if (details) details.classList.remove("expanded");
      } else {
        this._expanded.add(id);
        row.classList.add("expanded");
        row.setAttribute("aria-expanded", "true");
        if (details) details.classList.add("expanded");
        // Lazy-fetch the historical image for any event the panel
        // tagged with an image (img=1) — image-request events as well
        // as photo-detector alarms ("Allarme Foto", type 14).  Skip
        // synthetic ids (prefix `ha-`) — those are HA-side placeholders
        // the Verisure server can't resolve.  Injected events from the
        // capture button use the real server id, so the fetch works
        // for them too.
        const event = this._latestEvents.find(
          (e) => String(e.id_signal || "") === id
        );
        if (
          event &&
          event.img === 1 &&
          !id.startsWith("ha-") &&
          !this._imageCache.has(id)
        ) {
          this._fetchEventImage(event);
        }
      }
    };
    // Drag threshold (px) for distinguishing a click from a text-selection drag.
    // Pointer travel of more than this many px between pointerdown and click
    // (strict > — a 4-px jitter still toggles) means the user was selecting
    // text, not tapping the row, so leave the row state alone.
    const DRAG_THRESHOLD = 4;
    this.shadowRoot.querySelectorAll(".event").forEach((row) => {
      let downX = 0;
      let downY = 0;
      row.addEventListener("pointerdown", (e) => {
        downX = e.clientX;
        downY = e.clientY;
      });
      row.addEventListener("click", (e) => {
        if (
          Math.abs(e.clientX - downX) > DRAG_THRESHOLD ||
          Math.abs(e.clientY - downY) > DRAG_THRESHOLD
        ) {
          return;
        }
        toggleRow(row);
      });
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleRow(row);
        }
      });
    });
  }

  async _fetchEventImage(event) {
    const id = String(event.id_signal || "");
    if (!id || this._imageCache.has(id)) return;
    this._imageCache.set(id, { state: "loading" });
    // Trigger a re-render so the spinner appears in the just-expanded details
    this._lastRenderedState = null;
    this._render();
    try {
      const result = await this._callServiceWithResponse(
        "verisure_owa",
        "fetch_activity_image",
        {
          entity_id: this._config.entity,
          id_signal: id,
          signal_type: String(event.signal_type ?? event.type ?? ""),
        },
      );
      // Entity services return a dict keyed by entity_id; unwrap.
      const payload = result?.[this._config.entity] ?? result;
      const b64 = payload?.image_b64;
      const mime = payload?.mime_type || "image/jpeg";
      if (b64) {
        this._imageCache.set(id, {
          state: "loaded",
          dataUrl: `data:${mime};base64,${b64}`,
        });
      } else {
        // eslint-disable-next-line no-console
        console.warn(
          "[verisure-owa-activity-log-card] fetch_activity_image returned no image_b64; result:",
          result,
        );
        this._imageCache.set(id, { state: "error" });
      }
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("[verisure-owa-activity-log-card] fetch_activity_image threw:", e);
      this._imageCache.set(id, { state: "error" });
    }
    this._lastRenderedState = null;
    this._render();
  }

  _renderRow(event, lang) {
    const cat = event.category || "unknown";
    const icon = CATEGORY_ICONS[cat] || CATEGORY_ICONS.unknown;
    const color = CATEGORY_COLORS[cat] || CATEGORY_COLORS.unknown;
    const label = _t(lang, `category.${cat}`);
    const actor = formatActor(event, lang);
    const rel = relativeTime(event.time, lang);
    const id = String(event.id_signal || "");
    const isExpanded = this._expanded.has(id);
    const isInjected = event.injected === true;
    const injectedBadge = isInjected
      ? `<ha-icon class="injected-badge" icon="mdi:home-assistant" title="${escHtml(_t(lang, "from_home_assistant"))}"></ha-icon>`
      : "";
    const duplicates = this._duplicatesByParent?.get(id) || [];
    const detailsId = `details-${escHtml(id)}`;
    return `
      <div class="event${isExpanded ? " expanded" : ""}${isInjected ? " injected" : ""}" data-id="${escHtml(id)}" role="button" tabindex="0" aria-expanded="${isExpanded}" aria-controls="${detailsId}">
        <ha-icon icon="${escHtml(icon)}" style="color:${color}"></ha-icon>
        <div class="meta">
          <div class="line1">
            <span class="category" style="color:${color}">${escHtml(label)}</span>${actor ? ` <span class="actor">${actor}</span>` : ""}${injectedBadge}
          </div>
          <div class="line2">${escHtml(event.alias || "")}</div>
        </div>
        <div class="time" title="${escHtml(event.time || "")}">${escHtml(rel)}</div>
      </div>
      <div class="details-row ${isExpanded ? "expanded" : ""}" id="${detailsId}" data-id="${escHtml(id)}">
        ${this._renderDetails(event, lang, duplicates)}
      </div>
    `;
  }

  _renderDetails(event, lang, duplicates = []) {
    const imageBlock = event.img === 1 ? this._renderImageBlock(event) : "";
    const prompt =
      event.category === "unknown"
        ? `<div class="unknown-prompt">${escHtml(_t(lang, "unknown_event_prompt"))}</div>`
        : "";
    // The matched panel echo(es) of this HA action — kept out of the main
    // list, surfaced here because the panel's `type`/native alias is richer
    // than our generic injected row.
    const dupBlocks = duplicates
      .map(
        (d) => `
        <div class="duplicate-record">
          <div class="duplicate-record-header">${escHtml(_t(lang, "verisure_record"))}</div>
          <table class="details">${renderRows(d, lang)}</table>
        </div>`,
      )
      .join("");
    return `${imageBlock}${prompt}<table class="details">${renderRows(event, lang)}</table>${dupBlocks}`;
  }

  _renderImageBlock(event) {
    const lang = hassLang(this._hass);
    const id = String(event.id_signal || "");
    // Synthetic ids (prefix `ha-`) can't resolve to a server-side image.
    if (id.startsWith("ha-")) return "";
    const cached = this._imageCache.get(id);
    const alt = escHtml(event.device_name || "");
    if (cached?.state === "loaded" && cached.dataUrl) {
      return `<img class="event-image" src="${cached.dataUrl}" alt="${alt}" />`;
    }
    if (cached?.state === "error") {
      return `<div class="event-image-error">${escHtml(_t(lang, "image_unavailable"))}</div>`;
    }
    // Loading or not-yet-fetched (the row's expand handler kicks off the
    // fetch on first click; both states render the same placeholder).
    return `
      <div class="event-image-loading">
        <ha-icon icon="mdi:loading" class="spin"></ha-icon>
        <span>${escHtml(_t(lang, "image_loading"))}</span>
      </div>`;
  }


  _writeShell(bodyHtml) {
    // Preserve scroll position across re-renders — replacing innerHTML
    // resets it, so capture scrollTop before the replace and restore
    // after.  Without this, expanding a row that triggers a render
    // (e.g. lazy image fetch) jumps the user back to the top.
    const prevScroll = this.shadowRoot.querySelector(".scroll")?.scrollTop || 0;
    const lang = hassLang(this._hass);
    const titleHtml = this._config.title
      ? `<div class="card-header">${escHtml(this._config.title)}</div>`
      : "";
    const refreshLabel = escHtml(_t(lang, "refresh"));
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
          /* HA's Lovelace shell inherits user-select: none into our shadow
             tree; explicitly opt back in so users can highlight the alias
             / actor text on the row. The pointerdown/click handler wired
             in _render() filters out drags so selection doesn't also
             toggle the row. */
          user-select: text;
          -webkit-user-select: text;
        }
        .event:first-of-type { border-top: 0; }
        .event:hover { background: var(--secondary-background-color, rgba(0,0,0,.03)); }
        .event:focus-visible {
          outline: 2px solid var(--primary-color, #03a9f4);
          outline-offset: -2px;
        }
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
          user-select: text;
          -webkit-user-select: text;
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
        img.event-image {
          display: block;
          max-width: 100%;
          margin: 0 auto 8px auto;
          border-radius: 4px;
          background: var(--secondary-background-color);
        }
        .event-image-loading, .event-image-error {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 24px 8px;
          margin-bottom: 8px;
          color: var(--secondary-text-color);
          font-size: 0.9em;
          background: var(--secondary-background-color, rgba(0,0,0,.04));
          border-radius: 4px;
        }
        .event-image-loading .spin {
          animation: spin 1s linear infinite;
          --mdc-icon-size: 18px;
        }
      </style>
      <ha-card>
        ${refreshBtn}
        ${titleHtml}
        <div class="scroll">${bodyHtml}</div>
      </ha-card>
    `;
    if (prevScroll) {
      // Defer until after the next paint so scrollHeight reflects the
      // re-rendered content; otherwise the browser clamps scrollTop to
      // an outdated (often 0) scrollHeight and the user is teleported
      // back to the top of the list.
      requestAnimationFrame(() => {
        const newScroll = this.shadowRoot.querySelector(".scroll");
        if (newScroll) newScroll.scrollTop = prevScroll;
      });
    }
  }
}

// ── Editor ────────────────────────────────────────────────────────────────────

class VerisureOwaActivityLogCardEditor extends HTMLElement {
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
    const lang = hassLang(this._hass);
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

/* v8 ignore start -- defensive duplicate-registration guards;
   the "already defined" branches can't be hit in single-process tests. */
if (!customElements.get("verisure-owa-activity-log-card"))
  customElements.define("verisure-owa-activity-log-card", VerisureOwaActivityLogCard);
if (!customElements.get("verisure-owa-activity-log-card-editor"))
  customElements.define("verisure-owa-activity-log-card-editor", VerisureOwaActivityLogCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "verisure-owa-activity-log-card")) {
  window.customCards.push({
    type: "verisure-owa-activity-log-card",
    name: "Verisure OWA Activity Log Card",
    description: "Shows recent activity log entries from a Verisure OWA installation.",
    preview: false,
    documentationURL:
      "https://github.com/guerrerotook/securitas-direct-new-api",
  });
}
/* v8 ignore stop */
