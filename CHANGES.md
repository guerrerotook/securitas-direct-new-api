# Changelog

Most recent at the top.  For changes prior to v5, see [the GitHub release notes](https://github.com/guerrerotook/securitas-direct-new-api/releases).

## v5.8.0

A new opt-in auto-force-arm tick box on the alarm card, plus opt-in DEBUG diagnostics to help pin down a refresh-login crash that a few accounts still hit on every restart after the v5.7.0 fix.

### Added

**Auto-force-arm past open sensors, straight from the card ([#566](https://github.com/guerrerotook/securitas-direct-new-api/issues/566)).**  When you arm with a door or window left open, the alarm blocks and waits for you to tap **Force Arm** — easy to miss, and until you do the alarm never arms.  A new opt-in setting, **"Offer an auto-force-arm tick box on the alarm card"**, adds a *force-arm past open sensors* tick box below the arm buttons on the alarm card; with it ticked, arming from that card and hitting an open sensor force-arms past the open zones automatically instead of waiting for you to confirm.  The bypassed zones are still recorded in the activity log as *Armed with exceptions*.  It is off by default — force-arming silently bypasses open doors and windows, and some panels (Spain has been observed) don't support it at all — and the tick box is remembered per device in the browser, so it only ever affects arming from that card and never changes how automations or the stock alarm card behave.  Thanks to [@WSorban](https://github.com/WSorban) for the request.

**Opt-in diagnostics for the refresh-login crash that persists after v5.7.0 ([#568](https://github.com/guerrerotook/securitas-direct-new-api/issues/568)).**  v5.7.0 fixed one cause of the `xSRefreshLogin failed: Cannot read properties of undefined (reading 'fr')` crash that leaves the integration stuck until it is deleted and re-added, but a few accounts still hit it.  This release re-adds DEBUG-level logging — off by default and with no behaviour change — that fingerprints the refresh token across a restart, records each rotation and whether it was persisted, and tags the raw server response for the refresh call.  Together these tell apart the two remaining possibilities: a stale token loaded from disk (something our side still isn't persisting) versus the server crashing on a token that is actually current (a server-side fault, which re-authenticating would not fix).  If you are affected, enable debug logging for `custom_components.securitas` — a `logs:` entry under `logger:` in `configuration.yaml` — then leave Home Assistant running for half an hour, restart it, and share the log on the issue.  Thanks to [@amullr](https://github.com/amullr) for the report.

## v5.7.0

Two fixes: a partial-arming entry in the activity log that showed up as an unknown event now reads as an arm, and the refresh-login crash that left some accounts stuck on every restart is fixed at its root.

### Fixed

**Refresh-login crash on every restart left some accounts stuck ([#557](https://github.com/guerrerotook/securitas-direct-new-api/issues/557)).**  Some accounts — France especially — hit a server-side `xSRefreshLogin failed: Cannot read properties of undefined (reading 'fr')` error on every Home Assistant restart, and the integration stayed down in a retry loop until it was deleted and re-added.  The integration keeps its session alive by rotating the refresh token roughly every fifteen minutes and writing each new token back to the config entry, so the latest one survives a restart.  The catch: the session built during the initial login exists *before* its config entry does, and when Home Assistant then set up the new entry it reused that same session without ever attaching the entry to it — so every rotated token was dropped instead of saved.  On the next restart the integration reloaded the *original* token from disk, long since invalidated by all the rotations the server had performed, and the server rejected it.  The reused session is now attached to its config entry during setup, so rotated tokens are persisted and the newest valid token is the one restored after a restart.  If you run several installations on one account and remove the one the shared session happened to be saving through, persistence now hands off to a surviving installation instead of stranding it on a stale token, so the same failure cannot resurface there either.  Huge thanks to [@NatsuOnFire](https://github.com/NatsuOnFire), who reported it, captured the debug logs, tracked down the exact cause, and provided the fix — tested on their own French installation — and to [@benunter](https://github.com/benunter) for confirming it.

**A partial arm showed as "Unknown event" in the activity log ([#555](https://github.com/guerrerotook/securitas-direct-new-api/issues/555)).**  When the panel armed a partial mode it emitted event code `702`, which the integration did not recognise, so the activity log listed it as an *Unknown event* instead of an arm.  Code `702` is now mapped alongside the other arm signals, so a partial activation appears as an armed event — correctly grouped, iconed and coloured — like any other arm.  Thanks to [@philippemezzadri](https://github.com/philippemezzadri) for reporting it with the event details.

## v5.6.0

One fix, for anyone whose alarm has been reset remotely by Securitas' monitoring centre: disarming from Home Assistant no longer fails afterwards with an "unknown state" error.

### Fixed

**Disarm failed with "unknown state 'N'" after a central-station reset ([#551](https://github.com/guerrerotook/securitas-direct-new-api/pull/551)).**  When the monitoring centre cancels a false alarm and re-arms your system remotely, Verisure can leave the alarm in a state code this integration doesn't recognise (`N`).  Disarming from Home Assistant then failed outright: the alarm panel refused with *"Alarm is in unknown state 'N'"*, and unlocking a smart lock set to disarm-on-unlock silently skipped the disarm — opening the door over a still-armed alarm.  A disarm command is unconditional (it clears the alarm whatever state it is in), so disarming now goes ahead from any unrecognised state instead of refusing, while *arming* — which needs to know the current state to choose the right command — still declines and reports the code so it can be added.  Axis sub-panels disarm only their own circuit, and a smart-lock auto-disarm now clears every configured circuit when the state can't be read rather than skipping.  Thanks to [@danielmugica-beep](https://github.com/danielmugica-beep) for the detailed report.

## v5.5.0

The local alarm PIN can now guard your smart locks as well as the alarm panel — and it is stored hashed rather than in plain text.  Four fixes besides: a long-standing bug that silently discarded your PIN and alarm mappings shortly after a fresh install, an integration left permanently down by a network blip during Home Assistant startup, camera capture delivering nothing for long-idle cameras, and forward compatibility with Home Assistant 2026.8's device-registry change.

### Added

**Require the alarm PIN for smart lock operations ([#535](https://github.com/guerrerotook/securitas-direct-new-api/pull/535)).**  A new opt-in setting — **Require PIN for lock operations**, in the PIN section of the integration options — extends the local PIN you already use for disarming to locking, unlocking, and opening your smart locks.  There is no second PIN to manage: it reuses the one that is already there, and it is off by default and inert unless a PIN is set, so nothing changes until you turn it on.  It closes a real gap for anyone using [auto-disarm on unlock](https://github.com/guerrerotook/securitas-direct-new-api#lock-automations) — until now, unlocking the door from Home Assistant disarmed the alarm *without* ever asking for the PIN the alarm panel itself demands.  The integration's own auto-lock-on-arm and auto-disarm-on-unlock automations stay internal and are never gated.  Thanks to [@edwin-anne](https://github.com/edwin-anne) for the feature.

> [!WARNING]
> **Enabling this breaks anything that locks or unlocks without supplying the PIN.**  Only the Home Assistant UI prompts for it.  Your own automations and scripts need `code:` adding to their `lock.lock` / `lock.unlock` / `lock.open` calls, and anything bridging your locks outwards — HomeKit, Alexa, Google Assistant, Assist — has to be configured separately (HomeKit Bridge, for example, has its own per-entity `code` option).  Home Assistant's per-entity **Default code** setting must also be left empty, or it will either bypass the PIN or, if it is wrong, block every lock and unlock with no way to enter the right one.  See [Requiring a PIN for lock operations](https://github.com/guerrerotook/securitas-direct-new-api#requiring-a-pin-for-lock-operations) before turning it on.

### Fixed

**Camera capture delivered nothing for long-idle cameras ([#541](https://github.com/guerrerotook/securitas-direct-new-api/pull/541)).**  Requesting a fresh image for a camera left idle for days delivered nothing to Home Assistant until the next scheduled poll — up to 30 minutes later — even though the panel took the photo.  Verisure's CDN stops serving a thumbnail after some idle days, so the pre-capture baseline came back empty and `capture_image` returned that empty frame immediately instead of waiting for the freshly-taken one.  The freshness wait now engages even when the baseline is missing, polls through the empty responses until the real frame is published, and rides out a transient network blip mid-wait instead of dropping the whole capture.  Thanks to [@jpmreis](https://github.com/jpmreis) for spotting and fixing this on a live installation.

**Integration stayed down after a network blip during Home Assistant startup ([#540](https://github.com/guerrerotook/securitas-direct-new-api/pull/540)).**  A connect timeout escaped the transport unwrapped, so Home Assistant recorded a permanent setup failure it never retries and the integration stayed down until a manual reload.  Network-level failures are now raised as `APIConnectionError` and retried; connection resets and truncated response bodies, which escaped the same way, are covered too.  The distinct type also stops the poll loop misreading a dropped packet as a refusal: polling for confirmation of an arm, disarm or lock keeps retrying instead of aborting a command the panel already accepted.  And setup now applies the same genuine-versus-transient classification as [#528](https://github.com/guerrerotook/securitas-direct-new-api/pull/528) to a failed token refresh, so *any* transient failure there — a network blip, a 5xx, a 409 or a WAF block — retries instead of forcing re-authentication on a token-only account, closing the one refresh path #528 had not yet reached.

**A fresh install silently lost its PIN and alarm mappings minutes after setup ([#537](https://github.com/guerrerotook/securitas-direct-new-api/pull/537)).**  If you enabled any of the optional sub-panels (Interior, Perimeter, Annex) while first setting the integration up, your PIN, all five alarm-state mappings, the scan interval and the notify settings were quietly discarded on the first successful login — within minutes of finishing setup.  The visible symptoms were an alarm panel that had stopped asking for the PIN and accepted *any* code, and mapped buttons reverting to defaults.  Only installs that turned a sub-panel on during the initial wizard were affected; enabling one later, from the options dialog, was always safe.  The cause was that setup stores the sub-panel toggles separately from everything else, and the routine that keeps options and stored settings in step mistook that partial state for "the user has saved every setting", so it discarded the ones it could not see.  This bug predates the PIN work above — it is only now that its consequence was a disabled PIN rather than lost mappings.

If you were affected, the settings are gone and cannot be recovered: open the integration options once, re-enter your PIN and mappings, and save.  From then on this cannot recur on that installation.

**Forward compatibility with Home Assistant 2026.8's device-registry change ([#542](https://github.com/guerrerotook/securitas-direct-new-api/pull/542)).**  Home Assistant 2026.8 deprecates the `via_device` link this integration uses to nest each camera and smart lock under its alarm panel — removing it in 2027.8 — in favour of `via_device_id`.  The integration now feature-detects which one the running Home Assistant expects and uses it: `via_device_id` on 2026.8 and later, the original `via_device` on the cores it still supports back to 2025.2.  Child devices keep nesting under the panel exactly as before, with no deprecation warning on new Home Assistant and no break when the old link is removed.

### Security

**The alarm PIN is stored hashed instead of in plain text ([#536](https://github.com/guerrerotook/securitas-direct-new-api/pull/536)).**  The local PIN is never sent to Verisure — it only gates arm, disarm, and now lock actions inside Home Assistant — but it was written to the config entry verbatim, so a configuration backup, or a config dump attached to a support request, disclosed it directly.  It is now kept only as a salted PBKDF2-HMAC-SHA256 hash: a PIN you type can be checked against it, but the PIN itself can no longer be read back — not even by the integration.  Any existing PIN is hashed automatically on upgrade, with nothing for you to do.  The one visible consequence is that the options field can no longer be pre-filled with your real PIN, so it shows a fixed `●●●●●●●●` mask once one is set: leaving the mask untouched keeps the PIN, clearing the field removes it, and typing anything else replaces it.  A forgotten PIN can't be recovered — clear the field and set a new one.  See [How the PIN is stored](https://github.com/guerrerotook/securitas-direct-new-api#how-the-pin-is-stored).  Thanks to [@edwin-anne](https://github.com/edwin-anne) for the change.

## v5.4.1

Three fixes: the Home Assistant automation editor no longer breaks — for every integration, not just this one — whenever this integration is loaded; token-only accounts are no longer dragged to a re-authentication prompt by transient backend session errors; and the coordinator degrades gracefully instead of crashing when the comfort / air-quality API returns partial sensor data.

### Fixed

**Automation editor "Target could not be loaded" while the integration is loaded ([#525](https://github.com/guerrerotook/securitas-direct-new-api/pull/525)).**  On recent Home Assistant (reproduced on 2026.7.1), adding *any* action in the automation editor failed: the target picker showed "Target could not be loaded" and the websocket call returned `unknown_error` — for every device, not only this integration's entities.  The six services registered through `async_set_service_schema` declared their `target` entity filter as a bare mapping (`{"integration": …, "domain": …}`).  Unlike `services.yaml` — which Home Assistant validates and normalises with `cv.ensure_list` at every level — that registration path copies the target through unchanged, so the automation-editor lookup iterated the mapping's string keys and raised `AttributeError`.  Because Home Assistant builds that lookup once across *all* installed integrations, the single malformed entry aborted it for every device.  Both the entity filter and its `domain` are now declared as lists — the outer list stops the crash, and the inner list keeps the filter matching this integration's own entities — with a regression test guarding the shape.  Thanks to [@MarcelHoell](https://github.com/MarcelHoell) for the diagnosis and fix.

**Spurious daily/weekly re-authentication on token-only accounts during backend wobbles ([#528](https://github.com/guerrerotook/securitas-direct-new-api/pull/528)).**  Two Spain users were being forced to re-authenticate every day or two even though their refresh token was healthy the whole time — in the debug logs, 493 of 493 token refreshes returned `OK`.  The reauth was self-inflicted: a transient server-side 403 — *"Invalid session. Please, try again later."* — that outlived a *successful* token refresh was routed into `login()`, which for a refresh-token-only account (no stored password since v5.1.0) always fails with "no password available" and was misclassified as a genuine auth failure, raising a re-authentication prompt.  Session-expiry recovery now classifies on the actual server response instead: a 403 that survives the client's own refresh-and-retry is treated as a transient backend desync and simply retried on the next poll, while a genuinely dead refresh token (error `60067`) still prompts re-authentication as it should.  The same genuine-versus-transient distinction was extended to camera thumbnail fetches, and a faithful repro of the observed reauth sequence is now a regression test.

**Coordinator crash on partial comfort / air-quality data ([#528](https://github.com/guerrerotook/securitas-direct-new-api/pull/528)).**  During the same backend hiccups the comfort and air-quality API can return a null status object, null humidity or temperature readings, or a present-but-null `current` value.  `get_sentinel_data` and `get_air_quality_data` crashed on these — a `dict.get` default only fills in *absent* keys, not present-but-null ones — so the whole coordinator update failed.  Both now degrade gracefully to empty/zero instead of raising.

## v5.4.0

The always-visible alarm chip now appears almost instantly on a cold dashboard load, the activity log recognises smart-lock door and Verisure-routine events instead of labelling them "Unknown event", and the card UI is fully localised and screen-reader friendly.

### Performance

**The alarm chip and badge load fast on a cold start ([#518](https://github.com/guerrerotook/securitas-direct-new-api/pull/518)).**  The always-visible Verisure alarm chip used to live inside the 90 KB alarm-card bundle, so on a cold companion-app load the whole bundle had to download before the chip could register and render — it could take 5–10 seconds to appear, long enough that the alarm might trigger before you could tap to disarm.  The chip and badge are now split into their own lightweight module (a ~43 KB render path) that loads independently of the heavy card and editor, so the chip shows up almost immediately.  Card bundles are now also hard-cached for 31 days with version-stamped imports, so the browser and companion app serve them from cache on later cold opens instead of re-downloading them — with a CI guard that keeps every cache-bust token in sync with the release version.

### Added

**Smart-lock door and Verisure-routine events in the activity log ([#512](https://github.com/guerrerotook/securitas-direct-new-api/issues/512), [#513](https://github.com/guerrerotook/securitas-direct-new-api/issues/513), [#514](https://github.com/guerrerotook/securitas-direct-new-api/pull/514)).**  Three panel event types used to show up as "Unknown event": a connected smart lock opening a door and auto-locking it again a few minutes later, and a Verisure-app routine firing — the user-scheduled automations that can arm or disarm the alarm.  They are now recognised as distinct **Door opened**, **Door closed**, and **Routine executed** categories, each with its own icon, colour, and label in every supported language.

### Changed

**Full frontend localisation and accessibility pass ([#519](https://github.com/guerrerotook/securitas-direct-new-api/pull/519)).**  The strings that were still hardcoded in English across the alarm, camera, and activity-log cards — the PIN keypad's clear and delete buttons, the unavailable-state notice, the alarm-card editor labels, the camera capture button, and the activity-log editor labels — are now translated in every supported language.  The PIN keypad, camera capture, and popup close buttons also gained accessible names so screen readers can announce them, and a dialog connection-listener leak was fixed.  Automated CI guards now block any new untranslated string or hardcoded English UI label.

## v5.3.0

Arm and disarm no longer report a false failure — and roll the panel back to a stale, untrustworthy state — when the backend accepts the command but is slow to confirm it.

### Fixed

**Arm/disarm wrongly reported as failed when the backend is slow to confirm ([#508](https://github.com/guerrerotook/securitas-direct-new-api/issues/508)).**  On some backends — notably Italy (SDVECU) — the panel accepts an arm or disarm (the command returns `OK`) but the follow-up confirmation poll can sit on `processing.request` past the timeout.  The integration used to treat that timeout as an outright failure: it rolled the entity back to its previous state, logged an error, and raised an "arm/disarm failed" notification — even though the panel had actually carried out the command.  The result was a Home Assistant alarm state that couldn't be trusted (showing `disarmed` while the panel was armed, or the reverse) plus spurious failure alerts.  A command the backend has accepted but not yet confirmed is now treated as **accepted-but-provisional**: the entity optimistically shows the intended state, flags it as provisional, logs a *warning* rather than an error, and posts a distinct "not confirmed" notification — then reconciles automatically against the next authoritative status read.  Genuine failures still roll back and notify exactly as before.  A re-entry guard also stops a duplicate command being sent while one is already in flight.

### Added

**Configurable operation poll timeout.**  A new **Operation poll timeout** option (Configure → Advanced; default 120 s, range 60–300 s) sets how long to wait for the panel to confirm an arm/disarm before treating it as accepted-but-unconfirmed.  Raise it if you see "not confirmed within timeout" warnings in the log.

## v5.2.0

Re-authentication is now reserved for genuine credential problems, and transient Verisure backend hiccups no longer drag you to the login screen.

### Fixed

**Spurious re-auth prompts during backend wobbles ([#502](https://github.com/guerrerotook/securitas-direct-new-api/pull/502)).**  A short Verisure-side outage — an "Invalid session, try again later" (HTTP 403), a 500 on the zones endpoint, or even a server-side crash in the token-refresh call — used to surface as a Home Assistant re-authentication request, even though your username and password were perfectly fine.  The integration now classifies failures: only a genuine auth problem (wrong credentials, a blocked account, 2-factor required, or an explicitly revoked token) triggers a re-auth prompt.  Everything else — server errors, timeouts, WAF blocks, transient session drops — is treated as temporary and simply retried on the next poll, so the integration heals itself once Verisure recovers, with no clicking required.  The password is still never stored on disk; the fix does not reintroduce it.

### Added

**Visible, reportable diagnostics when recovery stalls.**  Because ambiguous failures are now retried indefinitely rather than forcing a re-auth, the logs make it obvious when something is genuinely stuck: after several consecutive transient auth-recovery failures the integration logs an escalating warning — stating that re-auth is being deliberately withheld, how long the trouble has lasted, the exact server response, and a link to file an issue — so a misclassified, truly-dead session can be spotted and reported instead of silently retrying forever.

## v5.1.2

A bugfix release for Spain (and any market) hitting repeated re-authentication failures since v5.1.0.

### Fixed

**Session drops every few hours ([#499](https://github.com/guerrerotook/securitas-direct-new-api/issues/499)).**  Since v5.1.0 the password is used once to mint a long-lived refresh token and then dropped from storage.  Two problems combined to break that on Spanish accounts: when the short-lived session token expired, the several entity coordinators that share one connection would all try to refresh at the same instant, racing each other over the single-use refresh token — the first won, the rest were rejected.  A rejected refresh then fell back to a password login, but the password was already gone, so the integration sent an empty one and the server replied "el usuario o la contraseña son incorrectos" — which also counts toward the three-strikes account lock.  Token renewal is now serialized so only one refresh runs at a time, and a refresh failure with no stored password now triggers a clean re-auth prompt instead of an empty-password login.

## v5.1.1

Bugfix release.

**Disarm fallback restored.**  Some panels — observed on Spanish installations in night+perimeter mode — reject the combined `DARM1DARMPERI` disarm command with an HTTP 404 ("Requested data not found") instead of the more usual 400.  Pre-v5 code fell back to plain `DARM1` on any non-busy error, but the v5 resolver/executor only fell back on 400, so on these panels the disarm appeared to silently fail.  The executor now treats 404 the same as 400 — a permanent panel-side rejection of *this* specific command — and falls through to `DARM1`, restoring the v4 behaviour.

## v5.1.0

This is the first stable v5 release, and the first major update since v4.0.9 in April.

### Verisure OWA

The integration has been renamed from Securitas Direct to Verisure OWA.  The Lovelace cards have all picked up new names (`custom:verisure-owa-alarm-card` and so on), and the services and events have done the same (`verisure_owa.*` and `verisure_owa_*`).  Every old `securitas`-prefixed name will keep working as an alias until v6.0, so there is nothing you need to migrate today.  If you are writing new automations or dashboards, prefer the new names.

While we are on the subject, the refresh and capture *button* entities on alarm panels and cameras have been deprecated.  They have been replaced by proper service actions: `verisure_owa.refresh_alarm` targets an `alarm_control_panel`, and `verisure_owa.capture_image` targets a `camera`.  The buttons themselves still work, but they log a deprecation warning each time they are pressed, so swap your automations over to the actions when you get a chance.

### Upgrading

This is a normal HACS upgrade, and your existing config entries will upgrade in place with no entity churn.

There is one thing to watch for: passwords are no longer kept on disk.  The first time HA starts after the upgrade you may see a reauth dialog asking you to type your password in again.  The integration uses it once to mint a long-lived refresh token, and the password is then dropped from storage.

### What's new

**Smart-lock automations.**  You can now have the door lock when you arm a chosen circuit, and have the alarm disarm when you unlock from HA.  Both are configurable from the integration's Options page.  The disarm and unlock dispatch in parallel, so the door pops open without a noticeable wait.

**Activity log.**  This is a proper timeline of what the panel does, covering arms, disarms, intrusions, image requests, and power events.  It comes with a new Lovelace card and a sensor.  Actions you fire from HA are tagged with your HA user, and the panel's later polled echo of the same action is folded into the same row so that your automations do not double-fire.  Background polling is off by default, and the card pulls fresh data on demand while it is on screen.

**Sub-panels per circuit.**  If your installation has separate Interior, Perimeter, or Annex sensors, you can opt into a dedicated `alarm_control_panel` entity for each one alongside the main panel.

**Compact alarm widgets.**  There is a new alarm badge and a Mushroom-style chip, for dashboards where the full alarm card is too much.

**Peru support.**  Peru is now supported alongside the existing Argentina, Brazil, Chile, France, Ireland, Italy, Portugal, Spain, and UK markets.
