import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from sqlalchemy import UniqueConstraint, inspect, select, or_, text, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Define missing columns as (table, column, type) on module level for testability and maintainability
MIGRATIONS = [
    ("devices", "topology_x", "INTEGER"),
    ("devices", "topology_y", "INTEGER"),
    ("devices", "max_ports",  "INTEGER DEFAULT 24"),
    ("devices", "topology_config", "TEXT"),
    ("devices", "parent_id",  "INTEGER"),
    ("devices", "rack_id",    "INTEGER"),
    ("devices", "rack_unit",  "INTEGER"),
    ("devices", "rack_height","INTEGER DEFAULT 1"),
    ("devices", "is_wlan",    "BOOLEAN DEFAULT FALSE"),
    ("devices", "is_ap",      "BOOLEAN DEFAULT FALSE"),
    ("devices", "is_host",    "BOOLEAN DEFAULT FALSE"),
    ("devices", "ip_placeholder", "BOOLEAN DEFAULT FALSE"),
    ("devices", "missed_scans", "INTEGER DEFAULT 0"),
    ("devices", "dns_names", "TEXT"),
    ("devices", "hostname_source", "VARCHAR(10)"),
    ("topology_links", "source_handle", "TEXT"),
    ("topology_links", "target_handle", "TEXT"),
    ("topology_links", "role", "VARCHAR(20) DEFAULT 'primary'"),
    ("rack_ports", "side", "VARCHAR(10) DEFAULT 'front'"),
    ("discovered_hosts", "is_reserved", "BOOLEAN DEFAULT FALSE"),
    ("discovered_hosts", "ip_placeholder", "BOOLEAN DEFAULT FALSE"),
    ("discovered_hosts", "old_ip", "VARCHAR(45)"),
    ("discovered_hosts", "ip_changed_at", "DATETIME"),
    ("discovered_hosts", "ports", "TEXT"),
    ("agent_tokens", "pending_token", "VARCHAR(64)"),
    ("agent_tokens", "pending_at", "DATETIME"),
    ("agent_tokens", "os_pretty", "VARCHAR(255)"),
    ("agent_tokens", "os_name", "VARCHAR(100)"),
    ("agent_tokens", "os_version", "VARCHAR(100)"),
    ("agent_tokens", "os_codename", "VARCHAR(100)"),
    ("agent_tokens", "os_arch", "VARCHAR(50)"),
    ("agent_tokens", "os_kernel", "VARCHAR(100)"),
    ("api_tokens", "scopes", "TEXT"),
    ("device_metrics", "patch_available", "INTEGER DEFAULT 0"),
    ("device_metrics", "patch_security", "INTEGER DEFAULT 0"),
    ("device_metrics", "patch_manager", "VARCHAR(20)"),
    ("device_metrics", "reboot_required", "BOOLEAN DEFAULT FALSE"),
    ("device_metrics", "major_upgrade_available", "VARCHAR(100)"),
    ("agent_configs", "enable_patch_check", "BOOLEAN DEFAULT TRUE"),
    ("agent_configs", "enable_scanner_relay", "BOOLEAN DEFAULT FALSE"),
    # Multi-VLAN gateways; the device_interfaces table itself comes from init_db's create_all
    ("subnets", "gateway_ip", "VARCHAR(45)"),
    ("subnets", "vlan_id", "INTEGER"),
    # Service health telemetry columns
    ("services", "latency_ms", "FLOAT"),
    ("services", "ssl_expiry_days", "INTEGER"),
    ("services", "ssl_checked_at", "DATETIME"),
    ("services", "ignore_ssl", "BOOLEAN DEFAULT FALSE"),
    ("devices", "alert_offline", "BOOLEAN DEFAULT TRUE"),
    ("device_history", "read", "BOOLEAN DEFAULT FALSE"),
    ("webhook_subscriptions", "name", "VARCHAR(100)"),
    ("webhook_subscriptions", "service_type", "VARCHAR(20) DEFAULT 'webhook'"),
    ("webhook_subscriptions", "encrypted_token", "TEXT"),
]


