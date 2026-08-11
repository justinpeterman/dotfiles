#!/usr/bin/env bash
# Provision tmux plugins via TPM (Tmux Plugin Manager).
#
# TPM defaults to ~/.tmux/plugins, but the config lives at the XDG path, so
# tmux.conf sets TMUX_PLUGIN_MANAGER_PATH to ~/.config/tmux/plugins and this
# script clones TPM into the same place. That directory is listed in
# .chezmoiignore so chezmoi doesn't fight TPM over the plugin clones.
#
# tmux itself comes from the shared Brewfile. Plugins currently installed:
#   tmux-plugins/tpm, tmux-plugins/tmux-sensible
#
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState
set -euo pipefail

PLUGIN_DIR="${HOME}/.config/tmux/plugins"
TPM_DIR="${PLUGIN_DIR}/tpm"

if ! command -v tmux >/dev/null 2>&1; then
  echo "→ tmux not installed; skipping TPM setup."
  exit 0
fi

if [[ ! -d "${TPM_DIR}/.git" ]]; then
  echo "→ Cloning TPM into ${TPM_DIR}..."
  mkdir -p "${PLUGIN_DIR}"
  git clone --depth 1 https://github.com/tmux-plugins/tpm "${TPM_DIR}"
else
  echo "→ Updating TPM..."
  git -C "${TPM_DIR}" pull --ff-only --quiet || echo "  (pull skipped)"
fi

# install_plugins is safe to re-run; it no-ops for already-present plugins.
#
# It resolves the install path with `tmux start-server; show-environment -g
# TMUX_PLUGIN_MANAGER_PATH`, and `start-server` brings up a bare server that has
# sourced no config — so the variable tmux.conf sets is not there yet and the
# install aborts. Seed it on the server first. Harmless if a server is already
# running: sourcing tmux.conf sets the same value.
echo "→ Installing tmux plugins..."
tmux start-server
tmux set-environment -g TMUX_PLUGIN_MANAGER_PATH "${PLUGIN_DIR}/"
"${TPM_DIR}/bin/install_plugins" || echo "  (install reported an issue; run 'prefix + I' inside tmux)"

echo "✓ tmux plugins ready"
