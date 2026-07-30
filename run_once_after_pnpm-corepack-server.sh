#!/usr/bin/env bash

# SERVER-only (gated off personal machines in .chezmoiignore). Provisions pnpm for
# the deploy pipeline. The Daybreaker deploy runs `pnpm install --frozen-lockfile`
# in each release (see the app's deploy/activate-release.sh), so pnpm has to be on
# the same non-interactive PATH the CI `ssh host 'cmd'` deploy and launchd see.
#
# We use Corepack (bundled with the node@22 formula from Brewfile.server) rather than
# a separately-versioned `brew "pnpm"`, so the mini honors the app's package.json
# `packageManager` pin — the SAME mechanism CI uses (pnpm/action-setup derives its
# version from package.json). The exact pnpm version is downloaded on first use from
# that pin; dot_zshenv sets COREPACK_ENABLE_DOWNLOAD_PROMPT=0 so that first fetch
# doesn't hang on an interactive confirm during an unattended deploy.
#
# Shims are installed into /opt/homebrew/bin (stable, already first on the
# non-interactive PATH via dot_zshenv) instead of the keg-only node@22 bin dir, so a
# `brew upgrade node@22` can't silently wipe them.
#
# This is a server *prerequisite*, not per-app setup. Non-interactive: no sudo
# (/opt/homebrew is user-owned on Apple Silicon).
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

# dot_zshenv adds these to PATH for future shells, but the shell running THIS script
# (first `chezmoi apply`) hasn't re-sourced it yet — so put them on PATH here too.
[[ -d /opt/homebrew/bin ]] && export PATH="/opt/homebrew/bin:$PATH"
[[ -d /opt/homebrew/opt/node@22/bin ]] && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"

if ! command -v corepack >/dev/null 2>&1; then
  echo "⚠ corepack not found — expected it bundled with the 'node' formula from Brewfile.server (did brew bundle fail?). Skipping pnpm setup."
  exit 0
fi

echo "→ Enabling pnpm via Corepack (shim into /opt/homebrew/bin)..."
# --install-directory keeps the shim out of the keg dir so node@22 upgrades don't drop it.
corepack enable --install-directory /opt/homebrew/bin pnpm

# ── Verify ──────────────────────────────────────────────────
echo "→ Verifying..."
hash -r 2>/dev/null || true
if command -v pnpm >/dev/null 2>&1; then
  echo "✓ pnpm shim installed at $(command -v pnpm) (version resolves from each app's packageManager pin on first use)."
else
  echo "✗ pnpm shim not on PATH after corepack enable." >&2
  exit 1
fi
