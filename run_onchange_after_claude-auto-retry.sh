#!/usr/bin/env bash
# Installs claude-auto-retry as a mise-managed global npm tool, so it lands on
# PATH via mise's shims on every machine — honoring "mise is the single runtime
# manager; no global Node install." It's npm-only (not in Homebrew), so it can't
# live in the Brewfile alongside tmux.
#
# mise's npm backend writes a shim that ends in `exec node <cli.js>`, so the tool
# only runs when a Node is on PATH. Outside a project that pins its own, that
# means mise needs a *global* Node pin — without one you get:
#   claude-auto-retry: line 8: exec: node: not found
# A mise-global Node is still not a system-wide Node install: it's a version-
# managed fallback for global CLIs, and per-repo mise.toml pins still win.
#
# We install the CLI automatically, but do NOT run `claude-auto-retry install`:
# that injects a claude() wrapper straight into ~/.zshrc between marker comments,
# and ~/.zshrc is chezmoi-managed (dot_zshrc), so the next `chezmoi apply` would
# overwrite the file from source and erase the wrapper. Instead we render the
# same wrapper template into an *unmanaged* file (~/.config/claude-auto-retry/
# wrapper.zsh) ourselves, and dot_zshrc sources it if present. That keeps the
# wrapper outside anything chezmoi clobbers, with no manual per-machine step —
# every `chezmoi apply` (which reruns this script) just re-renders it fresh.
# Runs `after` file apply so mise (brew-bundled) exists.
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

# A global Node backs the npm shim. Only pin one if nothing is pinned already,
# so a machine that deliberately tracks a different major keeps it.
mise_global_config="${MISE_GLOBAL_CONFIG_FILE:-$HOME/.config/mise/config.toml}"
if [ -z "$(mise config get -f "$mise_global_config" tools.node 2>/dev/null)" ]; then
  echo "→ Pinning a mise-global Node (backs npm-tool shims)..."
  mise use -y --global node@lts || echo "⚠ failed to pin global node (continuing)"
fi

echo "→ Ensuring claude-auto-retry (mise-global npm tool)..."
if mise use -y --global "npm:claude-auto-retry@latest"; then
  mise reshim >/dev/null 2>&1 || true
  echo "✓ claude-auto-retry installed (mise global)"
else
  echo "⚠ failed to install claude-auto-retry via mise (continuing)"
  exit 0
fi

echo "→ Wiring the claude() wrapper (rendered outside chezmoi's dot_zshrc)..."
# Render the package's own wrapper.sh template ourselves rather than running
# `claude-auto-retry install` — see the header comment for why. wrapper.sh has
# exactly one placeholder, __LAUNCHER_PATH__, substituted with a plain `sed`;
# no need to invoke the package's own installer code for that. `mise where`
# resolves the *actual* npm-tool install dir (not the `latest` symlink), so this
# tracks whatever version mise just installed above.
pkg_dir="$(mise where npm:claude-auto-retry)/node_modules/claude-auto-retry"
wrapper_out="$HOME/.config/claude-auto-retry/wrapper.zsh"
mkdir -p "$(dirname "$wrapper_out")"
sed "s|__LAUNCHER_PATH__|$pkg_dir/src/launcher.js|g" "$pkg_dir/src/wrapper.sh" > "$wrapper_out"
echo "✓ wrapper written to $wrapper_out (sourced by dot_zshrc)"
