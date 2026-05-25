# Changelog

Most recent at the top.  For changes prior to v5, see [the GitHub release notes](https://github.com/guerrerotook/securitas-direct-new-api/releases).

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
