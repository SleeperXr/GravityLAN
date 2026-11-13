"""requirements.txt (what the image installs) and uv.lock (what Dependabot scans) name the same versions.

Dependabot reads uv.lock, the Dockerfile installs requirements.txt. When they drift apart, a security
alert describes versions the image does not run, and merging a Dependabot PR leaves the image unchanged.
"""
import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PIN = re.compile(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==(\S+)")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_requirements(text: str) -> dict[str, str]:
    pins = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        assert match, f"requirements.txt: '{line}' is not pinned with =="
        pins[_normalize(match.group(1))] = match.group(2)
    return pins


def locked_versions(text: str) -> dict[str, str]:
    return {_normalize(p["name"]): p["version"] for p in tomllib.loads(text)["package"]}


def drift(requirements: str, lock: str) -> dict[str, tuple[str, str | None]]:
    locked = locked_versions(lock)
    return {name: (version, locked.get(name)) for name, version in pinned_requirements(requirements).items()
            if locked.get(name) != version}


def test_uv_lock_matches_requirements():
    found = drift((BACKEND / "requirements.txt").read_text(encoding="utf-8"),
                  (BACKEND / "uv.lock").read_text(encoding="utf-8"))
    assert not found, (
        "requirements.txt and uv.lock disagree (requirements, lock): "
        f"{found}. After a Dependabot PR, copy its versions into requirements.txt; after editing "
        "requirements.txt, run `uv lock --upgrade-package <name>==<version>` in backend/."
    )


def test_drift_is_reported():
    requirements = "fastapi==0.162.1\nuvicorn[standard]==0.54.0  # comment\n"
    lock = '[[package]]\nname = "fastapi"\nversion = "0.136.1"\n\n[[package]]\nname = "uvicorn"\nversion = "0.54.0"\n'
    assert drift(requirements, lock) == {"fastapi": ("0.162.1", "0.136.1")}


def test_a_package_missing_from_the_lock_is_drift():
    assert drift("docker==7.2.0\n", '[[package]]\nname = "fastapi"\nversion = "1"\n') == {"docker": ("7.2.0", None)}
