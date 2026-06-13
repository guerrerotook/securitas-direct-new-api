# Changelog

Most recent at the top.  For changes prior to v5, see [the GitHub release notes](https://github.com/guerrerotook/securitas-direct-new-api/releases).

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
