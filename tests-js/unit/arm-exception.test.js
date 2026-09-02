import { describe, expect, it, vi } from "vitest";
import {
  armExceptionState,
  armExceptionTranslation,
} from "../../custom_components/securitas/www/verisure-owa-arm-exception.js";
import { makeHass } from "../fixtures/hass.js";

describe("arming-exception shared helpers", () => {
  it("resolves regional, English and key fallbacks", () => {
    expect(armExceptionTranslation("es-MX", "cancel")).toBe("Cancelar");
    expect(armExceptionTranslation("unknown", "cancel")).toBe("Cancel");
    expect(armExceptionTranslation("unknown", "missing_key")).toBe("missing_key");
    expect(armExceptionTranslation(undefined, "action_failed_detail", { error: "$&" })).toBe(
      "The alarm action failed: $&",
    );
  });

  it("normalizes missing, malformed and forceable entity state", () => {
    expect(armExceptionState()).toEqual({
      active: false,
      forceArmAvailable: false,
      sensors: [],
    });
    expect(
      armExceptionState({
        attributes: { force_arm_available: true, arm_exceptions: [1, "Window"] },
      }),
    ).toEqual({
      active: true,
      forceArmAvailable: true,
      sensors: ["1", "Window"],
    });
  });
});

describe("verisure-owa-arm-exception-alert public API", () => {
  it("updates all presentation state through one method", () => {
    const alert = document.createElement("verisure-owa-arm-exception-alert");
    const stateObj = {
      entity_id: "alarm_control_panel.test",
      attributes: { arm_exception_active: true, arm_exceptions: ["Patio"] },
    };
    const hass = makeHass({ language: undefined, locale: { language: "es" } });

    alert.update({
      hass,
      stateObj,
      entityId: "alarm_control_panel.test",
      presentation: "compact",
    });
    document.body.appendChild(alert);

    expect(alert.active).toBe(true);
    expect(alert.getAttribute("presentation")).toBe("compact");
    expect(alert.shadowRoot.textContent).toContain("Patio");

    alert.update({
      hass,
      stateObj,
      entityId: "alarm_control_panel.test",
      presentation: null,
    });
    expect(alert.getAttribute("presentation")).toBe("full");
    expect(alert.shadowRoot.querySelector("ha-button.cancel").textContent).toBe("Cancelar");
    expect(alert.shadowRoot.querySelector("style").textContent).toContain("grid-column: 2");
  });

  it("uses the generic notification for non-Error service rejections", async () => {
    const hass = makeHass();
    hass.callService = vi.fn().mockRejectedValue("offline");
    const alert = document.createElement("verisure-owa-arm-exception-alert");
    alert.update({
      hass,
      entityId: "alarm_control_panel.test",
      stateObj: {
        attributes: { arm_exception_active: true, force_arm_available: true },
      },
    });
    document.body.appendChild(alert);
    const notification = vi.fn();
    alert.addEventListener("hass-notification", notification);

    alert.shadowRoot.querySelector(".force").click();
    alert.shadowRoot.querySelector(".cancel").click();
    await Promise.resolve();
    await Promise.resolve();

    expect(hass.callService).toHaveBeenCalledOnce();
    expect(notification.mock.calls[0][0].detail.message).toBe(
      "The alarm action failed. Please try again.",
    );
  });
});
