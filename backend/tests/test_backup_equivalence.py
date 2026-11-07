"""app/api/backup.py: missing-column defaults and row cleaning give the same result as before the refactor.

Frozen copies (0.7.0-rc.7) of _default_for_missing_col and _clean_rows run next to the live functions over
every column type x SQL default combination and over seeded random rows against a real SQLite table
(unknown columns, NULLs in NOT NULL columns, missing columns, protected settings, unsafe service links).
"""

import random
import sqlite3
from datetime import datetime

import pytest

import app.api.backup as backup
from app.schemas.device import is_safe_url_template


# --- frozen copies -------------------------------------------------------------------------

def _old_default(table, col, info, now_str):
    sql_default = info.get("default")
    if sql_default is not None:
        cleaned = str(sql_default).strip().strip("'\"")
        if cleaned.upper() in ("CURRENT_TIMESTAMP", "NOW()"):
            return now_str
        if any(t in info["type"].upper() for t in ("INT", "BOOLEAN")):
            if cleaned.upper() == "TRUE":
                return 1
            if cleaned.upper() == "FALSE":
                return 0
            try:
                return int(cleaned)
            except ValueError:
                pass
        return cleaned
    if (table, col) in {
        ("devices", "alert_offline"), ("devices", "is_online"), ("services", "is_up"), ("services", "is_auto_detected"),
        ("discovered_hosts", "is_online"), ("device_interfaces", "is_online"), ("agent_configs", "enable_temp"),
        ("agent_configs", "enable_patch_check"), ("agent_tokens", "is_active"),
    }:
        return 1
    if (table, col) == ("agent_configs", "interval"):
        return 30
    if (table, col) == ("agent_configs", "version"):
        return 1
    if any(t in info["type"].upper() for t in ("DATETIME", "TIMESTAMP")):
        return now_str
    if any(t in info["type"].upper() for t in ("INT", "BOOLEAN")):
        return 0
    return ""


def _old_clean_rows(cursor, table, rows, now_str):
    cursor.execute(f"PRAGMA table_info({table})")
    table_info = {col[1]: {"notnull": col[3], "default": col[4], "type": col[2]} for col in cursor.fetchall()}
    if not table_info:
        return []
    if table == "app_settings":
        rows = [r for r in rows if r.get("key") not in backup.PROTECTED_SETTING_KEYS]
        table_info.pop("id", None)
    valid_rows = []
    for row in rows:
        clean_row = {col: val for col, val in row.items() if col in table_info and not (val is None and table_info[col]["notnull"])}
        for col, info in table_info.items():
            if info["notnull"] and (col not in clean_row or clean_row[col] is None):
                clean_row[col] = _old_default(table, col, info, now_str)
        if table == "services" and not is_safe_url_template(clean_row.get("url_template") or ""):
            clean_row["url_template"] = ""
        valid_rows.append(clean_row)
    return valid_rows


# --- defaults --------------------------------------------------------------------------------

TABLE_COLS = [("devices", "alert_offline"), ("devices", "is_online"), ("services", "is_up"), ("agent_configs", "interval"),
              ("agent_configs", "version"), ("agent_tokens", "is_active"), ("devices", "name"), ("racks", "units")]
TYPES = ["INTEGER", "BOOLEAN", "VARCHAR(30)", "DATETIME", "TIMESTAMP", "FLOAT", "TEXT", "bigint", "SMALLINT"]
DEFAULTS = [None, "'1'", "0", "'TRUE'", "false", "CURRENT_TIMESTAMP", "now()", "'abc'", '"x"', " 7 ", "1.5", "''"]


def test_missing_column_defaults_match_for_every_combination():
    now = "2026-11-07 12:00:00"
    diffs = []
    for (table, col), typ, default in [(tc, t, d) for tc in TABLE_COLS for t in TYPES for d in DEFAULTS]:
        info = {"type": typ, "default": default, "notnull": 1}
        if backup._default_for_missing_col(table, col, info, now) != _old_default(table, col, info, now):
            diffs.append((table, col, typ, default))
    assert diffs == []


# --- row cleaning ----------------------------------------------------------------------------

SCHEMAS = {
    "services": "CREATE TABLE services (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, port INTEGER NOT NULL, "
                "url_template VARCHAR NOT NULL DEFAULT '', is_up BOOLEAN NOT NULL, color VARCHAR, "
                "last_checked DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "app_settings": "CREATE TABLE app_settings (id INTEGER PRIMARY KEY, key VARCHAR NOT NULL, value TEXT NOT NULL, "
                    "category VARCHAR NOT NULL DEFAULT 'general')",
    "devices": "CREATE TABLE devices (id INTEGER PRIMARY KEY, ip VARCHAR NOT NULL, alert_offline BOOLEAN NOT NULL, "
               "missed_scans INTEGER NOT NULL, first_seen DATETIME NOT NULL, notes TEXT)",
}


def _rows(rnd, table):
    pool = {
        "services": ["id", "name", "port", "url_template", "is_up", "color", "last_checked", "ghost_column"],
        "app_settings": ["id", "key", "value", "category", "extra"],
        "devices": ["id", "ip", "alert_offline", "missed_scans", "first_seen", "notes", "legacy_flag"],
    }[table]
    values = [None, 0, 1, "x", "https://{ip}", "javascript:alert(1)", "", "2026-01-01 00:00:00", 42]
    keys = list(backup.PROTECTED_SETTING_KEYS) + ["ui.theme", "dns.server"]
    rows = []
    for i in range(rnd.randint(0, 6)):
        row = {c: rnd.choice(values) for c in pool if rnd.random() < 0.7}
        if table == "app_settings" and rnd.random() < 0.8:
            row["key"] = rnd.choice(keys)
        if rnd.random() < 0.8:
            row["id"] = i + 1
        rows.append(row)
    return rows


@pytest.mark.parametrize("seed", range(150))
def test_row_cleaning_matches(seed, monkeypatch):
    rnd = random.Random(seed)
    now = datetime(2026, 11, 7, 12, 0)

    class FrozenNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.replace(tzinfo=tz)

    monkeypatch.setattr(backup, "datetime", FrozenNow)
    now_str = FrozenNow.now(backup.timezone.utc).isoformat().replace("T", " ")
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    for ddl in SCHEMAS.values():
        cursor.execute(ddl)
    def outcome(fn, *args):
        try:
            return fn(*args)
        except Exception as exc:  # a non-text link in a tampered backup fails the same way in both
            return type(exc)

    for table in (*SCHEMAS, "missing_table"):
        rows = _rows(rnd, table if table in SCHEMAS else "devices")
        assert outcome(backup._clean_rows, cursor, table, [dict(r) for r in rows]) == \
            outcome(_old_clean_rows, cursor, table, [dict(r) for r in rows], now_str)
    conn.close()
