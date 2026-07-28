#!/usr/bin/env bash

# PERSONAL machines only (gated off servers in .chezmoiignore). Servers run the
# open-source tailscaled daemon via run_once_after_tailscale-daemon-server.sh;
# this is the GUI path for a machine someone actually logs into.
#
# Enables Tailscale SSH and subnet-route acceptance. Requires the standalone
# tailscale-app cask (installed by brew bundle from Brewfile.personal) — the sandboxed
# Mac App Store build cannot run the SSH server ("The Tailscale SSH server
# does not run in sandboxed Tailscale GUI builds."). Homebrew cask installs
# don't overwrite an app that's already at the target path, so if the MAS
# build was already installed, `brew bundle` silently left it in place
# instead of replacing it with the standalone build — this script detects
# that case and bails with instructions rather than failing opaquely.
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

APP_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
MAS_RECEIPT="/Applications/Tailscale.app/Contents/_MASReceipt/receipt"

if [[ ! -x "$APP_BIN" ]]; then
  echo "⚠ Tailscale.app not found — skipping tailscale up"
  exit 0
fi

if [[ -f "$MAS_RECEIPT" ]]; then
  cat <<'EOF'
⚠ /Applications/Tailscale.app is the Mac App Store build (sandboxed) — it
  cannot run the SSH server. Homebrew won't overwrite an app that's already
  there, so `brew bundle` silently left it in place instead of installing
  the standalone tailscale-app cask.

  Fix: quit Tailscale, remove it from /Applications (Launchpad → uninstall,
  or drag to Trash), then run:
    chezmoi state delete-bucket --bucket=scriptState && chezmoi apply
  to install the standalone cask and re-run this script.
EOF
  exit 0
fi

echo "→ Enabling Tailscale SSH..."
sudo "$APP_BIN" up --ssh --accept-routes
echo "✓ tailscale up --ssh --accept-routes complete"
