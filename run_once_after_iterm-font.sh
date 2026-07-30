#!/usr/bin/env bash
# Point iTerm2's default profile at the dotfiles-managed "Justin's Defaults"
# profile so
# the JetBrainsMono Nerd Font is actually used (that's what makes powerline /
# devicon glyphs render instead of tofu boxes).
#
# The profile itself ships as an iTerm2 Dynamic Profile at
#   ~/Library/Application Support/iTerm2/DynamicProfiles/dotfiles.json
# which iTerm auto-loads and hot-reloads. It inherits from the built-in
# "Default" profile and overrides only the font, so colors/keys stay intact.
# This script just makes it the default; the font install lives in Brewfile
# (cask "font-jetbrains-mono-nerd-font").
#
# Applies wherever iTerm is installed (gated on /Applications/iTerm.app in
# .chezmoiignore) — including the mini, which is machine_type=server but is used
# interactively with a display. Not gated on machine_type.
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState
set -euo pipefail

GUID="4805797C-B5C0-468E-ABBE-68E20990AEF5"

# Only meaningful on macOS with iTerm2 installed.
if [[ "$(uname -s)" != "Darwin" ]]; then exit 0; fi
if [[ ! -d "/Applications/iTerm.app" ]]; then
  echo "→ iTerm2 not installed; skipping default-profile wiring."
  exit 0
fi

echo "→ Setting iTerm2 default profile to 'Justin's Defaults' (Nerd Font)..."
defaults write com.googlecode.iterm2 "Default Bookmark Guid" -string "$GUID"

if pgrep -xq iTerm2; then
  cat <<'MSG'
⚠  iTerm2 is running. It keeps preferences in memory and rewrites them on quit,
   which reverts the change above. To apply without losing it:
     • Settings → Profiles → select "Justin's Defaults" → Other Actions ▾ → Set as Default
   or fully quit iTerm2 (Cmd-Q, not just the window) and relaunch.
MSG
fi

echo "✓ iTerm2 font wiring done"
