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
# Non-interactive: no sudo. The boot hook is a user LaunchAgent we write directly to
# ~/Library/LaunchAgents (a user-owned dir), sidestepping PM2's `pm2 startup`, which
# refuses to run without root and then loads the agent into root's domain.
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

# Install the boot hook as a user LaunchAgent. We write the plist ourselves instead
# of using `pm2 startup` because PM2 hard-requires root (uid 0): run without sudo it
# only prints a command and exits 1; run WITH sudo it writes the plist but does its
# final `launchctl load` as root, so the agent lands in root's domain, not yours
# (macOS warns "Expecting a LaunchDaemons path since the command was run as root").
# A user LaunchAgent lives in a user-owned dir and needs no root, so writing it
# directly is both simpler and correct. The agent just runs `pm2 resurrect`, which
# restarts whatever `pm2 save` last persisted — stable PM2 behavior. PATH is baked in
# so keg-only node@22 and the pm2 shim resolve at boot. Resurrection fires when the
# user session starts, which relies on auto-login being enabled (Phase 1 of the guide).
echo "→ Installing PM2 launchd startup hook (user LaunchAgent; relies on auto-login)..."
USER_NAME="$(id -un)"
UID_NUM="$(id -u)"
PM2_BIN="$(command -v pm2)"
PLIST="$HOME/Library/LaunchAgents/pm2.$USER_NAME.plist"
mkdir -p "$HOME/Library/LaunchAgents"
# A prior `sudo pm2 startup` can leave a root-owned plist here. The user owns the
# directory (so can delete the file) but not the root-owned file itself (so can't
# overwrite it in place). Remove then rewrite as the user. -f: no error if absent.
rm -f "$PLIST"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>pm2.$USER_NAME</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/sh</string>
      <string>-c</string>
      <string>exec "$PM2_BIN" resurrect</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key><string>$PATH</string>
      <key>PM2_HOME</key><string>$HOME/.pm2</string>
    </dict>
    <key>StandardOutPath</key><string>$HOME/.pm2/pm2.launchd.out</string>
    <key>StandardErrorPath</key><string>$HOME/.pm2/pm2.launchd.err</string>
  </dict>
</plist>
PLIST_EOF

# Load it into the user's GUI domain now (present because the server auto-logs in), so
# it's active without waiting for a reboot. Boot out any prior copy first; fall back
# to legacy load if bootstrap isn't available. Best-effort — the plist on disk is what
# guarantees resurrection at the next boot regardless of whether this load lands.
launchctl bootout "gui/$UID_NUM/pm2.$USER_NAME" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null \
  || launchctl load -w "$PLIST" 2>/dev/null || true

# Write an (initially empty) process dump so a reboot before the first deploy doesn't
# leave the resurrect hook with nothing to restore. Each app's first deploy re-saves
# this with the real process list (Phase 4 Step 11).
pm2 save --force >/dev/null 2>&1 || true

# ── Verify ──────────────────────────────────────────────────
echo "→ Verifying..."
node -v >/dev/null || { echo "✗ node is not runnable after install." >&2; exit 1; }
pm2  -v >/dev/null || { echo "✗ pm2 is not runnable after install." >&2; exit 1; }
[[ -f "$PLIST" ]] || { echo "✗ LaunchAgent plist was not written to $PLIST." >&2; exit 1; }
if launchctl list 2>/dev/null | grep -qi 'pm2'; then
  echo "✓ Node $(node -v), PM2 v$(pm2 -v) installed; resurrect LaunchAgent loaded."
else
  echo "✓ Node $(node -v), PM2 v$(pm2 -v) installed; resurrect LaunchAgent written to"
  echo "  $PLIST."
  echo "  ℹ Not loaded in this session, but it loads automatically at the next"
  echo "    (auto-login) boot. The Phase 8 reboot test confirms resurrection end-to-end."
fi