def _fuzzy_match(n1: str, n2: str) -> bool:
    if not n1 or not n2: return False
    s1 = n1.lower().replace("-", "").replace("_", "").replace(" ", "")
    s2 = n2.lower().replace("-", "").replace("_", "").replace(" ", "")
    return s1 in s2 or s2 in s1


def _build_docker_container_map() -> dict:
    """Map running local Docker container names (lowercase) to their first IP."""
    from app.services.docker_service import docker_service

    docker_container_map = {}
    if not docker_service.is_available():
        return docker_container_map
    try:
        for c in docker_service.get_local_containers():
            c_name = c.get("name")
            c_ips = c.get("ips", [])
            if c_name and c_ips and c.get("status") == "running":
                docker_container_map[c_name.lower()] = c_ips[0]
        if docker_container_map:
            logger.info(f"Migration: Docker socket active. Found {len(docker_container_map)} running containers: {list(docker_container_map.keys())}")
    except Exception as e:
        logger.warning(f"Migration: Could not fetch local docker containers: {e}")
    return docker_container_map


def _is_free(candidate: str, used_ips: set, old_corrupted_ip: str) -> bool:
    """A candidate IP is usable if unused or if it is the record's own current IP."""
    return candidate not in used_ips or candidate == old_corrupted_ip


def _next_free_placeholder_ip(used_ips: set) -> str:
    counter = 0
    while True:
        candidate = f"0.0.0.{counter}"
        if candidate not in used_ips:
            return candidate
        counter += 1


def _ip_from_docker_fuzzy(dev_name: str, docker_map: dict, used_ips: set, old_corrupted_ip: str):
    """1a. Fuzzy match against running Docker container names."""
    for c_name, c_ip in docker_map.items():
        if _fuzzy_match(dev_name, c_name) and _is_free(c_ip, used_ips, old_corrupted_ip):
            return c_ip
    return None


def _restorable_old_ip(dev, used_ips: set):
    """1b. Restore old_ip if it is a valid, free IP."""
    from app.scanner.hostname import is_ip_like

    old_ip = dev.old_ip
    if not old_ip or old_ip.startswith("offline-") or not is_ip_like(old_ip):
        return None
    if old_ip in used_ips:
        return None
    return old_ip


def _resolve_device_repair(dev, used_ips: set, docker_map: dict):
    """Find a safe replacement for a corrupted Device.

    Returns (safe_ip, is_online, ip_placeholder) or None when only the
    unique-placeholder fallback applies. Only installation-independent sources
    are used (live Docker containers, the device's own old_ip): no hardcoded
    IPs or names, which would overwrite data on other people's networks.
    """
    dev_name = (dev.display_name or dev.hostname or "").lower()

    docker_ip = _ip_from_docker_fuzzy(dev_name, docker_map, used_ips, dev.ip)
    if docker_ip:
        return docker_ip, True, False

    old_ip = _restorable_old_ip(dev, used_ips)
    if old_ip:
        return old_ip, False, True
    return None


def _apply_repair(record, safe_ip: str, used_ips: set, old_corrupted_ip: str):
    """Swap the corrupted IP for the safe one and keep the used-set consistent."""
    used_ips.discard(old_corrupted_ip)
    used_ips.add(safe_ip)
    record.ip = safe_ip


async def _repair_corrupted_devices(db: AsyncSession, docker_map: dict):
    from app.models.device import Device

    res_devs = await db.execute(select(Device).where(or_(Device.ip.like("offline-%"), Device.ip_placeholder == True)))
    corrupted_devs = res_devs.scalars().all()
    if not corrupted_devs:
        return

    logger.info(f"Migration: Cleaning {len(corrupted_devs)} corrupted/placeholder Device records...")
    res_all_ips = await db.execute(select(Device.ip))
    used_ips = set(res_all_ips.scalars().all())

    for dev in corrupted_devs:
        old_corrupted_ip = dev.ip
        repair = _resolve_device_repair(dev, used_ips, docker_map)
        if repair:
            safe_ip, dev.is_online, dev.ip_placeholder = repair
        else:
            safe_ip = _next_free_placeholder_ip(used_ips)
            dev.is_online = False
            dev.ip_placeholder = True

        _apply_repair(dev, safe_ip, used_ips, old_corrupted_ip)
        logger.info(f"Migration: Repaired Device id={dev.id} ({dev.display_name}) IP to {dev.ip} (online={dev.is_online})")


