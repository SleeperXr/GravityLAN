import logging
from sqlalchemy import inspect
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
    ("topology_links", "source_handle", "TEXT"),
    ("topology_links", "target_handle", "TEXT"),
    ("discovered_hosts", "is_reserved", "BOOLEAN DEFAULT FALSE"),
    ("discovered_hosts", "ip_placeholder", "BOOLEAN DEFAULT FALSE"),
    ("discovered_hosts", "old_ip", "VARCHAR(45)"),
    ("discovered_hosts", "ip_changed_at", "DATETIME"),
    ("discovered_hosts", "ports", "TEXT"),
    ("agent_tokens", "pending_token", "VARCHAR(64)"),
    ("agent_tokens", "pending_at", "DATETIME"),
    ("api_tokens", "scopes", "TEXT"),
    ("device_metrics", "patch_available", "INTEGER DEFAULT 0"),
    ("device_metrics", "patch_security", "INTEGER DEFAULT 0"),
    ("device_metrics", "patch_manager", "VARCHAR(20)"),
    ("device_metrics", "reboot_required", "BOOLEAN DEFAULT FALSE"),
    ("device_metrics", "major_upgrade_available", "VARCHAR(100)"),
    ("agent_configs", "enable_patch_check", "BOOLEAN DEFAULT TRUE"),
]

async def _clean_corrupted_ip_placeholders(db: AsyncSession):
    """Repair existing production database records corrupted with 'offline-<MAC>' or placeholder IPs."""
    from sqlalchemy import select, or_
    from app.models.device import Device, DiscoveredHost
    from app.scanner.hostname import is_ip_like
    from app.services.docker_service import docker_service

    # Try mapping running Docker containers by container name
    docker_container_map = {}
    if docker_service.is_available():
        try:
            local_containers = docker_service.get_local_containers()
            for c in local_containers:
                c_name = c.get("name")
                c_ips = c.get("ips", [])
                c_status = c.get("status")
                if c_name and c_ips and c_status == "running":
                    docker_container_map[c_name.lower()] = c_ips[0]
            if docker_container_map:
                logger.info(f"Migration: Docker socket active. Found {len(docker_container_map)} running containers: {list(docker_container_map.keys())}")
        except Exception as e:
            logger.warning(f"Migration: Could not fetch local docker containers: {e}")

    KNOWN_CONTAINER_IPS = {
        27: "192.168.100.241", # NPM / NGINX Proxy Manager
        30: "192.168.100.253", # Lancache
        35: "192.168.100.240", # netboot
        36: "192.168.100.230", # paperless-ngx
        37: "192.168.100.18",  # Redis
        38: "192.168.100.19",  # postgresql17
        39: "192.168.100.231", # Nextcloud
    }

    RECONCILIATION_KEYWORD_MAP = {
        "unraid": "192.168.100.252",
        "lancache": "192.168.100.253",
        "termix": "192.168.100.246",
        "nextcloud": "192.168.100.231",
        "redis": "192.168.100.18",
        "netboot": "192.168.100.240",
        "postgresql": "192.168.100.19",
        "paperless": "192.168.100.230",
        "nginx": "192.168.100.241",
        "npm": "192.168.100.241",
    }

    def _fuzzy_match(n1: str, n2: str) -> bool:
        if not n1 or not n2: return False
        s1 = n1.lower().replace("-", "").replace("_", "").replace(" ", "")
        s2 = n2.lower().replace("-", "").replace("_", "").replace(" ", "")
        return s1 in s2 or s2 in s1

    # 1. Clean Devices
    res_devs = await db.execute(select(Device).where(or_(Device.ip.like("offline-%"), Device.ip_placeholder == True)))
    corrupted_devs = res_devs.scalars().all()
    if corrupted_devs:
        logger.info(f"Migration: Cleaning {len(corrupted_devs)} corrupted/placeholder Device records...")
        res_all_ips = await db.execute(select(Device.ip))
        used_ips = set(res_all_ips.scalars().all())

        for dev in corrupted_devs:
            old_corrupted_ip = dev.ip
            safe_ip = None
            dev_name = (dev.display_name or dev.hostname or "").lower()
            
            # 1a. Try explicit ID mapping first
            if dev.id in KNOWN_CONTAINER_IPS:
                target_ip = KNOWN_CONTAINER_IPS[dev.id]
                if target_ip not in used_ips or target_ip == old_corrupted_ip:
                    safe_ip = target_ip
                    dev.is_online = True
                    dev.ip_placeholder = False

            # 1b. Try keyword reconciliation map
            if not safe_ip and dev_name:
                for kw, kw_ip in RECONCILIATION_KEYWORD_MAP.items():
                    if kw in dev_name:
                        if kw_ip not in used_ips or kw_ip == old_corrupted_ip:
                            safe_ip = kw_ip
                            dev.is_online = True
                            dev.ip_placeholder = False
                            break

            # 1c. Try matching running Docker container by name (fuzzy)
            if not safe_ip:
                for c_name, c_ip in docker_container_map.items():
                    if _fuzzy_match(dev_name, c_name):
                        if c_ip not in used_ips or c_ip == old_corrupted_ip:
                            safe_ip = c_ip
                            dev.is_online = True
                            dev.ip_placeholder = False
                            break

            # 1c. Try restoring old_ip if valid and free
            if not safe_ip and dev.old_ip and not dev.old_ip.startswith("offline-") and is_ip_like(dev.old_ip):
                if dev.old_ip not in used_ips:
                    safe_ip = dev.old_ip
                    dev.is_online = False
                    dev.ip_placeholder = True

            # 1d. Fallback to unique 0.0.0.x IP
            if not safe_ip:
                dev.is_online = False
                dev.ip_placeholder = True
                counter = 0
                while True:
                    candidate = f"0.0.0.{counter}"
                    if candidate not in used_ips:
                        safe_ip = candidate
                        break
                    counter += 1

            if old_corrupted_ip in used_ips:
                used_ips.remove(old_corrupted_ip)
            used_ips.add(safe_ip)
            dev.ip = safe_ip
            logger.info(f"Migration: Repaired Device id={dev.id} ({dev.display_name}) IP to {dev.ip} (online={dev.is_online})")

    # 2. Clean DiscoveredHosts
    res_disc = await db.execute(select(DiscoveredHost).where(or_(DiscoveredHost.ip.like("offline-%"), DiscoveredHost.ip_placeholder == True)))
    corrupted_disc = res_disc.scalars().all()
    if corrupted_disc:
        logger.info(f"Migration: Cleaning {len(corrupted_disc)} corrupted/placeholder DiscoveredHost records...")
        res_all_disc_ips = await db.execute(select(DiscoveredHost.ip))
        used_disc_ips = set(res_all_disc_ips.scalars().all())

        for disc in corrupted_disc:
            old_corrupted_ip = disc.ip
            safe_ip = None
            disc_name = (disc.custom_name or disc.hostname or "").lower()
            
            if disc_name and disc_name in docker_container_map:
                docker_ip = docker_container_map[disc_name]
                if docker_ip not in used_disc_ips or docker_ip == old_corrupted_ip:
                    safe_ip = docker_ip
                    disc.is_online = True
                    disc.ip_placeholder = False

            if not safe_ip:
                disc.is_online = False
                disc.ip_placeholder = True
                counter = 0
                while True:
                    candidate = f"0.0.0.{counter}"
                    if candidate not in used_disc_ips:
                        safe_ip = candidate
                        break
                    counter += 1

            if old_corrupted_ip in used_disc_ips:
                used_disc_ips.remove(old_corrupted_ip)
            used_disc_ips.add(safe_ip)
            disc.ip = safe_ip
            logger.info(f"Migration: Repaired DiscoveredHost id={disc.id} IP to {disc.ip}")

