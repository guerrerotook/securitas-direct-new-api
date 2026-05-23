# Future migration plan: `securitas` → `verisure_owa`

This document records the plan to eventually complete the domain rename from
`securitas` to `verisure_owa`, deferred indefinitely after v5.0.1 shipped
broken via HACS (see the post-mortem at the bottom).

It exists so a future maintainer (possibly future-us) doesn't have to
reconstruct the history when picking this back up. **Do not act on this
without re-validating the HACS limitations first** — HACS may have grown
multi-directory support in the interim.

---

## Why this is deferred, in one line

HACS only manages one `custom_components/<dir>/` per repository. There is no
way to ship both a shim and a new directory from one repo for upgrade users.

The full investigation is in this conversation's debugging thread; the
authoritative external reference is
[hacs/integration #385](https://github.com/hacs/integration/issues/385).

## What was already done (and stays done)

- v4.0.x: the integration always called itself "Verisure" in the UI;
  internals were still `securitas`.
- v5.0.0: a registry-rewriting migration was attempted. It also bundled real
  features (sub-panels, autolock, activity log, refresh tokens). The features
  shipped; the migration was effectively never reached by anyone because
  v5.0.0 was superseded quickly by v5.0.1.
- v5.0.1: introduced a two-directory layout (`custom_components/securitas/`
  shim + `custom_components/verisure_owa/`). Bricked every HACS install.
- v5.0.2 (the revert): rolled `verisure_owa/` back into `securitas/`,
  collapsed to one directory, dropped the new domain. The brand "Verisure
  OWA" is kept everywhere the user sees it. Detailed scope and grep targets
  are in `docs/V502_REVERT_PLAN.md`.

## Where the v5.0.1 verisure_owa code lives

The full `custom_components/verisure_owa/` tree (including
`migrate.py`, the `repairs.py` translation keys, the brand assets, the
`alarm_control_panel/` package split, the new card files) is preserved at
the git tag **`verisure_owa-snapshot`**, which points at the same commit as
**`v5.0.1`**. Either reference works.

To extract:

```sh
git archive verisure_owa-snapshot custom_components/verisure_owa/ \
  | tar -x -C /tmp/verisure_owa_payload/
```

That's the starting point for the new repo's `custom_components/verisure_owa/`.

## The plan, when picked up

### Step 1 — Stand up a second HACS repository

Create a new GitHub repo (e.g. `verisure-owa-ha`) with its own `hacs.json`,
and copy the `custom_components/verisure_owa/` tree from
`verisure_owa-snapshot` as its initial commit. Adjust:

- Update `manifest.json` `documentation` / `issue_tracker` URLs to point at
  the new repo (or keep pointing at this one — your call).
- Re-validate via hassfest / HACS action workflows.
- Submit to the default HACS store if appropriate.

The existing `securitas-direct-new-api` repo continues to ship the
`securitas/` integration. The two repos co-exist; HACS users add the new one
manually (or it lands in the default store after submission).

### Step 2 — Cut a `securitas` shim release in this repo

In this repo, ship a release where `custom_components/securitas/` is reduced
to the migration shim — essentially the same shim concept as v5.0.1's
`securitas/__init__.py`, but with one critical difference: it `import`s from
`custom_components.verisure_owa.migrate` only after asserting the
`verisure_owa` integration is installed, and surfaces a clear Repairs issue
otherwise (with a link to "install the Verisure OWA repo from HACS").

Shim manifest:

```json
{
  "domain": "securitas",
  "name": "Verisure OWA (legacy — please install Verisure OWA from HACS)",
  "dependencies": ["verisure_owa"],
  "config_flow": false,
  "version": "<release version>"
}
```

The `dependencies: ["verisure_owa"]` declaration prevents HA from setting up
`securitas` until `verisure_owa` is loadable — which is what we want; it
keeps users from silently half-migrating.

### Step 3 — User-facing instructions

The CHANGES.md entry / repo README must spell out:

1. Open HACS → Integrations → ⋮ → Custom Repositories.
2. Add the URL of the new `verisure-owa-ha` repo, category "Integration".
3. Install "Verisure OWA" from the now-populated repo.
4. Restart Home Assistant.
5. The legacy `securitas` integration tile detects the new install,
   migrates the config entry, and removes itself. A Repairs issue prompts
   the user to remove this `securitas` repo from HACS afterwards.

### Step 4 — Eventual sunset of this repo

After ~12 months (one HA major bump's worth) of the shim release being out,
this repo can either:

- Be archived (telling users to migrate to the other repo by hand if they
  haven't already), or
- Continue shipping a no-op shim indefinitely. Cheap. Probably preferable.

## Things to revisit when this is picked up

- **HACS multi-directory support.** Re-check
  [hacs/integration #385](https://github.com/hacs/integration/issues/385)
  and the HACS docs at the time. If HACS has grown a way to ship multiple
  integration directories from one repo, the second-repo gymnastics
  disappear and the whole thing collapses to "rename in place".
- **HA's `repairs` flow.** It evolves fast; the v5.0.1 `is_fixable` repair
  pattern may be replaced by something cleaner (e.g. a config-flow
  reconfigure step) by the time this is picked up.
- **`migrate.py` correctness against current entity-registry schema.** It
  was last validated against HA 2026.05; the storage-format assumptions in
  `_migrate_entity_registry()` need rechecking against whatever HA version
  is current at migration time.
- **Reverse-migration shim.** v5.0.2 ships `securitas` only and doesn't
  handle the (vanishingly small) population of users who somehow got
  v5.0.0/v5.0.1 working with their config entry on the `verisure_owa`
  domain. If that population grows by the time you pick this back up,
  ship a small "is your config entry on the wrong domain?" Repairs check.
- **v5.0.2 entity services are already verisure_owa-only.** The
  `verisure_owa.refresh_alarm`, `verisure_owa.capture_image`,
  `verisure_owa.refresh_activity_log`, and `verisure_owa.fetch_activity_image`
  services exist exclusively under the `verisure_owa.*` domain (no
  `securitas.*` twin). When the rename ships, those services need no
  alias — automations using them already use the target name. The
  dual-registered services that DO still need `securitas.*` aliases
  are `force_arm` and `force_arm_cancel` (both pre-date v5).

## Post-mortem: what we should learn from v5.0.0/v5.0.1

- **Test the deployment mechanism, not just the integration.** All v5.0.x
  CI tested the Python via pytest, which doesn't exercise HACS at all.
  HACS deployment of a multi-directory repo would have failed on the first
  manual install and saved the release.
- **Don't bundle a domain rename with a feature release.** v5.0.0 mixed
  the rename with autolock, activity log, refresh-token auth, sub-panels.
  When the rename had to be reverted, all those features either had to
  carry the rebrand baggage in their commits, or be re-merged separately.
- **Renaming a HA integration domain via HACS is, as of 2026-05, not a
  solved problem.** Future renames in HACS-distributed integrations should
  assume "manual user action required" until HACS multi-directory support
  exists.
