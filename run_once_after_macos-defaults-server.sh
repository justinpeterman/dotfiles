#!/usr/bin/env bash
# Applied once, after run_once_macos-defaults.sh. Re-run manually with:
# chezmoi state delete-bucket --bucket=scriptState
set -euo pipefail

echo "→ Applying server-only macOS defaults..."

# Add server-specific defaults here, e.g.:
# defaults write com.apple.loginwindow LoginwindowText -string "Managed server — contact justin"

echo "✓ Server-only macOS defaults applied"
