// Legacy alias for /verisure-owa-panel/verisure-owa-alarm-card.js.
//
// Kept as a Lovelace-resource shim for installs from before v5.0.0 that
// still have /securitas_panel/securitas-alarm-card.js registered in their
// resources list (the integration's HACS upgrade doesn't auto-deregister
// old resources). Forwards to the canonical files, which register BOTH
// verisure-owa-* AND securitas-* custom-element names (alarm card,
// editor, badge, chip, mushroom-chip) — so old dashboards using
// `custom:securitas-alarm-card` and friends keep rendering.
//
// The card and the chip/badge are now separate modules (the chip/badge live
// in verisure-owa-alarm-chip.js so they render without the heavy card bundle);
// both are imported here so this single legacy resource still defines every
// element, as it did before the split.
//
// ES modules dedup by URL, so loading both this file AND the canonical
// /verisure-owa-panel/...js resources causes the canonical code to run once:
// customElements.define is guarded by `if (!customElements.get(...))` to make
// any duplicate-registration attempt a silent no-op.
//
// To collapse the dual-resource situation entirely, remove the
// /securitas_panel/securitas-alarm-card.js entry from Settings →
// Dashboards → Resources; the canonical /verisure-owa-panel/...js
// resources are auto-registered by the integration.
import "./verisure-owa-alarm-card.js";
import "./verisure-owa-alarm-chip.js";
