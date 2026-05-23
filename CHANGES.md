# Changelog

The most recent release is at the top; append new entries above the previous one with each release.

## v5.0.5

### Bug fixes

- **Auto-lock verify silently polled a stale cache (regression from v5.0.4).** The verify mechanism added in v5.0.4 read through `hub.get_lock_modes()`, which had a 60s TTL cache. The first verify read repopulated the cache with stale pre-command data; the remaining six reads all hit that cache and the verify saw no movement, so it gave up and fired false "Auto-lock failed" notifications even when the lock actuated correctly. The cache had only two callers (startup discovery, which always missed; and the verify loop, which the cache broke) — the lock coordinator already bypassed it. Removed: `hub.get_lock_modes` is now a thin pass-through to the queued client call.

- **Verify baseline could be stale when sourced from coordinator data.** The pre-command `statusTimestamp` baseline was read from `self._current_mode` (eventually-consistent coordinator data). If the user physically moved the lock between coordinator updates, the baseline was older than the actual current backend timestamp, and the first verify read looked "fresh" while still reflecting pre-command physical state — a false confirmation. The baseline is now captured via a foreground `_read_lock_mode` API call at command time. The transitional UI state (LOCKING/UNLOCKING) is still forced *first* so the spinner is instant; the baseline read happens after, under `_operation_in_progress` so concurrent coordinator updates can't clobber the transitional state.

