"""Where the version comes from (app/version.py): the first readable VERSION file, else a fallback."""

from pathlib import Path

from app import version


def test_the_first_existing_version_file_wins(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text(" 9.8.7\n")
    monkeypatch.chdir(tmp_path)
    # Only the last candidate (VERSION in the working directory) exists
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == "VERSION")
    assert version.get_version() == "9.8.7"


def test_unreadable_files_are_skipped_and_the_fallback_used(monkeypatch):
    def broken(self):
        raise PermissionError("no access")

    monkeypatch.setattr(Path, "exists", broken)
    assert version.get_version() == "0.2.5"


def test_normalize_version():
    assert version.normalize_version(" v1.2.3 ") == "1.2.3"
    assert version.normalize_version(None) is None
