// Legacy alias for /verisure-owa-panel/verisure-owa-camera-card.js.
// See securitas-alarm-card.js in this directory for the full rationale.
//
// Forwards to the canonical camera-card file, which registers both
// verisure-owa-camera-card AND securitas-camera-card (plus their
// -editor variants) so old dashboards using `custom:securitas-camera-card`
// keep rendering. This shim is served from /securitas_panel/, so its import
// resolves there rather than under /verisure-owa-panel/: a user with both
// resources registered loads the canonical module twice (harmless, as the
// registrations are guarded).
import "./verisure-owa-camera-card.js?v=e6c0f7b8-5.9.0";
