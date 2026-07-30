#!/usr/bin/env bash

# Provisions pnpm via Corepack on EVERY machine (personal + server) — one setup for
# one tool, rather than wiring pnpm up two different ways. Corepack ships with both
# the server's brew node@22 and a personal machine's fnm-managed node, and honors each
# project's package.json `packageManager` pin, so the same command is correct
# everywhere and matches CI's pnpm/action-setup (which also reads that pin).
#
#   - Server: the Daybreaker deploy runs `pnpm install --frozen-lockfile` in each
#     release over a non-interactive SSH shell, so pnpm MUST be on that PATH. The
#     unattended-download knob (COREPACK_ENABLE_DOWNLOAD_PROMPT=0) is set server-only
#     in dot_zshenv so that first, app-pinned pnpm fetch doesn't hang on a confirm.
#   - Personal: convenience; the interactive download prompt is left on (you're there
#     to confirm), which is why that env var is NOT set on personal machines.
#
# Shims go into /opt/homebrew/bin (stable, on PATH on both machines) rather than a
# version-manager's bin dir, so a node upgrade can't silently drop them; the shim
# re-resolves whichever node is active at call time. Non-interactive: no sudo
# (/opt/homebrew is user-owned on Apple Silicon).
# Re-run manually with: chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

# Best-effort: put Homebrew + the keg-only server node@22 on PATH so corepack resolves
# during `chezmoi apply`. Both are no-ops if absent (e.g. node@22 on a personal box,
# where corepack comes from fnm's node instead). If corepack still isn't found we skip
# gracefully below rather than fail the whole apply.
[[ -d /opt/homebrew/bin ]] && export PATH="/opt/homebrew/bin:$PATH"
[[ -d /opt/homebrew/opt/node@22/bin ]] && export PATH="/opt/homebrew/opt/node@22/bin:$PATH"

if ! command -v corepack >/dev/null 2>&1; then
  echo "⚠ corepack not found on PATH — expected it bundled with Node (server: node@22 formula; personal: fnm's node). Skipping pnpm setup; re-run with a node on PATH."
  exit 0
fi

echo "→ Enabling pnpm via Corepack (shim into /opt/homebrew/bin)..."
corepack enable --install-directory /opt/homebrew/bin pnpm

# ── Verify ──────────────────────────────────────────────────
echo "→ Verifying..."
hash -r 2>/dev/null || true
if command -v pnpm >/dev/null 2>&1; then
  echo "✓ pnpm shim installed at $(command -v pnpm) (version resolves from each app's packageManager pin on first use)."
else
  echo "✗ pnpm shim not on PATH after corepack enable." >&2
  exit 1
fi
