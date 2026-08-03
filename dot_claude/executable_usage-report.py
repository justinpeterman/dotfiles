#!/opt/homebrew/bin/python3
"""Combined Claude + Codex usage report — meant to run hourly via launchd.

  usage-report.py            # ping Codex for a fresh number, then report both
  usage-report.py --no-ping  # read whatever is already on disk (0 tokens)
  usage-report.py --quiet    # only print when a window is close to its cap

Codex persists rate limits to its rollout files, so we force a fresh reading with a
tiny `codex exec` on the cheapest model. Claude never writes its 5h/weekly numbers to
disk — the statusline (executable_statusline.py) caches them to ~/.claude/usage-cache.json
on each render, so Claude figures here are only as fresh as your last interactive turn.

Windows at/above CLOSE% are flagged with ⚠ and show their reset time. Every run appends
a one-line summary to ~/.claude/usage.log.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

CLOSE = 80  # notify at/above this %
HOME = Path.home()
CACHE = HOME / ".claude" / "usage-cache.json"
LOG = HOME / ".claude" / "usage.log"
SESSIONS = HOME / ".codex" / "sessions"


def bar(p, width=10):
    p = max(0, min(100, int(round(p))))
    filled = int(round(p / 100 * width))
    return "█" * filled + "░" * (width - filled)


def when(epoch):
    if not epoch:
        return "?"
    t = time.localtime(epoch)
    return time.strftime("%a %b %d %-I:%M", t) + time.strftime("%p", t).lower()


def age(epoch):
    if not epoch:
        return "never"
    secs = int(time.time()) - int(epoch)
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _find_key(obj, key):
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


def codex_bin():
    """Absolute path to the codex CLI. launchd runs with a minimal PATH that omits
    /opt/homebrew/bin, so a bare 'codex' would raise FileNotFoundError and the ping
    would silently no-op — leaving every scheduled run on a stale snapshot."""
    for p in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        if Path(p).exists():
            return p
    return shutil.which("codex") or "codex"


def ping_codex():
    """Cheapest possible call so Codex writes a fresh rate_limits snapshot."""
    try:
        subprocess.run(
            [codex_bin(), "exec", "-m", "gpt-5.4-mini",
             "-c", "model_reasoning_effort=minimal",
             "--skip-git-repo-check", "x"],
            capture_output=True, timeout=60,
        )
    except Exception:
        pass


def codex_windows():
    """Return list of (label, pct, resets_at) plus snapshot age string."""
    try:
        files = list(SESSIONS.rglob("rollout-*.jsonl"))
        if not files:
            return [], "no data"
        newest = max(files, key=lambda f: f.stat().st_mtime)
        snap_age = age(int(newest.stat().st_mtime))
        for line in reversed(newest.read_text(errors="ignore").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                rl = _find_key(json.loads(line), "rate_limits")
            except Exception:
                continue
            if not isinstance(rl, dict):
                continue
            out = []
            for key, prim in (("primary", rl.get("primary")), ("secondary", rl.get("secondary"))):
                if not prim or prim.get("used_percent") is None:
                    continue
                weekly = (prim.get("window_minutes") or 0) >= 10080
                out.append((
                    "codex wk" if weekly else "codex 5h",
                    prim["used_percent"], prim.get("resets_at"),
                ))
            return out, snap_age
        return [], snap_age
    except Exception:
        return [], "error"


def claude_windows():
    """Return list of (label, pct, resets_at) plus cache age string."""
    try:
        d = json.loads(CACHE.read_text())
    except Exception:
        return [], "no data (open a Claude session)"
    rl = d.get("rate_limits") or {}
    cache_age = age(d.get("written_at"))
    out = []
    for key, label in (("five_hour", "claude 5h"), ("seven_day", "claude wk")):
        w = rl.get(key) or {}
        if w.get("used_percentage") is not None:
            out.append((label, w["used_percentage"], w.get("resets_at")))
    return out, cache_age


def row(label, pct, resets):
    if pct is None:
        return f"  {label}"
    flag = " ⚠" if pct >= CLOSE else "  "
    return f"{flag}{label:9} {bar(pct)} {pct:5.1f}%   resets {when(resets)}"


def main():
    args = set(sys.argv[1:])
    if "--no-ping" not in args:
        ping_codex()

    cx, cx_age = codex_windows()
    cl, cl_age = claude_windows()

    lines = [f"  claude  ({cl_age})"]
    lines += [row(l, p, r) for (l, p, r) in (cl or [("(no cache)", None, None)])]
    lines.append(f"  codex   ({cx_age})")
    lines += [row(l, p, r) for (l, p, r) in (cx or [("(no data)", None, None)])]

    close = [(l, p, r) for (l, p, r) in (cx + cl) if p is not None and p >= CLOSE]

    if close or "--quiet" not in args:
        print("\n".join(lines))

    # one-line history
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M")
        flat = " ".join(f"{l.replace(' ', '-')}:{int(round(p))}%" for l, p, r in (cx + cl) if p is not None)
        with LOG.open("a") as f:
            f.write(f"{stamp}  {flat}\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
