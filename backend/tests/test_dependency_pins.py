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


def exported_pins(text: str) -> dict[str, str]:
    """requirements.lock.txt: one pin per line, maybe with an environment marker after ';'."""
    pins = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        assert match, f"requirements.lock.txt: '{line}' is not pinned with =="
        pins[_normalize(match.group(1))] = match.group(2)
    return pins


def test_lock_export_matches_uv_lock_and_requirements():
    requirements = pinned_requirements((BACKEND / "requirements.txt").read_text(encoding="utf-8"))
    locked = locked_versions((BACKEND / "uv.lock").read_text(encoding="utf-8"))
    exported = exported_pins((BACKEND / "requirements.lock.txt").read_text(encoding="utf-8"))
    stale = {name: (version, locked.get(name)) for name, version in exported.items() if locked.get(name) != version}
    missing = {name: (version, exported.get(name)) for name, version in requirements.items()
               if exported.get(name) != version}
    assert not stale and not missing, (
        f"requirements.lock.txt is out of date (export, uv.lock): {stale}; direct pins not in it: {missing}. "
        "Run in backend/: uv export --frozen --no-dev --no-hashes --no-emit-project > requirements.lock.txt"
    )


def test_exported_pins_skip_comments_and_markers():
    text = "\n".join(["# header", "aiosqlite==0.22.1", "    # via x", "colorama==0.4.6 ; sys_platform == 'win32'"])
    assert exported_pins(text) == {"aiosqlite": "0.22.1", "colorama": "0.4.6"}
