#!/opt/homebrew/bin/python3
"""tmux status bar renderer for Claude Code + Codex.

Two subcommands, both invoked from tmux.conf via #():

  status.py left  <pane_current_path>
  status.py right <session_name> <active_pane_id> <client_width>

`left` draws the working directory and git branch. `right` draws the AI meters:
Claude's context window plus its 5h/weekly limits, and Codex's context window
plus its weekly limit.

Where the numbers come from
---------------------------
Claude never writes its usage to disk. The statusline (~/.claude/statusline.py)
is the only place that sees `rate_limits` and `context_window`, so it caches a
per-pane snapshot to ~/.cache/ai-status/claude-<N>.json and the account-wide
usage to ~/.claude/usage-cache.json. This script only ever reads those.

Codex has no statusline hook at all, so its session is identified from the
outside by joining pid -> tty -> tmux pane (see codex_snapshot). Its numbers are
then read from the session's rollout JSONL and cached for CODEX_TTL seconds.

Rules this file has to respect
------------------------------
- Never block. tmux is single-threaded and a slow status command can hang the
  whole server (tmux#1854). No network calls, every subprocess capped with a
  timeout, the rollout read bounded to TAIL_BYTES, and main() swallows anything
  that escapes so a traceback can never reach the status bar.
- Never show a group for an agent that isn't running. Each group is gated on
  that agent actually occupying a pane of the attached session.
- Write caches atomically. tmux reads these files while other processes write
  them, so a partial read would garble the bar.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

# ---- thresholds & timings ---------------------------------------------------
WARN = 50            # green below this
CLOSE = 80           # red at/above this
STALE_AFTER = 600    # a Claude snapshot older than this renders dimmed with a ~
# Codex numbers are only as fresh as that session's last turn, and a session
# left open for days will happily report last week's limits. Judged against the
# rollout's mtime rather than when we read it.
CODEX_STALE_AFTER = 3600
CODEX_TTL = 60       # don't re-derive Codex more than once a minute
TAIL_BYTES = 256 * 1024   # rollout files reach tens of MB; only read the tail
CODEX_BASELINE = 12000    # approximates Codex's own context accounting

# ---- Solarized via the ANSI palette ----------------------------------------
# Deliberately colourN rather than hex: tmux resolves these through the iTerm2
# profile, so the bar tracks "Justin's Defaults" instead of freezing a copy.
BASE = "colour12"    # base0  #839496 — default status fg
DIM = "colour10"     # base01 #586e75 — labels, empty meter cells, separators
DIR = "colour14"     # base1  #93a1a1
BRANCH = "colour5"   # magenta #d33682
GREEN = "colour2"    # #859900
YELLOW = "colour3"   # #b58900
RED = "colour1"      # #dc322f

HOME = Path.home()
CACHE_DIR = HOME / ".cache" / "ai-status"
CLAUDE_USAGE = HOME / ".claude" / "usage-cache.json"
CODEX_CACHE = CACHE_DIR / "codex.json"
LEFT_WIDTH_CACHE = CACHE_DIR / "left-width"
CODEX_SESSIONS = HOME / ".codex" / "sessions"

STYLE_RE = re.compile(r"#\[[^\]]*\]")
ROLLOUT_RE = re.compile(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-")


# ---- small helpers ----------------------------------------------------------
def fg(color, text):
    return f"#[fg={color}]{text}#[fg={BASE}]"


def vis_width(s):
    """Rendered column count, ignoring tmux #[...] style markup."""
    return sum(
        2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        for c in STYLE_RE.sub("", s)
    )


def run(args, timeout=1.0):
    """Subprocess that can never hang the status bar."""
    try:
        out = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout
    except Exception:
        return ""


MAX_CACHE_BYTES = 1 << 20   # these files are small; refuse to read a runaway one


def read_json(path):
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return None   # never let a runaway file stall the status bar
        return json.loads(path.read_text())
    except Exception:
        return None


def write_json_atomic(path, obj):
    """Temp file + os.replace, so a reader never sees a half-written file."""
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


def is_stale(ts):
    return not ts or (time.time() - ts) > STALE_AFTER


# ---- meters -----------------------------------------------------------------
def pct_color(p):
    if p >= CLOSE:
        return RED
    if p >= WARN:
        return YELLOW
    return GREEN


