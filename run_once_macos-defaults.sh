#!/usr/bin/env bash
# Applied once. Re-run manually with: chezmoi state delete-bucket --bucket=scriptState
set -euo pipefail

echo "→ Applying macOS defaults..."

# ── Keyboard ─────────────────────────────────────────────────
defaults write NSGlobalDomain KeyRepeat -int 2
defaults write NSGlobalDomain InitialKeyRepeat -int 15
defaults write NSGlobalDomain ApplePressAndHoldEnabled -bool false

# ── Finder ───────────────────────────────────────────────────
defaults write com.apple.finder AppleShowAllFiles -bool true
defaults write NSGlobalDomain AppleShowAllExtensions -bool true
defaults write com.apple.finder FXPreferredViewStyle -string "Nlsv"   # list view
defaults write com.apple.finder ShowPathbar -bool true
defaults write com.apple.finder ShowStatusBar -bool true
defaults write com.apple.desktopservices DSDontWriteNetworkStores -bool true

# ── Dock ─────────────────────────────────────────────────────
defaults write com.apple.dock autohide -bool true
defaults write com.apple.dock autohide-delay -float 0
defaults write com.apple.dock autohide-time-modifier -float 0.3
defaults write com.apple.dock minimize-to-application -bool true
defaults write com.apple.dock show-recents -bool false
defaults write com.apple.dock tilesize -int 48

# ── Screenshots ──────────────────────────────────────────────
mkdir -p "$HOME/Desktop/Screenshots"
defaults write com.apple.screencapture location "$HOME/Desktop/Screenshots"
defaults write com.apple.screencapture type "png"
defaults write com.apple.screencapture disable-shadow -bool true

# ── Trackpad ─────────────────────────────────────────────────
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad Clicking -bool true
defaults write com.apple.AppleMultitouchTrackpad Clicking -bool true

# ── Restart affected apps ────────────────────────────────────
for app in Dock Finder SystemUIServer; do
  killall "$app" &>/dev/null || true
done

echo "✓ macOS defaults applied"
