import { describe, it, expect } from "vitest";
import {
  defaultArmState,
  FEATURE,
  ARM_ACTIONS,
} from "../../custom_components/securitas/www/verisure-owa-alarm-card.js";
import { makeHass } from "../fixtures/hass.js";
import { makeAlarmEntity } from "../fixtures/entities.js";

describe("FEATURE bitmask", () => {
  it("matches HA AlarmControlPanelEntityFeature values", () => {
    expect(FEATURE).toEqual({
      ARM_HOME: 1,
      ARM_AWAY: 2,
      ARM_NIGHT: 4,
      ARM_CUSTOM_BYPASS: 16,
      ARM_VACATION: 32,
    });
  });
});

describe("ARM_ACTIONS", () => {
  it("contains arm_away as the first entry (default preference)", () => {
    expect(ARM_ACTIONS[0].key).toBe("arm_away");
    expect(ARM_ACTIONS[0].service).toBe("alarm_arm_away");
  });

  it("covers all five arm modes", () => {
    const keys = ARM_ACTIONS.map((a) => a.key);
    expect(keys).toEqual([
      "arm_away",
      "arm_home",
      "arm_night",
      "arm_vacation",
      "arm_custom_bypass",
    ]);
  });
});

describe("defaultArmState", () => {
  it("picks arm_away when entity supports it", () => {
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity({ supportedFeatures: FEATURE.ARM_AWAY }) },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x")).toBe("arm_away");
  });

  it("falls back to first supported feature when away is unavailable", () => {
    const hass = makeHass({
      states: {
        "alarm_control_panel.x": makeAlarmEntity({ supportedFeatures: FEATURE.ARM_NIGHT }),
      },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x")).toBe("arm_night");
  });

  it("returns 'arm_away' when entity is missing", () => {
    expect(defaultArmState(makeHass(), "alarm_control_panel.missing")).toBe("arm_away");
  });

  it("returns 'arm_away' when supported_features is 0", () => {
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity({ supportedFeatures: 0 }) },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x")).toBe("arm_away");
  });
});