async def _repair_corrupted_discovered_hosts(db: AsyncSession, docker_map: dict):
    from app.models.device import DiscoveredHost

    res_disc = await db.execute(select(DiscoveredHost).where(or_(DiscoveredHost.ip.like("offline-%"), DiscoveredHost.ip_placeholder == True)))
    corrupted_disc = res_disc.scalars().all()
    if not corrupted_disc:
        return

    logger.info(f"Migration: Cleaning {len(corrupted_disc)} corrupted/placeholder DiscoveredHost records...")
    res_all_disc_ips = await db.execute(select(DiscoveredHost.ip))
    used_disc_ips = set(res_all_disc_ips.scalars().all())

    for disc in corrupted_disc:
        old_corrupted_ip = disc.ip
        disc_name = (disc.custom_name or disc.hostname or "").lower()

        docker_ip = docker_map.get(disc_name) if disc_name else None
        if docker_ip and _is_free(docker_ip, used_disc_ips, old_corrupted_ip):
            safe_ip = docker_ip
            disc.is_online = True
            disc.ip_placeholder = False
        else:
            safe_ip = _next_free_placeholder_ip(used_disc_ips)
            disc.is_online = False
            disc.ip_placeholder = True

        _apply_repair(disc, safe_ip, used_disc_ips, old_corrupted_ip)
        logger.info(f"Migration: Repaired DiscoveredHost id={disc.id} IP to {disc.ip}")


async def _clean_corrupted_ip_placeholders(db: AsyncSession):
    """Repair existing production database records corrupted with 'offline-<MAC>' or placeholder IPs."""
    docker_map = _build_docker_container_map()
    await _repair_corrupted_devices(db, docker_map)
    await _repair_corrupted_discovered_hosts(db, docker_map)


def _migrations_by_table() -> dict:
    migrations_by_table = defaultdict(list)
    for table, column, col_type in MIGRATIONS:
        migrations_by_table[table].append((column, col_type))
    return migrations_by_table


async def _get_existing_columns(raw_conn, table: str):
    """Column names of a table, or None if the table does not exist yet."""
    def check_table_and_columns(sync_conn):
        inspector = inspect(sync_conn)
        if not inspector.has_table(table):
            return None
        return {col["name"] for col in inspector.get_columns(table)}

    return await raw_conn.run_sync(check_table_and_columns)


async def _apply_table_migrations(raw_conn, table: str, cols: list):
    existing_columns = await _get_existing_columns(raw_conn, table)
    if existing_columns is None:
        logger.info(f"Migration: Table '{table}' does not exist yet. It will be created by init_db. Skipping migrations for it.")
        return

    for column, col_type in cols:
        if column not in existing_columns:
            logger.info(f"Migration: Adding column '{column}' to '{table}'...")
            await raw_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info(f"Migration: Column '{column}' added successfully to '{table}'.")


def _column_names(constraint) -> tuple[str, ...]:
    return tuple(c.name for c in constraint.columns)


def _name_then_columns(constraint) -> tuple:
    """Sort key: Table.constraints and Table.indexes are unordered sets."""
    return constraint.name or "", _column_names(constraint)


def _declared_unique_sets(model) -> list[tuple[str, ...]]:
    """Unique column sets of a table in a fixed order: constraints, unique columns, unique indexes."""
    constraints = [con for con in model.constraints if isinstance(con, UniqueConstraint)]
    indexes = [idx for idx in model.indexes if idx.unique]
    return [
        *[_column_names(con) for con in sorted(constraints, key=_name_then_columns)],
        *[(c.name,) for c in sorted(model.columns, key=lambda c: c.name) if c.unique],
        *[_column_names(idx) for idx in sorted(indexes, key=_name_then_columns)],
    ]


