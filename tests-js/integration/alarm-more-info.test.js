import { afterEach, describe, expect, it, vi } from "vitest";
import { makeHass } from "../fixtures/hass.js";

const ENTITY = "alarm_control_panel.test";

await import("../../custom_components/securitas/www/verisure-owa-more-info.js");

function makeState({
  state = "disarmed",
  armExceptionActive = false,
  forceArmAvailable = false,
  armExceptions = [],
  entityId = ENTITY,
} = {}) {
  return {
    entity_id: entityId,
    state,
    attributes: {
      arm_exception_active: armExceptionActive,
      force_arm_available: forceArmAvailable,
      arm_exceptions: armExceptions,
    },
  };
}

async function mountMoreInfo({ stateObj = makeState(), hass = makeHass() } = {}) {
  const element = document.createElement("more-info-verisure-owa-alarm");
  element.hass = hass;
  element.stateObj = stateObj;
  document.body.appendChild(element);
  return element;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("Verisure native alarm More Info extension", () => {
  it("registers the global custom More Info element", () => {
    expect(customElements.get("more-info-verisure-owa-alarm")).toBeDefined();
  });

  it("exposes the current hass and state object", async () => {
    const hass = makeHass();
    const stateObj = makeState();
    const element = await mountMoreInfo({ hass, stateObj });

    expect(element.hass).toBe(hass);
    expect(element.stateObj).toBe(stateObj);
  });

  it("delegates the alarm control to Home Assistant's stock More Info content", async () => {
    const stateObj = makeState();
    stateObj.attributes.custom_ui_more_info = "more-info-verisure-owa-alarm";
    const hass = makeHass();
    const element = await mountMoreInfo({ stateObj, hass });
    const native = element.shadowRoot.getElementById("native-control");

    expect(native.localName).toBe("more-info-content");
    expect(native.stateObj).not.toBe(stateObj);
    expect(native.stateObj).toEqual({
      ...stateObj,
      attributes: {
        arm_exception_active: false,
        force_arm_available: false,
        arm_exceptions: [],
      },
    });
    expect(native.hass).toBe(hass);
    expect(element.shadowRoot.getElementById("force-extension").hidden).toBe(true);

    const nextState = makeState({ state: "armed_home" });
    const entry = { entity_id: ENTITY };
    element.entry = entry;
    element.editMode = true;
    element.data = { source: "test" };
    element.stateObj = nextState;

    expect(element.shadowRoot.getElementById("native-control")).toBe(native);
    expect(native.stateObj).toEqual(nextState);
    expect(native.stateObj).not.toBe(nextState);
    expect(native.entry).toBe(entry);
    expect(native.editMode).toBe(true);
    expect(native.data).toEqual({ source: "test" });
  });

  it("shows sensors and calls Force Arm when the panel allows forcing", async () => {
    const hass = makeHass();
    const element = await mountMoreInfo({
      hass,
      stateObj: makeState({
        armExceptionActive: true,
        forceArmAvailable: true,
        armExceptions: ["Kitchen Window", "Front Door"],
      }),
    });
    const extension = element.shadowRoot.getElementById("force-extension");

    expect(extension.hidden).toBe(false);
    expect(extension.textContent).toContain("Kitchen Window");
    expect(extension.textContent).toContain("Front Door");
    const force = extension.querySelector(".force");
    force.click();
    expect(force.disabled).toBe(true);
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm", {
      entity_id: ENTITY,
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(force.disabled).toBe(false);
  });

  it("keeps non-forceable exceptions useful for Spain", async () => {
    const hass = makeHass({ language: "es" });
    const element = await mountMoreInfo({
      hass,
      stateObj: makeState({
        armExceptionActive: true,
        armExceptions: ["Ventana cocina"],
      }),
    });
    const extension = element.shadowRoot.getElementById("force-extension");

    expect(extension.textContent).toContain("Ventana cocina");
    expect(extension.querySelector(".force")).toBeNull();
    extension.querySelector(".cancel").click();
    expect(hass.callService).toHaveBeenCalledWith("verisure_owa", "force_arm_cancel", {
      entity_id: ENTITY,
    });
  });

  it("uses locale and English fallbacks and ignores malformed sensor lists", async () => {
    const localeHass = makeHass({ language: undefined });
    localeHass.locale = { language: "es" };
    const stateObj = makeState({ armExceptionActive: true });
    stateObj.attributes.arm_exceptions = "not-an-array";
    const localized = await mountMoreInfo({ hass: localeHass, stateObj });

    expect(localized.shadowRoot.querySelector(".force-title").textContent).toContain(
      "Sensor(es) abierto(s)",
    );
    expect(localized.shadowRoot.querySelector(".sensor-list")).toBeNull();

    const englishHass = makeHass({ language: undefined });
    delete englishHass.locale;
    const english = await mountMoreInfo({ hass: englishHass, stateObj });
    expect(english.shadowRoot.querySelector(".force-title").textContent).toContain(
      "Open sensor(s)",
    );
  });

  it("escapes sensor names and clears the extension when the exception ends", async () => {
    const element = await mountMoreInfo({
      stateObj: makeState({
        armExceptionActive: true,
        armExceptions: ['Window <img src=x onerror="bad">'],
      }),
    });
    const extension = element.shadowRoot.getElementById("force-extension");

    expect(extension.querySelector("img")).toBeNull();
    expect(extension.querySelector("li").textContent).toBe('Window <img src=x onerror="bad">');

    element.stateObj = makeState();
    expect(extension.hidden).toBe(true);
    expect(extension.children).toHaveLength(0);
  });

  it("does not call services without an entity id", async () => {
    const hass = makeHass();
    const element = await mountMoreInfo({
      hass,
      stateObj: makeState({
        armExceptionActive: true,
        forceArmAvailable: true,
        entityId: "",
      }),
    });
    const force = element.shadowRoot.querySelector(".force");

    force.click();
    expect(hass.callService).not.toHaveBeenCalled();
    expect(force.disabled).toBe(false);
  });

  it("does not update a Force button after the dialog has closed", async () => {
    let finishService;
    const hass = makeHass();
    hass.callService = vi.fn(
      () =>
        new Promise((resolve) => {
          finishService = resolve;
        }),
    );
    const element = await mountMoreInfo({
      hass,
      stateObj: makeState({ armExceptionActive: true, forceArmAvailable: true }),
    });
    const force = element.shadowRoot.querySelector(".force");

    force.click();
    element.remove();
    finishService();
    await Promise.resolve();
    await Promise.resolve();
    expect(force.disabled).toBe(true);
  });

  it("keeps defensive render guards side-effect free", async () => {
    const element = await mountMoreInfo();

    element._nativeControl = null;
    expect(() => element._forwardNativeProperties()).not.toThrow();
    element.shadowRoot.getElementById("force-extension").remove();
    expect(() => element._renderForceExtension()).not.toThrow();
  });
});
