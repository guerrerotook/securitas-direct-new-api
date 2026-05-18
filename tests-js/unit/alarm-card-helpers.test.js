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

  // PR #475 added the optional `configStates` 3rd arg — when the user has
  // explicitly enabled only a subset via `states: [...]`, the default arm key
  // must come from that subset (filtered ∩ supported), not from the entity's
  // raw supported_features.

  it("picks the first entry in configStates when all are supported", () => {
    // All 5 features supported; configStates restricts to night only.
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x", ["arm_night"])).toBe("arm_night");
  });

  it("respects configStates ordering by ARM_ACTIONS (canonical), not user array order", () => {
    // ARM_ACTIONS canonical order is away, home, night, vacation, custom — the
    // helper iterates over that, intersected with configStates. So even if the
    // user lists ["arm_night", "arm_home"], the first canonical hit wins.
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x", ["arm_night", "arm_home"])).toBe(
      "arm_home",
    );
  });

  it("falls back to entity-supported list when configStates intersection is empty", () => {
    // User hid every mode (or listed only modes the entity doesn't support) —
    // `filtered` collapses to []. The helper falls back to `supported` so the
    // gesture isn't silently dropped.
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x", [])).toBe("arm_away");
  });

  it("uses configStates ∩ supported (drops modes the entity doesn't advertise)", () => {
    // Entity supports only NIGHT; user listed both AWAY and NIGHT — only NIGHT
    // is the intersection.
    const hass = makeHass({
      states: {
        "alarm_control_panel.x": makeAlarmEntity({
          supportedFeatures: FEATURE.ARM_NIGHT,
        }),
      },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x", ["arm_away", "arm_night"])).toBe(
      "arm_night",
    );
  });

  it("ignores a non-array configStates (treated as unset)", () => {
    // Defensive: a malformed YAML `states: arm_away` (string, not list) should
    // fall through the `Array.isArray` guard inside _filteredArmActions.
    const hass = makeHass({
      states: { "alarm_control_panel.x": makeAlarmEntity() },
    });
    expect(defaultArmState(hass, "alarm_control_panel.x", "arm_night")).toBe("arm_away");
  });
});
