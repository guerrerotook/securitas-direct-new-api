/**
 * Securitas Direct Alarm Card
 * A custom Lovelace card for the Securitas Direct HA integration.
 *
 * Features:
 *  - Displays alarm state with icon, colour and label
 *  - Arm / Disarm action buttons appropriate to the current state
 *  - When force_arm_available is true, shows a warning section listing
 *    the open sensors (from the arm_exceptions attribute) with Force Arm
 *    and Cancel buttons — no Template Binary Sensor helper required
 *
 * Config:
 *   type: custom:securitas-alarm-card
 *   entity: alarm_control_panel.YOUR_PANEL_ID
 *   name: My Alarm          # optional – overrides friendly_name
 */

const STATE_CONFIG = {
  disarmed: {
    icon: "mdi:shield-off-outline",
    color: "var(--success-color, #4CAF50)",
    label: "Disarmed",
    actions: ["arm_away", "arm_home", "arm_night"],
  },
  armed_away: {
    icon: "mdi:shield-lock",
    color: "var(--error-color, #F44336)",
    label: "Armed Away",
    actions: ["disarm"],
  },
  armed_home: {
    icon: "mdi:shield-home",
    color: "var(--warning-color, #FF9800)",
    label: "Armed Home",
    actions: ["disarm"],
  },
  armed_night: {
    icon: "mdi:shield-moon",
    color: "#9C27B0",
    label: "Armed Night",
    actions: ["disarm"],
  },
  arming: {
    icon: "mdi:shield-sync",
    color: "var(--warning-color, #FF9800)",
    label: "Arming…",
    actions: [],
  },
  pending: {
    icon: "mdi:shield-alert-outline",
    color: "var(--warning-color, #FF9800)",
    label: "Pending",
    actions: [],
  },
  triggered: {
    icon: "mdi:shield-alert",
    color: "var(--error-color, #F44336)",
    label: "TRIGGERED",
    actions: ["disarm"],
  },
  unavailable: {
    icon: "mdi:shield-off",
    color: "var(--disabled-color, #9E9E9E)",
    label: "Unavailable",
    actions: [],
  },
};

const ACTION_LABELS = {
  arm_away: "Arm Away",
  arm_home: "Arm Home",
  arm_night: "Arm Night",
  disarm: "Disarm",
};

class SecuritasAlarmCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define an entity (alarm_control_panel)");
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _stateObj() {
    return this._hass && this._hass.states[this._config.entity];
  }

  _render() {
    if (!this._hass || !this._config) return;

    const stateObj = this._stateObj();
    const name =
      this._config.name ||
      (stateObj && stateObj.attributes.friendly_name) ||
      this._config.entity;

    if (!stateObj) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding:16px;color:var(--error-color)">
            Entity not found: ${this._config.entity}
          </div>
        </ha-card>`;
      return;
    }

    const state = stateObj.state;
    const attrs = stateObj.attributes;
    const forceArmAvailable = attrs.force_arm_available === true;
    const openSensors = attrs.arm_exceptions || [];
    const cfg = STATE_CONFIG[state] || STATE_CONFIG["unavailable"];

    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          overflow: hidden;
          transition: box-shadow 0.3s;
        }

        /* ── Header bar (state colour strip) ── */
        .state-bar {
          height: 4px;
          background: ${cfg.color};
          transition: background 0.4s;
        }

        /* ── Main content ── */
        .content {
          padding: 16px;
        }

        /* ── Header row: icon + name + state ── */
        .header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
        }
        .header ha-icon {
          --mdc-icon-size: 36px;
          color: ${cfg.color};
          transition: color 0.4s;
          flex-shrink: 0;
        }
        .info .name {
          font-size: 1.1em;
          font-weight: 600;
          color: var(--primary-text-color);
          line-height: 1.2;
        }
        .info .state-label {
          font-size: 0.875em;
          color: ${cfg.color};
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }

        /* ── Action buttons (normal state) ── */
        .actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .action-btn {
          flex: 1;
          min-width: 80px;
          padding: 8px 12px;
          border: none;
          border-radius: 8px;
          font-size: 0.875em;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.2s, transform 0.1s;
        }
        .action-btn:active { transform: scale(0.97); }

        .action-btn.arm_away,
        .action-btn.arm_home,
        .action-btn.arm_night {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }
        .action-btn.arm_away:hover,
        .action-btn.arm_home:hover,
        .action-btn.arm_night:hover {
          filter: brightness(1.1);
        }
        .action-btn.disarm {
          background: var(--error-color, #F44336);
          color: #fff;
        }
        .action-btn.disarm:hover { filter: brightness(1.1); }

        /* ── Force arm section ── */
        .force-arm-section {
          border-radius: 10px;
          background: rgba(255, 152, 0, 0.1);
          border: 1px solid var(--warning-color, #FF9800);
          padding: 14px;
          margin-bottom: 16px;
        }
        .force-arm-header {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
          color: var(--warning-color, #FF9800);
          margin-bottom: 10px;
          font-size: 0.95em;
        }
        .force-arm-header ha-icon {
          --mdc-icon-size: 20px;
          color: var(--warning-color, #FF9800);
          flex-shrink: 0;
        }
        .sensor-list {
          list-style: none;
          padding: 0;
          margin: 0 0 12px 28px;
        }
        .sensor-list li {
          font-size: 0.875em;
          color: var(--secondary-text-color);
          padding: 2px 0;
        }
        .sensor-list li::before {
          content: "• ";
          color: var(--warning-color, #FF9800);
          font-weight: bold;
        }
        .force-arm-actions {
          display: flex;
          gap: 8px;
        }
        .action-btn.force_arm {
          flex: 2;
          background: var(--warning-color, #FF9800);
          color: #fff;
        }
        .action-btn.force_arm:hover { filter: brightness(1.1); }
        .action-btn.cancel_force {
          flex: 1;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          border: 1px solid var(--divider-color);
        }
        .action-btn.cancel_force:hover {
          background: var(--divider-color);
        }
      </style>

      <ha-card>
        <div class="state-bar"></div>
        <div class="content">

          <!-- Header: icon + name + state -->
          <div class="header">
            <ha-icon icon="${cfg.icon}"></ha-icon>
            <div class="info">
              <div class="name">${name}</div>
              <div class="state-label">${cfg.label}</div>
            </div>
          </div>

          <!-- Force arm warning (only when pending) -->
          ${forceArmAvailable ? `
          <div class="force-arm-section">
            <div class="force-arm-header">
              <ha-icon icon="mdi:alert"></ha-icon>
              Open sensor(s) — arm anyway?
            </div>
            ${openSensors.length > 0 ? `
              <ul class="sensor-list">
                ${openSensors.map((s) => `<li>${s}</li>`).join("")}
              </ul>` : ""}
            <div class="force-arm-actions">
              <button class="action-btn force_arm" data-action="force_arm">
                Force Arm
              </button>
              <button class="action-btn cancel_force" data-action="cancel_force">
                Cancel
              </button>
            </div>
          </div>` : ""}

          <!-- Normal arm / disarm buttons -->
          ${cfg.actions.length > 0 ? `
          <div class="actions">
            ${cfg.actions
              .map(
                (a) => `
              <button class="action-btn ${a}" data-action="${a}">
                ${ACTION_LABELS[a]}
              </button>`
              )
              .join("")}
          </div>` : ""}

        </div>
      </ha-card>`;

    // Attach click listeners after DOM is written
    this.shadowRoot.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => this._handleAction(btn.dataset.action));
    });
  }

  _handleAction(action) {
    const entity = this._config.entity;
    const h = this._hass;
    const svc = (domain, service, data = {}) =>
      h.callService(domain, service, { entity_id: entity, ...data });

    switch (action) {
      case "arm_away":   return svc("alarm_control_panel", "alarm_arm_away");
      case "arm_home":   return svc("alarm_control_panel", "alarm_arm_home");
      case "arm_night":  return svc("alarm_control_panel", "alarm_arm_night");
      case "disarm":     return svc("alarm_control_panel", "alarm_disarm");
      case "force_arm":  return svc("securitas", "force_arm");
      case "cancel_force": return svc("securitas", "force_arm_cancel");
    }
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    // Visual config editor could be added here in the future
    return null;
  }

  static getStubConfig() {
    return { entity: "alarm_control_panel.your_panel_id" };
  }
}

customElements.define("securitas-alarm-card", SecuritasAlarmCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "securitas-alarm-card",
  name: "Securitas Alarm Card",
  description:
    "Alarm control panel card for Securitas Direct with force-arm support.",
  preview: false,
});
