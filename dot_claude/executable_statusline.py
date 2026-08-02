#!/opt/homebrew/bin/python3
"""Claude Code status line.

Renders:  daybreaker ⎇ main · Opus 4.8 · 5h 30% · wk 62% · ctx 45% · codex gpt-5.6-terra 7%

Data sources:
  - Claude Code statusLine JSON (stdin): model, cwd/repo, context %, rate_limits
  - git (via subprocess): current branch
  - ~/.codex/config.toml: current Codex model
  - ~/.codex/sessions/**/rollout-*.jsonl: last persisted Codex rate-limit snapshot
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ---- ANSI helpers -----------------------------------------------------------
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
SEP = f" {DIM}·{RESET} "


def pct_color(p):
    """Green under 50%, yellow under 80%, red at/above 80%."""
    if p >= 80:
        return RED
    if p >= 50:
        return YELLOW
    return GREEN


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
        b = out.stdout.strip()
        return b or None
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


def codex_usage():
    """Return (weekly_pct:int|None, stale:bool). Reads the newest rollout file's
    last rate_limits snapshot. 'stale' = snapshot file older than 8 hours."""
    sessions = Path.home() / ".codex" / "sessions"
    try:
        files = list(sessions.rglob("rollout-*.jsonl"))
        if not files:
            return None, True
        newest = max(files, key=lambda f: f.stat().st_mtime)
        stale = (time.time() - newest.stat().st_mtime) > 8 * 3600
        weekly = None
        # scan from the end for the last line containing rate_limits
        for line in reversed(newest.read_text(errors="ignore").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                # find the rate_limits object regardless of nesting
                idx = line.index('"rate_limits"')
                # locate the primary window's used_percent
                obj = json.loads(line)
                rl = _find_key(obj, "rate_limits")
                if isinstance(rl, dict):
                    primary = rl.get("primary") or {}
                    wm = primary.get("window_minutes")
                    up = primary.get("used_percent")
                    if up is not None:
                        # primary window is the weekly (10080 min) bucket
                        weekly = int(round(up))
                        return weekly, stale
            except Exception:
                continue
        return weekly, stale
    except Exception:
        return None, True


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


def main():
    d = read_stdin_json()
    parts = []

    # 1) dir + branch
    ws = d.get("workspace") or {}
    cwd = ws.get("current_dir") or d.get("cwd") or os.getcwd()
    repo = ws.get("repo") or {}
    name = repo.get("name") or os.path.basename(cwd.rstrip("/")) or cwd
    seg = f"{BOLD}{name}{RESET}"
    branch = git_branch(cwd)
    if branch:
        seg += f" {MAGENTA}⎇ {branch}{RESET}"
    parts.append(seg)

    # 2) Claude model
    model = (d.get("model") or {}).get("display_name")
    if model:
        parts.append(f"{CYAN}{model}{RESET}")

    # 3) Claude 5h usage
    rl = d.get("rate_limits") or {}
    fh = (rl.get("five_hour") or {}).get("used_percentage")
    if fh is not None:
        p = int(round(fh))
        parts.append(f"5h {pct_color(p)}{p}%{RESET}")

    # 4) Claude weekly usage
    sd = (rl.get("seven_day") or {}).get("used_percentage")
    if sd is not None:
        p = int(round(sd))
        parts.append(f"wk {pct_color(p)}{p}%{RESET}")

    # 5) context window
    cw = (d.get("context_window") or {}).get("used_percentage")
    if cw is not None:
        p = int(round(cw))
        parts.append(f"ctx {pct_color(p)}{p}%{RESET}")

    # 6) codex model + weekly usage
    cmodel = codex_model()
    if cmodel:
        cx = f"{DIM}codex{RESET} {cmodel}"
        weekly, stale = codex_usage()
        if weekly is not None:
            cx += f" {pct_color(weekly)}{weekly}%{RESET}"
        parts.append(cx)

    sys.stdout.write(SEP.join(parts))


if __name__ == "__main__":
    main()
