#!/usr/bin/env bash
# Point this clone's git hooks at the version-controlled .githooks/ dir.
#
# Uses a RELATIVE path on purpose: git resolves core.hooksPath relative to each
# working tree's root, so the same setting works in the main checkout, in any
# linked worktree, and across machines (devcontainer + host) — unlike an
# absolute /workspaces/... path, which only resolves in one environment.
#
# Run once per clone:  bash bin/install-hooks.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true
echo "✓ core.hooksPath -> .githooks ($(git config core.hooksPath))"
