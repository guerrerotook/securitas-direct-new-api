import { describe, expect, it, vi } from "vitest";
import { resolveEntityName } from "../../custom_components/securitas/www/verisure-owa-card-utils.js";

const ENTITY = "alarm_control_panel.home";
const stateObj = { entity_id: ENTITY, attributes: { friendly_name: "Home Main" } };

describe("resolveEntityName", () => {
  it("asks Home Assistant first, passing the configured name through", () => {
    const formatEntityName = vi.fn(() => "Hall Home Main");
    const name = [{ type: "area" }, { type: "entity" }];

    expect(resolveEntityName({ formatEntityName }, stateObj, name)).toBe("Hall Home Main");
    expect(formatEntityName).toHaveBeenCalledWith(stateObj, name);
  });

  it("falls back when Home Assistant's formatter throws", () => {
    const formatEntityName = () => {
      throw new Error("registries not loaded");
    };

    expect(resolveEntityName({ formatEntityName }, stateObj, undefined)).toBe("Home Main");
    expect(resolveEntityName({ formatEntityName }, stateObj, "Mine")).toBe("Mine");
  });

  it("uses a configured string on a Home Assistant without the formatter", () => {
    expect(resolveEntityName({}, stateObj, "Mine")).toBe("Mine");
  });

  it("keeps an empty configured string", () => {
    expect(resolveEntityName({}, stateObj, "")).toBe("");
  });

  it("joins text-only structured names", () => {
    const name = [{ type: "text", text: "My" }, { type: "text" }, { type: "text", text: "Alarm" }];
    expect(resolveEntityName({}, stateObj, name)).toBe("My  Alarm");
  });

  it("accepts one structured item that is not in a list", () => {
    expect(resolveEntityName({}, stateObj, { type: "text", text: "Mine" })).toBe("Mine");
  });

  it("uses the friendly name for structured names it cannot resolve itself", () => {
    expect(resolveEntityName({}, stateObj, [{ type: "area" }])).toBe("Home Main");
  });

  it("uses the friendly name with no configured name and no hass", () => {
    expect(resolveEntityName(undefined, stateObj, undefined)).toBe("Home Main");
  });

  it("ends at the entity id when there is no friendly name", () => {
    expect(resolveEntityName({}, { entity_id: ENTITY, attributes: {} }, undefined)).toBe(ENTITY);
  });
});
