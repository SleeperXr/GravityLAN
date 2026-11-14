"""The inventory database is copied before another version migrates it; the newest three copies stay."""
import logging
import os
import sqlite3

from app.database import upgrade_backup as ub


def _inventory(path, devices: int = 1) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY, ip TEXT)")
    conn.executemany("INSERT INTO devices (ip) VALUES (?)", [(f"192.0.2.{i}",) for i in range(1, devices + 1)])
    conn.commit()
    conn.close()


def _devices(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    finally:
        conn.close()


def _copies(data_dir):
    return sorted((data_dir / ub.BACKUP_DIR).glob("gravitylan-*.db")) if (data_dir / ub.BACKUP_DIR).exists() else []


def test_a_fresh_install_makes_no_copy(tmp_path):
    assert ub.backup_before_upgrade(tmp_path, tmp_path / "gravitylan.db", "0.8.0") is None
    assert _copies(tmp_path) == []


def test_an_empty_database_file_counts_as_fresh(tmp_path):
    (tmp_path / "gravitylan.db").write_bytes(b"")
    assert ub.backup_before_upgrade(tmp_path, tmp_path / "gravitylan.db", "0.8.0") is None


def test_the_same_version_makes_no_copy(tmp_path):
    db = tmp_path / "gravitylan.db"
    _inventory(db)
    ub.remember_version(tmp_path, "0.8.0")
    assert ub.backup_before_upgrade(tmp_path, db, "0.8.0") is None
    assert _copies(tmp_path) == []


def test_a_new_version_copies_the_database_first(tmp_path):
    db = tmp_path / "gravitylan.db"
    _inventory(db, devices=3)
    ub.remember_version(tmp_path, "0.7.1")
    copy = ub.backup_before_upgrade(tmp_path, db, "0.8.0")
    assert copy is not None and copy.name.startswith("gravitylan-0.7.1-")
    assert _devices(copy) == 3
    assert not list((tmp_path / ub.BACKUP_DIR).glob("*.partial"))


def test_an_install_from_before_this_feature_is_copied_as_unknown(tmp_path):
    db = tmp_path / "gravitylan.db"
    _inventory(db)
    copy = ub.backup_before_upgrade(tmp_path, db, "0.8.0")
    assert copy is not None and copy.name.startswith("gravitylan-unknown-")


def test_only_the_newest_three_copies_stay(tmp_path):
    db = tmp_path / "gravitylan.db"
    _inventory(db)
    made = []
    for i, version in enumerate(["0.5.0", "0.6.0", "0.7.0", "0.7.1", "0.8.0"]):
        ub.remember_version(tmp_path, version)
        copy = ub.backup_before_upgrade(tmp_path, db, f"next-{i}")
        os.utime(copy, (1_000_000 + i, 1_000_000 + i))  # distinct ages, independent of the clock
        made.append(copy.name)
    ub._prune(tmp_path / ub.BACKUP_DIR, ub.KEEP)
    assert [p.name for p in _copies(tmp_path)] == sorted(made[-3:])


def test_a_failed_copy_does_not_stop_the_start(tmp_path, caplog):
    db = tmp_path / "gravitylan.db"
    _inventory(db)
    (tmp_path / ub.BACKUP_DIR).write_text("a file where the folder should be")
    with caplog.at_level(logging.ERROR, logger=ub.__name__):
        assert ub.backup_before_upgrade(tmp_path, db, "0.8.0") is None
    assert "Could not copy the database" in caplog.text


def test_the_version_is_remembered(tmp_path):
    ub.remember_version(tmp_path, "0.8.0")
    assert ub._read_last_version(tmp_path) == "0.8.0"


def test_an_external_database_is_left_alone(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    db = tmp_path / "gravitylan.db"
    _inventory(db)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://db.example/gravitylan")
    main._backup_before_upgrade()
    main._remember_migrated_version()
    assert _copies(tmp_path) == []
    assert ub._read_last_version(tmp_path) is None
