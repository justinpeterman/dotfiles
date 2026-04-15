#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────
# bootstrap.sh
# Installs Xcode CLI tools → Homebrew → chezmoi, then applies
# your dotfiles repo. Everything else is driven by chezmoi.
# Usage: ./bootstrap.sh
# ────────────────────────────────────────────────────────────

DOTFILES_REPO="${1:-https://github.com/justinpeterman/dotfiles}"

# ── Xcode CLI Tools ──────────────────────────────────────────
if ! xcode-select -p &>/dev/null; then
  echo "→ Installing Xcode Command Line Tools..."
  xcode-select --install
  echo "  Waiting for installation to complete..."
  until xcode-select -p &>/dev/null; do sleep 5; done
  echo "  Done."
else
  echo "✓ Xcode CLI tools already installed"
fi

# ── Homebrew ─────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "→ Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Add brew to PATH for this session (handles both Apple Silicon + Intel)
if [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -f /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

echo "✓ Homebrew $(brew --version | head -1)"

# ── chezmoi ──────────────────────────────────────────────────
if ! command -v chezmoi &>/dev/null; then
  echo "→ Installing chezmoi..."
  brew install chezmoi
fi

echo "✓ chezmoi $(chezmoi --version | head -1)"

# ── Dotfiles ─────────────────────────────────────────────────
if [[ -n "$DOTFILES_REPO" ]]; then
  echo "→ Applying dotfiles from $DOTFILES_REPO..."
  echo ""
  echo "  chezmoi will prompt for a few personal details to configure git."
  echo "  These are stored locally only and never committed to the repo."
  echo ""
  chezmoi init --apply "$DOTFILES_REPO"
  echo "✓ Dotfiles applied."
fi