def meter(p, width=6):
    p = max(0, min(100, p))
    filled = int(round(p / 100 * width))
    return fg(pct_color(p), "█" * filled) + fg(DIM, "░" * (width - filled))


def reset_str(epoch, wide):
    """'resets 8:10pm' when there's room, '⟲ 8:10pm' when there isn't.

    The weekday is included whenever the reset isn't today — the weekly windows
    land days out, and a bare '1:00am' would read as tonight.
    """
    if not epoch:
        return ""
    t = time.localtime(epoch)
    stamp = time.strftime("%-I:%M", t) + time.strftime("%p", t).lower()
    if time.strftime("%F", t) != time.strftime("%F", time.localtime()):
        stamp = time.strftime("%a ", t) + stamp
    return fg(DIM, f" {'resets' if wide else '⟲'} {stamp}")


def gauge(label, pct, resets_at=None, tier="full", always_reset=False):
    """'5h ██░░░░ 42% resets 8:10pm', trimmed down as the tier tightens."""
    p = int(round(pct))
    if tier == "full":
        seg = f"{label} {meter(p)} {fg(pct_color(p), f'{p}%')}"
    else:
        seg = f"{label} {fg(pct_color(p), f'{p}%')}"
    if tier != "min" and (always_reset or p >= CLOSE):
        seg += reset_str(resets_at, tier == "full")
    return seg


# ---- tmux introspection -----------------------------------------------------
def list_panes(session):
    """[{id, tty, cmd, path, active, window}] for every pane in the session."""
    fmt = "#{pane_id}\t#{pane_tty}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_active}\t#{window_index}"
    panes = []
    for line in run(["tmux", "list-panes", "-s", "-t", session, "-F", fmt]).splitlines():
        parts = line.split("\t")
        if len(parts) == 6:
            panes.append({
                "id": parts[0], "tty": parts[1], "cmd": parts[2],
                "path": parts[3], "active": parts[4] == "1", "window": parts[5],
            })
    return panes


def window_list_width(session):
    fmt = "#{window_index}:#{window_name}"
    names = run(["tmux", "list-windows", "-t", session, "-F", fmt]).split()
    return sum(len(n) + 2 for n in names)


# ---- Claude -----------------------------------------------------------------
def pane_cache_path(pane_id):
    return CACHE_DIR / f"claude-{pane_id.lstrip('%')}.json"


def claude_snapshot(panes):
    """The Claude session to display, or None if none is running here.

    Presence is decided by the pane scan, not by the cache: a Claude that just
    started hasn't written a snapshot yet, and should still show its cached
    account-wide usage rather than vanishing. Active pane wins; otherwise the
    most recently updated. Snapshots for panes that are gone are unlinked on the
    way past.
    """
    # Liveness is judged against every pane on the SERVER, not just this
    # session's. Scoping it to `panes` would make rendering one session delete
    # the snapshots of Claude sessions running in all the others.
    all_panes = run(["tmux", "list-panes", "-a", "-F", "#{pane_id}"]).split()
    if all_panes:
        live = set(all_panes)
        try:
            for f in CACHE_DIR.glob("claude-*.json"):
                if f"%{f.stem.split('-', 1)[1]}" not in live:
                    f.unlink(missing_ok=True)
        except Exception:
            pass

    running = [p for p in panes if p["cmd"] == "claude"]
    if not running:
        return None

    found = []
    for p in running:
        snap = read_json(pane_cache_path(p["id"])) or {}
        snap["_active"] = p["active"]
        found.append(snap)
    found.sort(key=lambda s: (s.get("_active", False), s.get("ts", 0)), reverse=True)
    return found[0]


def claude_usage(snap):
    """Account-wide 5h/weekly, preferring the live snapshot over the cache.

    The on-disk cache is what makes a brand-new tmux session render numbers
    before Claude's first turn of the day has delivered any.
    """
    rl = (snap or {}).get("rate_limits")
    if rl:
        return rl, snap.get("ts")
    cached = read_json(CLAUDE_USAGE) or {}
    return cached.get("rate_limits") or {}, cached.get("written_at")


