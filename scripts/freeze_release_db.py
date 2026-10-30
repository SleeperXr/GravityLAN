"""Freeze the inventory database of the current release as a test fixture.

Run once per release, after the release commit (see docs/RELEASING.md):

    cd backend && python ../scripts/freeze_release_db.py

It builds an inventory database from the current models, fills it with a small, representative
homelab and writes it as SQL to backend/tests/fixtures/db/gravitylan-<VERSION>.sql.
test_release_upgrade.py starts the next versions on these files, so a model column without a
migration in app/database/migrations.py fails CI. The files are never edited afterwards.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GRAVITYLAN_DATA_DIR", tempfile.mkdtemp())

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401 - registers every model
from app.models.agent import AgentConfig  # noqa: E402
from app.models.device import Device, DeviceGroup, DeviceHistory, DeviceInterface, DiscoveredHost, Service  # noqa: E402
from app.models.network import Subnet  # noqa: E402
from app.models.rack_cabling import RackCable, RackItem, RackPort  # noqa: E402
from app.models.setting import Setting  # noqa: E402
from app.models.topology import Rack, TopologyLink  # noqa: E402


def seed(s: Session) -> None:
    for key, value in {
        "setup.complete": "true",
        "api.master_token": "frozen-master-token",
        "api.admin_password": "$argon2id$frozen-hash",
        "scan_interval": "5",
        "ui.default_frontend": "vue",
    }.items():
        s.add(Setting(key=key, value=value))
    s.add(Subnet(id=1, cidr="192.168.10.0/24", name="LAN", gateway_ip="192.168.10.1", vlan_id=10))
    s.add(DeviceGroup(id=1, name="Server"))
    s.add(Rack(id=1, name="Keller", units=12, width=19))
    s.flush()
    s.add_all([
        Device(id=1, ip="192.168.10.1", mac="aa:bb:cc:00:00:01", display_name="Router", group_id=1, rack_id=1, rack_unit=12),
        Device(id=2, ip="192.168.10.20", mac="aa:bb:cc:00:00:02", display_name="NAS", group_id=1, rack_id=1, rack_unit=8,
               rack_height=2, is_host=True),
        Device(id=3, ip="192.168.10.30", mac="aa:bb:cc:00:00:03", display_name="VM", group_id=1, parent_id=2),
    ])
    s.flush()
    s.add(DeviceInterface(id=1, device_id=2, ip="192.168.20.20", mac="aa:bb:cc:00:00:22", label="VLAN 20", is_online=True))
    s.add(Service(id=1, device_id=2, name="Web UI", port=443, protocol="https", url_template="https://{ip}"))
    s.add(DiscoveredHost(id=1, ip="192.168.10.99", mac="aa:bb:cc:00:00:99", hostname="unknown"))
    s.add(DeviceHistory(device_id=2, status="online"))
    s.add(AgentConfig(device_id=2))
    s.add(TopologyLink(id=1, source_id=1, target_id=2, link_type="10GbE", role="primary"))
    s.add(RackItem(id=1, rack_id=1, name="Patchpanel", kind="patch_panel", rack_unit=11))
    s.flush()
    s.add_all([RackPort(id=1, rack_item_id=1, number=1), RackPort(id=2, device_id=1, number=1)])
    s.flush()
    s.add(RackCable(id=1, a_port_id=1, b_port_id=2, cable="Cat6", color="#3b82f6"))


def main() -> None:
    version = (ROOT / "VERSION").read_text().strip()
    target = ROOT / "backend" / "tests" / "fixtures" / "db" / f"gravitylan-{version}.sql"
    if target.exists():
        sys.exit(f"{target.relative_to(ROOT)} exists already; frozen databases are never rewritten.")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gravitylan.db"
        engine = create_engine(f"sqlite:///{path}")
        # Inventory tables only: the measurement tables live in telemetry.db
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.schema is None])
        with Session(engine) as s:
            seed(s)
            s.commit()
        engine.dispose()

        conn = sqlite3.connect(path)
        try:
            dump = "\n".join(conn.iterdump()) + "\n"
        finally:
            conn.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"-- Inventory database of GravityLAN {version}, written by scripts/freeze_release_db.py\n" + dump,
                      encoding="utf-8", newline="\n")
    print(f"Wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
