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
    // Propagate to ha-form elements already in DOM
    const entityForm = this.shadowRoot.getElementById("entity-form");
    if (entityForm) entityForm.hass = hass;
    const nameForm = this.shadowRoot.getElementById("name-form");
    if (nameForm) nameForm.hass = hass;
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
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
        this._config = { ...this._config, entity: newEntity };
        this._fireChanged();
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
      if (val.trim()) {
        this._config = { ...this._config, name: val.trim() };
      } else {
        const { name: _, ...rest } = this._config;
        this._config = rest;
      }
      this._fireChanged();
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
      this._refreshing = false;
    }
    this._render();
  }

  // Stub — full implementation added in Task 4
  _render() {
    const entityId = this._config.entity;
    const stateObj = this._hass?.states[entityId];
    if (!stateObj) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px;color:var(--error-color)">Entity not found: ${entityId}</div></ha-card>`;
      return;
    }
    this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px">Camera card stub: ${entityId}</div></ha-card>`;
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

  static getStubConfig() {
    return { entity: "" };
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
