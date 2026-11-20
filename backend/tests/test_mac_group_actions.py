"""AP 5a backend tests: confirmed target snapshots for MAC adoption, validation, rollback,
and backwards compatibility of legacy apply_to_shared / manual correction.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models.device import Device, DeviceHistory, DeviceMacObservation
from app.services import mac_observations

M1 = "02:00:00:00:00:01"
M2 = "02:00:00:00:00:02"
M3 = "02:00:00:00:00:03"


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _seed_conflict(db, *, ip: str, name: str, doc_mac: str = M1, obs_mac: str = M2, state: str = "open") -> Device:
    dev = Device(ip=ip, mac=doc_mac, display_name=name, is_online=True)
    db.add(dev)
    await db.flush()
    now = datetime.now(UTC)
    db.add(DeviceMacObservation(
        device_id=dev.id, observed_mac=obs_mac, source="relay", first_seen=now, last_seen=now, state=state,
    ))
    await db.commit()
    return dev


@pytest.mark.asyncio
async def test_confirmed_targets_never_expand_to_newly_added_devices_even_with_apply_to_shared(client, db, auth):
    c1 = await _seed_conflict(db, ip="192.168.120.1", name="c1")
    c2 = await _seed_conflict(db, ip="192.168.120.2", name="c2")
    # c3 joins the conflict group AFTER the user opened the dialog
    c3 = await _seed_conflict(db, ip="192.168.120.3", name="c3")

    res = await client.put(
        f"/api/devices/{c1.id}/mac",
        json={
            "mac": M2,
            "apply_to_shared": True,  # must be ignored when targets is provided
            "targets": [
                {"id": c1.id, "ip": c1.ip, "documented_mac": M1},
                {"id": c2.id, "ip": c2.ip, "documented_mac": M1},
            ],
        },
        headers=auth,
    )
    assert res.status_code == 200
    assert res.json() == {"changed_device_ids": [c1.id, c2.id], "skipped_device_ids": []}

    await db.refresh(c1)
    await db.refresh(c2)
    await db.refresh(c3)
    assert (c1.mac, c2.mac, c3.mac) == (M2, M2, M1)
    remaining = (await db.execute(select(DeviceMacObservation.device_id))).scalars().all()
    assert remaining == [c3.id]


@pytest.mark.asyncio
async def test_context_drift_resolved_or_deleted_targets_are_skipped_without_blocking_valid_ones(client, db, auth):
    ip_moved = await _seed_conflict(db, ip="192.168.120.10", name="ip-moved")
    mac_changed = await _seed_conflict(db, ip="192.168.120.11", name="mac-changed")
    obs_resolved = await _seed_conflict(db, ip="192.168.120.12", name="obs-resolved")
    deleted_dev = await _seed_conflict(db, ip="192.168.120.13", name="deleted")
    still_valid = await _seed_conflict(db, ip="192.168.120.14", name="still-valid")

    # Confirmed snapshot captured before concurrent drift
    snapshot = [
        {"id": deleted_dev.id, "ip": "192.168.120.13", "documented_mac": M1},
        {"id": ip_moved.id, "ip": "192.168.120.10", "documented_mac": M1},
        {"id": mac_changed.id, "ip": "192.168.120.11", "documented_mac": M1},
        {"id": obs_resolved.id, "ip": "192.168.120.12", "documented_mac": M1},
        {"id": still_valid.id, "ip": "192.168.120.14", "documented_mac": M1},
    ]

    # Drift happens between opening dialog and submitting
    ip_moved.ip = "192.168.120.99"
    mac_changed.mac = M3
    await mac_observations.clear_open_observations(db, obs_resolved.id)
    await db.delete(deleted_dev)
    await db.commit()

    # Even when the URL device_id itself was deleted, valid targets are applied and deleted_dev is skipped
    res = await client.put(
        f"/api/devices/{deleted_dev.id}/mac",
        json={"mac": M2, "targets": snapshot},
        headers=auth,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["changed_device_ids"] == [still_valid.id]
    assert body["skipped_device_ids"] == [deleted_dev.id, ip_moved.id, mac_changed.id, obs_resolved.id]

    await db.refresh(ip_moved)
    await db.refresh(mac_changed)
    await db.refresh(obs_resolved)
    await db.refresh(still_valid)
    assert (ip_moved.mac, mac_changed.mac, obs_resolved.mac, still_valid.mac) == (M1, M3, M1, M2)

    # Re-triggering the exact same request changes nothing and writes no duplicate history
    res2 = await client.put(
        f"/api/devices/{deleted_dev.id}/mac",
        json={"mac": M2, "targets": snapshot},
        headers=auth,
    )
    assert res2.status_code == 200
    assert res2.json()["changed_device_ids"] == []
    assert len(res2.json()["skipped_device_ids"]) == 5
    hist = (await db.execute(select(DeviceHistory).where(DeviceHistory.device_id == still_valid.id))).scalars().all()
    assert len(hist) == 1


@pytest.mark.asyncio
async def test_targets_validation_rejects_empty_duplicates_and_missing_url_id(client, db, auth):
    dev = await _seed_conflict(db, ip="192.168.120.20", name="srv")

    # targets=[] is rejected (422), NOT treated as "targets omitted"
    res_empty = await client.put(f"/api/devices/{dev.id}/mac", json={"mac": M2, "targets": []}, headers=auth)
    assert res_empty.status_code == 422

    # Duplicate device ids in targets are rejected (422)
    res_dup = await client.put(
        f"/api/devices/{dev.id}/mac",
        json={
            "mac": M2,
            "targets": [
                {"id": dev.id, "ip": dev.ip, "documented_mac": M1},
                {"id": dev.id, "ip": "192.168.120.99", "documented_mac": M1},
            ],
        },
        headers=auth,
    )
    assert res_dup.status_code == 422

    # URL device_id must be present in targets (422)
    res_mismatch = await client.put(
        f"/api/devices/{dev.id}/mac",
        json={"mac": M2, "targets": [{"id": dev.id + 1, "ip": dev.ip, "documented_mac": M1}]},
        headers=auth,
    )
    assert res_mismatch.status_code == 422

    await db.refresh(dev)
    assert dev.mac == M1


@pytest.mark.asyncio
async def test_technical_db_error_rolls_back_all_targets_and_is_not_masked_as_skipped(client, db, auth, monkeypatch):
    c1 = await _seed_conflict(db, ip="192.168.120.30", name="c1")
    c2 = await _seed_conflict(db, ip="192.168.120.31", name="c2")

    real_commit = db.commit
    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=OperationalError("COMMIT", None, Exception("disk I/O"))))

    with pytest.raises(OperationalError):
        await client.put(
            f"/api/devices/{c1.id}/mac",
            json={
                "mac": M2,
                "targets": [
                    {"id": c1.id, "ip": c1.ip, "documented_mac": M1},
                    {"id": c2.id, "ip": c2.ip, "documented_mac": M1},
                ],
            },
            headers=auth,
        )

    monkeypatch.setattr(db, "commit", real_commit)
    await db.refresh(c1)
    await db.refresh(c2)
    assert (c1.mac, c2.mac) == (M1, M1)
    obs = (await db.execute(select(DeviceMacObservation.device_id).order_by(DeviceMacObservation.device_id))).scalars().all()
    assert obs == [c1.id, c2.id]


@pytest.mark.asyncio
async def test_legacy_apply_to_shared_and_manual_correction_without_targets_remain_compatible(client, db, auth):
    c1 = await _seed_conflict(db, ip="192.168.120.40", name="c1")
    c2 = await _seed_conflict(db, ip="192.168.120.41", name="c2")
    manual_dev = Device(ip="192.168.120.42", mac=M1, display_name="manual", is_online=True)
    db.add(manual_dev)
    await db.commit()

    # Legacy apply_to_shared=True without targets still dynamically updates both
    res_legacy = await client.put(
        f"/api/devices/{c1.id}/mac", json={"mac": M2, "apply_to_shared": True}, headers=auth,
    )
    assert res_legacy.status_code == 200
    assert res_legacy.json() == {"changed_device_ids": [c1.id, c2.id], "skipped_device_ids": []}

    # Manual correction without targets works unchanged
    res_manual = await client.put(
        f"/api/devices/{manual_dev.id}/mac", json={"mac": M3}, headers=auth,
    )
    assert res_manual.status_code == 200
    assert res_manual.json() == {"changed_device_ids": [manual_dev.id], "skipped_device_ids": []}


@pytest.mark.asyncio
async def test_concurrent_context_change_in_second_wal_session_is_not_silently_overwritten(tmp_path):
    """Coordinated two-session WAL concurrency test on a temporary file database:
    Session 1 reads the confirmed context, Session 2 concurrently moves the device to a new IP
    and commits, then Session 1 runs adopt_confirmed_targets and commits.
    The atomic conditional UPDATE must detect the drift (skipped) and NEVER overwrite the moved device's MAC.
    """
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.database import Base

    db_file = tmp_path / "mac_race.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    try:
        tables = [t for t in Base.metadata.sorted_tables if t.schema is None]
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=tables)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        async with session_factory() as seed:
            dev = Device(ip="192.168.120.50", mac=M1, display_name="nas", is_online=True)
            seed.add(dev)
            await seed.flush()
            now = datetime.now(UTC)
            seed.add(DeviceMacObservation(
                device_id=dev.id, observed_mac=M2, source="relay", first_seen=now, last_seen=now, state="open",
            ))
            await seed.commit()
            dev_id = dev.id

        async with session_factory() as s1:
            # Session 1 reads the pre-drift context (starting its own connection/read state)
            pre = await s1.get(Device, dev_id)
            assert (pre.ip, pre.mac) == ("192.168.120.50", M1)

            # Session 2 concurrently changes the device's IP (and clears observations) and commits
            async with session_factory() as s2:
                d2 = await s2.get(Device, dev_id)
                d2.ip = "192.168.120.99"
                await mac_observations.clear_observations(s2, dev_id)
                await s2.commit()

            # Session 1 now attempts the confirmed adoption against the stale (ip, mac) snapshot
            changed, skipped = await mac_observations.adopt_confirmed_targets(
                s1, M2, [(dev_id, "192.168.120.50", M1)],
            )
            await s1.commit()
            assert changed == []
            assert skipped == [dev_id]

        # Independent verification session: moved device kept its documented MAC M1 and wrote no mac_changed history
        async with session_factory() as verify:
            final_dev = await verify.get(Device, dev_id)
            assert (final_dev.ip, final_dev.mac) == ("192.168.120.99", M1)
            hist = (await verify.execute(select(DeviceHistory).where(DeviceHistory.device_id == dev_id))).scalars().all()
            assert hist == []
    finally:
        await engine.dispose()
