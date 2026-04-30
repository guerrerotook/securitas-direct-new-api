/**
 * Securitas Camera Card
 *
 * Displays the latest image from a Securitas Direct camera entity with:
 *  - Auto-discovered refresh (capture) button in the top-right corner
 *  - Image timestamp overlay (relative + absolute tooltip)
 *  - Click to open the HA more-info dialog: for the auto-discovered
 *    full-resolution entity if available, otherwise the thumbnail entity
 *
 * Card config:
 *   type: custom:securitas-camera-card
 *   entity: camera.sala             # thumbnail entity (required)
 *   name: Sala                       # optional display name
 *   name: Front Door   # optional — overrides the device name
 */

// ── Translations ──────────────────────────────────────────────────────────────

const TRANSLATIONS = {
  en: {
    editor_entity: "Entity",
    editor_name: "Name",
    editor_name_placeholder: "Override friendly name",
    entity_not_found: "Entity not found: {entity}",
    ago_seconds: "{n}s ago",
    ago_minutes: "{n} min ago",
    ago_hours: "{n}h ago",
    ago_days: "{n}d ago",
    card_name: "Securitas Camera Card",
    card_description: "Displays a Securitas Direct camera image with capture trigger and timestamp.",
  },
  es: {
    editor_entity: "Entidad",
    editor_name: "Nombre",
    editor_name_placeholder: "Nombre personalizado",
    entity_not_found: "Entidad no encontrada: {entity}",
    ago_seconds: "hace {n}s",
    ago_minutes: "hace {n} min",
    ago_hours: "hace {n}h",
    ago_days: "hace {n}d",
    card_name: "Tarjeta de Cámara Securitas",
    card_description: "Muestra la imagen de una cámara Securitas Direct con captura y marca de tiempo.",
  },
  fr: {
    editor_entity: "Entité",
    editor_name: "Nom",
    editor_name_placeholder: "Remplacer le nom",
    entity_not_found: "Entité introuvable : {entity}",
    ago_seconds: "il y a {n}s",
    ago_minutes: "il y a {n} min",
    ago_hours: "il y a {n}h",
    ago_days: "il y a {n}j",
    card_name: "Carte Caméra Securitas",
    card_description: "Affiche l’image d’une caméra Securitas Direct avec capture et horodatage.",
  },
  it: {
    editor_entity: "Entità",
    editor_name: "Nome",
    editor_name_placeholder: "Nome personalizzato",
    entity_not_found: "Entità non trovata: {entity}",
    ago_seconds: "{n}s fa",
    ago_minutes: "{n} min fa",
    ago_hours: "{n}h fa",
    ago_days: "{n}g fa",
    card_name: "Scheda Camera Securitas",
    card_description: "Mostra l’immagine di una camera Securitas Direct con cattura e timestamp.",
  },
  pt: {
    editor_entity: "Entidade",
    editor_name: "Nome",
    editor_name_placeholder: "Nome personalizado",
    entity_not_found: "Entidade não encontrada: {entity}",
    ago_seconds: "há {n}s",
    ago_minutes: "há {n} min",
    ago_hours: "há {n}h",
    ago_days: "há {n}d",
    card_name: "Cartão de Câmara Securitas",
    card_description: "Mostra a imagem de uma câmara Securitas Direct com captura e marca temporal.",
  },
  "pt-BR": {
    editor_entity: "Entidade",
    editor_name: "Nome",
    editor_name_placeholder: "Substituir nome",
    entity_not_found: "Entidade não encontrada: {entity}",
    ago_seconds: "{n}s atrás",
    ago_minutes: "{n} min atrás",
    ago_hours: "{n}h atrás",
    ago_days: "{n}d atrás",
    card_name: "Cartão de Câmera Securitas",
    card_description: "Exibe a imagem de uma câmera Securitas Direct com captura e marca de tempo.",
  },
  ca: {
    editor_entity: "Entitat",
    editor_name: "Nom",
    editor_name_placeholder: "Sobreescriu el nom",
    entity_not_found: "Entitat no trobada: {entity}",
    ago_seconds: "fa {n}s",
    ago_minutes: "fa {n} min",
    ago_hours: "fa {n}h",
    ago_days: "fa {n}d",
    card_name: "Targeta de Càmera Verisure",
    card_description: "Mostra la imatge d’una càmera Verisure amb captura i marca de temps.",
  },
};