# ---- Codex ------------------------------------------------------------------
def codex_pids_in_session(panes):
    """Codex pids occupying a pane of this session, via pid -> tty -> pane.

    This is what keeps the hourly `usage-report.py` ping out of the status bar:
    headless `codex exec` runs have no controlling terminal, so ps reports '??'
    and they simply never match a pane.
    """
    ttys = {p["tty"] for p in panes}
    pids = []
    for pid in run(["pgrep", "-x", "codex"]).split():
        line = run(["ps", "-o", "tty=,lstart=", "-p", pid]).strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        tty, started = parts
        if f"/dev/{tty}" in ttys:
            pids.append((pid, started))
    return pids


def rollout_for_start(started, pid=None):
    """Find the rollout file whose embedded timestamp matches process start.

    Codex names the file after the moment the session began, so a match is
    normally exact and needs no directory walk beyond that one day. Two sessions
    launched within the tolerance window would be ambiguous, though, so in that
    case fall back to asking lsof which file the process actually holds open.
    That call is ~50-100ms, which is why it isn't the primary path.
    """
    try:
        dt = datetime.strptime(" ".join(started.split()), "%a %b %d %H:%M:%S %Y")
    except Exception:
        return None
    day = CODEX_SESSIONS / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
    if not day.is_dir():
        return None

    candidates = []
    for f in day.glob("rollout-*.jsonl"):
        m = ROLLOUT_RE.search(f.name)
        if not m:
            continue
        try:
            ft = datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S")
        except Exception:
            continue
        delta = abs((ft - dt).total_seconds())
        if delta <= 2:
            candidates.append((delta, f))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]

    if pid:
        held = {c[1] for c in candidates}
        for line in run(["lsof", "-p", str(pid)], timeout=3.0).splitlines():
            for f in held:
                if f.name in line:
                    return f
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def tail_lines(path, nbytes=TAIL_BYTES):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read()
        if size > nbytes:
            data = data.split(b"\n", 1)[-1]   # drop the partial first line
        return data.decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def codex_from_rollout(path):
    """Last token_count event -> context %, weekly usage, model."""
    ctx = weekly = resets = model = None
    lines = tail_lines(path)
    for line in reversed(lines):
        if '"token_count"' not in line:
            continue
        try:
            payload = json.loads(line).get("payload") or {}
        except Exception:
            continue
        if payload.get("type") != "token_count":
            continue
        info = payload.get("info") or {}
        window = info.get("model_context_window")
        used = (info.get("last_token_usage") or {}).get("total_tokens")
        if window and used is not None and window > CODEX_BASELINE:
            pct = 100.0 * (used - CODEX_BASELINE) / (window - CODEX_BASELINE)
            ctx = max(0, min(100, int(round(pct))))
        primary = (payload.get("rate_limits") or {}).get("primary") or {}
        if primary.get("used_percent") is not None:
            weekly = int(round(primary["used_percent"]))
            resets = primary.get("resets_at")
        if ctx is not None or weekly is not None:
            break
    for line in reversed(lines):
        if '"turn_context"' not in line:
            continue
        try:
            model = (json.loads(line).get("payload") or {}).get("model")
        except Exception:
            model = None
        if model:
            break
    try:
        data_ts = path.stat().st_mtime   # when this session last took a turn
    except Exception:
        data_ts = None
    return {"ctx": ctx, "weekly": weekly, "resets_at": resets,
            "model": model, "data_ts": data_ts}


def codex_snapshot(panes):
    """Codex numbers for this session, or None if Codex isn't running in it.

    Whether Codex is present is resolved fresh on every call, because it is
    per-session and cheap (a pgrep plus a ps per pid). Only the expensive part —
    parsing the rollout — is cached, keyed by the rollout path. Caching the
    presence verdict instead would leak across sessions: a shell-only session
    would write "not running" and suppress Codex in a sibling session that has
    it, for up to a minute.
    """
    pids = codex_pids_in_session(panes)
    if not pids:
        return None

    path = None
    for pid, started in pids:
        path = rollout_for_start(started, pid)
        if path:
            break
    if not path:
        return {"ctx": None, "weekly": None, "resets_at": None,
                "model": None, "data_ts": None}

    cached = read_json(CODEX_CACHE)
    if (cached and cached.get("path") == str(path)
            and (time.time() - cached.get("ts", 0)) < CODEX_TTL):
        return cached

    snap = codex_from_rollout(path)
    snap.update({"ts": time.time(), "path": str(path)})
    write_json_atomic(CODEX_CACHE, snap)
    return snap


