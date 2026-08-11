#!/opt/homebrew/bin/python3
"""Two-line Claude Code status display with Claude and Codex usage.

The first line contains workspace and session identity; the second contains the
usage meters so narrow terminals do not force everything into one long row.
The display is identical inside and outside tmux. Claude's status-line payload
is authoritative for this session's model, context, and subscription limits. Codex
context and limits are read locally from its latest rollout through
``usage-report.py --json --no-ping``; the status line never refreshes either
provider or makes a network request.

Data sources:
  - Claude Code statusLine JSON (stdin): model, cwd/repo, context %, rate_limits,
    effort level, fast mode
  - ~/.claude/usage-report.py: cached/local Codex context and rate limits
  - git (via subprocess): current branch

Side effect:
  - ~/.claude/usage-cache.json gets the rate_limits object. Claude's 5h/weekly
    numbers arrive here on stdin, so this cache lets the hourly usage report see
    them. Writes are locked and atomic because multiple Claude sessions publish
    to the shared file.
"""
import fcntl
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
EL = "\033[K"

CACHE = Path.home() / ".claude" / "usage-cache.json"
# Separate from CACHE itself so the lock survives the os.replace that swaps the
# cache file out from under it.
CACHE_LOCK = Path.home() / ".claude" / ".usage-cache.lock"
LOCK_TIMEOUT = 0.25   # seconds to wait for the cache lock before skipping
USAGE_REPORT = Path.home() / ".claude" / "usage-report.py"


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


def expired(resets_at):
    return bool(resets_at) and resets_at <= time.time()


def rate_limit_gauges(rate_limits):
    """Render Claude's live 5h/week subscription windows."""
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "wk")):
        window = (rate_limits or {}).get(key) or {}
        pct = window.get("used_percentage")
        resets_at = window.get("resets_at")
        if numeric(pct) and not expired(resets_at):
            parts.append(gauge(label, pct, resets_at))
    return parts


def read_cached_claude_usage():
    try:
        return (json.loads(CACHE.read_text()) or {}).get("rate_limits") or {}
    except Exception:
        return {}


def read_codex_status():
    """Read Codex's latest local rollout through the shared reporter.

    The reporter is explicitly cache-only here. A short timeout keeps Claude's
    UI responsive if the filesystem is busy or the helper is unavailable.
    """
    try:
        result = subprocess.run(
            [str(USAGE_REPORT), "--json", "--no-ping", "--provider", "codex"],
            capture_output=True, text=True, timeout=1.5, check=False,
        )
        if result.returncode != 0:
            return {}
        return (json.loads(result.stdout).get("providers") or {}).get("codex") or {}
    except Exception:
        return {}


def codex_gauges(status):
    parts = []
    ctx = status.get("context_percent")
    if numeric(ctx):
        parts.append(gauge("ctx", ctx))
    for window in status.get("windows") or []:
        pct = window.get("used_percent")
        if numeric(pct) and not window.get("expired"):
            parts.append(gauge(window.get("label") or "usage", pct,
                               window.get("resets_at")))
    return parts


