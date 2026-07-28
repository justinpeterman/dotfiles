#!/usr/bin/env bash

# Installs the `tailscale` CLI wrapper that Tailscale.app otherwise only offers via
# its menu bar item ("Install Command Line Tool..."), which triggers a GUI
# admin-password prompt. That item just drops a shell wrapper in /usr/local/bin/tailscale
# (already on PATH via the macOS default /etc/paths) that execs the app's binary — this
# replicates it non-interactively. Runs once, after brew bundle installs tailscale-app.
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

APP_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
CLI="/usr/local/bin/tailscale"

if [[ ! -x "$APP_BIN" ]]; then
  echo "⚠ Tailscale.app not found — skipping CLI install"
  exit 0
fi

if [[ -x "$CLI" ]] && grep -q "$APP_BIN" "$CLI" 2>/dev/null; then
  echo "✓ tailscale CLI already installed"
  exit 0
fi

echo "→ Installing tailscale CLI wrapper..."
sudo mkdir -p /usr/local/bin
sudo tee "$CLI" > /dev/null <<EOF
#!/bin/sh
exec "$APP_BIN" "\$@"
EOF
sudo chmod +x "$CLI"
echo "✓ tailscale CLI installed at $CLI"
