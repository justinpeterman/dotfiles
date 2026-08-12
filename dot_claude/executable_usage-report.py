#!/opt/homebrew/bin/python3
"""Shared Claude + Codex usage collector and renderer.

  usage-report.py            # refresh both providers, then report both
  usage-report.py --no-ping  # read whatever is already on disk (0 tokens)
  usage-report.py --quiet    # only print when a window is close to its cap
  usage-report.py --json     # normalized data for another UI
  usage-report.py --refresh-claude  # force a zero-token Claude usage refresh

Codex persists rate limits to its rollout files, so a tiny `codex exec` on the
cheapest model can refresh them. Claude's interactive statusline caches its
5h/weekly numbers in ~/.claude/usage-cache.json; this command can refresh that
same cache without model tokens by invoking Claude's built-in `/usage` command.

Windows at/above CLOSE% are flagged with ⚠ and show their reset time. Every run appends
a one-line summary to ~/.claude/usage.log.
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

CLOSE = 80  # notify at/above this %
HOME = Path.home()
CACHE = HOME / ".claude" / "usage-cache.json"
CACHE_LOCK = HOME / ".claude" / ".usage-cache.lock"
LOG = HOME / ".claude" / "usage.log"
SESSIONS = HOME / ".codex" / "sessions"
AI_CACHE = HOME / ".cache" / "ai-status"
REFRESH_LOCK = AI_CACHE / "usage-refresh.lock"
CLAUDE_STALE_AFTER = 10 * 60
CODEX_STALE_AFTER = 60 * 60
WATCH_INTERVAL = 60
CODEX_LOOKBACK_DAYS = 4
MAX_ROLLOUT_SCAN = 5
TAIL_BYTES = 256 * 1024
CODEX_BASELINE = 12000


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


def codex_bin():
    """Absolute path to the codex CLI. launchd runs with a minimal PATH that omits
    /opt/homebrew/bin, so a bare 'codex' would raise FileNotFoundError and the ping
    would silently no-op — leaving every scheduled run on a stale snapshot."""
    for p in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        if Path(p).exists():
            return p
    return shutil.which("codex") or "codex"


def claude_bin():
    for p in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if Path(p).exists():
            return p
    return shutil.which("claude") or "claude"


def ping_codex():
    """Cheapest possible call so Codex writes a fresh rate_limits snapshot."""
    try:
        result = subprocess.run(
            [codex_bin(), "exec", "--ignore-user-config", "--ignore-rules",
             "-m", "gpt-5.4-mini",
             "-c", "model_reasoning_effort=minimal",
             "--skip-git-repo-check", "x"],
            cwd="/tmp", capture_output=True, timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def parse_claude_reset(stamp):
    """Parse Claude /usage's local reset time, including New Year rollover."""
    now = time.time()
    try:
        dt = datetime.strptime(
            f"{datetime.now().year} {stamp}", "%Y %b %d at %I:%M%p"
        )
        epoch = time.mktime(dt.timetuple())
        if epoch < now:
            epoch = time.mktime(dt.replace(year=dt.year + 1).timetuple())
        return int(epoch)
    except Exception:
        return None


def write_json_atomic(path, obj):
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
            raise
        return True
    except Exception:
        return False


def write_claude_usage(windows):
    """Serialize with statusline writers, retaining their context fallbacks."""
    try:
        with CACHE_LOCK.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                existing = json.loads(CACHE.read_text()) or {}
            except Exception:
                existing = {}
            existing.update({
                "written_at": int(time.time()),
                "rate_limits": windows,
            })
            return write_json_atomic(
                CACHE, existing
            )
    except Exception:
        return False


def parse_claude_usage(report):
    patterns = {
        "five_hour": (
            r"Current session:\s*([\d.]+)% used.*?resets\s+"
            r"([A-Z][a-z]{2}\s+\d{1,2}\s+at\s+\d{1,2}:\d{2}[ap]m)"
        ),
        "seven_day": (
            r"Current week \(all models\):\s*([\d.]+)% used.*?resets\s+"
            r"([A-Z][a-z]{2}\s+\d{1,2}\s+at\s+\d{1,2}:\d{2}[ap]m)"
        ),
    }
    windows = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, report)
        if not match:
            return None
        resets_at = parse_claude_reset(match.group(2))
        if resets_at is None:
            return None
        windows[key] = {
            "used_percentage": float(match.group(1)),
            "resets_at": resets_at,
        }
    return windows


