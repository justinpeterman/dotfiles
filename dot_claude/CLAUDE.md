# Development environment

## Node & package managers — mise
- Manager: `mise` (Homebrew, shared Brewfile). Replaces the old fnm + Corepack setup.
- One tool-version manager across personal development, CI, and servers. No system-wide Node install (no Homebrew/nvm node).
- Exception: `~/.config/mise/config.toml` pins a mise-global `node` — global `npm:` backend tools (e.g. `claude-auto-retry`) ship shims that `exec node`, so they break with `exec: node: not found` when nothing is pinned. Per-repo `mise.toml` pins still take precedence; the global pin is only the fallback for tools installed outside any project.
- Each repo pins its exact runtimes (Node, pnpm, etc.) in `mise.toml`; run `mise install` inside a project to provision them. `mise activate` is hooked in `.zshrc`, so runtimes resolve automatically in an interactive shell (or via `mise exec` non-interactively).
- Preferred package manager remains `pnpm` over `npm`/`yarn` for new project work — pin it per-repo in `mise.toml`. Use `npm` only when (a) the project already uses it and switching is out of scope, or (b) publishing a library where downstream installs assume npm.

## Java — jenv
- Manager: `jenv`
- Default: `21` → `/Users/jpeterman/.jenv/versions/21/bin/java`
- Also installed: `21.0`, `21.0.11`, `openjdk64-21.0.11`, `system`
- Use `jenv local <version>` per project; `JAVA_HOME` is managed by jenv (enable the `export` plugin if a tool needs it).
- Build tool: `gradle` (Homebrew, shared Brewfile).

## Python — pyenv
- Manager: `pyenv`
- Installed: `system`, `3.14.4`
- Global default: `system` (system `python3` is 3.14.4 at `/opt/homebrew/bin/python3`)
- Bare `python` (no 3) is not on PATH — use `python3`.
- Switch the pyenv-managed version per project with `pyenv local 3.14.4`, or set it globally with `pyenv global 3.14.4`.

# Shell & other tooling
- Env: `direnv` auto-loads `.envrc` per directory (hooked in `.zshrc`, composes with mise).
- GitHub: `gh` CLI installed (shared Brewfile).
- Interactive shell aliases `cat`→`bat`, `ls`/`ll`/`la`→`eza`; use `rg` (ripgrep) for search and `z` (zoxide) for smart `cd`. A bare `cat`/`ls` in an interactive shell is not GNU `cat`/`ls`.

# Machine profiles (chezmoi `machine_type`)
Both machine types run macOS. The shared `Brewfile` always applies; then `Brewfile.personal` or `Brewfile.server` layers on based on `machine_type` in `~/.config/chezmoi/chezmoi.toml`.

- **Shared** (both): mise, pyenv, jenv/openjdk@21/gradle, gh, direnv, ripgrep/eza/bat/zoxide, starship, VS Code, Codex, Claude Code.
- **Personal only**: WebStorm, Xcode + CocoaPods (iOS/mobile dev), 1Password, Tailscale GUI app, `mas`. Mobile/iOS work only exists here.
- **Server only**: a macOS box provisioned for always-on services — `cloudflared`, `webhook`, `logrotate`, and the open-source `tailscale`/`tailscaled` system daemon (starts before login / at boot). Still macOS with a display, just the server toolset.

`mise` is the single runtime manager across all three (personal, CI, servers).

# Editing these dotfiles (chezmoi)
Two clones of `git@github.com:justinpeterman/dotfiles.git` exist: **`~/workspace/dotfiles` is the canonical editing clone** (source of truth), and `~/.local/share/chezmoi` is the operational clone that `chezmoi apply` reads from.

**Always edit dotfiles in `~/workspace/dotfiles` first**, using chezmoi source names (`dot_*`, `*.tmpl`, `executable_*`, `run_onchange_*`). Then commit + push to `main`, and run `chezmoi update` (git pull + apply) to sync `~/.local/share/chezmoi`. **Never** edit `~/.local/share/chezmoi` directly, and don't use `chezmoi edit`/`chezmoi add` — they write to the operational clone and split its history from the canonical repo. If a change ever lands in the operational clone by mistake, relocate it to `~/workspace/dotfiles`, then `git checkout`/`rm` the stray edit in `~/.local/share/chezmoi` and re-pull.

## Keeping `~/.claude/settings.json` synced with its template

`~/.claude/settings.json` is applied from `dot_claude/settings.json.tmpl`, but the live file can also change outside chezmoi entirely. Left alone, the two quietly diverge, and the next `chezmoi apply` silently reverts the live file back to the stale template.

If I change something that persists to `~/.claude/settings.json`, or a system-reminder reports the file "was modified," check for drift: run `chezmoi diff -- "$HOME/.claude/settings.json"`, update `dot_claude/settings.json.tmpl` to match the live (correct) value, then commit + push + `chezmoi update` as above.

**Exception:** `enabledPlugins` entries owned by `run_onchange_after_claude-plugins.sh` are expected to exist live without being mirrored into the template — that script re-asserts them on every apply. Only sync genuine drift elsewhere in the file.

# Codex review gate
The Codex Companion plugin's stop-time review gate (`/codex:setup --enable-review-gate`) is a per-workspace toggle stored in plugin state, not a global setting. Until every workspace has it enabled natively, proactively hold yourself to the same standard everywhere: before ending a turn that made code changes, run `/codex:review` (or otherwise get a Codex review) and address anything it flags, the same way the hook would block on.