def unique_column_sets(table: str) -> list[tuple[str, ...]]:
    """The column sets a table keeps unique (besides its id), read from the models."""
    import app.models  # noqa: F401 - registers the models
    import app.models.rack_cabling  # noqa: F401
    from app.database import Base

    model = Base.metadata.tables.get(table)
    if model is None:
        return []
    return [s for s in dict.fromkeys(_declared_unique_sets(model)) if s and s != ("id",)]


def _inventory_tables() -> list[str]:
    import app.models  # noqa: F401 - registers the models
    import app.models.rack_cabling  # noqa: F401
    from app.database import Base

    return [t.name for t in Base.metadata.sorted_tables if t.schema is None]


def _live_unique_sets(sync_conn, table: str) -> tuple[set[str], list[frozenset[str]]] | None:
    """Columns of a table and the column sets the live database already keeps unique, or None if it is missing."""
    inspector = inspect(sync_conn)
    if not inspector.has_table(table):
        return None
    columns = {col["name"] for col in inspector.get_columns(table)}
    unique = [frozenset(c["column_names"]) for c in inspector.get_unique_constraints(table)]
    unique += [frozenset(i["column_names"]) for i in inspector.get_indexes(table) if i.get("unique")]
    return columns, unique


def _missing_unique_sets(columns: set[str], live: list[frozenset[str]], table: str) -> list[tuple[str, ...]]:
    """Model unique sets the live table lacks; sets naming a column the table does not have are skipped."""
    if "id" not in columns:
        return []
    return [
        cols for cols in unique_column_sets(table)
        if frozenset(cols) not in live and set(cols) <= columns
    ]


# Next to the database: the copy a start takes before it deletes rows
CLEANUP_COPY_GLOB = "*.pre-cleanup-*.db"


async def _copy_database_once(db: AsyncSession) -> None:
    """Copy the database next to itself before a migration deletes rows, once per start.

    Deleting a duplicate can take agent tokens, services or rack ports with it, and nobody chose that.
    A failed copy raises, so the caller deletes nothing and the next start tries again.
    """
    if db.info.get("cleanup_copy_taken"):
        return
    await db.commit()  # VACUUM cannot run inside a transaction
    url = (await db.connection()).engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    source = Path(url.database)
    target = source.with_name(f"{source.stem}.pre-cleanup-{datetime.now():%Y%m%d-%H%M%S}.db")
    await db.execute(text("VACUUM INTO :target"), {"target": str(target)})
    await db.commit()
    db.info["cleanup_copy_taken"] = True
    logger.warning(f"Migration: Duplicates found, database copied to {target.name} before removing them")


async def _deduplicate_and_index(db: AsyncSession, table: str, cols: tuple[str, ...]) -> int:
    """Keep the newest row (highest id) per key, then add the unique index. Returns the rows removed.

    Rows with an empty key column are never duplicates: SQL treats NULL as distinct, as the index does.
    Foreign keys are on, so ON DELETE CASCADE / SET NULL clean up what pointed at a removed row.
    """
    quoted = ", ".join(f'"{c}"' for c in cols)
    not_null = " AND ".join(f'"{c}" IS NOT NULL' for c in cols)
    has_duplicates = await db.execute(text(
        f'SELECT 1 FROM "{table}" WHERE {not_null} GROUP BY {quoted} HAVING COUNT(*) > 1 LIMIT 1'
    ))
    if has_duplicates.first():
        await _copy_database_once(db)
    result = await db.execute(text(
        f'DELETE FROM "{table}" WHERE {not_null} AND id NOT IN '
        f'(SELECT MAX(id) FROM "{table}" WHERE {not_null} GROUP BY {quoted})'
    ))
    index_name = f"uix_{table}_{'_'.join(cols)}"
    await db.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ({quoted})'))
    return result.rowcount or 0


