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

# dot_zshenv adds these to PATH for future shells, but the shell running THIS script
# (first `chezmoi apply`) hasn't re-sourced it yet — so put them on PATH here too.
# /opt/homebrew/bin has the pm2 shim; node@22 is keg-only and needs its own entry.
# This also ensures the PATH `pm2 startup` captures for the launchd hook covers both.
[[ -d /opt/homebrew/bin ]] && export PATH="/opt/homebrew/bin:$PATH"
[[ -d /opt/homebrew/opt/node@22/bin ]] && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"

if ! command -v node >/dev/null 2>&1; then
  echo "⚠ node not found — expected the 'node' formula from Brewfile.server (did brew bundle fail?). Skipping PM2 setup."
  exit 0
fi

echo "→ Installing PM2 globally..."
npm install -g pm2

# Install the boot hook. On macOS, PM2 creates a *user* LaunchAgent at
# ~/Library/LaunchAgents/pm2.<user>.plist — so it must be installed WITHOUT sudo, or
# it loads into root's domain instead of the user's (macOS even warns: "Expecting a
# LaunchDaemons path since the command was run as root"). We pass the platform
# (`launchd`) explicitly so PM2 performs the install directly instead of printing a
# sudo command to copy-paste. Resurrection then happens when the user session starts
# at boot — which relies on auto-login being enabled (see Phase 1 of the guide).
# Idempotent: unload any prior (possibly wrong-domain) registration first, ignoring
# errors, then (re)install and load in the user domain.
echo "→ Installing PM2 launchd startup hook (survives reboot; relies on auto-login)..."
USER_NAME="$(id -un)"
launchctl unload "$HOME/Library/LaunchAgents/pm2.$USER_NAME.plist" 2>/dev/null || true
pm2 startup launchd -u "$USER_NAME" --hp "$HOME"

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
