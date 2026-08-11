#!/opt/homebrew/bin/python3
"""Claude Code status line.

Renders one of two lines depending on whether tmux is in front of it:

  inside tmux   Opus 5 · plan · high
  outside tmux  📁 dotfiles  ⎇ main  ·  Opus 5  ·  ctx █░░░░░ 8%

Inside tmux the bar below already owns the directory, branch, context and usage
meters, so this line narrows to session identity — the things tmux cannot know
per-pane. Outside tmux nothing else is drawing them, so the full line stands.

Data sources:
  - Claude Code statusLine JSON (stdin): model, cwd/repo, context %, rate_limits,
    effort level, fast mode
  - git (via subprocess): current branch

Side effects, both of which exist to feed readers outside this process:
  - ~/.claude/usage-cache.json gets the rate_limits object. Claude's 5h/weekly
    numbers arrive ONLY here on stdin and are never otherwise written to disk,
    so this cache is what lets the hourly usage-report and the tmux bar see them
    at all. usage-report.py depends on this file.
  - ~/.cache/ai-status/claude-<N>.json gets a per-pane snapshot (context %,
    model, billing mode) keyed by TMUX_PANE, which the tmux status script reads.
    When the published values change, we poke tmux with `refresh-client -S` so
    the bar updates immediately instead of waiting out its 60s tick.

Both writes are atomic (temp file + os.replace) because tmux reads them on its
own schedule and a partial read would garble the status bar.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---- thresholds & ANSI ------------------------------------------------------
WARN = 50   # green below this
CLOSE = 80  # red at/above this; also reveals the reset time

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
ORANGE = "\033[33m"
SEP = f"  {DIM}·{RESET}  "

CACHE = Path.home() / ".claude" / "usage-cache.json"
PANE_CACHE_DIR = Path.home() / ".cache" / "ai-status"


def pct_color(p):
    if p >= CLOSE:
        return RED
    if p >= WARN:
        return YELLOW
    return GREEN


def meter(p, width=6):
    """Colored █/░ bar for a 0-100 percentage."""
    p = max(0, min(100, p))
    filled = int(round(p / 100 * width))
    c = pct_color(p)
    return f"{c}{'█' * filled}{DIM}{'░' * (width - filled)}{RESET}"


def reset_str(epoch):
    """' resets 8:10pm', with the weekday when it isn't today.

    The weekly window resets days out, so a bare time would read as tonight.
    """
    if not epoch:
        return ""
    t = time.localtime(epoch)
    stamp = time.strftime("%-I:%M", t) + time.strftime("%p", t).lower()
    if time.strftime("%F", t) != time.strftime("%F", time.localtime()):
        stamp = time.strftime("%a ", t) + stamp
    return f" {DIM}resets {stamp}{RESET}"


def gauge(label, pct, resets_at=None, always_reset=False):
    """Render 'label ██░░░░ 42%', appending the reset time when close to the cap
    (or always, when always_reset is set)."""
    p = int(round(pct))
    seg = f"{label} {meter(p)} {pct_color(p)}{p}%{RESET}"
    if always_reset or p >= CLOSE:
        seg += reset_str(resets_at)
    return seg


def read_stdin_json():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def git_branch(cwd):
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True, timeout=1,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def write_json_atomic(path, obj):
    """Temp file + os.replace, so tmux never reads a half-written cache."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(obj, f)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    except Exception:
        pass


def billing_mode(d):
    """Whether this session bills against the subscription or an API key.

    The statusLine payload has no billing field, so this is a heuristic. It runs
    here rather than in the tmux script because only this process inherits the
    real Claude Code environment.
    """
    env = os.environ
    if env.get("CLAUDE_CODE_USE_BEDROCK", "").lower() in ("1", "true"):
        return "bedrock"
    if env.get("CLAUDE_CODE_USE_VERTEX", "").lower() in ("1", "true"):
        return "vertex"
    if env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY"):
        return "api"
    if d.get("rate_limits"):
        return "plan"   # rate limits are a subscription concept
    try:
        account = json.loads((Path.home() / ".claude.json").read_text()).get("oauthAccount") or {}
        if "subscription" in (account.get("billingType") or ""):
            return "plan"
    except Exception:
        pass
    return "api"


def publish_pane_snapshot(snapshot):
    """Cache this pane's state for tmux, and nudge tmux only when it changed."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return
    path = PANE_CACHE_DIR / f"claude-{pane.lstrip('%')}.json"

    def comparable(s):
        return {k: v for k, v in (s or {}).items() if k != "ts"}

    previous = None
    try:
        previous = json.loads(path.read_text())
    except Exception:
        pass

    write_json_atomic(path, snapshot)

    if comparable(previous) == comparable(snapshot):
        return
    try:
        subprocess.run(["tmux", "refresh-client", "-S"], timeout=1,
                       capture_output=True, check=False)
    except Exception:
        pass   # a tmux hiccup must never stall a render


def main():
    d = read_stdin_json()

    ws = d.get("workspace") or {}
    cwd = ws.get("current_dir") or d.get("cwd") or os.getcwd()
    repo = ws.get("repo") or {}
    name = repo.get("name") or os.path.basename(cwd.rstrip("/")) or cwd
    model = (d.get("model") or {}).get("display_name")
    cw = (d.get("context_window") or {}).get("used_percentage")
    rl = d.get("rate_limits") or {}
    billing = billing_mode(d)

    # Persist rate_limits so the tmux bar and the hourly usage-report can see
    # Claude's 5h/weekly numbers. Guarded: an early-session render arrives with
    # no rate_limits and must not clobber good cached values.
    if rl:
        write_json_atomic(CACHE, {"written_at": int(time.time()), "rate_limits": rl})

    publish_pane_snapshot({
        "ts": int(time.time()),
        "ctx": int(round(cw)) if cw is not None else None,
        "model": model,
        "billing": billing,
        "rate_limits": rl or None,
    })

    if os.environ.get("TMUX"):
        # tmux owns dir, branch, context and usage — show only what it can't.
        parts = []
        if model:
            parts.append(f"{CYAN}{model}{RESET}")
        color = GREEN if billing == "plan" else ORANGE
        parts.append(f"{color}{billing}{RESET}")
        effort = (d.get("effort") or {}).get("level")
        if effort:
            parts.append(f"{DIM}{effort}{RESET}")
        if d.get("fast_mode"):
            parts.append("⚡")
        sys.stdout.write(SEP.join(parts))
        return

    out = f"📁 {BOLD}{name}{RESET}"
    branch = git_branch(cwd)
    if branch:
        out += f"  {MAGENTA}⎇ {branch}{RESET}"
    if model:
        out += f"{SEP}{CYAN}{model}{RESET}"
    if cw is not None:
        out += SEP + gauge("ctx", cw)
    sys.stdout.write(out)


if __name__ == "__main__":
    main()
