# Before-release manual testing todo

This branch combines the `subpanels` work (three-axis alarm model + opt-in
sub-panels), the `eventlog` work (xSActV2 activity timeline → events
bus, sensor, Lovelace card), and the **v5 Verisure rebrand** (domain
renamed from `securitas` to `verisure_owa`, full registry migration via
a legacy-domain shim, vendored API library renamed to `verisure_owa_api`,
brand strings updated everywhere, and ~6 months of legacy
service/event/URL/card-tag aliases for backwards compatibility).
Automated tests cover the unit-level behavior; the items below need a
real HA install + real Verisure account to validate, since they depend
on actual API responses, multi-axis state, or hardware configuration.

## Required before merge

### Sub-panel work

- [ ] **Sub-panel disarm preserves siblings.** Pressing Disarm on the
      Perimeter (or Annex) sub-panel must disarm only that axis, leaving
      the interior axis armed. Regression test for the bug behind
      [b509c13](https://github.com/clintongormley/securitas-direct-new-api/commit/b509c13)
      / [8cf541d](https://github.com/clintongormley/securitas-direct-new-api/commit/8cf541d).
      Setup: arm interior + perimeter (PARTIAL_DAY_PERI). Press Disarm on
      the Perimeter sub-panel. Expected:
      - integration sends `DARMPERI` (not `DARM1` or `DARM1DARMPERI`)
      - alarm transitions to PARTIAL_DAY (interior armed, perimeter off)
      - Interior sub-panel still shows ARMED_HOME

- [ ] **Italy: rejected-command notification names the failed command.**
      Map "Night" to "Partial Night" and press Night on the main panel.
      The panel rejects ARMNIGHT1 (Italian SDVECU). Expected
      user-facing notification text:
      > "This alarm mode is not supported by your panel (rejected: ARMNIGHT1).
      > Check the state mappings…"

      Then restore Night to "Not Used".

- [ ] **Sub-panel toggle visibility in options flow.** With the
      capability-gating change in
      [894953f](https://github.com/clintongormley/securitas-direct-new-api/commit/894953f),
      the Interior toggle should be visible whenever any sibling capability
      (`has_peri` or `has_annex`) is supported, *regardless* of whether the
      sibling toggle is currently enabled. Settings → Devices & Services →
      Verisure OWA → Configure:
      - With `has_peri=True`: Perimeter and Interior toggles both visible.
      - Toggling Perimeter on/off must NOT cause the Interior toggle to
        appear/disappear.

- [ ] **Toggle-off removes the entity.** Disable a sub-panel toggle in
      options. The corresponding `alarm_control_panel.<alias>_<axis>`
      entity must disappear from the entity registry / dashboard.
      Re-enable: entity reappears.

### Activity log work

- [ ] **An HA automation can be triggered by `verisure_owa_activity`
      events.** The integration documents these as the primary
      automation entrypoint, but no one has wired one up on a real
      install yet. Create an automation in the UI:

      ```yaml
      trigger:
        - platform: event
          event_type: verisure_owa_activity
          event_data:
            category: alarm   # or tampering / sabotage / disarmed / …
      action:
        - service: notify.persistent_notification
          data:
            message: "fired: {{ trigger.event.data.alias }}"
      ```

      Trigger that category from the panel (or app) and confirm the
      notification fires once. Then add the documented "skip
      HA-issued" template condition and confirm it skips events
      injected from HA (arm/disarm via the alarm panel entity) but
      still fires for panel/app-originated activity:

      ```yaml
      condition:
        - condition: template
          value_template: "{{ not trigger.event.data.injected }}"
      ```

- [ ] **Force-arm injects `armed_with_exceptions` with the exception
      list.** Trigger an arm with an open sensor → expect the integration
      to surface the persistent notification with Force Arm. Press Force
      Arm. The activity timeline should show:
      - an entry with category `armed_with_exceptions` (HA badge), and
      - the open zone(s) listed inline when the row is expanded
      - `event.exceptions[]` populated on the bus event
      Then trigger a hard arm failure (5802/5824) and confirm an
      `arming_failed` row appears with the exceptions list.

- [ ] **Disabling the activity log sensor does not break bus events.**
      Originally the `verisure_owa_activity` listener was attached inside
      `ActivityLogSensor.async_added_to_hass`,
      so disabling the sensor entity in the entity registry silently killed
      all bus events too. Commit `a084e19` moved the listener to
      `async_setup_entry` so it lives for the lifetime of the integration.
      Unit tests cover the decoupling, but the actual HA "disable entity"
      path isn't automation-testable. Sanity check on a real install:
      1. Set up an automation that listens for `verisure_owa_activity`
         (any category) and writes a persistent notification.
      2. Disable `sensor.<alias>_activity_log` in
         Settings → Devices & Services → Entities.
      3. Arm / disarm at the panel.
      4. Confirm the notification still fires.

      Then re-enable the sensor.

### V5 Verisure rebrand work

- [ ] **🚧 BLOCKS v5.0.0 TAG: annex camera unique-id collision (issue #441) is still unfixed.**
      The v5 spec §5 explicitly gates v5.0.0 release on this: "v5 does
      not ship until investigation completes."
      
      What main *did* land via the subpanels work:
      - `AnnexVerisureOwaAlarmPanel` and `ARMANNEX1` / `DARMANNEX1`
        command wiring — covers the alarm-panel axis.
      
      What's still NOT addressed:
      - The original [#441](https://github.com/guerrerotook/securitas-direct-new-api/issues/441)
        report is about **camera** unique-id collisions:
        `v5_verisure_owa.{numinst}_camera_{zone_id}` collides when main
        and annex sub-panels both return `zone_id="YR08"`. The annex
        camera + capture button get silently dropped at HA startup with
        an `ERROR ... Platform does not generate unique IDs` log.
      - Locks plausibly have the same collision risk if an annex
        sub-panel numbers its locks independently from `device_id="01"`
        — unconfirmed, needs investigation alongside cameras.
      
      What we have:
      - Two HAR captures from Vatrinus (`vatrinus.json`,
        `customers.verisure.co.uk.redacted.json` — same account, both
        `numinst: ***5885`) but **neither contains `xSDeviceList`** —
        only home / status / disarm screens were captured. The captures
        confirm `panel: SDVFAST` is a per-installation hardware-type
        identifier (not a per-device discriminator) and that the OWA
        web frontend models alarm operations as
        `{interior, exterior, smartLock}` axes — but neither tells us
        what `xSDeviceList` returns for an annex camera.
      
      What we need:
      - A fresh HAR capture from Vatrinus's OWA web client taken on
        the *Cameras* screen. That will include the unredacted
        `xSDeviceList` response and (likely) the `xSSrv` response that
        delivers `Installation.alarm_partitions` — the two operations
        we need to settle whether the discriminator is a per-device
        partition field, a partition-segmented response shape, or
        something else.
      - Once we have that, the implementation is mechanical: add the
        discriminator field to `CameraDevice` and `SmartLock` (only if
        confirmed for locks too), adjust the unique-id format to
        append the discriminator only when populated, and ride along
        with the existing `migrate_legacy_entry` mapping table for
        existing-user state preservation. The pattern is the same as
        the `[_{discriminator}]` suffix scheme in the v5 design spec
        §2's mapping table — the suffix is empty for main-panel
        devices so existing main-only users come out unchanged after
        migration.
      
      **What we still don't know:** the API field name and shape of
      the discriminator. Earlier hypotheses (`panel`, partition `id`)
      are educated guesses that could not be verified from the HAR
      data we have. Do not pick one speculatively — picking wrong
      either fails to fix #441 or breaks users who don't have an
      annex.

- [ ] **Upgrade-from-v4 smoke test (the migration path).** Install v4
      (current `main` minus this branch) into a Docker HA, configure a
      `securitas` integration entry, log in, let cameras/sensors
      discover, customize one entity's name and area assignment in the
      HA UI, capture the entity_id list. Then update the codebase to
      this branch and start HA. **Verify:**
      - The migration shim's persistent notification appears with the
        full deprecation list (services, two events, URLs, card types)
        and the v6 removal date.
      - HA logs show the migration ran without errors (`migrate_legacy_entry`
        info line, no `ConfigEntryError` rollback).
      - Restart HA. The integration appears under domain
        `verisure_owa` (Settings → Devices & Services). The legacy
        `securitas` entry is gone. All entity_ids match the
        pre-upgrade snapshot. The customized entity still has its
        custom name and area.
      - In Developer Tools → Services: `verisure_owa.force_arm` is
        listed and works. `securitas.force_arm` (legacy alias) is also
        listed (marked deprecated in services.yaml description) and,
        when called, both works AND emits a `_LOGGER.warning`
        deprecation message in the log.
      - Browser fetch of `http://<ha>:8123/securitas_panel/securitas-alarm-card.js`
        and `/verisure_owa_panel/verisure_owa-alarm-card.js` both
        return 200 with byte-identical content.
      - Existing dashboards using `type: custom:securitas-alarm-card`
        keep rendering. Browser console shows the deprecation
        `console.warn` once per element instance per page load.

- [ ] **Spain user verifies API hostname change.** A Spanish account
      should now hit `customers.verisure.es` (changed from
      `customers.securitasdirect.es`). Spot-check the integration's
      DEBUG logs after a fresh login or refresh — the request URL
      should show `customers.verisure.es`.

- [ ] **Peru appears in the country dropdown.** During a fresh
      install via the config flow, Peru (`PE`) is selectable in the
      country dropdown.

- [ ] **HA brand assets render.** The integration's icon and logo
      (the four PNG files in `custom_components/verisure_owa/brand/`)
      should render in HA's integration UI. HA looks them up via the
      `brand/` directory adjacent to `manifest.json`. Check
      Settings → Devices & Services and confirm the integration
      shows the Verisure logo and icon, not a placeholder.

## Post-merge follow-ups

- [ ] **Map the four perimeter+annex proto codes.** Issue #441 supplied
      the table for the four annex-armed-without-perimeter codes
      (X/R/S/O), now mapped to ANNEX_ONLY / PARTIAL_DAY_ANNEX /
      PARTIAL_NIGHT_ANNEX / TOTAL_ANNEX in PROTO_TO_STATE. The four
      perimeter+annex combinations remain unmapped:
      - PERI_ANNEX (no interior, perimeter on, annex on)
      - PARTIAL_DAY_PERI_ANNEX
      - PARTIAL_NIGHT_PERI_ANNEX
      - TOTAL_PERI_ANNEX

      A user with all three axes (interior + perimeter + annex) can
      cycle through these and capture the protomResponse code for each,
      then we add four more rows to PROTO_TO_STATE in
      `verisure_owa_api/const.py`. Until then the alarm panel falls
      back to ARMED_CUSTOM_BYPASS for these states with an info-level
      "unmapped proto code" log line.

- [ ] **Compound transition optimization (optional).** Verisure web app
      uses single-API-call compound commands when transitioning between
      partial states (e.g. `ARMINTFPART1` to go DAY → TOTAL without an
      explicit DARM1 in between). Our resolver always emits
      `DARM1 + <new-mode>`. Functionally correct but costs an extra
      round-trip and briefly transitions through DISARMED, which can
      fire HA automations. Decoded JS analysis in
      `docs/handoffs/2026-05-05-verisure-web-dispatch-findings.md`
      (gitignored).

- [ ] **Activity log: catalogue smart-lock event types.** Lock/unlock
      actions surfaced in `xSActV2` haven't been catalogued — no entries
      in `_ACTIVITY_TYPE_TO_CATEGORY` and no `lock_*` categories in
      `ActivityCategory`. Capture fixtures for HA-issued and
      panel/app-issued lock + unlock, then add categories + type-code
      mappings + injection from `lock.py` (mirroring how
      `alarm_control_panel.py` injects arm/disarm). Until then, lock
      events surface as either a `unknown`-category polled row or
      nothing at all.

- [ ] **Repo rename + HACS update (release-day operation).** Per the
      v5 design spec §8.1: rename the GitHub repo from
      `guerrerotook/securitas-direct-new-api` to
      `guerrerotook/verisure-owa-ha`. Update `manifest.json`'s
      `documentation` and `issue_tracker` URLs, README badges and
      links, GitHub Actions workflows (if any reference the repo
      URL), update `hacs.json` → submit a PR to `hacs/default`
      pointing at the new repo URL. GitHub creates a 301 redirect
      automatically so existing clones / HACS installs keep working.

- [ ] **v5.0.0 release notes.** Required content:
      - The Securitas Direct → Verisure OWA rebrand and the GitHub
        repo rename.
      - Migration is automatic on first v5 launch; HA restart required.
        The shim shows a persistent notification listing what changed.
      - 6-month deprecation window with a hard cutoff in v6.0.0.
        Specific list of what's deprecated:
        - `securitas` integration domain (config entries auto-migrate)
        - `securitas.force_arm[_cancel]` services
        - `securitas_arming_exception` event
        - `/securitas_panel/` static URL prefix
        - `custom:securitas-alarm-card` (and badge / chip / camera-card)
          Lovelace types
      - Lovelace resource cleanup hint: users may see a duplicate
        resource entry (old `/securitas_panel/...js` + new
        `/verisure_owa_panel/...js`) — both work; either can be
        deleted manually if desired.
      - Spain users: API now goes to `customers.verisure.es`
        automatically, no action required.
      - Peru added as a new supported country.
      - Vendored library directory + class names changed (e.g.
        `SecuritasDirectError` → `VerisureOwaError`). Any third-party
        tooling that imports from `custom_components.securitas...`
        must update its import paths.

## Done

- [x] **Force-arm flow.** Persistent notification with Force Arm /
      Cancel buttons fires when arming with an open sensor; Force Arm
      bypasses the exception. Confirmed working on the user's install.

- [x] **Backwards compatibility.** Existing users keep their
      `entity_id`, mappings, and PIN configuration. `CONF_HAS_PERI` is
      dropped from stored data and recomputed at load time.

- [x] **Sub-panel state derivation.** Multi-axis state from the API is
      correctly projected onto each sub-panel via `_extract_state`.
      Confirmed by user during regular use.

- [x] **V5 rebrand: in-tree work landed.** The following items from
      the v5 spec landed during the rebrand branch and are covered by
      automated tests (1300+ passing on this branch):
      - Domain rename `securitas` → `verisure_owa`; folder rename;
        DOMAIN constant, manifest, services.yaml, all platform files.
      - Vendored API library renamed: `securitas_direct_new_api` →
        `verisure_owa_api`. Classes `SecuritasClient` →
        `VerisureOwaClient`, `SecuritasDirectError` → `VerisureOwaError`,
        `SecuritasState` → `VerisureOwaState`. No backwards-compat
        aliases (vendored library has no external consumers).
      - Python integration class names renamed `Securitas*` →
        `Verisure*` / `VerisureOwa*`.
      - JS card class names renamed `SecuritasAlarmCard` etc. →
        `VerisureOwaAlarmCard` etc. Custom-element TAG names are
        preserved as deprecation shims (both `verisure-owa-alarm-card`
        canonical AND `securitas-alarm-card` legacy registered;
        `console.warn` on legacy use; only canonical types listed in
        `window.customCards`).
      - Atomic per-entry registry migration (`migrate.py`) with
        try/except + `ConfigEntryError` rollback on failure.
      - Legacy-domain shim at `custom_components/securitas/` triggers
        migration on upgrade and shows a persistent notification
        listing every deprecated surface (services, events, URLs,
        card types) with the v6 removal date.
      - Legacy aliases active: `securitas.force_arm[_cancel]`
        services, `securitas_arming_exception` event,
        `/securitas_panel/` URL prefix
        — all forward to / fire alongside the canonical
        `verisure_owa.*` names with one-time deprecation warnings.
      - Sentinel sensors / WiFi binary sensor / Refresh button
        switched to `_attr_has_entity_name = True` so device renames
        propagate to entity display.
      - `v5_verisure_owa.*` unique-id and device-identifier schema;
        CI guardrail asserts every f-string in platform code is in
        the migration mapping table.
      - Branding strings updated: hacs.json, README, info.md,
        strings.json, all 7 translation files, JS card user-visible
        strings. Verisure brand assets (icon/logo) added to
        `custom_components/verisure_owa/brand/`.
      - Peru added to `COUNTRY_CODES`, language map, API domain map.
        Spain hostname → `customers.verisure.es`.
      - End-to-end migration tests cover multi-installation and
        camera-device migration paths.