async def run_migrations(db: AsyncSession):
    """Run schema migrations for SQLite or any alternative database.
    
    This handles adding missing columns to existing tables without breaking 
    compatibility for users with older database versions. Uses a dialect-agnostic
    SQLAlchemy Inspector approach.
    """
    raw_conn = await db.connection()
    
    # Group migrations by table to run inspection only once per table
    from collections import defaultdict
    migrations_by_table = defaultdict(list)
    for table, column, col_type in MIGRATIONS:
        migrations_by_table[table].append((column, col_type))
        
    for table, cols in migrations_by_table.items():
        try:
            # Dialect-agnostic column inspection using SQLAlchemy run_sync
            def check_table_and_columns(sync_conn):
                inspector = inspect(sync_conn)
                if not inspector.has_table(table):
                    return None
                return {col["name"] for col in inspector.get_columns(table)}

            table_info = await raw_conn.run_sync(check_table_and_columns)
            
            if table_info is None:
                logger.info(f"Migration: Table '{table}' does not exist yet. It will be created by init_db. Skipping migrations for it.")
                continue

            existing_columns = table_info
            
            for column, col_type in cols:
                if column not in existing_columns:
                    logger.info(f"Migration: Adding column '{column}' to '{table}'...")
                    await raw_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    logger.info(f"Migration: Column '{column}' added successfully to '{table}'.")
        except Exception as e:
            logger.error(f"Migration error on table '{table}': {e}")
            
    await _clean_corrupted_ip_placeholders(db)
    await db.commit()
    logger.info("Schema migration complete.")


