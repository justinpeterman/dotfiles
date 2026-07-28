# dotfiles

Reproducible Mac dev environment managed with [chezmoi](https://chezmoi.io) and Homebrew.

## Bootstrap

On a new machine, run:

```bash
curl -fsSL https://raw.githubusercontent.com/justinpeterman/dotfiles/main/bootstrap.sh | bash
```

This installs Xcode CLI tools → Homebrew → chezmoi, then applies all dotfiles.

## Repo structure

```
dotfiles/
├── bootstrap.sh                              # Run once on a new machine
├── Brewfile                                  # Shared essentials (personal + server)
├── Brewfile.personal                         # Personal-only packages/apps
├── Brewfile.server                           # Server-only packages
├── dot_claude/
│   └── settings.json.tmpl                    # → ~/.claude/settings.json (Claude Code config)
├── dot_gitconfig.tmpl                        # → ~/.gitconfig (templated with name/email)
├── dot_gitignore_global                      # → ~/.gitignore_global
├── dot_zprofile                              # → ~/.zprofile (PATH setup for login shells)
├── dot_zshrc                                 # → ~/.zshrc
├── private_dot_ssh/
│   └── config                                # → ~/.ssh/config (GitHub SSH)
├── run_onchange_brew-bundle.sh.tmpl          # Reruns brew bundle when Brewfile* changes
├── run_once_macos-defaults.sh                # Applied once, shared across machines
├── run_once_after_macos-defaults-server.sh   # Applied once, server-only (after the shared script)
├── run_once_after_tailscale-cli.sh           # Installs the `tailscale` CLI wrapper after brew bundle
└── .chezmoiignore
```

## Multi-machine setup

`chezmoi init` prompts for a `machine_type` (`personal` or `server`), stored in
`~/.config/chezmoi/chezmoi.toml`. This single repo drives both machines:

- `.chezmoiignore` conditionally excludes `Brewfile.personal` on servers and
  `Brewfile.server` / `run_once_after_macos-defaults-server.sh` on personal machines,
  so the "wrong" machine-specific files are never applied.
- `run_onchange_brew-bundle.sh.tmpl` always runs the shared `Brewfile`, plus
  whichever of `Brewfile.personal` / `Brewfile.server` applies.
- Everything else (macOS defaults, shell config, SSH config, Claude settings) is shared
  and untemplated — it applies identically everywhere.

To change an existing machine's type, edit `machine_type` directly in
`~/.config/chezmoi/chezmoi.toml`, or re-run `chezmoi init` to be re-prompted.

## Post-bootstrap checklist

After running bootstrap on a new machine:

- [ ] **Add SSH key to GitHub** — `cat ~/.ssh/github_ed25519.pub` then add at [github.com/settings/keys](https://github.com/settings/keys)
- [ ] **Verify SSH auth** — `ssh -T git@github.com`
- [ ] **Set Node version** — `fnm install --lts && fnm use lts-latest`
- [ ] **Set Python version** — `pyenv install 3.x.x && pyenv global 3.x.x`
- [ ] **Configure iTerm2** — set font to JetBrains Mono Nerd Font, configure profile as needed
- [ ] **Sign in to WebStorm** — restore settings via JetBrains account sync

## Daily workflow

**Apply all changes:**
```bash
chezmoi apply
```

**Add a new CLI tool or app:**
1. Add it to `Brewfile`
2. Run `chezmoi apply` — detects the change and runs `brew bundle`

**Edit a dotfile:**
```bash
chezmoi edit ~/.zshrc   # opens in $EDITOR
chezmoi apply           # applies the change
```

**Re-run macOS defaults** (e.g. on a new machine after the fact):
```bash
chezmoi state delete-bucket --bucket=scriptState
chezmoi apply
```

## Stack

| Tool | Purpose |
|---|---|
| chezmoi | Dotfile manager |
| Homebrew + Brewfile | Package manager, source of truth for installs |
| starship | Shell prompt |
| zoxide | Smart `cd` (`z`) |
| fnm | Node version manager |
| pyenv | Python version manager |
| direnv | Per-directory env vars |
| ripgrep | Fast search |
| eza | Modern `ls` |