async def _run_step(db: AsyncSession, what: str, step, *args) -> None:
    """Run one step on its own: whatever goes wrong is rolled back and logged, and the start goes on.

    Catches everything on purpose. A step can also fail outside the database (a full disk while copying
    raises OSError), and no single repair is worth a server that does not start. The next start tries again.
    """
    try:
        await step(db, *args)
    except Exception as e:
        await db.rollback()
        logger.error(f"Migration error while {what}: {e}")


async def _add_unique_index(db: AsyncSession, table: str, cols: tuple[str, ...]) -> None:
    removed = await _deduplicate_and_index(db, table, cols)
    await db.commit()
    logger.info(f"Migration: Unique index on {table}({', '.join(cols)}) added, {removed} duplicate row(s) removed")


async def _add_missing_unique_indexes(db: AsyncSession) -> None:
    """Give old databases the unique keys of the models.

    create_all never adds a constraint to an existing table, so a database from before a constraint
    existed can hold duplicates (e.g. the same orbit link twice) and keeps accepting new ones.
    Each table runs in its own transaction; a failure leaves that table as it was.
    """
    for table in _inventory_tables():
        conn = await db.connection()
        live = await conn.run_sync(_live_unique_sets, table)
        if live is None:
            continue
        for cols in _missing_unique_sets(*live, table):
            await _run_step(db, f"adding unique index on {table}({', '.join(cols)})", _add_unique_index, table, cols)


async def _add_missing_columns(db: AsyncSession) -> None:
    """Add the columns of MIGRATIONS that an older database lacks.

    A failing table is only logged: all tables share one transaction, so a rollback would undo the others.
    """
    raw_conn = await db.connection()

    for table, cols in _migrations_by_table().items():
        try:
            await _apply_table_migrations(raw_conn, table, cols)
        except Exception as e:
            logger.error(f"Migration error on table '{table}': {e}")


def _repair_steps() -> list[tuple]:
    """What runs after the columns, in this order, with the words the error log uses for it."""
    from app.services.agent_tokens import normalize_agent_tokens

    return [
        # Tag stored agent token hashes (sha256:) and hash leftover plaintext tokens
        (normalize_agent_tokens, "upgrading agent tokens"),
        (_hash_master_token, "hashing the master token"),
        (_clear_unsafe_service_links, "clearing unsafe service links"),
        (_retire_phone_system_items, "retiring phone system rack items"),
        (_add_missing_unique_indexes, "adding unique indexes"),
        (_drop_outbox_token_copies, "removing token copies from the notification outbox"),
        (_deduplicate_generic_port_services, "deduplicating generic port services"),
        (_repair_infra_alert_offline, "repairing infrastructure alert_offline flags"),
    ]


async def run_migrations(db: AsyncSession):
    """Run schema migrations for SQLite or any alternative database.

    This handles adding missing columns to existing tables without breaking
    compatibility for users with older database versions. Uses a dialect-agnostic
    SQLAlchemy Inspector approach.
    """
    await _add_missing_columns(db)

    await _clean_corrupted_ip_placeholders(db)
    await db.commit()

    for step, what in _repair_steps():
        await _run_step(db, what, step)

    logger.info("Schema migration complete.")


async def _hash_master_token(db: AsyncSession) -> None:
    """Replace a plaintext master token with its tagged SHA-256; a stored hash stays as it is."""
    from app.models.setting import Setting
    from app.services.auth_service import MASTER_TOKEN_PREFIX, hash_master_token

    row = (await db.execute(select(Setting).where(Setting.key == "api.master_token"))).scalar_one_or_none()
    if row is None or not row.value or row.value.startswith(MASTER_TOKEN_PREFIX):
        return
    row.value = hash_master_token(row.value)
    await db.commit()
    logger.info("Migration: Master token is now stored as a hash")


