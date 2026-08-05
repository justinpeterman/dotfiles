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
├── run_once_macos-defaults.sh                  # Applied once, shared across machines
├── run_once_after_macos-defaults-server.sh     # Applied once, server-only (after the shared script)
├── run_once_after_tailscale-daemon-server.sh   # Server-only: installs tailscaled system daemon + `up --ssh`
├── run_once_after_tailscale-cli.sh             # Personal-only: installs the `tailscale` CLI wrapper for the GUI app
└── .chezmoiignore
```

## Multi-machine setup

`chezmoi init` prompts for a `machine_type` (`personal` or `server`), stored in
`~/.config/chezmoi/chezmoi.toml`. This single repo drives both machines:

- `.chezmoiignore` gates machine-specific `run_once` scripts by type: servers skip the
  personal Tailscale GUI script (`tailscale-cli.sh`), and personal
  machines skip the server-only scripts (`macos-defaults-server.sh`,
  `tailscale-daemon-server.sh`), so the "wrong" machine's setup never runs.
- `run_onchange_brew-bundle.sh.tmpl` always runs the shared `Brewfile`, plus
  whichever of `Brewfile.personal` / `Brewfile.server` applies. Tailscale is the one app
  split by type: the `tailscale-app` GUI cask is personal-only, the `tailscale` (tailscaled)
  formula is server-only.
- Server-only operational tools such as `logrotate` also live in
  `Brewfile.server`; individual apps own their rotation policies and schedules.
- Everything else (macOS defaults, shell config, SSH config, Claude settings) is shared
  and untemplated — it applies identically everywhere.

To change an existing machine's type, edit `machine_type` directly in
`~/.config/chezmoi/chezmoi.toml`, or re-run `chezmoi init` to be re-prompted.

## Post-bootstrap checklist

After running bootstrap on a new machine:

- [ ] **Add SSH key to GitHub** — `cat ~/.ssh/github_ed25519.pub` then add at [github.com/settings/keys](https://github.com/settings/keys)
- [ ] **Verify SSH auth** — `ssh -T git@github.com`
- [ ] **Install project runtimes** — run `mise install` inside each project
- [ ] **Set Python version** — `pyenv install 3.x.x && pyenv global 3.x.x`
- [ ] **Configure iTerm2** — set font to JetBrains Mono Nerd Font, configure profile as needed
- [ ] **Sign in to WebStorm** — restore settings via JetBrains account sync
- [ ] **Verify Tailscale**
    - **Server:** `run_once_after_tailscale-daemon-server.sh` installs the open-source
      `tailscaled` as a launchd **system daemon** and runs `sudo tailscale up --ssh --accept-routes`.
      Confirm with `tailscale status` and `sudo tailscale debug prefs | grep RunSSH` (expect `true`).
      The daemon is the only macOS variant that starts **before login / at boot** — a headless
      server needs that so an unattended reboot doesn't lock you out.
      See [macOS variants](https://tailscale.com/docs/concepts/macos-variants).
    - **Personal:** the `tailscale-app` GUI cask plus `run_once_after_tailscale-cli.sh` (CLI
      wrapper) make the machine a Tailscale **client** — enough to `ssh`/screen-share *into* the
      server. Personal machines do **not** run their own SSH server; just confirm `tailscale status`
      shows the machine on the tailnet.
    - **Never install Tailscale from the App Store** — it is fully sandboxed (no CLI, subnet
      routing, or exit nodes). Servers use the `tailscale` formula (`Brewfile.server`); personal
      machines use the `tailscale-app` cask (`Brewfile.personal`).

## Daily workflow

This repo has **two clones**: `~/workspace/dotfiles` is the canonical editing clone
(always edit here), and `~/.local/share/chezmoi` is the operational clone chezmoi
applies from. Edits flow **workspace → push → `chezmoi update`**, never the other way.

**Edit a dotfile / add a CLI tool or app:**
1. Edit the source file in `~/workspace/dotfiles` using chezmoi source names
   (`dot_*`, `*.tmpl`, `executable_*`, `run_onchange_*`) — e.g. add a tool to `Brewfile`.
2. `git commit` + `git push` to `main`.
3. `chezmoi update` — pulls into `~/.local/share/chezmoi` and applies (reruns
   `brew bundle` if a Brewfile changed).

> Do **not** use `chezmoi edit`/`chezmoi add` or edit `~/.local/share/chezmoi`
> directly — that writes to the operational clone and diverges it from this repo.
> On any other machine, `chezmoi update` alone pulls and applies the latest.

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
| mise | Project runtime and CLI version manager |
| pyenv | Python version manager |
| direnv | Per-directory env vars |
| ripgrep | Fast search |
| eza | Modern `ls` |