- **Verify loop wasted up to 18s on definite failures.** A fresh-but-wrong-state read (e.g. lock blocked, device snapped back) used to keep polling until window exhaust before the failure notification could fire. Any read with a `statusTimestamp` newer than the pre-command baseline is now authoritative — success or failure returns immediately. The defensive quiet-success-on-exhaust branch stays (covers devices that don't re-stamp `statusTimestamp` on a no-op command).

- **Tapping the icon inside an alarm badge/chip popup opened HA's standard more-info dialog over the popup.** Two distinct causes. (1) The badge/chip's `tap_action` (whose editor default is `more-info`, meaning "open our popup") was passed through to the `securitas-alarm-card` embedded inside the popup; in that card's context the same key dispatches `hass-more-info`, which `<home-assistant>` catches and opens the standard dialog. Gesture config keys (`tap_action`, `hold_action`, `double_tap_action`) are now stripped before the embedded card is configured. (2) On a normal tap, the gesture handler's capture-phase click only stopped propagation when a long-press fired; the native click bubbled to wrapping containers with their own `tap_action: more-info` (e.g. a parent tile-card) and opened a second parallel dialog. Native clicks are now always swallowed since our gesture handler owns interaction on the element.

## v5.0.4

### New: opt-in background polling for the activity log

The activity log no longer polls every minute by default — most installs never look at it, and the per-minute API traffic was wasted.

Background polling is now controlled by an **Activity Log and Events** options toggle (`enable_activity_polling`, **default off**), in both the initial config flow and the options flow.

- When **off**: the `ActivityCoordinator` is created with `update_interval=None` (no timer). The activity-log Lovelace card pulls fresh data via the existing `refresh_activity_log` service — once on connect and once a minute while it's on screen (spinner shown) — and stops when the card is removed. Zero API calls when nobody's viewing. Remote (panel-originated) events are **not** raised on the `verisure_owa_activity` bus while polling is off, so opening a dashboard after a gap can't replay a burst of stale events. HA-injected events still fire live.
- When **on**: continuous 60s polling, as before — turn this on if you want event automations to fire for actions taken outside HA.

No config migration: a missing `enable_activity_polling` reads as the default (off) for existing installs.

### New: HA-action echoes are de-duplicated

When you arm/disarm/request-an-image from HA, the panel later returns its own echo of that action. The previous null-user heuristic stopped matching once Verisure attributed the echo to the integration's signed-in user. Now the echo is paired to the injected event by **category + timestamp (±15s)** — robust to clock skew and to however the panel attributes the user — and tagged `duplicate_of`. The echo is **kept** (its native-language description and precise `type` are richer than the generic injected row) but the card folds it into the HA event's detail (unfold to see the **Verisure record**) and the echo never fires on the bus. So an HA action enriches the log once and triggers automations once.

### Bug fixes

- **Auto-lock-on-arm fired false "Auto-lock failed" notifications.** The Verisure backend acks a lock command before the device physically actuates (~6s to start, ~4.5s to complete per PR #413), so the single immediate read-back raced ahead of the lock and saw it still unlocked. The ~15s actuation wait that PR #413 added (`hub.py: _LOCK_CMD_MIN_WAIT`) was lost when `change_lock_mode` moved to the generic submit-and-poll scaffold, which returns on the ~2s command ack. Two changes on the entity side:
  - Auto-lock-on-arm no longer skips when the cached state reads LOCKED. That cache is eventually-consistent and can be stale (user physically unlocked moments before arming) — trusting it would leave the door silently unlocked while armed. We now skip only when a lock operation is genuinely in flight; a redundant lock on an already-locked door is harmless.
  - The single read-back is replaced by `_poll_lock_until()`, which re-reads up to `LOCK_VERIFY_ATTEMPTS` times (`LOCK_VERIFY_DELAY` apart) and confirms success on `lockStatus == target` **with a `statusTimestamp` newer than the pre-command baseline**. A stale target read does not confirm, closing the "armed + silently unlocked" hole. The failure notification fires only when the settled state is definitively unlocked; UNKNOWN falls back to optimistic (no false alarm). (See v5.0.5 for the follow-up cache-bypass and fresh-baseline fixes.)

- **Danalock-protocol locks logged a full traceback on every detection.** Such locks return HTTP 500 to the `xSGetSmartlockConfig` fast-path query — the *expected* signal to fall back to Danalock detection. The fallback was logged with `exc_info=True`, dumping a traceback every time. The known HTTP 500 case is now logged as a single concise DEBUG line; any other status (auth, WAF, rate-limit, connection failures) still logs the full traceback so real faults aren't hidden.

### Docs

- README + options-flow description (in all locales: en/es/fr/it/pt/pt-BR/ca) tell users to **disable autolock in the Verisure app** — the app's timer-based autolock fights this integration's arm-driven locking — and clarify that the **direction differs from the Verisure app**: there is no unlock-on-disarm here; "Disarm before unlocking" is the *inverse* (unlocking from HA disarms). README points at an HA automation for unlock-on-disarm.
- `docs/architecture.md` refreshed for the verify-poll scheme and the no-skip-on-stale-LOCKED change.

## v5.0.3

### New: configurable arm-state buttons in the alarm card

The Verisure OWA alarm card supports an optional `states: [...]` config key to filter which arm-state buttons are shown, mirroring HA's stock `alarm-modes` tile feature.

- `states` omitted → today's behavior (all `supported_features` buttons).
- `states: []` → no arm buttons; gesture editor's `arm_state` dropdown shows a helper hint instead of options.
- `states: [arm_away, arm_home]` → only those buttons appear (subject to `supported_features`).
- The user's filter is intersected with what the panel actually supports, and sub-panel runtime rejection still shrinks `supported_features` *before* the filter runs.
- Editor gets a new **Arm modes** checkbox section. The gesture `arm_state` dropdown is filtered live by the same subset; stale `arm_state` values on existing gestures are scrubbed when the underlying mode is hidden. Badge and Chip inherit the behaviour through their embedded card.

### Bug fixes

- **Lock Automation options page silently skipped when the user opened it before background lock discovery finished.** Reported on #447. The options flow now waits up to 15s on a per-entry `lock_discovery_complete` asyncio.Event before deciding the installation has no locks, so users see the lock page on first visit even on slow API responses. Discovery additionally runs locks before cameras to get the event set sooner, and the `get_lock_modes` discovery call is bumped to FOREGROUND priority. The event is set in a `finally` so the await unblocks even when discovery raises mid-way.

- **Lovelace editor took an extra hop opening any of the cards.** The alarm card (Card and Badge variants) and the camera card returned the legacy `securitas-*-card-editor` tag from `getConfigElement()`, even though the canonical `verisure-owa-*-card-editor` is the real class (the legacy tag is a shim alias). Switched all three to the canonical tag — the legacy alias still resolves.

- **Card editor regressions surfaced while testing the new `states` config.**
  - Per-variant gesture defaults: editor's `holdDefaults` was always `arm_or_disarm` regardless of variant, but only the Badge runtime defaults to that — Card and Chip were silently doing nothing on long-press despite the editor showing "Arm Away". Variant detection only matched `custom:securitas-alarm-badge` exactly, missing the canonical `verisure-owa-*` names and the `mushroom-*` chip alias. Editor defaults now mirror per-variant runtime fallbacks.
  - YAML-mode edits silently no-op'd the UI: the editor's `setConfig` only re-rendered on entity/type changes (intentional, to preserve focus during in-editor keystrokes). An `_internalWriteInFlight` flag now suppresses focus-destroying round-trips for in-editor writes, while every *external* `setConfig` always re-renders.
  - All three variants' `disconnectedCallback` freed gesture listeners but never reset `_lastKey`, so the `set hass` short-circuit prevented re-render on reconnection — Card hold and Badge/Chip tap+hold went dead after any dashboard re-mount (tab switch, editor open/close, conditional/stack re-render).

- **Panel-rejection codes surfaced as raw integers in the activity feed.** Bare codes like `48` ("Already armed in this mode") were shown verbatim instead of the humanized string. Now resolved through the same translation path as the rest of the panel-event codes.

- **Alarm panel entity_id healer overwrote user renames.** The healer that re-attaches a panel after a config-entry reload now respects user renames in the entity registry — it matches via the panel's stable `unique_id` rather than recomputing the entity_id.

- **Browser cached older versions of the bundled Lovelace cards across releases.** Card URLs now embed the integration version (`?v=5.0.3` etc.), so every release busts the browser cache without users having to hard-reload.

### Internal

- **JS test infrastructure for the bundled Lovelace cards.** Vitest + happy-dom + ESLint + Prettier; 286 tests; 90% coverage gate on statements / branches / functions / lines, enforced in CI. The activity-log, camera, and alarm cards each got pure-helper extraction, unit tests for helpers, integration tests for render/state/interaction paths, editor integration tests, legacy-shim re-export tests, and gesture-handler edge-case tests.
- **Vitest bumped 2 → 4** (and happy-dom 15 → 20). Vitest 4's v8 coverage uses AST-aware remapping (more accurate branch counts), which dropped the same source from 90.67% → ~85% branches under v2. Targeted edge-case tests cover the genuinely new branches; the defensive duplicate-registration guards at the bottom of each card file are wrapped in `/* v8 ignore */` since their "already defined" branch can't be exercised in a single-process test run. Net coverage stays above the 90% gate.
- **Unit and integration tests split into separate CI jobs** per HA channel, with a combined 90% coverage gate on the stable channel. `pytest.mark.integration` is auto-applied to any test file that imports `homeassistant` or `tests.mock_graphql`, or requests the `mock_server` fixture. Coverage configuration moved into `pyproject.toml` so local and CI runs share the same exclusions and branch-coverage settings.

## v5.0.2

### New: refresh & capture as entity services

The refresh button (on alarm panels) and capture button (on cameras) used to be plain HA `button.*` entities that the alarm and camera cards had to *discover* on the device, then trigger via `button.press`. That discovery was fragile — HA entity_id disambiguation (`button.refresh_2`), user renames, or icon changes broke the lookup. The bundled cards now call entity services directly on the configured panel / camera entity:

- **`verisure_owa.refresh_alarm`** (target: `alarm_control_panel`) — supersedes pressing `VerisureRefreshButton`. Same authoritative `CheckAlarm` + status-poll round-trip, same `refresh_failed` / `waf_blocked` semantics, same `verisure_owa_activity` event injection on failure.
- **`verisure_owa.capture_image`** (target: `camera`) — supersedes pressing `VerisureCaptureButton`. Same fresh-image wait, same `verisure_owa_activity` event injection with the real server `id_signal` so the activity-log card can fetch the photo.

These services exist only under the `verisure_owa.*` domain — they were never released under `securitas.*` so there's no backwards-compat twin.

`VerisureRefreshButton` and `VerisureCaptureButton` remain as deprecated thin delegating wrappers so existing automations and Lovelace button cards continue to work; pressing them logs a one-line deprecation warning and will be removed in a future release.

### Activity-log services no longer dual-registered

`refresh_activity_log` and `fetch_activity_image` are now registered only under `verisure_owa.*` (previously also as `securitas.refresh_activity_log` / `securitas.fetch_activity_image` for symmetry with the older services). These two services are v5+ only, so there's no pre-v5 automation to keep working. If you scripted against the `securitas.*` form, switch to `verisure_owa.*`. `verisure_owa.force_arm` and `verisure_owa.force_arm_cancel` keep their dual `securitas.*` aliases — those pre-date v5.

### New event category: `communication_restored`

Activity-log type code `3121` ("Estado de las comunicaciones" on Spanish firmware) — fires when the panel's link to the central / website returns to normal after a period of being unreachable. Mirrors the existing `communication_failed` category. New icon (`mdi:lan-connect`) + success-green color in the activity-log card, with translations in all seven supported locales.

### Bug fixes

- **Camera refresh button: spinner stuck for 15s after the API succeeded.** The hub cleared the `capturing` flag in a `finally` block AFTER the coordinator update had already written entity state, so the published state kept reporting `capturing=true` until the next 30-min poll. The camera card's spinner-clear condition never fired and the spinner only cleared via the 15s fallback timer. The flag is now cleared *before* the state-writing coordinator update.

- **Camera refresh button: returned image was sometimes the previous frame.** `xSGetThumbnail` immediately after the alarm-manager's `photo-request.success` could return a frame timestamped well before the request — the CDN serves the previous frame for tens of seconds after capture acknowledges. The client now pre-fetches a baseline thumbnail at click time and then polls until something strictly newer is published (5s cadence, 30s budget). Lexicographic string compare on the server's ISO timestamp — no timezone math needed since both come from the same server clock.

- **Camera refresh button: stale-image polling cadence was hammering the API.** Pre-v5 the image-status poll used `max(5, delay_check_operation)` — a hard 5s minimum. A refactor on 2026-04-09 (the unification onto a generic `_poll_operation`) silently dropped that floor and let the integration-wide `poll_delay` (typically 2s, tuned for arm/disarm UX) drive image-status polling too, producing ~40 status calls per ~80s capture and risking WAF rate-limiting. Restored the 5s minimum for image capture without changing arm/disarm cadence.

- **Camera coordinator overwrote a freshly-captured frame with a stale one.** Race between the user clicking capture and a concurrent in-flight 30-min coordinator poll: the poll started before the capture (snapshotting `self.data`), the capture wrote a fresh thumbnail+image to `self.data`, then the poll's `_fetch_thumbnails` returned an older frame for the same zone and overwrote. The poll now re-reads `self.data` after fetching and merges per-zone — a fetched thumbnail strictly older than what's currently stored is dropped in favour of the existing one, and its corresponding full image is preserved.

- **Activity log: HA-injected image-request rows didn't show the image.** The activity-log card's lazy image fetch is gated on the event's `img=1` flag; HA-injected `IMAGE_REQUEST` events were leaving `img=0`. With this and the fresh-frame fix above, the injected event now uses the real server `id_signal` AND sets `img=1`, so the activity-log card renders the captured photo inline. Same fix dedupes the polled echo of the same event (it now matches the injected event's real id).

- **Camera card editor: full-image variants appeared in the entity picker.** The picker was filtering by entity_id suffix (`endsWith("_full_image")`), which missed HA's disambiguation suffix (`camera.salon_full_image_2`) and any user-renamed entities. Now filters via the entity registry's platform + entity_id regex.

- **Stale `xSRefreshLogin response is None` log message obscured Verisure's reauth signal.** The integration logged "response is None" even when the GraphQL response carried a perfectly readable `Invalid Session (err=60067)` in `errors[]`. `_extract_response_data` now surfaces the first GraphQL error's message + err code in the raised exception (`xSRefreshLogin failed: Invalid Session (err=60067)`), so reauth failures are debuggable from logs alone.

### Internal cleanups

- All in-card lookups that previously walked the entity_id space looking for "the right button" or "the right full-image entity" now match on `device_id` + entity-domain prefix. Each Verisure sub-device only ever holds the expected entities (camera sub-device: thumbnail + full + capture button; installation device: alarm panel + refresh button + activity log sensor), so device matching alone is sufficient. Survives any future HA entity_id-generation change.
- Drop the deprecated `hass` positional argument to `async_extract_entity_ids` (removed in HA Core 2026.10).

### HACS bug fix

- **HACS upgrade from any prior version now works.** v5.0.1 introduced a second `custom_components/verisure_owa/` directory alongside the legacy `custom_components/securitas/` shim. HACS only ever manages one directory per repository ([hacs/integration#385](https://github.com/hacs/integration/issues/385)) — HACS users only got the shim, the new directory was never deployed, and Home Assistant refused to load the `securitas` integration because its declared dependency `verisure_owa` was missing. v5.0.2 collapses everything back into a single `custom_components/securitas/` directory and stays on the `securitas` domain. The full domain rename is deferred until it can ship via a separate HACS repository; see [`docs/MIGRATION_PLAN.md`](docs/MIGRATION_PLAN.md).

### Service and event naming

Every service is now registered under BOTH `securitas.<X>` AND `verisure_owa.<X>`, and every event the integration fires is emitted under BOTH `securitas_<X>` AND `verisure_owa_<X>`. Both forms are functionally identical and equal-weight in HA's eyes — no deprecation, no warnings, no scheduled removal.

**Prefer the `verisure_owa.*` / `verisure_owa_*` form in any automation you write going forward.** When the deferred domain rename completes (see `docs/MIGRATION_PLAN.md`), the `securitas.*` form will move to a separate compatibility integration; automations using the `verisure_owa` form will keep working unchanged. The Lovelace card picker only offers the `custom:verisure-owa-*` forms; old dashboards using `custom:securitas-*` types continue to render via aliased custom-element registrations.

The `services.yaml` descriptions and the README explicitly recommend the verisure_owa form. The `verisure_owa.*` services also get a programmatic UI schema via `async_set_service_schema` so they appear in the Developer Tools service picker with full field validation, identical to the securitas form.

### Cleanup notice

- If your `/config/custom_components/` still contains a `verisure_owa/` directory left behind by the failed v5.0.1 upgrade attempt, a Repairs issue will prompt you to delete it. The folder does nothing now; deleting it and restarting Home Assistant clears the notice.

### What stays the same

- "Verisure OWA" remains the integration display name and the Lovelace card brand.
- All v5.0.0 / v5.0.1 features are preserved (sub-panels, autolock, activity log, refresh-token auth, force-arm event API, sub-panel feature gating, etc.).
- Entity unique_ids stay on the v4 schema (`v4_securitas_direct.<...>`) — no entity churn on upgrade.

### Removed

- `custom_components/securitas/migrate.py` and the `restart_required_after_migration` Repairs flow — the forward migration from `securitas` to `verisure_owa` is no longer applicable.
- The `console.warn` deprecation message on `custom:securitas-*-card` Lovelace types — both names are kept indefinitely as equal aliases.

## v5.0.1

### Bug fixes

- **Activity log refresh button.** The refresh button and the on-expand image fetch for image-request events called the legacy `securitas.*` services and failed with "Action securitas.refresh_activity_log not found"; both now use the new `verisure_owa.*` services.
- **Activity log text selection.** The event rows in the activity log card swallowed text selection — Lovelace inherits `user-select: none` into the card's shadow tree, and the row click handler toggled expand/collapse on any drag. The card now opts back in to text selection on both the header and the expanded details and only toggles on clicks (drags of more than 4 px no longer fire the toggle).
- **Sub-panel entity_ids.** Enabling the Interior, Perimeter, or Annex sub-panel created an entity_id with the installation alias repeated (`alarm_control_panel.<alias>_<alias>_<circuit>` on HA 2026.5+, `<alias>_<circuit>_<alias>` on the earlier breakage path). The sub-panel mixin's `suggested_object_id` now returns `"<alias> <circuit>"` (space separator) instead of `"<alias>_<circuit>"` so fresh installs land on the canonical `<alias>_<circuit>` slot. HA 2026.5 unconditionally prepends the device name onto a `has_entity_name=False` entity's slug, running a strip-prefix heuristic to avoid doubling, and that heuristic recognises space/dash/colon as a separator but NOT underscore — so the underscore version came back device-prepended-twice. The space separator lets HA strip the prefix cleanly and slugify maps to the same canonical slug on every supported HA version. An upgrade-time healer still relocates already-broken entries on existing installs whose canonical slot is free at startup; if the slot is already held by another `verisure_owa` entity (most likely another installation sharing the alias slug) the healer logs a warning and leaves the broken entity in place rather than risk evicting someone else's sub-panel. The healer also rewrites stored entity_ids on entity-registry tombstones (HA's `deleted_entities`), so a delete-and-readd cycle doesn't reintroduce the doubled-alias slug — `async_get_or_create` restores entities onto their previous (cached) entity_id, bypassing the entity's `suggested_object_id`, so the tombstone needed correction too.
- **Activity log unknown events.** Event type 820 ("Disattivazione Perimetrale", perimeter disarm — the disarm counterpart to the existing 821/823/824 perimeter-arm codes) is now mapped to `DISARMED` instead of `UNKNOWN`. Event type 14 ("Allarme Foto", a photo-detector alarm with an attached image) is now mapped to `ALARM` — same category as the generic type 13 alarm.
- **Activity log image expansion.** The Lovelace card gates image fetch/display on the event's `img=1` flag instead of `category == "image_request"`, so photo-detector alarms (type 14) now show their attached image on row expand — same as the existing image-request flow.
- **Sub-panel arming modes the panel rejects are now disabled, persistently — on every axis.** On an Italian SDVECU Interior sub-panel, pressing Armed Night triggers an `ARMNIGHT1` the panel rejects — there's no way to detect this in advance. Previously the error notification pointed users at the state-mapping UI (which sub-panels don't have) and the button came back on the next HA restart, so the same rejection happened again. The `CommandResolver` is now hydrated from a persisted `unsupported_commands` mapping in `entry.data`, and each 400-rejection appends to it. The Interior, **Perimeter, and Annex** sub-panels each recompute `supported_features` against the resolver via `can_reach_interior` / `can_reach_perimeter` / `can_reach_annex` — so a rejected `ARMNIGHT1` / `PERI1` / `ARMANNEX1` removes the corresponding button from the card the moment it fails and stays gone across restarts (previously only the Interior sub-panel filtered features; Perimeter and Annex kept showing `ARM_AWAY` even after their single arm command was rejected). The persisted mapping is keyed by `installation.number` (`{"<install_num>": [<commands>...]}`) so a legacy config entry covering multiple installations no longer cross-contaminates sibling panels' resolvers; the v5.0.1-pre flat-list format is preserved on read and migrated to the keyed shape on the next write. The notification still uses a sub-panel-specific translation key that explains the mode has been disabled, rather than pointing at the missing mappings UI.
- **Clearing a mapping field actually clears it.** PR #463 swapped the "Not used" dropdown choice for "leave the field blank", but the field couldn't actually be cleared. Three layers were broken: (1) when the user cleared via the X clear button, HA's frontend omitted the key entirely from user_input — and since the prior options dict also lacked it (from an earlier broken save), the merged options matched the existing state and the update listener never fired; (2) even when the listener did fire, it synced options into data via `{**entry.data, **entry.options}`, which preserved the stale value in data for any cleared key; (3) the form's pre-fill then fell back to that stale data value, so the cleared field re-appeared on the next open. The mappings step now records cleared optional fields as explicit `""` in entry.options (so the listener sees the diff) and the listener replaces options-managed fields in entry.data instead of merging — clearing a previously-set Vacation or Custom mapping now sticks.
- **Pre-emptive fix for HA 2026.6 config-flow deprecation.** HA 2026.6 deprecates the combination of `entry.add_update_listener` and the implicit reload-on-update path of `_abort_if_unique_id_configured` (it errors in 2026.12) — the two together can race and double-reload. We rely on the listener to sync options into data, so the listener stays; the abort call in `_create_entry_for_installation` now passes `reload_on_update=False` to opt out of the other half of the combo. No runtime behaviour change on HA ≤ 2026.5; silences the deprecation warning on 2026.6+.

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
