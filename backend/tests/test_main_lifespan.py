"""Start and shutdown of the app (app/main.py lifespan and its steps)."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.main as main


# --- data directory -------------------------------------------------------------------------

def test_data_dir_is_created_and_checked(monkeypatch, tmp_path):
    target = tmp_path / "new" / "data"
    monkeypatch.setattr(main.settings, "data_dir", target)
    main._ensure_writable_data_dir()
    assert target.is_dir()
    assert not (target / ".write_test").exists()


def test_unwritable_data_dir_says_how_to_fix_it(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.config.process_ids", lambda: (1000, 100))

    def refuse(self, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "touch", refuse)
    with pytest.raises(RuntimeError) as exc:
        main._ensure_writable_data_dir()
    message = str(exc.value)
    assert "UID 1000 / GID 100" in message
    assert "chown -R 1000:100 ./data" in message
    assert "/mnt/user/appdata/gravitylan" in message


def test_other_data_dir_errors_are_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "data_dir", tmp_path)

    def broken(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "touch", broken)
    with pytest.raises(RuntimeError, match="Failed to initialize data directory .*disk full"):
        main._ensure_writable_data_dir()


# --- saved log level -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_saved_log_level_is_applied(monkeypatch, db):
    from app.models.setting import Setting

    db.add(Setting(key="system.log_level", value="WARNING"))
    await db.commit()

    @asynccontextmanager
    async def same_session():
        yield db

    applied = []
    monkeypatch.setattr("app.database.async_session", same_session)
    monkeypatch.setattr("app.services.log_streamer.apply_log_level", applied.append)

    await main._apply_saved_log_level()
    assert applied == ["WARNING"]


@pytest.mark.asyncio
async def test_saved_log_level_failure_keeps_the_default(monkeypatch):
    @asynccontextmanager
    async def broken_session():
        raise RuntimeError("db locked")
        yield

    monkeypatch.setattr("app.database.async_session", broken_session)
    await main._apply_saved_log_level()  # no exception


# --- whole lifespan ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_runs_the_steps_in_order_and_cleans_up(monkeypatch):
    calls = []

    def step(name, result=None):
        async def run(*_a, **_k):
            calls.append(name)
            return result
        return run

    monkeypatch.setattr(main, "_configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(main, "_apply_saved_log_level", step("log_level"))
    monkeypatch.setattr(main, "_ensure_writable_data_dir", lambda: calls.append("data_dir"))
    monkeypatch.setattr(main, "init_db", step("init_db"))
    monkeypatch.setattr(main, "_run_startup_migrations", step("migrations"))
    monkeypatch.setattr(main, "_ensure_default_rack", step("rack"))
    fake_scheduler = SimpleNamespace(start=step("scheduler.start"), stop=step("scheduler.stop"))
    monkeypatch.setattr("app.scanner.scheduler.scheduler", fake_scheduler)

    app = SimpleNamespace(state=SimpleNamespace())
    async with main.lifespan(app):
        calls.append("running")
        task = asyncio.create_task(asyncio.sleep(60))
        app.state.background_tasks.add(task)

    assert calls == ["logging", "log_level", "data_dir", "init_db", "migrations", "scheduler.start", "rack",
                     "running", "scheduler.stop"]
    assert task.cancelled()


@pytest.mark.asyncio
async def test_startup_migrations_run_in_order_and_survive_a_failed_telemetry_move(monkeypatch):
    calls = []

    @asynccontextmanager
    async def session():
        yield "db"

    async def failing_move(_db):
        calls.append("telemetry")
        raise RuntimeError("locked")

    async def record(name, *_a):
        calls.append(name)

    monkeypatch.setattr("app.database.async_session", session)
    monkeypatch.setattr("app.database.migrations.run_migrations", lambda db: record("schema"))
    monkeypatch.setattr("app.services.telemetry_store.migrate_legacy_telemetry", failing_move)
    monkeypatch.setattr(main, "_migrate_legacy_scan_subnets", lambda: record("scan_subnets"))
    monkeypatch.setattr("app.api.network.cleanup_invalid_subnets", lambda: record("cleanup"))

    await main._run_startup_migrations()
    assert calls == ["schema", "telemetry", "scan_subnets", "cleanup"]


@pytest.mark.asyncio
async def test_startup_migrations_vacuum_after_moving_telemetry(monkeypatch):
    vacuumed = []

    @asynccontextmanager
    async def session():
        yield "db"

    async def nothing(*_a):
        return None

    async def moved(_db):
        return 3

    async def vacuum(engine):
        vacuumed.append(engine)

    monkeypatch.setattr("app.database.async_session", session)
    monkeypatch.setattr("app.database.migrations.run_migrations", nothing)
    monkeypatch.setattr("app.services.telemetry_store.migrate_legacy_telemetry", moved)
    monkeypatch.setattr("app.services.telemetry_store.vacuum_inventory", vacuum)
    monkeypatch.setattr(main, "_migrate_legacy_scan_subnets", nothing)
    monkeypatch.setattr("app.api.network.cleanup_invalid_subnets", nothing)

    await main._run_startup_migrations()
    assert len(vacuumed) == 1
