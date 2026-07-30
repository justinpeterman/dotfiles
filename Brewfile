# ── Shared CLI tools ───────────────────
brew "git"
brew "chezmoi"
brew "starship"
brew "zoxide"
brew "ripgrep"
brew "eza"
brew "bat"
# fnm (Node version manager) is intentionally NOT shared — it lives in
# Brewfile.personal. The server pins a single brew node@22 for its deploy runtime;
# fnm there would be unused and, if a node were ever installed under it, would make
# interactive shells diverge from what deploys (node@22) use. (pyenv/jenv stay shared
# because nothing on the server's deploy path depends on Python/Java.)
brew "pyenv"
brew "direnv"
brew "zsh-autosuggestions"
brew "zsh-syntax-highlighting"
brew "gh"
brew "openjdk@21"
brew "jenv"
brew "gradle"

# ── Shared Fonts ────────────────────────────────────────────────────
cask "font-jetbrains-mono-nerd-font"

# ── Shared Apps ─────────────────────────────────────────────────────
cask "claude-code"
cask "google-chrome"
cask "iterm2"
cask "visual-studio-code"
# Tailscale is intentionally NOT shared: servers use the open-source `tailscale`
# formula (tailscaled system daemon, runs before login) — see Brewfile.server —
# while personal machines use the `tailscale-app` GUI cask (Brewfile.personal).