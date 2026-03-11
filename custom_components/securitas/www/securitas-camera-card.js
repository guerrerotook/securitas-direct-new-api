/**
 * Securitas Camera Card
 *
 * Displays the latest image from a Securitas Direct camera entity with:
 *  - Auto-discovered refresh (capture) button in the top-right corner
 *  - Image timestamp overlay (relative + absolute tooltip)
 *  - Click to open HA more-info dialog
 *
 * Card config:
 *   type: custom:securitas-camera-card
 *   entity: camera.securitas_front_door
 *   name: Front Door   # optional — overrides friendly_name
 */

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
    this._updating = false;
  }

  set hass(hass) {
    this._hass = hass;
    // Propagate to ha-form elements already in DOM
    const entityForm = this.shadowRoot.getElementById("entity-form");
    if (entityForm) entityForm.hass = hass;
    const nameForm = this.shadowRoot.getElementById("name-form");
    if (nameForm) nameForm.hass = hass;
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this._updating) this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; display: flex; flex-direction: column; gap: 8px; }
      </style>
      <div class="editor">
        <ha-form id="entity-form"></ha-form>
        <ha-form id="name-form"></ha-form>
      </div>`;

    // Entity picker — filtered to camera domain
    const entityForm = this.shadowRoot.getElementById("entity-form");
    entityForm.hass = this._hass;
    entityForm.data = { entity: this._config.entity || "" };
    entityForm.schema = [
      { name: "entity", selector: { entity: { domain: "camera" } } },
    ];
    entityForm.computeLabel = () => "Entity";
    entityForm.addEventListener("value-changed", (e) => {
      const newEntity = e.detail.value?.entity;
      if (newEntity !== undefined) {
        this._updating = true;
        this._config = { ...this._config, entity: newEntity };
        this._fireChanged();
        this._updating = false;
      }
    });

    // Name field — optional, shows "+ Add" when empty (standard ha-form text behaviour)
    const nameForm = this.shadowRoot.getElementById("name-form");
    nameForm.hass = this._hass;
    nameForm.data = { name: this._config.name || "" };
    nameForm.schema = [
      { name: "name", selector: { text: {} } },
    ];
    nameForm.computeLabel = () => "Name";
    nameForm.addEventListener("value-changed", (e) => {
      const val = e.detail.value?.name ?? "";
      this._updating = true;
      if (val.trim()) {
        this._config = { ...this._config, name: val.trim() };
      } else {
        const { name: _, ...rest } = this._config;
        this._config = rest;
      }
      this._fireChanged();
      this._updating = false;
    });
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
    // Clear spinner when the image token rotates (new image available)
    if (this._refreshing && newToken && newToken !== prevToken) {
      clearTimeout(this._fallbackTimer);
      this._refreshing = false;
    }
    this._render();
  }

  _render() {
    const entityId = this._config.entity;
    const stateObj = this._hass?.states[entityId];

    if (!stateObj) {
      this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding:16px;color:var(--error-color)">
          Entity not found: ${_escHtml(entityId)}
        </div>
      </ha-card>`;
      return;
    }

    const token = stateObj.attributes.access_token || "";
    const imgUrl = `/api/camera_proxy/${entityId}?token=${token}`;
    const name = this._config.name || stateObj.attributes.friendly_name || entityId;
    const timestamp = stateObj.attributes.image_timestamp;
    const { relative, absolute } = this._formatTimestamp(timestamp);
    const hasCapture = !!this._captureEntityId;

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

    // Click image → more-info dialog (but not if clicking the refresh button)
    this.shadowRoot.getElementById("img-wrapper").addEventListener("click", (e) => {
      if (e.target.closest("#refresh-btn")) return;
      this._openMoreInfo();
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

  _formatTimestamp(timestamp) {
    if (!timestamp) return { relative: "", absolute: "" };
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) return { relative: timestamp, absolute: timestamp };
    const absolute = date.toLocaleString();
    const diffMs = Date.now() - date.getTime();
    const diffSec = Math.round(diffMs / 1000);
    if (diffSec < 60) return { relative: `${diffSec}s ago`, absolute };
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return { relative: `${diffMin} min ago`, absolute };
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return { relative: `${diffHr}h ago`, absolute };
    return { relative: `${Math.round(diffHr / 24)}d ago`, absolute };
  }

  _openMoreInfo() {
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId: this._config.entity },
      bubbles: true,
      composed: true,
    }));
  }

  async _handleRefresh() {
    clearTimeout(this._fallbackTimer);
    if (!this._captureEntityId || this._refreshing) return;
    this._refreshing = true;
    this._render();
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
    for (const [eid, entry] of Object.entries(hass.entities)) {
      if (!eid.startsWith("button.")) continue;
      if (entry.device_id !== deviceId) continue;
      const stateObj = hass.states[eid];
      if (stateObj?.attributes?.icon === "mdi:camera") return eid;
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
    name: "Securitas Camera Card",
    description: "Displays a Securitas Direct camera image with capture trigger and timestamp.",
    preview: false,
  });
}