async def _drop_outbox_token_copies(db: AsyncSession):
    """rc.4 to rc.6 copied each subscription's token into every outbox row; it stays on the subscription now."""
    def has_column(sync_conn) -> bool:
        inspector = inspect(sync_conn)
        return inspector.has_table("notification_outbox") and any(
            col["name"] == "encrypted_token" for col in inspector.get_columns("notification_outbox")
        )

    conn = await db.connection()
    if await conn.run_sync(has_column):
        await db.execute(text('ALTER TABLE "notification_outbox" DROP COLUMN "encrypted_token"'))
        await db.commit()
        logger.info("Migration: Removed token copies from the notification outbox")


async def _deduplicate_generic_port_services(db: AsyncSession):
    """Remove duplicate Service rows on the same (device_id, port, name) created by classifier generic_web_ports."""
    has_duplicates = await db.execute(text(
        'SELECT 1 FROM "services" GROUP BY "device_id", "port", "name" HAVING COUNT(*) > 1 LIMIT 1'
    ))
    if not has_duplicates.first():
        return
    await _copy_database_once(db)
    res = await db.execute(text(
        'DELETE FROM "services" WHERE id NOT IN '
        '(SELECT MIN(id) FROM "services" GROUP BY "device_id", "port", "name")'
    ))
    if res.rowcount:
        logger.info(f"Migration: Removed {res.rowcount} duplicate (device_id, port, name) service row(s)")
    await db.commit()


_CLIENT_DEVICE_TYPES = ("client", "desktop", "tv", "phone", "printer")


def _is_explicit_client(dev) -> bool:
    """Whether its type or name marks a device as a client, which may be switched off without an alert."""
    from app.scanner.classifier import is_client_hostname

    name = dev.hostname or dev.display_name or ""
    return (
        (dev.device_type or "").lower() in _CLIENT_DEVICE_TYPES
        or is_client_hostname(name)
        or "tv" in name.lower()
        or "pc" in name.lower()
    )


def _reenable_infra_alerts(devices) -> int:
    """Turn alert_offline back on for agents and everything that is no client. Returns how many."""
    repaired = 0
    for dev in devices:
        if dev.has_agent or not _is_explicit_client(dev):
            dev.alert_offline = True
            repaired += 1
    return repaired


async def _repair_infra_alert_offline(db: AsyncSession):
    """Repair what restoring an old backup left behind: alert_offline=False on every device at once.

    Only then. Devices that differ mean someone chose per device in the editor, and that choice stays.
    Needs no marker when there is nothing to repair: the check finds the same again on every start.
    """
    from app.models.device import Device
    from app.models.setting import Setting

    marker_key = "migration.rc4_infra_alert_offline_repaired"
    existing = (await db.execute(select(Setting).where(Setting.key == marker_key))).scalar_one_or_none()
    if existing is not None:
        return

    devices = (await db.execute(select(Device))).scalars().all()
    if not devices or any(dev.alert_offline for dev in devices):
        return

    repaired = _reenable_infra_alerts(devices)
    if repaired:
        db.add(Setting(key=marker_key, value="true", category="system"))
        await db.commit()
        logger.info(f"Migration: Re-enabled 24/7 alert_offline monitoring on {repaired} infrastructure/agent device(s)")


async def _retire_phone_system_items(db: AsyncSession):
    """Rack items of the retired kind phone_system become "other": a phone system has an IP and is a network device."""
    from app.models.rack_cabling import RackItem
    result = await db.execute(update(RackItem).where(RackItem.kind == "phone_system").values(kind="other"))
    if result.rowcount:
        logger.info(f"Retired {result.rowcount} phone system rack item(s) to 'other'")
    await db.commit()


async def _clear_unsafe_service_links(db: AsyncSession):
    """Empty url_template values with a scheme outside the allow-list, e.g. javascript: (#42)."""
    from app.models.device import Service
    from app.schemas.device import is_safe_url_template

    result = await db.execute(select(Service).where(Service.url_template != ""))
    cleared = 0
    for service in result.scalars():
        if not is_safe_url_template(service.url_template):
            logger.warning(f"Migration: Clearing unsafe link of service id={service.id} ({service.name!r})")
            service.url_template = ""
            cleared += 1
    if cleared:
        await db.commit()
