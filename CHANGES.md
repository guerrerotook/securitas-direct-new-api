# Changelog

All notable changes to this integration are recorded here. The most recent release is at the top; append new entries above the previous one with each release.

The README's "What's new" and "Breaking Changes" sections cover the **current** release; this file is the long-running record.

## v5.0.0

### Highlights

- **Rebrand to `verisure_owa`.** The domain, services, events, and side-panel URL all change from `securitas` to `verisure_owa`. Legacy aliases keep working until v6.0.0.
- **Peru support.** Verisure customers in Peru can now use the integration.
- **Per-axis sub-panels.** Optional Interior-only, Perimeter-only, and Annex-only alarm panels alongside the main one, on installations with the corresponding sensors.
- **Lock automations.** Auto-lock the door when a circuit arms, and auto-disarm before unlocking from HA. Disarm and unlock dispatch in parallel.
- **Activity log.** A first-class activity timeline — Lovelace card, sensor, and `verisure_owa_activity` event. Actions taken in HA are tagged with the user and de-duplicated against the panel's polled echo.
- **Alarm badge and Mushroom chip.** Compact alternatives to the alarm card for tighter dashboards.
- **Refresh-token authentication.** Your password is no longer persisted to disk. First login mints a long-lived refresh token; if it expires or is revoked, HA shows a one-time reauth dialog.
- **Sectioned options flow.** Settings are grouped into PIN, force-arm notifications, sub-panels, and Advanced sections.

### Breaking changes

Most users won't have to touch anything — every legacy reference keeps working through transparent shims until **v6.0.0**, at which point the aliases are removed. Plan to migrate any references before then.

- **Domain renamed `securitas` → `verisure_owa`.** Existing installs are migrated automatically and entity IDs are rewritten in the registry.
- **Service rename.** `securitas.force_arm` / `securitas.force_arm_cancel` become `verisure_owa.force_arm` / `verisure_owa.force_arm_cancel`.
- **Event rename.** `securitas_arming_exception` → `verisure_owa_arming_exception`. The legacy event still fires alongside the new one until v6.0.0. The activity-log event `verisure_owa_activity` is new in v5.0.0 and has no legacy alias.
- **Side-panel URL rename.** `/securitas_panel` → `/verisure-owa-panel`.
- **Lovelace card type rename.** `custom:securitas-alarm-card` → `custom:verisure-owa-alarm-card` (and likewise for `-alarm-badge` and `-camera-card`). Inside a Mushroom Chips Card, `type: securitas-alarm` → `type: verisure-owa-alarm`.
- **Mobile-notification action IDs.** Force-arm push notification actions (`SECURITAS_FORCE_ARM_<num>` / `SECURITAS_CANCEL_FORCE_ARM_<num>`) become `VERISURE_OWA_*` in v6.0.0. Only matters if you wrote a custom `mobile_app_notification_action` automation against the old strings.
- **Password is no longer persisted.** After upgrade, the integration may show a one-time reauth dialog so a refresh token can be minted from your existing password.
- **`set_authentication_token` service removed.** No longer needed — the refresh-token flow handles renewal automatically.

If you're upgrading from v3.x or earlier, the breaking changes from v4.0.0 still apply on top of the above — see the v4.0.0 release notes.
