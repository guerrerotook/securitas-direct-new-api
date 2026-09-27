# Claude Code Instructions

## Git Workflow

- **NEVER commit directly to main** — always create a feature branch first.
- Work from a fork: push branches to your fork and open the PR against
    `guerrerotook/securitas-direct-new-api` `main` (`gh repo set-default` there).
- **Branch naming**: descriptive (e.g. `fix/reauth-on-dead-refresh-token`).
    Never include version numbers in branch names — HACS scans all branches and
    complains about non-compliant ones, even after deletion.
- Commit subjects are conventional commits with a scope (`fix(alarm): …`,
    `feat(activity): …`).
- Do NOT merge PRs automatically — wait for user approval.
- When merging a PR (after approval), delete the feature branch.

## Changelog

- Record all user-facing changes in `CHANGES.md` (most recent at the top) under
    the next version's `## vX.Y.Z` section, with `### Added` / `### Fixed`
    headings. Each entry is a bold one-line summary linking the issue or PR,
    followed by a user-facing explanation; credit external contributors.

## Code Quality

- Run `bash bin/install-hooks.sh` once per clone/worktree. The committed
    `.githooks/pre-push` mirrors CI: ruff format + lint, pyright, translation
    drift (`scripts/check_translations.py`), docs drift (`scripts/check_docs.py`
    — adding, removing or renaming a module or service without touching
    README/docs blocks the push), then the unit tests
    (`pytest tests/ -m "not integration"`) and, when the card changed,
    the card import stamps (`python3 scripts/stamp_card_imports.py --check`),
    `npm run lint` and `npm test`. Bypass in an emergency with
    `git push --no-verify`.
- After editing a card module, re-stamp the imports with
    `python3 scripts/stamp_card_imports.py` and restart HA to serve the new
    entry-point URLs.
- CI additionally runs pylint, the integration suite (`-m integration`) on the
    stable, dev and minimum HA channels, and a combined 90% coverage gate.
- Before creating a PR run `ruff check .`, `ruff format .` and
    `pyright custom_components/`.
- New user-facing strings must be translated into every locale in
    `custom_components/securitas/translations/`; `strings.json` stays English.
- The `manifest.json` keys must be sorted: `domain`, `name` first, then all
    remaining keys in alphabetical order.
- Raw HAR captures contain auth tokens: only sanitised fixtures are committed
    (`tests/fixtures/*.har` and `*-events.json` are gitignored).
- `docs/superpowers/`, `docs/plans/` and `docs/handoffs/` are gitignored —
    specs, plans and handoffs are local working files; never commit them.
    `docs/architecture.md` is the committed developer overview.

## Integration Layout

- Component lives in `custom_components/securitas/`; the Lovelace cards under
    `custom_components/securitas/www/` with vitest tests in `tests-js/`.
- Domain: `securitas` (branded Verisure OWA). Alias in
    `~/workspace/tools/worktree.py`: `securitas`.
- Main HA dev container: `ha-securitas-main` (start with `ha-wt securitas-main`).
- Feature worktrees: `/new-worktree securitas <branch>`.
