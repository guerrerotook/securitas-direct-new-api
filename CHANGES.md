# Changelog

The most recent release is at the top; append new entries above the previous one with each release.

## v5.0.1

### Bug fixes

- **Activity log refresh button.** The refresh button and the on-expand image fetch for image-request events called the legacy `securitas.*` services and failed with "Action securitas.refresh_activity_log not found"; both now use the new `verisure_owa.*` services.
- **Activity log text selection.** The event rows in the activity log card swallowed text selection — Lovelace inherits `user-select: none` into the card's shadow tree, and the row click handler toggled expand/collapse on any drag. The card now opts back in to text selection on both the header and the expanded details and only toggles on clicks (drags of more than 4 px no longer fire the toggle).
- **Sub-panel entity_ids.** Enabling the Interior, Perimeter, or Annex sub-panel created an entity_id with the installation alias repeated (`alarm_control_panel.<alias>_<alias>_<circuit>` on HA 2026.5+, `<alias>_<circuit>_<alias>` on the earlier breakage path). The sub-panel mixin's `suggested_object_id` now returns `"<alias> <circuit>"` (space separator) instead of `"<alias>_<circuit>"` so fresh installs land on the canonical `<alias>_<circuit>` slot. HA 2026.5 unconditionally prepends the device name onto a `has_entity_name=False` entity's slug, running a strip-prefix heuristic to avoid doubling, and that heuristic recognises space/dash/colon as a separator but NOT underscore — so the underscore version came back device-prepended-twice. The space separator lets HA strip the prefix cleanly and slugify maps to the same canonical slug on every supported HA version. An upgrade-time healer still relocates already-broken entries on existing installs whose canonical slot is free at startup; if the slot is already held by another `verisure_owa` entity (most likely another installation sharing the alias slug) the healer logs a warning and leaves the broken entity in place rather than risk evicting someone else's sub-panel. The healer also rewrites stored entity_ids on entity-registry tombstones (HA's `deleted_entities`), so a delete-and-readd cycle doesn't reintroduce the doubled-alias slug — `async_get_or_create` restores entities onto their previous (cached) entity_id, bypassing the entity's `suggested_object_id`, so the tombstone needed correction too.
- **Activity log unknown events.** Event type 820 ("Disattivazione Perimetrale", perimeter disarm — the disarm counterpart to the existing 821/823/824 perimeter-arm codes) is now mapped to `DISARMED` instead of `UNKNOWN`. Event type 14 ("Allarme Foto", a photo-detector alarm with an attached image) is now mapped to `ALARM` — same category as the generic type 13 alarm.
- **Activity log image expansion.** The Lovelace card gates image fetch/display on the event's `img=1` flag instead of `category == "image_request"`, so photo-detector alarms (type 14) now show their attached image on row expand — same as the existing image-request flow.
- **Sub-panel arming modes the panel rejects are now disabled, persistently — on every axis.** On an Italian SDVECU Interior sub-panel, pressing Armed Night triggers an `ARMNIGHT1` the panel rejects — there's no way to detect this in advance. Previously the error notification pointed users at the state-mapping UI (which sub-panels don't have) and the button came back on the next HA restart, so the same rejection happened again. The `CommandResolver` is now hydrated from a persisted `unsupported_commands` mapping in `entry.data`, and each 400-rejection appends to it. The Interior, **Perimeter, and Annex** sub-panels each recompute `supported_features` against the resolver via `can_reach_interior` / `can_reach_perimeter` / `can_reach_annex` — so a rejected `ARMNIGHT1` / `PERI1` / `ARMANNEX1` removes the corresponding button from the card the moment it fails and stays gone across restarts (previously only the Interior sub-panel filtered features; Perimeter and Annex kept showing `ARM_AWAY` even after their single arm command was rejected). The persisted mapping is keyed by `installation.number` (`{"<install_num>": [<commands>...]}`) so a legacy config entry covering multiple installations no longer cross-contaminates sibling panels' resolvers; the v5.0.1-pre flat-list format is preserved on read and migrated to the keyed shape on the next write. The notification still uses a sub-panel-specific translation key that explains the mode has been disabled, rather than pointing at the missing mappings UI.
- **Clearing a mapping field actually clears it.** PR #463 swapped the "Not used" dropdown choice for "leave the field blank", but the field couldn't actually be cleared. Three layers were broken: (1) when the user cleared via the X clear button, HA's frontend omitted the key entirely from user_input — and since the prior options dict also lacked it (from an earlier broken save), the merged options matched the existing state and the update listener never fired; (2) even when the listener did fire, it synced options into data via `{**entry.data, **entry.options}`, which preserved the stale value in data for any cleared key; (3) the form's pre-fill then fell back to that stale data value, so the cleared field re-appeared on the next open. The mappings step now records cleared optional fields as explicit `""` in entry.options (so the listener sees the diff) and the listener replaces options-managed fields in entry.data instead of merging — clearing a previously-set Vacation or Custom mapping now sticks.

## v5.0.0

### Highlights

- **Rebrand to `verisure_owa`.** The domain, services, events, and side-panel URL all change from `securitas` to `verisure_owa`. Legacy aliases keep working until v6.0.0.
- **Peru support.** Verisure customers in Peru can now use the integration.
- **Per-circuit sub-panels.** Optional Interior-only, Perimeter-only, and Annex-only alarm panels alongside the main one, on installations with the corresponding sensors.
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
