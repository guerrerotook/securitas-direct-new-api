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
// A user who has BOTH this legacy resource and the canonical
// /verisure-owa-panel/...js resources registered loads the canonical modules
// twice (this legacy resource is served from /securitas_panel/, so its
// relative imports resolve under /securitas_panel/ rather than
// /verisure-owa-panel/, and the ES-module loader doesn't dedup them). That's a
// harmless, legacy-only redundant fetch: customElements.define is guarded by
// `if (!customElements.get(...))` and the customCards/customBadges pushes by
// `.find(...)`, so the second run's registrations are silent no-ops.
//
// To collapse the dual-resource situation entirely, remove the
// /securitas_panel/securitas-alarm-card.js entry from Settings →
// Dashboards → Resources; the canonical /verisure-owa-panel/...js
// resources are auto-registered by the integration.
import "./verisure-owa-alarm-card.js?v=2f18b675-5.10.0";
import "./verisure-owa-alarm-chip.js?v=644cc409-5.10.0";
