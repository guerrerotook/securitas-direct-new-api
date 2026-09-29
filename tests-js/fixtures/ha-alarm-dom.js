// Fake Home Assistant DOM around the alarm-mode buttons: the modes control,
// its PIN prompt, and the Tile card's feature nesting. Shared by the More Info
// and Tile auto-force tests.

// HA's modes control: an element whose shadow root holds the
// ha-control-select that fires the mode events.
export function makeModesControl(tag) {
  const control = document.createElement(tag);
  const select = document.createElement("ha-control-select");
  control.attachShadow({ mode: "open" }).appendChild(select);
  return { control, select };
}

// What HA's ha-control-select fires when a mode button is pressed
// (fireEvent defaults: bubbles + composed).
export function pressMode(select, value = "armed_away") {
  const event = new CustomEvent("value-changed", {
    detail: { value },
    bubbles: true,
    composed: true,
  });
  select.dispatchEvent(event);
  return event;
}

// HA's modes control fires show-dialog itself to open its PIN prompt.
export function openPinPrompt(select) {
  select.getRootNode().host.dispatchEvent(
    new CustomEvent("show-dialog", {
      detail: { dialogTag: "dialog-enter-code" },
      bubbles: true,
      composed: true,
    }),
  );
}

// The keypad's tick button in HA's PIN prompt, clicked as a user would.
export function submitPin() {
  const prompt = document.createElement("dialog-enter-code");
  const tick = document.createElement("ha-control-button");
  tick.className = "submit";
  prompt.attachShadow({ mode: "open" }).appendChild(tick);
  document.body.appendChild(prompt);
  tick.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
  prompt.remove();
}

// The prompt lives in HA's shell and fires dialog-closed there on Submit and
// Cancel alike; it reaches window.
export function closePinPrompt() {
  const prompt = document.createElement("dialog-enter-code");
  document.body.appendChild(prompt);
  prompt.dispatchEvent(
    new CustomEvent("dialog-closed", {
      detail: { dialog: "dialog-enter-code" },
      bubbles: true,
      composed: true,
    }),
  );
  prompt.remove();
}

// Mirrors Home Assistant's Tile DOM: hui-tile-card's shadow root holds
// ha-card > ha-tile-container, whose light DOM carries one hui-card-features
// per feature position (slot "features-inline" for the first feature when the
// Tile uses the inline position, slot "features" for the rest). Each
// hui-card-features renders one hui-card-feature per feature in its shadow
// root, and each hui-card-feature renders the feature element in its own.
export function buildTile() {
  const tile = document.createElement("hui-tile-card");
  const tileRoot = tile.attachShadow({ mode: "open" });
  const card = document.createElement("ha-card");
  const container = document.createElement("ha-tile-container");
  const slots = container.attachShadow({ mode: "open" });
  for (const name of ["features-inline", "features"]) {
    const slot = document.createElement("slot");
    slot.name = name;
    slots.appendChild(slot);
  }
  card.appendChild(container);
  tileRoot.appendChild(card);
  document.body.appendChild(tile);
  const groups = {};
  const group = (slot) => {
    if (!groups[slot]) {
      groups[slot] = document.createElement("hui-card-features");
      groups[slot].slot = slot;
      groups[slot].attachShadow({ mode: "open" });
      container.appendChild(groups[slot]);
    }
    return groups[slot].shadowRoot;
  };
  return { tile, tileRoot, group };
}

export function wrapFeature(element) {
  const wrapper = document.createElement("hui-card-feature");
  wrapper.attachShadow({ mode: "open" }).appendChild(element);
  return wrapper;
}

export function addAlarmModes(tileParts, slot = "features") {
  const { control, select } = makeModesControl("hui-alarm-modes-card-feature");
  const wrapper = wrapFeature(control);
  tileParts.group(slot).appendChild(wrapper);
  return { wrapper, select };
}

// The tick box is a persistent element toggled via `hidden`, so a hidden one
// counts as not shown.
export function autoForceToggle(host) {
  const el = host.shadowRoot.querySelector(".auto-force-toggle");
  return el && !el.hidden ? el : null;
}

export function autoForceCheckbox(host) {
  return host.shadowRoot.querySelector(".auto-force-checkbox");
}

export function autoForceCalls(callService) {
  return callService.mock.calls
    .map((call) => call[1])
    .filter((service) => ["suppress_arm_exception_prompt", "force_arm"].includes(service));
}
