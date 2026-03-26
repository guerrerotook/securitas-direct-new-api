/**
 * Securitas Camera Card
 *
 * Displays the latest image from a Securitas Direct camera entity with:
 *  - Auto-discovered refresh (capture) button in the top-right corner
 *  - Image timestamp overlay (relative + absolute tooltip)
 *  - Click to open a lightbox with the full-resolution image (if available),
 *    otherwise falls back to the HA more-info dialog
 *
 * Card config:
 *   type: custom:securitas-camera-card
 *   entity: camera.securitas_front_door
 *   name: Front Door   # optional — overrides the device name
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
  }

  set hass(hass) {
    this._hass = hass;
    const entityForm = this.shadowRoot.getElementById("entity-form");
    if (entityForm) entityForm.hass = hass;
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this.shadowRoot.getElementById("entity-form")) {
      // First call — build the DOM once
      this._render();
    } else {
      // Subsequent calls (HA bouncing config back) — update entity picker in place,
      // never touch the name textfield so focus is preserved while typing
      const entityForm = this.shadowRoot.getElementById("entity-form");
      if (entityForm) entityForm.data = { entity: this._config.entity || "" };
    }
  }

  _render() {
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
    entityForm.computeLabel = () => "Entity";
    entityForm.addEventListener("value-changed", (e) => {
      const newEntity = e.detail.value?.entity;
      if (newEntity !== undefined) {
        this._config = { ...this._config, entity: newEntity };
        this._fireChanged();
      }
    });

    // Name field — ha-textfield with input event (no value-changed → no re-render cycle)
    const nameTf = document.createElement("ha-textfield");
    nameTf.label = "Name";
    nameTf.value = this._config.name || "";
    nameTf.placeholder = "Override friendly name";
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
    this._fullEntityId = this._findFullImageEntity(hass, this._config.entity);
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
    const entityEntry = this._hass.entities?.[entityId];
    const deviceEntry = entityEntry?.device_id
      ? this._hass.devices?.[entityEntry.device_id]
      : null;
    const deviceName = deviceEntry
      ? deviceEntry.name_by_user || deviceEntry.name
      : null;
    const name = this._config.name || deviceName || stateObj.attributes.friendly_name || entityId;
    const timestamp = stateObj.attributes.image_timestamp;
    const { relative, absolute } = this._formatTimestamp(timestamp);
    const hasCapture = !!this._captureEntityId;
    const hasFull = !!this._fullEntityId;

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
      /* Lightbox */
      dialog.lightbox {
        padding: 0;
        border: none;
        background: rgba(0,0,0,0.92);
        width: 100vw;
        max-width: 100vw;
        height: 100vh;
        max-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        position: fixed;
        inset: 0;
      }
      dialog.lightbox::backdrop {
        background: rgba(0,0,0,0.85);
      }
      .lightbox-img {
        max-width: 95vw;
        max-height: 90vh;
        object-fit: contain;
        display: block;
        border-radius: 4px;
      }
      .lightbox-close {
        position: fixed;
        top: 16px;
        right: 16px;
        background: rgba(255,255,255,0.15);
        border: none;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        color: #fff;
        font-size: 20px;
        z-index: 10;
        transition: background 0.2s;
      }
      .lightbox-close:hover { background: rgba(255,255,255,0.3); }
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

    // Click image → lightbox (full entity) or more-info (fallback)
    this.shadowRoot.getElementById("img-wrapper").addEventListener("click", (e) => {
      if (e.target.closest("#refresh-btn")) return;
      if (hasFull) {
        this._openLightbox();
      } else {
        this._openMoreInfo();
      }
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

  _openLightbox() {
    const fullState = this._hass?.states[this._fullEntityId];
    if (!fullState) {
      this._openMoreInfo();
      return;
    }
    const fullToken = fullState.attributes.access_token || "";
    const fullUrl = `/api/camera_proxy/${this._fullEntityId}?token=${fullToken}`;

    // Remove any stale lightbox
    this.shadowRoot.getElementById("securitas-lightbox")?.remove();

    const dialog = document.createElement("dialog");
    dialog.id = "securitas-lightbox";
    dialog.className = "lightbox";
    dialog.innerHTML = `
      <button class="lightbox-close" id="lb-close" aria-label="Close">&#x2715;</button>
      <img class="lightbox-img" src="${_escHtml(fullUrl)}" alt="Full image" />`;

    this.shadowRoot.appendChild(dialog);
    dialog.showModal();

    const close = () => {
      dialog.close();
      dialog.remove();
    };
    dialog.querySelector("#lb-close").addEventListener("click", close);
    dialog.addEventListener("click", (e) => {
      // Close when clicking the backdrop (outside the image)
      if (e.target === dialog) close();
    });
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
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

  _findFullImageEntity(hass, thumbnailEntityId) {
    if (!hass?.entities || !thumbnailEntityId) return null;
    const thumbEntry = hass.entities[thumbnailEntityId];
    if (!thumbEntry?.unique_id) return null;
    // Thumbnail unique_id: v4_{num}_camera_{zone_id}
    // Full image unique_id: v4_{num}_camera_full_{zone_id}
    const fullUniqueId = thumbEntry.unique_id.replace("_camera_", "_camera_full_");
    if (fullUniqueId === thumbEntry.unique_id) return null;
    for (const [eid, entry] of Object.entries(hass.entities)) {
      if (entry.unique_id === fullUniqueId) return eid;
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