def ping_claude():
    """Refresh Claude limits with its zero-token built-in /usage command."""
    try:
        result = subprocess.run(
            [claude_bin(), "--safe-mode", "--output-format", "json", "-p", "/usage"],
            capture_output=True, text=True, timeout=30,
        )
        payload = json.loads(result.stdout or "{}")
        windows = parse_claude_usage(payload.get("result") or "")
        return bool(windows) and write_claude_usage(windows)
    except Exception:
        return False


def tail_lines(path, nbytes=TAIL_BYTES):
    """Read only the bounded tail of a rollout that may still be growing."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read(nbytes)
        if size > nbytes:
            data = data.split(b"\n", 1)[-1]
        return data.decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def recent_rollouts(limit=MAX_ROLLOUT_SCAN):
    """Newest rollout paths from a bounded set of recent date directories."""
    found = []
    now = datetime.now()
    for offset in range(CODEX_LOOKBACK_DAYS):
        day = now - timedelta(days=offset)
        directory = SESSIONS / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if not directory.is_dir():
            continue
        for path in directory.glob("rollout-*.jsonl"):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        if len(found) >= limit:
            break
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in found[:limit]]


def codex_from_rollout(path):
    """Extract context, model, and rate-limit windows from one rollout tail."""
    context = model = data_ts = None
    windows = []
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
        window_size = info.get("model_context_window")
        used = (info.get("last_token_usage") or {}).get("total_tokens")
        if context is None and window_size and used is not None and window_size > CODEX_BASELINE:
            pct = 100.0 * (used - CODEX_BASELINE) / (window_size - CODEX_BASELINE)
            context = max(0, min(100, int(round(pct))))
        if not windows:
            limits = payload.get("rate_limits") or {}
            for item in (limits.get("primary"), limits.get("secondary")):
                if not item or item.get("used_percent") is None:
                    continue
                minutes = item.get("window_minutes") or 0
                label = "wk" if minutes >= 10080 else "5h"
                windows.append((label, item["used_percent"], item.get("resets_at")))
        if context is not None and windows:
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
        data_ts = path.stat().st_mtime
    except OSError:
        pass
    return {"context_percent": context, "model": model,
            "windows": windows, "data_ts": data_ts}


def codex_status():
    """Combine the newest usable Codex context and account-limit snapshot."""
    context = model = context_ts = newest_ts = None
    windows = []
    for path in recent_rollouts():
        snapshot = codex_from_rollout(path)
        if newest_ts is None:
            newest_ts = snapshot.get("data_ts")
        if context is None and snapshot.get("context_percent") is not None:
            context = snapshot["context_percent"]
            model = snapshot.get("model")
            context_ts = snapshot.get("data_ts")
        if not windows and snapshot.get("windows"):
            windows = snapshot["windows"]
        if context is not None and windows:
            break
    return {"context_percent": context, "model": model,
            "windows": windows, "data_ts": context_ts or newest_ts}


def codex_windows():
    """Compatibility view used by the text report and freshness checks."""
    snapshot = codex_status()
    windows = [(f"codex {label}", pct, resets)
               for label, pct, resets in snapshot["windows"]]
    return windows, age(snapshot.get("data_ts")) if snapshot.get("data_ts") else "no data"


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


def expired(resets):
    """True once a window's reset time has passed, making its % obsolete.

    Neither agent pushes usage anywhere; both figures are frozen at whatever
    the last turn reported. Unchecked, this report restates a capped window for
    as long as the machine stays idle — it flagged claude wk at 100% ⚠ every
    hour from 2026-08-09 23:08 through 2026-08-10 09:51, long after that weekly
    window had in fact reset at 01:00.
    """
    return bool(resets) and resets <= time.time()


def claude_needs_refresh():
    try:
        data = json.loads(CACHE.read_text())
        if time.time() - data.get("written_at", 0) > CLAUDE_STALE_AFTER:
            return True
        rl = data.get("rate_limits") or {}
        windows = [rl.get("five_hour") or {}, rl.get("seven_day") or {}]
        return any(w.get("used_percentage") is None or expired(w.get("resets_at"))
                   for w in windows)
    except Exception:
        return True


def codex_needs_refresh():
    try:
        files = recent_rollouts(limit=1)
        if not files:
            return True
        newest = files[0]
        windows, _ = codex_windows()
        return (not windows
                or time.time() - newest.stat().st_mtime > CODEX_STALE_AFTER
                or any(expired(resets) for _, _, resets in windows))
    except Exception:
        return True


def refresh_stale(providers=("claude", "codex")):
    """Refresh selected stale limits; collapse simultaneous callers to one run."""
    try:
        AI_CACHE.mkdir(parents=True, exist_ok=True)
        with REFRESH_LOCK.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return
            if "claude" in providers and claude_needs_refresh():
                ping_claude()
            if "codex" in providers and codex_needs_refresh():
                ping_codex()
    except Exception:
        pass


def row(label, pct, resets):
    if pct is None:
        return f"  {label}"
    if expired(resets):
        return f"  {label:9} {'░' * 10}      ?   window reset {when(resets)}"
    flag = " ⚠" if pct >= CLOSE else "  "
    return f"{flag}{label:9} {bar(pct)} {pct:5.1f}%   resets {when(resets)}"


def selected_providers(provider):
    return ("claude", "codex") if provider == "all" else (provider,)


def usage_snapshot(provider="all"):
    """Return one provider-neutral shape for terminals and future UIs."""
    result = {"generated_at": int(time.time()), "providers": {}}
    if provider in ("all", "claude"):
        windows, data_age = claude_windows()
        result["providers"]["claude"] = {
            "age": data_age,
            "empty_message": "no cache",
            "windows": [
                {"label": label.removeprefix("claude "), "used_percent": pct,
                 "resets_at": resets, "expired": expired(resets)}
                for label, pct, resets in windows
            ],
        }
    if provider in ("all", "codex"):
        status = codex_status()
        data_age = age(status.get("data_ts")) if status.get("data_ts") else "no data"
        result["providers"]["codex"] = {
            "age": data_age,
            "empty_message": "no data",
            "context_percent": status.get("context_percent"),
            "model": status.get("model"),
            "windows": [
                {"label": label, "used_percent": pct,
                 "resets_at": resets, "expired": expired(resets)}
                for label, pct, resets in status["windows"]
            ],
        }
    return result


def render_text(snapshot, quiet=False):
    lines = []
    close = False
    for provider, data in snapshot["providers"].items():
        lines.append(f"  {provider:7} ({data['age']})")
        windows = data["windows"]
        if not windows:
            lines.append(f"  ({data['empty_message']})")
            continue
        for window in windows:
            lines.append(row(
                f"{provider} {window['label']}",
                window["used_percent"],
                window["resets_at"],
            ))
            close = close or (
                window["used_percent"] is not None
                and window["used_percent"] >= CLOSE
                and not window["expired"]
            )
    return "\n".join(lines) if lines and (close or not quiet) else ""


def append_log(snapshot):
    """Append one compact history row; watchers deliberately do not call this."""
    try:
        values = []
        for provider, data in snapshot["providers"].items():
            for window in data["windows"]:
                value = "?" if window["expired"] else f"{int(round(window['used_percent']))}%"
                values.append(f"{provider}-{window['label']}:{value}")
        if values:
            stamp = time.strftime("%Y-%m-%d %H:%M")
            with LOG.open("a") as f:
                f.write(f"{stamp}  {' '.join(values)}\n")
    except Exception:
        pass


def show_once(provider="all", quiet=False, as_json=False, log=True):
    snapshot = usage_snapshot(provider)
    output = json.dumps(snapshot, indent=2) if as_json else render_text(snapshot, quiet)
    if output:
        print(output, flush=True)
    if log:
        append_log(snapshot)


def watch(provider, interval):
    providers = selected_providers(provider)
    while True:
        refresh_stale(providers)
        if sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
        show_once(provider=provider, log=False)
        time.sleep(interval)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Collect and render Claude/Codex subscription usage windows."
    )
    parser.add_argument("--provider", choices=("all", "claude", "codex"), default="all")
    parser.add_argument("--no-ping", action="store_true",
                        help="read cached data without refreshing either provider")
    parser.add_argument("--quiet", action="store_true",
                        help="print only when a live window is at or above the warning threshold")
    parser.add_argument("--json", action="store_true",
                        help="emit normalized JSON instead of terminal text")
    parser.add_argument("--watch", action="store_true",
                        help="refresh stale data and redraw continuously")
    parser.add_argument("--interval", type=int, default=WATCH_INTERVAL,
                        help="watch refresh interval in seconds (default: 60)")
    parser.add_argument("--refresh-claude", action="store_true",
                        help="force a zero-token Claude /usage refresh")
    args = parser.parse_args(argv)
    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    if args.watch and (args.quiet or args.json):
        parser.error("--watch cannot be combined with --quiet or --json")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.refresh_claude:
        ping_claude()
        return
    if args.watch:
        try:
            watch(args.provider, args.interval)
        except (KeyboardInterrupt, BrokenPipeError):
            pass
        return
    if not args.no_ping:
        if args.provider in ("all", "claude"):
            ping_claude()
        if args.provider in ("all", "codex"):
            ping_codex()
    show_once(provider=args.provider, quiet=args.quiet, as_json=args.json)


if __name__ == "__main__":
    main()
