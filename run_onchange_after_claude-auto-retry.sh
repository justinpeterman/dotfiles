#!/usr/bin/env bash
# Installs claude-auto-retry as a mise-managed global npm tool, so it lands on
# PATH via mise's shims on every machine — honoring "mise is the single runtime
# manager; no global Node install." It's npm-only (not in Homebrew), so it can't
# live in the Brewfile alongside tmux.
#
# We install the CLI automatically, but do NOT run `claude-auto-retry install`:
# that injects a claude() wrapper into ~/.zshrc, which chezmoi manages, so
# chezmoi would clobber it on the next apply. Instead we print the one command
# for you to run manually. Runs `after` file apply so mise (brew-bundled) exists.
#
# run_onchange: edit this file to re-trigger on the next apply.
set -euo pipefail

# Non-interactive apply (esp. server SSH) may not have Homebrew/mise on PATH yet.
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

if ! command -v mise >/dev/null 2>&1; then
  echo "⚠ mise not found on PATH; skipping claude-auto-retry install"
  exit 0
fi

echo "→ Ensuring claude-auto-retry (mise-global npm tool)..."
if mise use -y --global "npm:claude-auto-retry@latest"; then
  mise reshim >/dev/null 2>&1 || true
  echo "✓ claude-auto-retry installed (mise global)"
else
  echo "⚠ failed to install claude-auto-retry via mise (continuing)"
  exit 0
fi

echo
echo "  ► Manual step (one-time per machine):"
echo "    claude-auto-retry's wrapper edits ~/.zshrc, which chezmoi manages, so"
echo "    it isn't auto-installed here. To finish wiring the claude() wrapper, run:"
echo
echo "        claude-auto-retry install && exec zsh"
echo