# ---- group rendering --------------------------------------------------------
def claude_group(snap, usage, usage_ts, tier):
    parts = []
    stale = is_stale(snap.get("ts"))
    ctx = snap.get("ctx")
    if ctx is not None:
        parts.append(gauge("ctx", ctx, tier=tier))

    fh = (usage or {}).get("five_hour") or {}
    if fh.get("used_percentage") is not None:
        parts.append(gauge("5h", fh["used_percentage"], fh.get("resets_at"),
                           tier=tier, always_reset=True))
    sd = (usage or {}).get("seven_day") or {}
    if sd.get("used_percentage") is not None:
        parts.append(gauge("wk", sd["used_percentage"], sd.get("resets_at"), tier=tier))
    if not parts:
        return None

    label = fg(DIM, "claude")
    if stale or is_stale(usage_ts):
        label += fg(DIM, "~")
    sep = fg(DIM, " · ") if tier != "min" else " "
    return f"{label} {sep.join(parts)}"


def codex_group(snap, tier):
    parts = []
    if snap.get("ctx") is not None:
        parts.append(gauge("ctx", snap["ctx"], tier=tier))
    if snap.get("weekly") is not None:
        parts.append(gauge("wk", snap["weekly"], snap.get("resets_at"), tier=tier))
    if not parts:
        return None

    label = fg(DIM, "codex")
    data_ts = snap.get("data_ts")
    if not data_ts or (time.time() - data_ts) > CODEX_STALE_AFTER:
        label += fg(DIM, "~")
    if tier == "full" and snap.get("model"):
        label += f" {snap['model']}"
    sep = fg(DIM, " · ") if tier != "min" else " "
    return f"{label} {sep.join(parts)}"


def render_right(claude, usage, usage_ts, codex, budget):
    """Widest rendering that fits, degrading detail then dropping groups."""
    divider = fg(DIM, "  │  ")
    for tier in ("full", "nobar", "min"):
        groups = []
        if claude:
            g = claude_group(claude, usage, usage_ts, tier)
            if g:
                groups.append(g)
        if codex:
            g = codex_group(codex, tier)
            if g:
                groups.append(g)
        if not groups:
            return ""
        out = divider.join(groups)
        if vis_width(out) <= budget:
            return out
    # Still over: keep Claude alone, then Claude's context alone.
    if claude:
        g = claude_group(claude, usage, usage_ts, "min")
        if g and vis_width(g) <= budget:
            return g
        ctx = claude.get("ctx")
        if ctx is not None:
            return f"{fg(DIM, 'claude')} {gauge('ctx', ctx, tier='min')}"
    return ""


# ---- subcommands ------------------------------------------------------------
def git_branch(cwd):
    out = run(["git", "-C", cwd, "branch", "--show-current"])
    return out.strip() or None


def cmd_left(argv):
    cwd = argv[0] if argv else os.getcwd()
    name = os.path.basename(cwd.rstrip("/")) or cwd
    out = f"📁 #[bold]{fg(DIR, name)}#[nobold]"
    branch = git_branch(cwd)
    if branch:
        out += "  " + fg(BRANCH, f"⎇ {branch}")
    # `right` reads this to size its own budget without re-running git.
    write_json_atomic(LEFT_WIDTH_CACHE, {"w": vis_width(out)})
    return out


def cmd_right(argv):
    session = argv[0] if argv else ""
    width = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else 200
    if not session:
        return ""

    panes = list_panes(session)
    if not panes:
        return ""

    claude = claude_snapshot(panes)
    codex = codex_snapshot(panes)
    if not claude and not codex:
        return ""   # pure-shell session: show nothing rather than dead meters

    usage, usage_ts = claude_usage(claude) if claude else ({}, None)

    left_w = (read_json(LEFT_WIDTH_CACHE) or {}).get("w", 40)
    budget = width - left_w - window_list_width(session) - 4
    return render_right(claude, usage, usage_ts, codex, max(budget, 0))


def main():
    argv = sys.argv[1:]
    if not argv:
        return ""
    try:
        if argv[0] == "left":
            return cmd_left(argv[1:])
        if argv[0] == "right":
            return cmd_right(argv[1:])
    except Exception:
        return ""   # a traceback must never reach the status bar
    return ""


if __name__ == "__main__":
    sys.stdout.write(main())
