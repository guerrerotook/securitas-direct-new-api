// Legacy alias for /verisure-owa-panel/verisure-owa-camera-card.js.
// See securitas-alarm-card.js in this directory for the full rationale.
//
// Forwards to the canonical camera-card file, which registers both
// verisure-owa-camera-card AND securitas-camera-card (plus their
// -editor variants) so old dashboards using `custom:securitas-camera-card`
// keep rendering. ES modules dedup by URL.
import "./verisure-owa-camera-card.js";
