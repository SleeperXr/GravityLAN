"""Fail when agent/ changed since BASE but the agent VERSION was not raised.

    python scripts/check_agent_version.py <base-ref>

Every change to the agent raises VERSION in agent/gravitylan-agent.py; server-only changes leave it alone
(docs/RELEASING.md). CI runs this for pull requests and pushes to main.
"""

import re
import subprocess
import sys

AGENT_FILE = "agent/gravitylan-agent.py"
VERSION_RE = re.compile(r'^VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def version(source: str) -> tuple[int, int, int]:
    match = VERSION_RE.search(source)
    if not match:
        sys.exit(f"No VERSION = \"x.y.z\" in {AGENT_FILE}")
    return tuple(int(part) for part in match.groups())


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    base = sys.argv[1]
    # Logs and caches next to the script are not part of the agent
    changed = [
        path for path in git("diff", "--name-only", f"{base}...HEAD", "--", "agent/").split()
        if not path.endswith((".log", ".pyc")) and "__pycache__" not in path
    ]
    if not changed:
        print("agent/ unchanged, the agent version stays.")
        return

    old = version(git("show", f"{base}:{AGENT_FILE}"))
    with open(AGENT_FILE, encoding="utf-8") as f:
        new = version(f.read())
    fmt = ".".join
    if new <= old:
        sys.exit(
            f"agent/ changed ({', '.join(changed)}) but the agent VERSION is still {fmt(map(str, new))}. "
            f"Raise it above {fmt(map(str, old))} in {AGENT_FILE} (and the README agent badge)."
        )
    print(f"Agent version raised {fmt(map(str, old))} -> {fmt(map(str, new))}.")


if __name__ == "__main__":
    main()
