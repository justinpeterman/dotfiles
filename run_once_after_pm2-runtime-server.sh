#!/usr/bin/env bash

# SERVER-only (gated off personal machines in .chezmoiignore). Installs the Node
# process-manager runtime the deploy pipeline needs: PM2 (a global npm package)
# plus its launchd "startup" hook, so PM2-managed apps come back after an
# unattended reboot. Node itself comes from the `node` formula in Brewfile.server;
# this script handles only the pieces brew can't (a global npm package + the boot
# hook).
#
# This is a server *prerequisite*, not per-app setup — it runs once and is shared by
# every app later scaffolded from the apps list. Per-app `pm2 save` (persisting the
# real running process list) happens on each app's first deploy — see Phase 4 Step 11.
#
# Interactive: `pm2 startup` installs a launchd item via `sudo`, so this prompts for
# a password. Don't background or pipe it unattended.
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

# node@22 is keg-only (not linked into /opt/homebrew/bin). dot_zshenv adds this to
# PATH for future shells, but the shell running THIS script (first `chezmoi apply`)
# hasn't re-sourced it yet — so put it on PATH here too. This also ensures the PATH
# `pm2 startup` captures for the launchd hook includes node/pm2.
if [[ -d /opt/homebrew/opt/node@22/bin ]]; then
  export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
fi

if ! command -v node >/dev/null 2>&1; then
  echo "⚠ node not found — expected the 'node' formula from Brewfile.server (did brew bundle fail?). Skipping PM2 setup."
  exit 0
fi

echo "→ Installing PM2 globally..."
npm install -g pm2

# `pm2 startup` detects the init system (launchd on macOS) and, run as a normal
# user, prints the exact `sudo env PATH=… pm2 startup launchd -u <user> --hp <home>`
# command that installs the boot hook rather than doing it directly. Grab that line
# and run it. Idempotent — re-running just rewrites the launchd plist.
echo "→ Installing PM2 launchd startup hook (survives reboot)..."
STARTUP_CMD="$(pm2 startup 2>&1 | grep -E 'pm2 startup launchd' | tail -1 || true)"
if [[ -z "$STARTUP_CMD" ]]; then
  echo "✗ Could not determine the PM2 startup command from 'pm2 startup' output." >&2
  echo "  Run 'pm2 startup' manually and follow its printed instructions." >&2
  exit 1
fi
eval "$STARTUP_CMD"

# Write an (initially empty) process dump so a reboot before the first deploy doesn't
# leave the resurrect hook with nothing to restore. Each app's first deploy re-saves
# this with the real process list (Phase 4 Step 11).
pm2 save --force >/dev/null 2>&1 || true

# ── Verify ──────────────────────────────────────────────────
echo "→ Verifying..."
node -v >/dev/null || { echo "✗ node is not runnable after install." >&2; exit 1; }
pm2  -v >/dev/null || { echo "✗ pm2 is not runnable after install." >&2; exit 1; }
if launchctl list 2>/dev/null | grep -qi 'pm2'; then
  echo "✓ Node $(node -v), PM2 v$(pm2 -v) installed; launchd resurrect hook registered."
else
  echo "✓ Node $(node -v), PM2 v$(pm2 -v) installed."
  echo "  ⚠ Could not confirm the PM2 launchd item via 'launchctl list'. If apps don't"
  echo "    come back after a reboot, re-run 'pm2 startup' and run the command it prints."
fi
