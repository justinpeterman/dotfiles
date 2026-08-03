#!/opt/homebrew/bin/python3
"""Claude Code status line.

Two rows:
  📁 daybreaker  ⎇ main  ·  Opus 4.8
  claude 5h ██░░░░ 23%  ·  wk ███░░░ 41%  ·  ctx █░░░░░ 8%  │  codex gpt-5.6-terra ░░░░░░ 7%

A meter that crosses the "close" threshold (80%) also shows when it resets:
  wk █████░ 82% ⟲ Aug 09 4:36pm

Data sources:
  - Claude Code statusLine JSON (stdin): model, cwd/repo, context %, rate_limits
      rate_limits.five_hour / .seven_day -> used_percentage + resets_at (unix secs)
  - git (via subprocess): current branch
  - ~/.codex/config.toml: current Codex model
  - ~/.codex/sessions/**/rollout-*.jsonl: last persisted Codex rate-limit snapshot
      (primary.used_percent + resets_at; window_minutes 10080 == weekly)

Side effect: each render persists the Claude rate_limits object (+ a timestamp) to
~/.claude/usage-cache.json. Claude's 5h/weekly numbers are delivered ONLY here on
stdin and never otherwise written to disk, so this cache is what lets an out-of-session
job (usage-report.py, run hourly) report Claude usage and reset times.
"""
import json
import os
import subprocess
import sys
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
SEP = f"  {DIM}·{RESET}  "   # between items within one tool's group
DIV = f"  {DIM}│{RESET}  "   # between the claude group and the codex group

CACHE = Path.home() / ".claude" / "usage-cache.json"


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
    if not epoch:
        return ""
    t = time.localtime(epoch)
    stamp = time.strftime("%b %d %-I:%M", t) + time.strftime("%p", t).lower()
    return f" {DIM}⟲ {stamp}{RESET}"


def gauge(label, pct, resets_at=None):
    """Render 'label ██░░░░ 42%', appending the reset time when close to the cap."""
    p = int(round(pct))
    seg = f"{label} {meter(p)} {pct_color(p)}{p}%{RESET}"
    if p >= CLOSE:
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


def codex_model():
    cfg = Path.home() / ".codex" / "config.toml"
    try:
        for line in cfg.read_text().splitlines():
            line = line.strip()
            if line.startswith("model") and "=" in line and "reasoning" not in line:
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return None


def _find_key(obj, key):
    """Depth-first search for the first value under `key` in nested dict/list."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def codex_usage():
    """Return (weekly_pct:int|None, resets_at:int|None, stale:bool) from the newest
    rollout file's last rate_limits snapshot. stale => file older than 8 hours."""
    sessions = Path.home() / ".codex" / "sessions"
    try:
        files = list(sessions.rglob("rollout-*.jsonl"))
        if not files:
            return None, None, True
        newest = max(files, key=lambda f: f.stat().st_mtime)
        stale = (time.time() - newest.stat().st_mtime) > 8 * 3600
        for line in reversed(newest.read_text(errors="ignore").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                rl = _find_key(json.loads(line), "rate_limits")
            except Exception:
                continue
            if isinstance(rl, dict):
                primary = rl.get("primary") or {}
                up = primary.get("used_percent")
                if up is not None:
                    return int(round(up)), primary.get("resets_at"), stale
        return None, None, stale
    except Exception:
        return None, None, True


def cache_claude(rl):
    """Persist the Claude rate_limits object so the hourly report can read it."""
    try:
        CACHE.write_text(json.dumps({"written_at": int(time.time()), "rate_limits": rl}))
    except Exception:
        pass


def main():
    d = read_stdin_json()

    # ---- row 1: dir + branch + model ----
    ws = d.get("workspace") or {}
    cwd = ws.get("current_dir") or d.get("cwd") or os.getcwd()
    repo = ws.get("repo") or {}
    name = repo.get("name") or os.path.basename(cwd.rstrip("/")) or cwd
    row1 = f"📁 {BOLD}{name}{RESET}"
    branch = git_branch(cwd)
    if branch:
        row1 += f"  {MAGENTA}⎇ {branch}{RESET}"
    model = (d.get("model") or {}).get("display_name")
    if model:
        row1 += f"{SEP}{CYAN}{model}{RESET}"

    # ---- row 2: usage meters ----
    rl = d.get("rate_limits") or {}
    if rl:  # don't let an early-session empty render clobber good cached numbers
        cache_claude(rl)

    claude_gauges = []
    claude_tag = f"{DIM}claude{RESET} "  # prefixes the first Claude window, like 'codex'
    fh = rl.get("five_hour") or {}
    if fh.get("used_percentage") is not None:
        claude_gauges.append(claude_tag + gauge("5h", fh["used_percentage"], fh.get("resets_at")))
        claude_tag = ""

    sd = rl.get("seven_day") or {}
    if sd.get("used_percentage") is not None:
        claude_gauges.append(claude_tag + gauge("wk", sd["used_percentage"], sd.get("resets_at")))
        claude_tag = ""

    cw = (d.get("context_window") or {}).get("used_percentage")
    if cw is not None:
        claude_gauges.append(gauge("ctx", cw))

    codex_gauges = []
    cmodel = codex_model()
    if cmodel:
        weekly, cresets, stale = codex_usage()
        if weekly is not None:
            label = f"{DIM}codex{RESET} {cmodel}{DIM}~{RESET}" if stale else f"{DIM}codex{RESET} {cmodel}"
            codex_gauges.append(gauge(label, weekly, cresets))
        else:
            codex_gauges.append(f"{DIM}codex {cmodel}{RESET}")

    # bullets within a tool's group, a divider between the two tools
    groups = [SEP.join(g) for g in (claude_gauges, codex_gauges) if g]
    out = row1
    if groups:
        out += "\n" + DIV.join(groups)
    sys.stdout.write(out)


if __name__ == "__main__":
    main()
