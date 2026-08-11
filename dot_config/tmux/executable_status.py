#!/opt/homebrew/bin/python3
"""Fast, failure-silent renderer for tmux's left status segment."""
import os
import subprocess
import sys


BASE = "colour12"
DIR = "colour14"
BRANCH = "colour5"


def fg(color, text):
    return f"#[fg={color}]{text}#[fg={BASE}]"


def git_branch(cwd):
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, text=True, timeout=1, check=False,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def main():
    try:
        cwd = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
        name = os.path.basename(cwd.rstrip("/")) or cwd
        output = fg(DIR, f" {name}")
        branch = git_branch(cwd)
        if branch:
            output += "  " + fg(BRANCH, f"⎇ {branch}")
        sys.stdout.write(output + "    ")
    except Exception:
        pass


if __name__ == "__main__":
    main()