def numeric(v):
    """A real number, excluding bool — which is an int in Python and would
    otherwise sail through every comparison below as 0 or 1."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def publishable(window):
    """True when a window carries a reading fit to overwrite a shared cache.

    Demands a numeric percentage AND a numeric resets_at still in the future.
    Each half rejects a different kind of unusable payload:

      - no usable percentage (absent, null, or the window an empty dict) means
        there is nothing to publish, and writing it anyway would blank a meter
        that another session had already filled in correctly. Surviving exactly
        those renders is what this cache is for.
      - no usable resets_at means the reading cannot be aged at all, and a
        figure an idle session has been replaying for days is indistinguishable
        from a live one. There is no defensible basis for letting it win.
      - a resets_at in the PAST describes a window that has since rolled over,
        so the percentage is not merely old but wrong, and no later reading can
        be inferred from it.

    Applied to every window the readers consume, all-or-nothing: a session
    stale in one window is stale in both. Readers keep their own expired()
    check for the case where nothing writes at all and the cache simply ages.
    """
    if not isinstance(window, dict):
        return False
    if not numeric(window.get("used_percentage")):
        return False
    return numeric(window.get("resets_at")) and window["resets_at"] > time.time()


def regressive(window, cached):
    """True when `window` is a STALER reading of the same window as `cached`.

    Usage inside a rate-limit window only ever climbs, so a lower percentage
    against the same resets_at cannot be a later reading — it is an idle
    session replaying whatever its last turn saw. publishable() only catches
    such a session once its window has rolled over; until then its reading is
    still nominally live, and this is what catches it. Without both, a session
    left open earlier the same day drags the shared cache back down every time
    it re-renders, and the bar flickers between the two figures.

    Keyed on resets_at, with a two-minute tolerance because Claude's statusline
    payload and `/usage` round the same reset boundary differently. A genuine
    rollover is hours away, so it cannot be mistaken for a stale replay.
    """
    if not isinstance(window, dict) or not isinstance(cached, dict):
        return False
    reset = window.get("resets_at")
    cached_reset = cached.get("resets_at")
    if (not numeric(reset) or not numeric(cached_reset)
            or abs(reset - cached_reset) > 120):
        return False   # a different window entirely; nothing to compare
    now, before = window.get("used_percentage"), cached.get("used_percentage")
    return now is not None and before is not None and now < before


def publish_usage(rl):
    """Write rate_limits to the shared cache unless something fresher is there.

    read -> compare -> write has to be one critical section. Every session on
    the machine writes this file, so without the lock a stale session can read
    the cache an instant before a live session replaces it, find its own stale
    numbers still plausible against what it read, and then clobber values it
    never saw — reintroducing exactly the flicker the guards exist to stop.

    Acquisition retries against a deadline rather than giving up on the first
    refusal. A single LOCK_NB attempt looks cheaper but inverts the outcome it
    was meant to protect: whichever session reaches the lock FIRST then wins,
    so a stale one arriving a moment earlier silently suppresses the live write
    behind it — measured, with a stale 31% beating a live 80%. Waiting instead
    means the comparison is always made against the cache as it actually is.

    The deadline exists because Claude renders this synchronously and a wedged
    holder must not hang every session's status line. It is generous next to a
    critical section that is one small read and one rename, and expiring it
    simply skips the write — by then someone else has just written anyway.
    """
    try:
        with open(CACHE_LOCK, "a") as lock:
            deadline = time.monotonic() + LOCK_TIMEOUT
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        return   # someone is mid-write; their value is no older
                    time.sleep(0.005)
            try:
                cached = (json.loads(CACHE.read_text()) or {}).get("rate_limits") or {}
            except Exception:
                cached = {}
            if any(regressive(w, cached.get(k)) for k, w in rl.items()):
                return
            write_json_atomic(CACHE, {"written_at": int(time.time()), "rate_limits": rl})
    except Exception:
        pass   # the cache is an optimisation; never fail a render over it


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
    """Temp file + os.replace, so readers never see a partial cache."""
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


def render_top_line(name, branch, model, billing, effort, fast_mode):
    """Render the colored identity row as one continuous ANSI state stream.

    Each field owns the ordinary space after its text. Only then do we switch
    to the dim separator style. There are no resets or special whitespace at a
    field/separator boundary for Conductor's renderer to mismeasure.
    """
    out = f"📁 {BOLD}{name}"
    if branch:
        out += f"{RESET}  {MAGENTA}⎇ {branch}"

    def append(value, style):
        nonlocal out
        if value:
            out += f" {DIM}·  {style}{value}"

    # append(model, CYAN)
    # append(billing, GREEN if billing == "plan" else ORANGE)
    # append(effort, DIM)
    append("⚡" if fast_mode else None, RESET)
    return out + RESET + EL


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

    # Persist rate_limits so the hourly usage report can see Claude's 5h/weekly
    # numbers. Guarded, because this cache is shared by every
    # session on the machine and a naive last-writer-wins lets an idle one
    # publish whatever its last API turn saw — a session left open for days was
    # measured overwriting the live 5h figure with a week-old 100%, which is the
    # flicker these checks exist to stop.
    #
    # publishable() covers the unusable payloads (nothing to publish, or nothing
    # to age it by); publish_usage() adds the comparison against what is already
    # cached, which has to happen under the lock to mean anything. Both windows
    # the readers consume must pass: a session stale in one is stale in both, and
    # a partial write would blank a meter another session had filled correctly.
    # Renders before a session's first API response fail this and leave the cache
    # alone, so it holds the newest LIVE reading rather than the newest render.
    if isinstance(rl, dict) and all(publishable(rl.get(k)) for k in ("five_hour", "seven_day")):
        publish_usage(rl)

    branch = git_branch(cwd)
    effort = (d.get("effort") or {}).get("level")
    out = render_top_line(name, branch, model, billing, effort, d.get("fast_mode"))

    claude = []
    if numeric(cw):
        claude.append(gauge("ctx", cw))
    # The shared cache may be newer than this particular session's payload.
    # publish_usage() prevents an idle session from regressing it.
    claude.extend(rate_limit_gauges(read_cached_claude_usage() or rl))
    usage_groups = []
    if claude:
        usage_groups.append(f"{CYAN}claude{RESET} "
                            + f" {DIM}·{RESET} ".join(claude))

    codex = codex_gauges(read_codex_status())
    if codex:
        usage_groups.append(f"{CYAN}codex{RESET} "
                            + f" {DIM}·{RESET} ".join(codex))
    lines = []
    if usage_groups:
        lines.append(f"  {DIM}│{RESET}  ".join(usage_groups))
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