function _t(lang, key, vars) {
  const l = TRANSLATIONS[lang] || TRANSLATIONS[lang?.split("-")[0]] || TRANSLATIONS.en;
  let s = l[key] || TRANSLATIONS.en[key] || key;
  if (vars) Object.entries(vars).forEach(([k, v]) => { s = s.replace(`{${k}}`, v); });
  return s;
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function _escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Editor ────────────────────────────────────────────────────────────────────

class SecuritasCameraCardEditor extends HTMLElement {
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
    const fullForm = this.shadowRoot.getElementById("full-entity-form");
    if (fullForm) fullForm.hass = hass;
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this.shadowRoot.getElementById("entity-form")) {
      // First call — build the DOM once
      this._render();
    } else {
      // Subsequent calls (HA bouncing config back) — update pickers in place,
      // never touch the name textfield so focus is preserved while typing
      const entityForm = this.shadowRoot.getElementById("entity-form");
      if (entityForm) entityForm.data = { entity: this._config.entity || "" };
    }
  }

  _render() {
    const lang = this._hass?.language || "en";
    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; display: flex; flex-direction: column; gap: 8px; }
        ha-textfield { display: block; width: 100%; }
      </style>
      <div class="editor">
        <ha-form id="entity-form"></ha-form>
        <div id="name-slot"></div>
      </div>`;

    // Entity picker — filtered to camera domain
    const entityForm = this.shadowRoot.getElementById("entity-form");
    entityForm.hass = this._hass;
    entityForm.data = { entity: this._config.entity || "" };
    entityForm.schema = [
      { name: "entity", selector: { entity: { domain: "camera" } } },
    ];
    entityForm.computeLabel = () => _t(lang, "editor_entity");
    entityForm.addEventListener("value-changed", (e) => {
      const newEntity = e.detail.value?.entity;
      if (newEntity !== undefined) {
        this._config = { ...this._config, entity: newEntity };
        this._fireChanged();
      }
    });

    // Name field — ha-textfield with input event (no value-changed → no re-render cycle)
    const nameTf = document.createElement("ha-textfield");
    nameTf.label = _t(lang, "editor_name");
    nameTf.value = this._config.name || "";
    nameTf.placeholder = _t(lang, "editor_name_placeholder");
    nameTf.addEventListener("input", (e) => {
      const val = e.target.value;
      if (val.trim()) {
        this._config = { ...this._config, name: val };
      } else {
        const { name: _, ...rest } = this._config;
        this._config = rest;
      }
      this._fireChanged();
    });
    this.shadowRoot.getElementById("name-slot").appendChild(nameTf);
  }

  _fireChanged() {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
  }
}

// ── Main Card ─────────────────────────────────────────────────────────────────

class SecuritasCameraCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._captureEntityId = null;
    this._fullEntityId = null;
    this._refreshing = false;
    this._fallbackTimer = null;
  }

  setConfig(config) {
    if (!config.entity) throw new Error("'entity' is required");
    this._config = { ...config };
  }

  set hass(hass) {
    const prevToken = this._hass?.states[this._config.entity]?.attributes?.access_token;
    const newToken = hass?.states[this._config.entity]?.attributes?.access_token;
    this._hass = hass;
    this._captureEntityId = this._findCaptureButton(hass, this._config.entity);
    this._fullEntityId = this._findFullEntity(hass, this._config.entity);
    // Clear spinner when the image token rotates (new image available) and
    // the capture is no longer in progress (capturing=false means final image).
    const capturing = hass?.states[this._config.entity]?.attributes?.capturing;
    if (this._refreshing && newToken && newToken !== prevToken && !capturing) {
      clearTimeout(this._fallbackTimer);
      this._refreshing = false;
    }
    this._render();
  }

  _render() {
    const entityId = this._config.entity;
    const lang = this._hass?.language || "en";
    const stateObj = this._hass?.states[entityId];

    if (!stateObj) {
      this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding:16px;color:var(--error-color)">
          ${_escHtml(_t(lang, "entity_not_found", { entity: entityId }))}
        </div>
      </ha-card>`;
      return;
    }

    const token = stateObj.attributes.access_token || "";
    const imgUrl = `/api/camera_proxy/${entityId}?token=${token}`;
    const entityEntry = this._hass.entities?.[entityId];
    const deviceEntry = entityEntry?.device_id
      ? this._hass.devices?.[entityEntry.device_id]
      : null;
    const deviceName = deviceEntry
      ? deviceEntry.name_by_user || deviceEntry.name
      : null;
    const name = this._config.name || deviceName || stateObj.attributes.friendly_name || entityId;
    const timestamp = stateObj.attributes.image_timestamp;
    const { relative, absolute } = this._formatTimestamp(timestamp, lang);
    const hasCapture = !!this._captureEntityId;
    // Only use the full entity if it has a real image (non-null timestamp).
    // PIR cameras may not support full-resolution images.
    const fullState = this._fullEntityId ? this._hass?.states[this._fullEntityId] : null;
    const hasFull = !!fullState?.attributes?.image_timestamp;

    this.shadowRoot.innerHTML = `
    <style>
      ha-card {
        position: relative;
        overflow: hidden;
        cursor: pointer;
        padding: 0;
      }
      .img-wrapper {
        width: 100%;
        display: block;
        position: relative;
      }
      .camera-img {
        width: 100%;
        display: block;
        object-fit: cover;
      }
      .overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 8px 12px;
        background: linear-gradient(transparent, rgba(0,0,0,0.55));
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        pointer-events: none;
      }
      .name {
        color: #fff;
        font-size: 0.95em;
        font-weight: 500;
        text-shadow: 0 1px 3px rgba(0,0,0,0.7);
      }
      .timestamp {
        color: rgba(255,255,255,0.85);
        font-size: 0.8em;
        text-shadow: 0 1px 3px rgba(0,0,0,0.7);
        cursor: default;
        pointer-events: all;
      }
      .refresh-btn {
        position: absolute;
        top: 8px;
        right: 8px;
        background: rgba(0,0,0,0.45);
        border: none;
        border-radius: 50%;
        width: 36px;
        height: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        color: #fff;
        transition: background 0.2s;
        z-index: 2;
      }
      .refresh-btn:hover { background: rgba(0,0,0,0.65); }
      .refresh-btn[hidden] { display: none; }
      @keyframes spin { to { transform: rotate(360deg); } }
      .refresh-btn.spinning ha-icon { animation: spin 1s linear infinite; }
    </style>
    <ha-card>
      <div class="img-wrapper" id="img-wrapper">
        <img class="camera-img" src="${_escHtml(imgUrl)}" alt="${_escHtml(name)}" />
        <div class="overlay">
          <span class="name">${_escHtml(name)}</span>
          ${timestamp ? `<span class="timestamp" title="${_escHtml(absolute)}">${_escHtml(relative)}</span>` : ""}
        </div>
        <button class="refresh-btn${this._refreshing ? " spinning" : ""}" id="refresh-btn" ${hasCapture ? "" : "hidden"}>
          <ha-icon icon="mdi:refresh"></ha-icon>
        </button>
      </div>
    </ha-card>`;

    // Click image → more-info for full entity (if configured) or thumbnail entity
    this.shadowRoot.getElementById("img-wrapper").addEventListener("click", (e) => {
      if (e.target.closest("#refresh-btn")) return;
      this._openMoreInfo(hasFull ? this._fullEntityId : this._config.entity);
    });

    // Refresh button
    const refreshBtn = this.shadowRoot.getElementById("refresh-btn");
    if (refreshBtn && !refreshBtn.hasAttribute("hidden")) {
      refreshBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._handleRefresh();
      });
    }
  }

  _formatTimestamp(timestamp, lang) {
    if (!timestamp) return { relative: "", absolute: "" };
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) return { relative: timestamp, absolute: timestamp };
    const absolute = date.toLocaleString(lang);
    const diffMs = Date.now() - date.getTime();
    const diffSec = Math.round(diffMs / 1000);
    if (diffSec < 60) return { relative: _t(lang, "ago_seconds", { n: diffSec }), absolute };
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return { relative: _t(lang, "ago_minutes", { n: diffMin }), absolute };
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return { relative: _t(lang, "ago_hours", { n: diffHr }), absolute };
    return { relative: _t(lang, "ago_days", { n: Math.round(diffHr / 24) }), absolute };
  }

  _openMoreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId: entityId || this._config.entity },
      bubbles: true,
      composed: true,
    }));
  }

  async _handleRefresh() {
    clearTimeout(this._fallbackTimer);
    if (!this._captureEntityId || this._refreshing) return;
    this._refreshing = true;
    // Update just the button class — avoid full re-render which destroys the
    // focused element and causes the page to jump to the top.
    this.shadowRoot.getElementById("refresh-btn")?.classList.add("spinning");
    try {
      await this._hass.callService("button", "press", {
        entity_id: this._captureEntityId,
      });
    } finally {
      // Fallback: clear spinner after 15s if no token rotation arrives
      this._fallbackTimer = setTimeout(() => {
        if (this._refreshing) {
          this._refreshing = false;
          this._render();
        }
      }, 15000);
    }
  }

  _findCaptureButton(hass, cameraEntityId) {
    if (!hass?.entities || !cameraEntityId) return null;
    const cameraEntry = hass.entities[cameraEntityId];
    if (!cameraEntry?.device_id) return null;
    const deviceId = cameraEntry.device_id;
    // Camera and its capture button share the same per-camera sub-device.
    // There is exactly one mdi:camera button per camera device.
    for (const [eid, entry] of Object.entries(hass.entities)) {
      if (!eid.startsWith("button.")) continue;
      if (entry.device_id !== deviceId) continue;
      const stateObj = hass.states[eid];
      if (stateObj?.attributes?.icon === "mdi:camera") return eid;
    }
    return null;
  }

  _findFullEntity(hass, cameraEntityId) {
    if (!hass?.entities || !cameraEntityId) return null;
    const cameraEntry = hass.entities[cameraEntityId];
    if (!cameraEntry?.device_id) return null;
    const deviceId = cameraEntry.device_id;
    // The full-resolution entity shares the same device and has a "_full_image" suffix.
    for (const [eid, entry] of Object.entries(hass.entities)) {
      if (!eid.startsWith("camera.")) continue;
      if (eid === cameraEntityId) continue;
      if (entry.device_id !== deviceId) continue;
      if (eid.endsWith("_full_image")) return eid;
    }
    return null;
  }

  getCardSize() { return 3; }

  static getConfigElement() {
    return document.createElement("securitas-camera-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass?.states || {}).find(e => e.startsWith("camera."));
    return { entity: entity || "" };
  }
}

// ── Registration ──────────────────────────────────────────────────────────────

if (!customElements.get("securitas-camera-card"))
  customElements.define("securitas-camera-card", SecuritasCameraCard);
if (!customElements.get("securitas-camera-card-editor"))
  customElements.define("securitas-camera-card-editor", SecuritasCameraCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.find(c => c.type === "securitas-camera-card")) {
  window.customCards.push({
    type: "securitas-camera-card",
    name: TRANSLATIONS.en.card_name,
    description: TRANSLATIONS.en.card_description,
    preview: false,
  });
}
