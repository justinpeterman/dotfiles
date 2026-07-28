#!/usr/bin/env bash

# Server Tailscale setup: run the open-source `tailscaled` as a launchd system
# daemon (provided by the `tailscale` formula in Brewfile.server). This is the
# only macOS Tailscale variant that starts *before* login and at boot — the
# standalone and App Store GUI builds only run inside a logged-in GUI session,
# so an unattended reboot would leave a headless server unreachable over SSH.
# See: https://tailscale.com/docs/concepts/macos-variants
#
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

if ! command -v tailscaled >/dev/null 2>&1; then
  echo "⚠ tailscaled not found — expected the 'tailscale' formula from Brewfile.server. Skipping."
  exit 0
fi

# If a previous GUI-based setup left the CLI shim at /usr/local/bin/tailscale
# (it execs the now-removed Tailscale.app binary), drop it so the formula's real
# client — earlier on PATH via /opt/homebrew/bin — is the one that gets used.
WRAPPER="/usr/local/bin/tailscale"
if [[ -f "$WRAPPER" ]] && grep -q "Tailscale.app" "$WRAPPER" 2>/dev/null; then
  echo "→ Removing stale GUI CLI wrapper at $WRAPPER..."
  sudo rm -f "$WRAPPER"
fi

# install-system-daemon is idempotent — it (re)writes the launchd plist at
# /Library/LaunchDaemons/com.tailscale.tailscaled.plist and starts tailscaled.
# Safe to run on every bootstrap.
echo "→ Installing tailscaled system daemon..."
sudo tailscaled install-system-daemon

# A leftover standalone/App Store GUI backend can keep its network *system
# extension* (io.tailscale.ipn.macsys) registered even after the app is deleted.
# While it is holding the Tailscale LocalAPI socket, `tailscale up` talks to that
# sandboxed GUI backend and fails with "does not run in sandboxed Tailscale GUI
# builds" (often with a client/daemon version mismatch). A reboot lets the freshly
# installed tailscaled claim the socket even when the orphaned extension is still
# listed (SIP blocks removing it directly), so we do NOT pre-block on mere
# registration — that's a false positive once the daemon owns the socket. Instead
# we run `up` and only surface recovery steps if it actually fails.
# --advertise-tags=tag:server makes this a *tagged* node: tagged devices are
# owned by the tailnet (not a user) and their node keys DO NOT EXPIRE, so an
# always-on headless server never gets forced offline by the default 180-day key
# rotation (which would require an interactive re-auth we can't do unattended).
# Requires `tag:server` declared in the tailnet ACL `tagOwners`. Keeping the flag
# here (not just a one-time console toggle) means a re-run can't silently revert
# the node to a user-owned, expiring key.
echo "→ Enabling Tailscale SSH..."
if ! sudo tailscale up --ssh --accept-routes --advertise-tags=tag:server; then
  if systemextensionsctl list 2>/dev/null | grep -q 'io.tailscale.ipn.macsys'; then
    cat <<'EOF'
⚠ `tailscale up` failed and a Tailscale GUI system extension
  (io.tailscale.ipn.macsys) is still registered — it is likely holding the
  Tailscale socket, so the command hit the sandboxed GUI backend instead of
  tailscaled. The daemon is installed and will take over once the extension
  releases the socket.

  Fix: reboot so tailscaled can claim the socket (the GUI app is already
  removed), then re-run:  chezmoi apply
EOF
  fi
  exit 1
fi
echo "✓ tailscaled running as a system daemon; SSH enabled."
