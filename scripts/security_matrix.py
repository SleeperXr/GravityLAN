"""Write docs/security-matrix.md from the access policies the routes declare (app.api.policy).

    cd backend && python ../scripts/security_matrix.py          # rewrite the document
    cd backend && python ../scripts/security_matrix.py --check  # exit 1 when it is out of date

tests/test_policy_matrix.py runs the check and calls every route as every kind of caller, so the
document, the declarations and the server's answers cannot drift apart.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "security-matrix.md"

SETUP = {
    "closed": "after setup",
    "open": "also during setup, without login",
    "only": "only during setup",
    "any": "always",
}

HEADER = """# Security matrix

Generated from the route declarations by `scripts/security_matrix.py`; do not edit by hand.
`tests/test_policy_matrix.py` fails when a route has no policy, when this file is out of date,
or when a route answers a caller differently than listed here.

Every route declares its access policy once, in its decorator: `dependencies=[policy(...)]`
(`backend/app/api/policy.py`). The policy checks, in this order:

1. **Setup**: until the first-run wizard is completed only routes marked *also during setup* answer
   (403 otherwise).
2. **Login**: a browser session (cookie), the master token or an API token (`Authorization: Bearer`;
   on a WebSocket also `?token=`). Missing or invalid: 401.
3. **Caller kind**: a caller kind marked `-` gets 403.
4. **Scope**: an API token needs the listed scope (403). `any` means every API token.
5. **Step-up**: the browser session must have confirmed the admin password for this class within
   `security.stepup_minutes` (403 with header `X-Step-Up: <class>`). `remote` is for browser
   sessions only; `credentials` and `instance` refuse API tokens, the master token passes.

Columns: **Session** = logged-in browser session, **Master** = master token (header, or the
deprecated cookie), **API token** = scope an API token needs. Public routes need no login; some
check a credential of their own, named under *Notes*.
"""


def _bootstrap():
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("GRAVITYLAN_DATA_DIR", tempfile.mkdtemp())
    from app.main import app

    return app


def _cell(ok: bool) -> str:
    return "yes" if ok else "-"


def _row(entry) -> str:
    from app.api.policy import API_TOKEN, MASTER, SESSION

    p = entry.policy
    method = "WebSocket" if entry.method == "WS" else entry.method
    notes = []
    if p.public:
        session = master = token = "public"
        step = "-"
        if p.credential:
            notes.append(f"Own check: {p.credential}.")
    else:
        session = _cell(SESSION in p.callers and not p.bearer_only)
        master = _cell(MASTER in p.callers)
        token = (f"`{p.scope}`" if p.scope else "any") if API_TOKEN in p.callers else "-"
        step = p.step_up or "-"
        if p.bearer_only:
            notes.append("Authorization header only (a GET with side effects; browsers use the POST variant).")
        if p.agent_token:
            notes.append("Also the device's agent token as `?token=`.")
        if p.credential:
            notes.append(f"Also: {p.credential}.")
    if p.note:
        notes.append(p.note[:1].upper() + p.note[1:] + ("" if p.note.endswith(".") else "."))
    return f"| {method} | `{entry.path}` | {session} | {master} | {token} | {step} | {SETUP[p.setup]} | {' '.join(notes)} |"


def _area(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "api":
        return f"/api/{parts[1]}"
    return "GravityUI and health"


def render(app) -> str:
    """The whole document for ``app``; every route must have exactly one policy."""
    from app.api.policy import iter_route_policies

    areas = defaultdict(list)
    for entry in iter_route_policies(app):
        if entry.policy is None:
            raise SystemExit(f"{entry.method} {entry.path} ({entry.endpoint}) has {len(entry.policies)} policies, not 1")
        areas[_area(entry.path)].append(entry)

    order = {"GET": 0, "HEAD": 1, "POST": 2, "PUT": 3, "PATCH": 4, "DELETE": 5, "WS": 6}
    lines = [HEADER]
    for area in sorted(areas, key=lambda a: (not a.startswith("/api"), a)):
        lines += [f"## {area}", "", "| Method | Path | Session | Master | API token | Step-up | Answers | Notes |",
                  "|---|---|---|---|---|---|---|---|"]
        for entry in sorted(areas[area], key=lambda e: (e.path, order.get(e.method, 9))):
            lines.append(_row(entry))
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    text = render(_bootstrap())
    if "--check" in sys.argv:
        current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if current != text:
            print(f"{DOC} is out of date: run 'cd backend && python ../scripts/security_matrix.py'")
            return 1
        return 0
    DOC.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
