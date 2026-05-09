# Verisure OWA

A Home Assistant custom integration for **Verisure** (formerly Securitas Direct in some markets), supporting Argentina, Brazil, Chile, France, Ireland, Italy, Peru, Portugal, Spain, and the United Kingdom.

Renamed from `securitas` to `verisure_owa` in v5.0.0. The legacy domain shim, service aliases, event aliases, and panel URL aliases remain available until v6.0.0. See [Breaking Changes in v5.0.0](#breaking-changes-in-v500) for migration details.

## Features

### Alarm control

- **Main panel** — arm, disarm, and monitor your alarm from Home Assistant. One per installation.
- **Configurable state mappings** — map each HA alarm button (Home, Away, Night, Vacation, Custom) to any Verisure alarm mode.
- **Per-axis sub-panels** — for installations with perimeter or annex alarms, optional dedicated Interior-only / Perimeter-only / Annex-only control panels alongside the main panel.
- **Force arming** — when arming is blocked by an open sensor, the integration fires `verisure_owa_arming_exception` and (optionally) notifies you. Force-arm via mobile notification, the `verisure_owa.force_arm` service, the custom alarm card, or your own automations.
- **Refresh button** — trigger a manual alarm status check.

### Lovelace cards

The integration ships purpose-built cards, registered automatically when the integration loads:

- **Alarm card** — dynamic arm buttons (only the modes you've mapped), PIN keypad, and force-arm UI.
- **Alarm badge** — compact dashboard badge with a state-specific shield icon; tap opens the alarm card, hold/double-tap can arm or disarm directly.
- **Mushroom chip** — pill-shaped chip for use inside a [Mushroom Chips Card](https://github.com/piitaya/lovelace-mushroom), with the same state-specific icon and color as the badge.
- **Camera card** — latest thumbnail with a capture button, timestamp overlay, and click-to-open full-resolution image.
- **Activity log card** — viewer for the activity log with a refresh button and click-through to entry details (including images for image-request entries).

### Smart locks

- **Lock / unlock / open** — multi-lock installations supported. Both Smartlock and Danalock-type locks work, with auto-detection. When the lock supports latch hold-back, an "Open" action is exposed.
- **Auto-lock on arm** — per lock, pick which circuits should automatically lock the door when they arm.
- **Auto-disarm before unlock** — per lock, pick which circuits should be disarmed when the lock is unlocked from HA. Disarm and unlock dispatch in parallel; sub-panels animate the disarm in real time.
- **Failure notifications** — persistent notifications when an auto-lock, auto-disarm, or post-disarm unlock fails.

### Cameras

- **Live thumbnails + full-resolution images** — one thumbnail entity and one full-resolution entity per camera.
- **On-demand capture** — a Capture button triggers a fresh image; a `capturing` attribute is exposed for automations.

### Sensors

- **Sentinel** — temperature, humidity, and air quality (numeric and categorical) for each Sentinel device.
- **WiFi connectivity** — diagnostic binary sensor showing the panel's connection status.
- **Activity log sensor** — the most recent Verisure event as state, with the last 30 entries available as an attribute.

### Activity log

- **Verisure event history in HA** — arm/disarm, the Verisure user who did it, intrusions, image requests, power cuts, and more — surfaced via: an activity log card, the activity log sensor, and a `verisure_owa_activity` event you can trigger automations on.
- **HA action enrichment** — actions taken from within Home Assistant are tagged with the actual HA user and replace the events coming from Verisure so that automations only fire once.

### Multi-installation & authentication

- **Multiple installations per account** — each installation gets its own config entry and entities, with a shared API session.
- **Two-factor authentication** — login via SMS verification code; if your account requires 2FA you'll be prompted automatically during setup.
- **Refresh-token authentication** — your password is never persisted; first login mints a ~180-day refresh token, and the integration uses that for the rest of the session lifetime. If the token is revoked or expires, HA shows a one-time reauth dialog.
- **Local PIN protection** — optional PIN code for arming and/or disarming from HA, independent of your Verisure account.

## What's new in v5.0.0

- **Rebrand to `verisure_owa`.** Domain, services, events, and the side-panel URL are all renamed. Legacy aliases stay until v6.0.0 — see [Breaking Changes in v5.0.0](#breaking-changes-in-v500).
- **Peru.** Added support for Verisure customers in Peru.
- **Per-axis sub-panels.** Opt in to Interior-only, Perimeter-only, and Annex-only control panels for installations with multiple axes. 
- **Lock automations.** Configure each lock to auto-lock when a circuit arms, and to auto-disarm circuits before an HA-initiated unlock. 
- **Activity log.** Verisure event history is now a first-class HA citizen — Lovelace card, sensor, and `verisure_owa_activity` event bus entries. HA actions are enriched and de-duplicated against polled echoes.
- **Sectioned options flow.** Settings are grouped into PIN, force-arm notifications, sub-panels, and Advanced sections. The Sub-panels section appears only when peri or annex is detected.
- **Refresh-token authentication.** Passwords are no longer persisted to disk; logins now mint a long-lived refresh token. After upgrade you may see a one-time reauth dialog so the token can be minted from your existing password.

## Breaking Changes in v5.0.0

> **Warning:** v5.0.0 renames the integration from `securitas` to `verisure_owa`. Most users won't have to touch anything — every legacy reference keeps working through transparent shims until **v6.0.0**, at which point the aliases are removed. Plan to migrate any references before then.

- **Domain renamed `securitas` → `verisure_owa`.** New installs use `verisure_owa` everywhere. Existing installs are migrated automatically and their entity IDs are rewritten in the registry.
- **Service rename.** `securitas.force_arm` / `securitas.force_arm_cancel` are now `verisure_owa.force_arm` / `verisure_owa.force_arm_cancel`. The legacy names continue to dispatch to the new ones until v6.0.0.
- **Event rename.** `securitas_arming_exception` → `verisure_owa_arming_exception`. The legacy event still fires alongside the new one until v6.0.0 — automations triggered on either name keep working. The activity-log event is `verisure_owa_activity` (new in v5.0.0; no legacy alias).
- **Side-panel URL rename.** `/securitas_panel` → `/verisure-owa-panel`. The legacy URL is kept available until v6.0.0 so existing dashboards don't break mid-migration.
- **Lovelace card type rename.** Existing dashboards keep working — the legacy type names continue to render until v6.0.0 — but new installs and visual-editor pickers use the `verisure-owa-*` names. To migrate dashboards manually, edit the YAML and update each card type:

  | Old type                          | New type                              |
  | --------------------------------- | ------------------------------------- |
  | `custom:securitas-alarm-card`     | `custom:verisure-owa-alarm-card`      |
  | `custom:securitas-alarm-badge`    | `custom:verisure-owa-alarm-badge`     |
  | `custom:securitas-camera-card`    | `custom:verisure-owa-camera-card`     |

  Inside a Mushroom Chips Card, change `type: securitas-alarm` to `type: verisure-owa-alarm`.
- **Mobile-notification action IDs renamed.** The force-arm push notification's action IDs change from `SECURITAS_FORCE_ARM_<num>` / `SECURITAS_CANCEL_FORCE_ARM_<num>` to `VERISURE_OWA_FORCE_ARM_<num>` / `VERISURE_OWA_CANCEL_FORCE_ARM_<num>` in v6.0.0. The integration's built-in handling keeps working with no user action needed. Only affects users who wrote a custom HA automation triggered on `mobile_app_notification_action` matching the old strings — update those automations before upgrading to v6.0.0.
- **Password is no longer persisted.** Login now mints a ~180-day refresh token; the password is discarded and only the refresh token lives in the config entry. After upgrade, the integration may show a one-time reauth dialog so you can mint a refresh token from your existing password — enter it once and you're done.
- **`set_authentication_token` service removed.** The previous workaround for stuck logins is no longer needed; the refresh-token flow handles renewal automatically.

If you're upgrading from v3.x or earlier, the breaking changes from v4.0.0 still apply on top of the above — see the v4.0.0 release notes.

## Supported Countries

| Code | Country       | 
| ---- | ------------- | 
| AR   | Argentina     | 
| BR   | Brazil        | 
| CL   | Chile         | 
| ES   | Spain         | 
| FR   | France        | 
| GB   | United Kingdom| 
| IE   | Ireland       | 
| IT   | Italy         | 
| PE   | Peru          | 
| PT   | Portugal      | 

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=guerrerotook&repository=securitas-direct-new-api)

Or manually:

1. [Install HACS](https://www.hacs.xyz/docs/use/download/download/) if you don't have it already.
2. Open the HACS dashboard in Home Assistant.
3. Search for **Verisure OWA**.
4. Click download.

## Setup

Go to **Settings → Integrations → Add Integration** and search for **Verisure OWA**.

The setup flow is a multi-step wizard:

1. **Login** — Enter your country, username, and password. 2FA is handled automatically if your account requires it.
2. **Installation** — If your account has multiple installations, pick which one to configure. Repeat the setup flow to add the others. Perimeter and annex support is auto-detected from the installation's services and capabilities.
3. **Options** — PIN code, force-arm notifications, optional per-axis sub-panel toggles (only shown when supported), and a collapsed Advanced section for scan interval / API delay.
4. **Mappings** — Map each HA alarm button (Home, Away, Night, Vacation, Custom) to a Verisure alarm mode.

Once setup completes, locks and cameras are discovered in the background. The **Lock automation** screen for configuring auto-lock and auto-disarm appears in the Configure dialog (**Settings → Devices & Services → Verisure OWA → Configure**) once locks have been registered.

### Login

![Setup](./docs/images/setup.png)

| Option       | Default  | Description                                                                       |
| ------------ | -------- | --------------------------------------------------------------------------------- |
| Username     | —        | Your Verisure account username.                                                   |
| Password     | —        | Your Verisure account password.                                                   |
| Country Code | _(auto)_ | Auto-detected from your HA locale. All supported countries available in dropdown. |

### Two-factor authentication

If your account requires 2FA, you will automatically be asked to select a phone number and enter the SMS code during setup.

![2FA](./docs/images/2fa.png)

### Credential storage

Your password is **not** persisted to disk. After the initial login the integration stores a long-lived refresh token (~180-day TTL) in the Home Assistant config entry, which is used to keep your session alive across restarts without your password. If the refresh token expires or is revoked (for example, you change your password externally), Home Assistant shows the standard reauth dialog asking you to re-enter your password — entering it once mints a fresh refresh token and the password is discarded again.

## Options

After setup, change most settings via **Settings → Integrations → Verisure OWA → Configure**. The Configure dialog walks you through three (or four, with locks) screens.

![Options](./docs/images/options.png)

### Screen 1 — Options

| Section | Option | Default | Description |
| ------- | ------ | ------- | ----------- |
| **PIN code for disarming** | PIN code | _(empty)_ | Optional local PIN for the HA alarm panel. This PIN is **not** sent to Verisure — it only protects the panel in Home Assistant. Numeric or alphanumeric. |
| | Require PIN to arm | No | When enabled, the PIN is also required to arm (not just disarm). No effect if no PIN is set. |
| **Force-arm notifications** | Notify service | _(none)_ | A `notify` service to call when arming is blocked. Pick a mobile app notify service to receive an actionable notification with **Force Arm** and **Cancel** buttons. |
| | Built-in force-arm notifications | Yes | When enabled (default), the integration creates persistent and mobile notifications when arming is blocked. Disable to handle the `verisure_owa_arming_exception` event from your own automations. See [Force Arming (advanced)](#force-arming-advanced). |
| **Additional sub-panels** _(only when supported)_ | Enable Perimeter-only panel | No | Adds a `Perimeter - <alias>` alarm panel that controls the perimeter axis only. Visible only on installations with perimeter sensors. |
| | Enable Annex-only panel | No | Adds an `Annex - <alias>` alarm panel that controls the annex axis only. Visible only on installations with an annex zone. |
| | Enable Interior-only panel | No | Adds an `Interior - <alias>` alarm panel that controls the interior axis only. Visible whenever any sibling axis is supported. |
| **Advanced** _(collapsed)_ | Update scan interval | 120s | How often the integration checks the alarm status. Set to 0 to disable automatic polling. |
| | Delay between API requests | 2s | Minimum gap between consecutive API requests. Higher values reduce the risk of WAF rate limiting. |

### Screen 2 — Alarm State Mappings

See [Alarm State Mappings](#alarm-state-mappings) for the full reference.

### Screen 3 — Lock automation _(only shown when locks are discovered)_

See [Lock automations](#lock-automations) for the full reference.

## Alarm State Mappings

Verisure supports several alarm modes, but Home Assistant's alarm panel only has five buttons: **Home**, **Away**, **Night**, **Vacation**, and **Custom Bypass**. This integration lets you choose which Verisure mode each button activates.

![Alarm State Mapping](./docs/images/state-mappings.png)

### Available Modes

| Mode                              | Description                                              |
| --------------------------------- | -------------------------------------------------------- |
| Partial Day                       | Interior sensors armed (daytime)                         |
| Partial Night                     | Interior sensors armed (nighttime)                       |
| Total                             | All interior sensors armed                               |
| Perimeter only                    | External/outdoor sensors only                            |
| Partial Day + Perimeter           | Daytime interior + external sensors                      |
| Partial Night + Perimeter         | Nighttime interior + external sensors                    |
| Total + Perimeter                 | All interior + external sensors                          |
| Annex only                        | Annex armed, main alarm disarmed                         |
| Partial Day + Annex               | Daytime interior + annex                                 |
| Partial Night + Annex             | Nighttime interior + annex                               |
| Total + Annex                     | All interior + annex                                     |
| Perimeter + Annex                 | External sensors + annex                                 |
| Partial Day + Perimeter + Annex   | Daytime interior + external sensors + annex              |
| Partial Night + Perimeter + Annex | Nighttime interior + external sensors + annex            |
| Total + Perimeter + Annex         | All interior + external sensors + annex                  |

The available modes depend on which axes are detected on your installation: standard installations see only the four interior modes; perimeter installations add the four perimeter combinations; annex installations add the four annex combinations; installations with both add the four perimeter+annex combinations on top.

To hide a button from the alarm panel, leave its mapping field blank — clearing the field counts as "not used" and the button won't appear.

> **Note:** Your country may only support a single Partial mode, rather than a Partial Day and a Partial Night. In this case, use just Partial Day.

### How It Works

Each of the five HA alarm buttons can be mapped to any Verisure mode in the integration options. Leave a button's field blank to hide it from the alarm panel.

When the integration checks the alarm status, it translates the Verisure response back to the correct HA state using the same mapping. For example, if you mapped **Away** to "Total + Perimeter", then when Verisure reports "Total + Perimeter" the alarm panel will show "Armed Away".

When switching between modes (e.g. from "Armed Home" to "Armed Away + Perimeter" or to "Disarmed"), the integration automatically determines what changes need to be made to match the requested state.

### Default Mappings

**Standard installations** (no perimeter sensors):

| HA Button | Verisure Mode     |
| --------- | ----------------- |
| Home      | Partial Day       |
| Away      | Total             |
| Night     | Partial Night     |
| Custom    | Not Used (hidden) |
| Vacation  | Not Used (hidden) |

**Perimeter installations** (external sensors enabled):

| HA Button | Verisure Mode     |
| --------- | ----------------- |
| Home      | Partial Day       |
| Away      | Total + Perimeter |
| Night     | Partial Night     |
| Custom    | Perimeter Only    |
| Vacation  | Not Used (hidden) |

> **Note:** Perimeter variants (e.g. "Partial Night + Perimeter") are available as options and can be assigned to any button via the integration options.

### Unmapped Alarm States

If your alarm is put into a Verisure state that you have not mapped to any HA button (e.g. the perimeter is armed via a physical panel but perimeter support is not enabled in the integration), the alarm entity will show as **Custom Bypass**. This is not an error — enable perimeter support or adjust your alarm state mappings in the integration options to resolve it.

To see which status code the alarm is reporting, [enable debug logging](#reporting-issues).

## Sub-panels (advanced)

By default the integration creates one `alarm_control_panel` entity per installation — the **main panel**, named `Main - <installation alias>`. It represents the household's overall alarm intent and is driven by the user-configurable Home / Away / Night / Vacation / Custom mappings (Alarm State Mappings screen). This is unchanged from previous versions and works for almost everyone.

Installations with multiple alarm axes (interior, perimeter, annex) can optionally enable per-axis sub-panels via the integration's options (**Settings → Devices & Services → Verisure OWA → Configure**):

- **Interior-only control panel** — interior axis only (Home / Away / Night / Disarmed). Named `Interior - <installation alias>`.
- **Perimeter-only control panel** — perimeter axis only (Armed Away / Disarmed). Named `Perimeter - <installation alias>`. Visible only if your installation has perimeter sensors.
- **Annex-only control panel** — annex axis only (Armed Away / Disarmed). Named `Annex - <installation alias>`. Visible only if your installation has an annex zone.

The Interior toggle is offered as soon as Perimeter or Annex is detected, otherwise it is hidden as the Main panel is the equivalent. If your annex or perimeter circuit is not automatically detected, then [enable debug logging](#reporting-issues) and look for a line like:

```
capability detection for 123456: has_peri=False has_annex=False caps=['ARM', 'ARMDAY', ...]
```

Share that line in a bug report.

### Voice assistant note

Enabling sub-panels in HA creates additional `alarm_control_panel` entities, but **whether each is exposed to a voice assistant is configured independently in HA** (Settings → Voice assistants → Expose, or per-integration exposure config for HomeKit/Alexa). A common pattern: enable all sub-panels in HA for dashboards/automations, but expose only the main panel to voice — keeping voice commands unambiguous.

## Custom Alarm Card

The integration ships with a custom Lovelace card (`verisure-owa-alarm-card`) that is purpose-built for Verisure OWA. It goes beyond the standard HA alarm panel card by integrating the force-arm flow directly into the dashboard.

|                   Disarmed                   |                   Armed (Home)                   |                   Custom Mapping                    |
| :------------------------------------------: | :----------------------------------------------: | :-------------------------------------------------: |
| ![Disarmed](./docs/images/card-disarmed.png) | ![Armed Home](./docs/images/card-armed-home.png) | ![All Modes](./docs/images/card-custom-mapping.png) |

|                PIN Keypad                 |                   Force Arm                    |
| :---------------------------------------: | :--------------------------------------------: |
| ![PIN Keypad](./docs/images/card-pin.png) | ![Force Arm](./docs/images/card-force-arm.png) |

### Features

- **Dynamic arm buttons** — reads `supported_features` from the entity and only shows the modes that are actually configured. No unused buttons.
- **PIN keypad** — when a PIN code is configured, a numeric keypad appears automatically on arm/disarm. Alphanumeric codes use a text input instead. Respects `code_arm_required` (keypad only shown on arm if required, always shown on disarm).
- **Force-arm UI** — when arming is blocked by an open sensor, the card automatically shows a warning with the sensor name(s) and **Force Arm** / **Cancel** buttons. No Template Binary Sensor helper required.
- **Theme-aware** — uses Home Assistant CSS variables and works correctly in both light and dark mode.

### Setup

To add the card to your dashboard, click **Add Card → Search for "Verisure OWA Alarm Card"** and pick your alarm panel entity from the dropdown.

### Badge

A compact **Verisure OWA Alarm Badge** is also available for the badges section of your dashboard. It shows a state-specific shield icon that changes to an amber warning triangle when arming fails.

By default, tapping the badge opens the full alarm card in a popup overlay. You can also configure hold and double-tap actions — for example, to arm or disarm directly from the badge without opening the card. See [Gesture Actions](#gesture-actions) below.

To add the badge, click **Add Badge → Search for "Verisure OWA Alarm Badge"** and pick your alarm panel entity from the dropdown.

### Mushroom Chip

A **Verisure OWA Alarm Chip** is available for use inside a [Mushroom Chips Card](https://github.com/piitaya/lovelace-mushroom). Use `type: verisure-owa-alarm` in your Mushroom chips config. It shows the same state-specific icon and color as the badge, in a Mushroom-compatible pill shape.

Tapping the chip opens the full alarm card in a popup overlay. Gesture actions (hold, double-tap) are supported via YAML — see [Gesture Actions](#gesture-actions) below.

```yaml
type: custom:mushroom-chips-card
chips:
  - type: verisure-owa-alarm
    entity: alarm_control_panel.my_alarm
```

### Gesture Actions

The **alarm card**, **badge**, and **chip** all support configurable tap, hold, and double-tap actions. For the **card** and **badge**, these can be set in the visual editor under the **Tap action**, **Hold action**, and **Double-tap action** sections. For the **chip**, these actions are configured in YAML (see [below](#chip-gesture-actions)).

![Gesture Actions](./docs/images/card-gestures.png)

| Action     | Badge default | Chip default    | Card default |
| ---------- | ------------- | --------------- | ------------ |
| Tap        | Open alarm card | Open alarm card | _(none)_   |
| Hold       | Arm / Disarm  | _(none)_        | _(none)_     |
| Double-tap | _(none)_      | _(none)_        | _(none)_     |

Each action can be set to one of the following:

| Option   | Description                                                                                         |
| -------- | --------------------------------------------------------------------------------------------------- |
| None     | Do nothing.                                                                                         |
| Navigate | Navigate to a dashboard path. A path selector appears to choose the destination.                    |
| Arm      | Arm the alarm to a chosen state (Home, Away, Night, Custom, or Vacation). Only fires when disarmed. |
| Disarm   | Disarm the alarm. Only fires when armed.                                                            |

Example: set **Hold** to **Disarm** on the badge to disarm with a long press, without opening the card popup.

The card and badge have a visual editor for gesture actions. The chip only supports YAML configuration:

```yaml
type: custom:mushroom-chips-card
chips:
  - type: verisure-owa-alarm
    entity: alarm_control_panel.my_alarm
    tap_action:
      action: more-info           # default — opens alarm card popup
    hold_action:
      action: arm_or_disarm       # arms when disarmed, disarms when armed
    double_tap_action:
      action: navigate
      navigation_path: /lovelace/security
```

Available actions:

| Action           | YAML value                                                           |
| ---------------- | -------------------------------------------------------------------- |
| None             | `action: none`                                                       |
| Open alarm card  | `action: more-info`                                                  |
| Navigate         | `action: navigate` + `navigation_path: /path`                       |
| Arm or Disarm    | `action: arm_or_disarm` (optionally + `arm_state: armed_away` etc.) |

## Sentinel Sensors

If your installation includes Sentinel devices, the integration automatically creates temperature, humidity, and air quality sensors for each one.

## Smart Locks

If your installation includes smart door locks, the integration creates lock entities that you can lock and unlock from Home Assistant. Multiple locks per installation are supported — each lock gets its own entity.

Both Smartlock and Danalock-type locks are supported. The integration auto-detects which configuration API your lock uses, so no manual configuration is needed.

Lock features (latch hold-back time, auto-lock settings) are fetched from the lock configuration. When the lock supports latch hold-back, the entity exposes an "Open" action that unlatches the door without unlocking.

If the lock configuration cannot be fetched during startup (e.g. due to a temporary API outage), the lock entity is still created and works for lock/unlock operations. The integration retries the configuration fetch in the background, and the "Open" button will appear once the configuration is successfully retrieved.

### Lock automations

Each lock can be wired to two optional behaviours. Configure them under **Settings → Devices & Services → Verisure OWA → Configure**, in the **Lock automation** step (one section per discovered lock):

![Autolocking configuration](./docs/images/autolocking.png)

- **Auto-lock on arm** — pick which circuits (Interior, Perimeter, Annex) should trigger this lock to lock when they arm. With the Interior box ticked, arming Interior anywhere — main panel, Interior sub-panel, the Verisure app, the physical panel — automatically locks the door. 
- **Auto-disarm on unlock** — pick which circuits should be disarmed automatically when this lock is unlocked from HA. The disarm and the unlock dispatch in parallel, so both finish in roughly the time of one operation, and any sub-panels you've enabled show their normal "Disarming" → "Disarmed" animation while it's in flight.


Failures surface as persistent notifications:

| Notification | When it fires |
| ------------ | ------------- |
| **Auto-lock failed** | An arm transition fired the auto-lock but the lock couldn't reach the locked state. Notification ID is stable per lock, so consecutive failures replace rather than stack. |
| **Auto-disarm failed** | The pre-unlock disarm couldn't disarm the configured circuits. The unlock still proceeds. |
| **Unlock failed** | The disarm succeeded but the lock didn't unlock — the alarm is now disarmed but the door is still locked. |

Auto-disarm only triggers an HA-initiated unlock (via the lock entity, the dashboard, an automation calling `lock.unlock`, etc.). Unlocking from outside HA — the Verisure app, the physical lock — never reaches into the alarm.

## Cameras

If your installation includes Verisure cameras, the integration creates two camera entities per physical camera:

- **`camera.<name>`** — the thumbnail image, updated after each capture.
- **`camera.<name>_full_image`** — the full-resolution image fetched from the API after each capture.

A **Capture** button entity is also created for each camera, allowing you to request a new image on demand.

QR-type cameras, YR-type PIR cameras, and YP/QP perimetral (outdoor) cameras are all supported. The camera entity exposes a `capturing` attribute that is `true` while a capture is in progress, which can be used in automations or displayed on the dashboard.

When the capture button is pressed, the integration checks whether any images were taken since the last update (e.g. via the Verisure app or web portal) and displays them immediately, even before the newly requested capture arrives.

> **Note:** Images are fetched from the API queue and may take up to 30 seconds to appear after a capture completes, depending on queue depth.

### Custom Camera Card

The integration also ships with a custom Lovelace card (`verisure-owa-camera-card`) purpose-built for Verisure cameras.

![Camera Card](./docs/images/camera-card.png)

It shows the latest thumbnail image with:

- **Capture button** — shown in the top-right corner, requests a new photograph
- **Timestamp overlay** — displays when the image was taken, with a relative time and an absolute tooltip
- **Click to open** — clicking the image opens the HA more-info dialog. If a full-resolution image is available (auto-discovered from the same device), it opens the full-resolution entity; otherwise the thumbnail entity.

The card is registered automatically when the integration loads. To add it to your dashboard, click **Add Card → Search for "Verisure OWA Camera Card"** and pick your camera entity from the dropdown.

```yaml
type: custom:verisure-owa-camera-card
entity: camera.sala              # thumbnail entity (required)
name: Sala                       # optional — overrides the entity friendly name
```

| Option | Required | Description |
|---|---|---|
| `entity` | Yes | The thumbnail camera entity (`camera.<name>`) |
| `name` | No | Display name shown on the card. Defaults to the HA device name. |

## Activity Log

The Activity Log shows the same history of events as the Verisure app: when the alarm was armed or disarmed, who did it, intrusions, image requests, power cuts, and more. 

![Activity Log](docs/images/activity-log.png)

The integration brings that history into Home Assistant in three places.

### Where to find it

- **A Lovelace card.** When editing your dashboard, click **Add Card** and pick **Verisure OWA Activity Log Card**. It shows the most recent entries; click any row for details, including images for image-request entries. There's a refresh button in the top-right corner.
- **A sensor.** `sensor.<alias>_activity_log` shows the most recent event as its state. Its `events` attribute holds the last 30 entries — useful for templates, custom cards, or anything that needs to read the history programmatically.
- **The event bus.** Each new entry fires a `verisure_owa_activity` event you can use as an automation trigger (see below).

Each entry carries a **category** — a stable label for the type of event. The full list:

`armed`, `armed_with_exceptions`, `arming_failed`, `disarmed`, `alarm`, `alarm_resolved`, `tampering`, `sabotage`, `image_request`, `power_cut`, `power_restored`, `status_check`, `unknown`.

### Activity events vs the alarm panel entity

There are two natural ways to react to alarm activity in Home Assistant. Pick whichever matches what you're trying to do:

- **Use the alarm panel entity (`alarm_control_panel.<alias>`)** when you only care about the *current* armed/disarmed state. Its state changes between `armed_away`, `armed_home`, `disarmed`, `triggered`, etc., so it's the right fit for things like:
  - "Turn off the lights *when* the alarm becomes armed."
  - "Only run this automation *if* the alarm is currently armed."
  - "Notify me *when* the alarm is triggered."
- **Use Activity Log events (`verisure_owa_activity`)** when you need richer detail than just the on/off state — who did it, from where, or things the panel state doesn't reflect at all:
  - "Notify me when someone disarms the alarm and tell me **who** did it."
  - "Send me a message if a **tampering** or **sabotage** event is detected" (these never change the panel's state).
  - "Log every **image request** to a notification channel."
  - "Tell me when the panel **lost power** or **came back online**."

If both would work, the alarm panel entity is usually simpler. Reach for activity events when you need the extra context.

### Triggering automations on activity events

Trigger on a category and you'll catch every event of that kind:

```yaml
trigger:
  - platform: event
    event_type: verisure_owa_activity
    event_data:
      category: disarmed
```

Useful fields on `trigger.event.data`:

| Field | What it tells you |
| ----- | ----------------- |
| `category` | The stable label above (always present). |
| `alias` | The panel's own description, in your panel's language. |
| `verisure_user` | The Verisure account name that performed the action, if any. |
| `injected` | `true` if this event came from a Home Assistant action (see below). |

#### "Who disarmed it?" example

```yaml
trigger:
  - platform: event
    event_type: verisure_owa_activity
    event_data:
      category: disarmed
action:
  - service: notify.mobile_app
    data:
      message: "Alarm disarmed by {{ trigger.event.data.verisure_user or 'someone at the panel' }}"
```

#### Home Assistant actions and the `injected` flag

When you arm, disarm, or request an image **from Home Assistant** (the card, an automation, the alarm panel entity, a service call), the integration writes an enriched event into the log immediately — tagged with the actual HA user, any arming exceptions, and the captured image where applicable. These entries show a small Home Assistant badge in the card and have `injected: true`.

The matching event polled back from the panel ~60 seconds later is suppressed: it doesn't appear in the log and it doesn't fire on the event bus, so your automations only run once per action.

If you specifically want to react **only** to actions taken outside Home Assistant (at the panel, in the Verisure app, etc.), exclude the injected entries with a template condition:

```yaml
condition:
  - condition: template
    value_template: "{{ not trigger.event.data.injected }}"
```

### Unknown events — please report them

If a row appears in the card as **Unknown event**, the panel sent a code we haven't catalogued yet. Click to expand and you'll see a prompt asking for a screenshot. **Please take that screenshot** and open an issue at https://github.com/guerrerotook/securitas-direct-new-api/issues so we can add it. A short note about what triggered it (a manual disarm at the panel, an alarm test, a power cut, etc.) helps a lot.

### Missing Home Assistant action coverage

Home Assistant-issued arms, disarms, arming failures, and image requests are enriched and de-duplicated as described above. If you do one of those things from HA and instead see a *plain* row in the log (no Home Assistant badge, no user name, no extra detail), that means the resulting category isn't one we cover yet. Open an issue at https://github.com/guerrerotook/securitas-direct-new-api/issues describing what you did and what showed up — that's enough for us to add it.

## Automations & Scripts

You can arm, disarm, and control the alarm from automations and scripts using the standard Home Assistant alarm actions:

```yaml
action: alarm_control_panel.alarm_arm_away
target:
  entity_id: alarm_control_panel.my_alarm
data:
  code: "12345" # only needed if you have a PIN configured
```

Replace `alarm_arm_away` with the action for the mode you want:

| Action                                        | Mode     |
| --------------------------------------------- | -------- |
| `alarm_control_panel.alarm_arm_away`          | Away     |
| `alarm_control_panel.alarm_arm_home`          | Home     |
| `alarm_control_panel.alarm_arm_night`         | Night    |
| `alarm_control_panel.alarm_arm_vacation`      | Vacation |
| `alarm_control_panel.alarm_arm_custom_bypass` | Custom   |
| `alarm_control_panel.alarm_disarm`            | Disarm   |

> **Important:** Only actions for modes you have mapped in the [Alarm State Mappings](#alarm-state-mappings) will work. If you try to arm with an unmapped mode (e.g. calling `alarm_arm_home` when Home is left blank), the action will fail with an error. Check your mappings in **Settings → Integrations → Verisure OWA → Configure → Submit** (second page).

You can test which actions are available for your alarm in **Settings → Developer Tools → Actions** — type "arm alarm" to see the list.

## Force Arming (advanced)

Most users won't need anything from this section. When arming is blocked by an open sensor, the [custom alarm card](#custom-alarm-card) shows a warning with a **Force Arm** button, and — if **Built-in force-arm notifications** is enabled in the integration options — a mobile notification with **Force Arm** / **Cancel** action buttons does the same from your phone. That covers the common "window left open" case with no automation work.

The rest of this section is for users who want something more advanced: writing their own automations against the `verisure_owa_arming_exception` event (e.g. auto-force-arm only on `armed_away`, custom notification text, multi-step logic), or calling the `verisure_owa.force_arm` service directly.

### How it works

When you arm the alarm and a sensor is in a fault state (e.g. a window is open), Verisure may block the arm and report a non-blocking exception. The integration handles this as follows:

1. The alarm panel reverts to its previous state.
2. The alarm entity attributes `force_arm_available` and `arm_exceptions` are set.
3. A `verisure_owa_arming_exception` event is fired on the Home Assistant event bus (always, regardless of settings).
4. The [custom alarm card](#custom-alarm-card) shows a warning listing the problematic sensors, with **Force Arm** and **Cancel** buttons.
5. If **Built-in force-arm notifications** is enabled (default):
   - A **persistent notification** appears listing the affected sensors.
   - If a **Notify service** is configured, a **mobile notification** is sent with **Force Arm** and **Cancel** action buttons.

### Resolving the exception

- **Fix the issue** (close the window, clear the fault) and arm again normally.
- **Force arm** to arm despite the exception. You can do this from:
  - The **Force Arm** button in the mobile notification (if built-in notifications are enabled).
  - The `verisure_owa.force_arm` service, targeted at the alarm panel entity.
  - The **Force Arm** button in the [custom alarm card](#custom-alarm-card).
  - Your own automation triggered by the `verisure_owa_arming_exception` event.

The force-arm context expires after 180 seconds, so force-arming is only possible shortly after the exception occurs.

### The `verisure_owa_arming_exception` event

Every time arming is blocked by open sensors, the integration fires this event with the following data:

| Field | Description |
| ----- | ----------- |
| `entity_id` | The alarm panel entity that failed to arm |
| `mode` | The HA alarm state that was attempted (e.g. `armed_away`, `armed_home`) |
| `zones` | List of open zone names (e.g. `["Kitchen window", "Bedroom sensor"]`) |
| `details.installation` | The Verisure installation number |
| `details.exceptions` | Full exception list from the API with `alias`, `zone_id`, `device_type` |

This event fires **regardless** of the **Built-in force-arm notifications** toggle, so you can always build automations against it.

### Custom automations

To write your own force-arm automations, disable **Built-in force-arm notifications** in the integration options, then create automations that listen for the `verisure_owa_arming_exception` event. Some examples:

**Auto force-arm when leaving home:**
```yaml
- id: verisure_owa_auto_force_arm
  alias: "Alarm: auto force-arm when leaving"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  conditions:
    - condition: template
      value_template: "{{ trigger.event.data.mode == 'armed_away' }}"
  actions:
    - action: verisure_owa.force_arm
      target:
        entity_id: "{{ trigger.event.data.entity_id }}"
  mode: single
```

**Notify with open zone details:**
```yaml
- id: verisure_owa_notify_open_zones
  alias: "Alarm: notify about open zones"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  actions:
    - action: notify.mobile_app_phone
      data:
        title: "Alarm blocked"
        message: >
          Cannot arm {{ trigger.event.data.mode }}.
          Open zones: {{ trigger.event.data.zones | join(', ') }}
  mode: single
```

**Different behaviour per mode** (force-arm for away, notify for night):
```yaml
- id: verisure_owa_smart_force_arm
  alias: "Alarm: smart force-arm by mode"
  triggers:
    - trigger: event
      event_type: verisure_owa_arming_exception
  actions:
    - choose:
        - conditions:
            - condition: template
              value_template: "{{ trigger.event.data.mode == 'armed_away' }}"
          sequence:
            - action: notify.mobile_app_phone
              data:
                message: >
                  Open zones: {{ trigger.event.data.zones | join(', ') }}
                  — force-arming...
            - action: verisure_owa.force_arm
              target:
                entity_id: "{{ trigger.event.data.entity_id }}"
        - conditions:
            - condition: template
              value_template: "{{ trigger.event.data.mode == 'armed_night' }}"
          sequence:
            - action: notify.mobile_app_phone
              data:
                title: "Cannot arm night mode"
                message: >
                  Please close: {{ trigger.event.data.zones | join(', ') }}
  mode: single
```

### Notifying multiple people

The **Notify service** field accepts a single service name. To notify multiple people at once, create a notify group in your `configuration.yaml`:

```yaml
notify:
  - platform: group
    name: Mobiles
    services:
      - service: mobile_app_your_phone
      - service: mobile_app_partner_phone
```

This registers a `notify.mobiles` service. After restarting Home Assistant, `mobiles` will appear in the **Notify service** dropdown in the integration options.

> **Note:** Action buttons (Force Arm / Cancel) in the notification are tied to the installation number, so any household member who taps a button will trigger the correct action regardless of which device they use.

### `verisure_owa.force_arm` service

| Field         | Description                                   |
| ------------- | --------------------------------------------- |
| Target entity | The Verisure alarm panel entity to force-arm. |

Example automation action:

```yaml
action: verisure_owa.force_arm
target:
  entity_id: alarm_control_panel.my_home
```

## Troubleshooting

- **HTTP 403 errors / rate limiting** — Verisure uses a web application firewall (WAF) that blocks requests if you poll too frequently. The integration retries once automatically, but if you see repeated 403 errors in the logs:
  - **Increase the update interval** — Go to **Settings → Integrations → Verisure OWA → Configure**, expand the **Advanced** section, and increase the **Update scan interval** (default: 120 seconds). Try 180 or 300 seconds.
  - **Increase the API request delay** — The **Delay between API requests** (default: 2 seconds) controls the minimum gap between consecutive API calls. Increasing this to 4–5 seconds reduces request bursts.
  - If you have **multiple installations** on one account, each one polls independently, multiplying the request rate. All API requests to the same country domain are serialized through a shared queue, which helps, but the total volume still increases with each installation.
- **Alarm shows wrong state after using the Verisure app** — Periodic polling reads the last known status from the Verisure server, which may take a moment to reflect changes made via the app. Press the **Refresh** button to force an immediate panel check.
- **Stale lock state after lock/unlock** — If the lock shows the old state after a lock or unlock command and only self-corrects after the next periodic poll (~2 minutes), please [open an issue](https://github.com/guerrerotook/securitas-direct-new-api/issues) with your debug logs. We are actively improving lock status polling and your logs will help.
- **Cannot clear PIN code** — In the options flow, clear the PIN field and save. The PIN will be removed.
- **2FA issues** — If 2FA fails, remove and re-add the integration. You will be prompted for a new SMS code. If the error persists, try creating a new user via the Verisure mobile app, then log in to the customer web portal for your country to accept the terms of use before using the new credentials in Home Assistant.

## Reporting Issues

If you encounter a bug or unexpected behavior, please [open an issue](https://github.com/guerrerotook/securitas-direct-new-api/issues) and include the following:

1. **Home Assistant version** and **integration version** (from Settings → Integrations → Verisure OWA).
2. **Country code** you are using.
3. **Debug logs** — enable debug logging from the UI: go to **Settings → Integrations → Verisure OWA**, click the three-dot menu, and select **Enable debug logging**. Reproduce the issue, then click **Disable debug logging** to download the log file.

   If you need debug logs **before the integration has been set up** (e.g. during initial installation), run this action from **Settings → Developer Tools → Actions**:

   ```yaml
   action: logger.set_level
   data:
     custom_components.verisure_owa: debug
   ```

   Then retrieve the logs from **Settings → System → Logs → three dots in the top right corner → Show full logs**.
4. **Steps to reproduce** — what you did, what you expected, and what happened instead.
5. If the issue is about an **unmapped alarm state**, include the `protomResponse` code shown in the Verisure OWA integration log messages (after enabling debug logging and reproducing the issue).

### HAR File of GraphQL Requests

It would be very helpful to include a HAR (HTTP Archive) file of the GraphQL requests sent by the Verisure website while you perform the task that is not working for you in Home Assistant, for instance setting the alarm, unlocking a lock, or taking a photograph with your camera.

To record the HAR file:

1. Log in to the [Verisure customer web site](https://customers.securitasdirect.es/owa-static/login) in your browser.
2. Open **Developer Tools** (press **F12**, or **Ctrl+Shift+I** / **Cmd+Opt+I**, or use the browser menu → **More tools** → **Developer tools**).
3. Navigate to the **Network** tab, tick the **Preserve log** checkbox, and filter on **graphql**.

   ![Network tab](./docs/images/developer_console.png)

4. Carry out the actions you want to record.
5. Click the **Download** icon to download the HAR file.

   ![Download HAR file](./docs/images/download_har.png)

> **WARNING**: The HAR file can contain sensitive or personal information. Either edit the file (it is just a JSON file) to remove that information, or ask for one of the developers' email addresses to send it directly to us.

You can also use this technique to [capture GraphQL payloads](./docs/new_operations.md) if you'd like to help implement support for new operations.

