"""Run the GravityLAN backend with demo data and without touching your network.

Meant for UI work (e.g. the redesign branch): serves the API on
http://127.0.0.1:8000 from a throw-away SQLite database in ``.demo-data/``
with example devices, services, agents, metrics and history. Simulated
agents keep reporting every 10 s, so live views update like in production.

Safety:
- the scan scheduler never starts, and every endpoint that would scan the
  LAN or open an SSH session (scanner start/discover/scan-ip, device
  refresh, add-from-ip, agent deploy/uninstall/patches) answers 403;
- the browser SSH terminal always lands on a built-in fake shell on
  127.0.0.1 (any user/password/key works), whatever host it targets;
- the server only listens on 127.0.0.1;
- the database URL is set explicitly, so a real database is never used.

Usage (repository root, backend virtualenv):
    backend/.venv/Scripts/python scripts/dev_demo.py        # Windows
    backend/.venv/bin/python scripts/dev_demo.py            # Linux/macOS
    ... --reset    wipe the demo database and seed it again
    ... --fresh    start like a new install (separate empty database, setup wizard)
    ... --company  a small company network instead of the homelab (own database in .demo-data/company/)

Then start the frontend (``cd frontend && npm run dev``), open
http://localhost:5173 and log in with the password ``demo``.
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import secrets
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from demo_scenarios import SCENARIOS, Scenario

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / ".demo-data"
DEMO_PASSWORD = "demo"
HOST, PORT = "127.0.0.1", 8000
REPORT_INTERVAL_S = 10

# Endpoints that would scan the LAN or SSH into hosts.
_BLOCKED_PATHS = re.compile(
    r"^/api/("
    r"scanner/(scan-ip|quick-subnet-scan|discover|start-dashboard|start|live-discovery)"
    r"|devices/(refresh-all|add-from-ip|\d+/refresh-(info|services))"
    r"|agent/(deploy|uninstall|patches)/"
    r")"
)

GRID_X, GRID_Y = 250, 150  # pixels per column/row of a scenario's React topology grid


def _utcnow() -> datetime:
    """Naive UTC, matching what the report endpoint stores in SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _prepare_environment(reset: bool, fresh: bool, scenario: str) -> Path:
    # --fresh uses its own throw-away database that starts empty every run; other scenarios keep their own
    data_dir = DEMO_DIR / "fresh" if fresh else DEMO_DIR if scenario == "home" else DEMO_DIR / scenario
    if (reset or fresh) and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    # Must be set before app.config is imported; the explicit URL also wins over any .env file.
    os.environ["GRAVITYLAN_DATA_DIR"] = str(data_dir)
    os.environ["GRAVITYLAN_DATABASE_URL"] = f"sqlite+aiosqlite:///{(data_dir / 'gravitylan-demo.db').as_posix()}"
    sys.path.insert(0, str(ROOT / "backend"))
    return data_dir


def _metrics_sample(profile: tuple, t: float) -> dict:
    """Plausible, slowly varying metrics for one simulated agent at time t (seconds)."""
    _, ram_gb, base_cpu, _ = profile
    cpu = max(1.0, min(99.0, base_cpu + 12 * math.sin(t / 1800) + random.uniform(-4, 4)))
    ram_total = ram_gb * 1024
    ram_pct = max(5.0, min(97.0, 40 + base_cpu / 3 + 6 * math.sin(t / 5400) + random.uniform(-1, 1)))
    return {
        "cpu_percent": round(cpu, 1),
        "ram": {"total_mb": ram_total, "used_mb": int(ram_total * ram_pct / 100), "percent": round(ram_pct, 1)},
        "disk": [
            {"path": "/", "total_gb": 256.0, "used_gb": round(256 * (0.3 + base_cpu / 300), 1), "percent": round(30 + base_cpu / 3, 1)},
            {"path": "/mnt/data", "total_gb": 4000.0, "used_gb": 2710.0, "percent": 67.8},
        ],
        "temperature": round(38 + cpu / 4 + random.uniform(-1, 1), 1),
        "network": {"eth0": {"rx_bytes_sec": random.randint(20_000, 4_000_000), "tx_bytes_sec": random.randint(10_000, 1_500_000)}},
    }


async def _seed(scenario: Scenario) -> dict[str, tuple[int, str, tuple]]:
    """Fill an empty demo database. Returns {device name: (id, agent token, profile)} for agents."""
    from sqlalchemy import select

    from app.database import async_session, init_db
    from app.models.agent import AgentConfig, AgentToken, DeviceMetrics
    from app.models.device import Device, DeviceGroup, DeviceHealthSample, DeviceHistory, DeviceInterface, DiscoveredHost, Service
    from app.models.network import Subnet
    from app.models.setting import Setting
    from app.models.topology import Rack, TopologyLink
    from app.scanner.utils import ensure_default_groups
    from app.services.agent_tokens import hash_agent_token
    from app.services.auth_service import hash_password

    from app.database.migrations import run_migrations

    await init_db()
    # Existing demo databases need new columns before the first ORM query
    async with async_session() as db:
        await run_migrations(db)
    async with async_session() as db:
        if (await db.execute(select(Device).limit(1))).scalar_one_or_none():
            rows = (await db.execute(select(AgentToken, Device).join(Device, AgentToken.device_id == Device.id))).all()
            profiles = {d[0]: d[6] for d in scenario.devices if d[6]}
            # Only the hash of an agent token is stored, so the simulated agents get fresh tokens
            agents = {}
            for tok, dev in rows:
                if dev.display_name in profiles:
                    raw = secrets.token_hex(32)
                    tok.token = hash_agent_token(raw)
                    agents[dev.display_name] = (dev.id, raw, profiles[dev.display_name])
            await db.commit()
            return agents

        now = _utcnow()
        for key, value in {
            "setup.complete": "true",
            "api.admin_password": hash_password(DEMO_PASSWORD),
            "api.master_token": secrets.token_hex(32),
            "scan_interval": "0",
            "quick_scan_interval": "0",
            "server.url": f"http://{HOST}:{PORT}",
            "ui.link_type_colors": json.dumps(scenario.link_colors),
        }.items():
            db.add(Setting(key=key, value=value, category="system"))

        groups = await ensure_default_groups(db, commit=False)
        for name, icon, order in scenario.extra_groups:
            group = DeviceGroup(name=name, icon=icon, sort_order=order)
            db.add(group)
            await db.flush()
            groups[name] = group.id

        subnets = {key: Subnet(cidr=cidr, name=name, vlan_id=vlan, gateway_ip=gateway) for key, cidr, name, vlan, gateway in scenario.subnets}
        db.add_all(subnets.values())
        racks = {name: Rack(name=name, units=units) for name, units in scenario.racks}
        db.add_all(racks.values())
        await db.flush()

        by_name: dict[str, Device] = {}
        agents: dict[str, tuple[int, str, tuple]] = {}
        for index, (name, ip, dtype, group, flags, services, profile) in enumerate(scenario.devices):
            offline = flags.get("offline", False)
            device = Device(
                ip=ip, display_name=name, hostname=name.lower().replace(" ", "-") + "." + scenario.domain, device_type=dtype,
                device_subtype=flags.get("subtype", "Unknown"), vendor=flags.get("vendor"), mac=flags.get("mac"),
                group_id=groups[group], is_online=not offline, is_host=flags.get("is_host", False),
                is_ap=flags.get("is_ap", False), is_wlan=flags.get("is_wlan", False),
                virtual_type=flags.get("virtual_type"), sort_order=index, has_agent=profile is not None,
                old_ip=flags.get("old_ip"), ip_changed_at=now - timedelta(hours=3) if flags.get("old_ip") else None,
                last_seen=now - timedelta(hours=2) if offline else now, status_changed_at=now - timedelta(hours=2),
            )
            if "max_ports" in flags:
                device.max_ports = flags["max_ports"]
            if flags.get("parent"):
                device.parent_id = by_name[flags["parent"]].id
            if name in scenario.grid:
                col, row = scenario.grid[name]
                device.topology_x, device.topology_y = int(col * GRID_X), int(row * GRID_Y)
            if name in scenario.rack_slots:
                rack, unit, height = scenario.rack_slots[name]
                device.rack_id, device.rack_unit, device.rack_height = racks[rack].id, unit, height
            db.add(device)
            await db.flush()
            by_name[name] = device

            for order, (sname, proto, port, up) in enumerate(services):
                db.add(Service(device_id=device.id, name=sname, protocol=proto, port=port, is_up=up and not offline, sort_order=order))
            db.add(DiscoveredHost(ip=ip, hostname=device.hostname, mac=device.mac, vendor=device.vendor, is_online=not offline, is_monitored=True))
            if offline:
                db.add(DeviceHistory(device_id=device.id, status="offline", message="Device went offline", timestamp=now - timedelta(hours=2)))

            if profile:
                available, security = scenario.patches.get(name, (0, 0))
                token = secrets.token_hex(32)
                db.add(AgentToken(device_id=device.id, token=hash_agent_token(token), agent_version=profile[3], last_seen=now,
                                  os_pretty=profile[0], os_arch="x86_64"))
                db.add(AgentConfig(device_id=device.id))
                agents[name] = (device.id, token, profile)
                # 24 h of history, one sample every 5 minutes
                for step in range(288):
                    ts = now - timedelta(minutes=5 * (288 - step))
                    sample = _metrics_sample(profile, ts.timestamp())
                    db.add(DeviceMetrics(
                        device_id=device.id, cpu_percent=sample["cpu_percent"], ram_used_mb=sample["ram"]["used_mb"],
                        ram_total_mb=sample["ram"]["total_mb"], ram_percent=sample["ram"]["percent"],
                        disk_json=json.dumps(sample["disk"]), temperature=sample["temperature"],
                        net_json=json.dumps(sample["network"]), timestamp=ts,
                        patch_available=available, patch_security=security,
                        patch_manager="apt", reboot_required=name in scenario.reboot_required,
                    ))

        # 24 h of health probes, one every 5 minutes, so uptime bars and latency charts have a history:
        # wired gear answers in a few ms, WLAN clients slower; offline devices dropped 2 h ago and the
        # scenario's outages show up as gaps.
        for name, ip, _dtype, _group, flags, services, _profile in scenario.devices:
            device = by_name[name]
            down = {step for r in scenario.outages.get(name, []) for step in r}
            base = random.uniform(8, 28) if flags.get("is_wlan") else random.uniform(0.4, 3.5)
            for step in range(288):
                ts = now - timedelta(minutes=5 * (288 - step))
                online = not (flags.get("offline") and step >= 264) and step not in down
                db.add(DeviceHealthSample(
                    device_id=device.id, timestamp=ts, is_online=online,
                    latency_ms=round(base + random.uniform(-0.3, 0.3) * base, 2) if online else None,
                    probe_type="icmp" if online else None,
                    ports_up=sum(1 for s in services if s[3]) if online else 0, ports_total=len(services),
                ))
        for name, ranges in scenario.outages.items():
            for r in ranges:
                db.add(DeviceHistory(device_id=by_name[name].id, status="offline", message="Device went offline",
                                     timestamp=now - timedelta(minutes=5 * (288 - r.start))))
                db.add(DeviceHistory(device_id=by_name[name].id, status="online", message="Device is back online",
                                     timestamp=now - timedelta(minutes=5 * (288 - r.stop))))

        for ip, vendor in scenario.unknown_hosts:
            db.add(DiscoveredHost(ip=ip, vendor=vendor, is_online=True))

        # The gateway of every VLAN is one box: its other addresses are attached interfaces, and the
        # pending ones (same MAC) wait as merge suggestions
        router = by_name[scenario.router]
        router.mac = scenario.router_mac
        for ip, key, vlan in scenario.router_interfaces:
            db.add(DeviceInterface(device_id=router.id, ip=ip, mac=scenario.router_mac, subnet_id=subnets[key].id,
                                   vlan_id=vlan, is_online=True, last_seen=now))
            db.add(DiscoveredHost(ip=ip, mac=scenario.router_mac, is_online=True, is_monitored=True))
        for ip in scenario.pending_router_ips:
            db.add(DiscoveredHost(ip=ip, mac=scenario.router_mac, hostname=router.hostname, is_online=True))
        # Further NICs of multi-homed hosts (cluster and backup networks)
        for name, ip, key, vlan, label in scenario.interfaces:
            db.add(DeviceInterface(device_id=by_name[name].id, ip=ip, mac=by_name[name].mac, subnet_id=subnets[key].id,
                                   vlan_id=vlan, label=label, is_online=True, last_seen=now))
            db.add(DiscoveredHost(ip=ip, mac=by_name[name].mac, is_online=True, is_monitored=True))
        for source, target, link_type in scenario.links:
            db.add(TopologyLink(source_id=by_name[source].id, target_id=by_name[target].id, link_type=link_type))
        for name, message, minutes in scenario.down_events:
            db.add(DeviceHistory(device_id=by_name[name].id, status="down", message=message, timestamp=now - timedelta(minutes=minutes)))
        await db.commit()
        return agents


async def _simulate_agents(server, scenario: Scenario, agents: dict[str, tuple[int, str, tuple]]) -> None:
    """Post a metrics report for every demo agent through the real /api/agent/report endpoint."""
    import httpx

    while not server.started:
        await asyncio.sleep(0.2)
    async with httpx.AsyncClient(base_url=f"http://{HOST}:{PORT}", timeout=5) as client:
        while not server.should_exit:
            now = datetime.now(timezone.utc).timestamp()
            for name, (device_id, token, profile) in agents.items():
                available, security = scenario.patches.get(name, (0, 0))
                payload = {"device_id": device_id, "agent_version": profile[3], "timestamp": now,
                           "system": {"os": profile[0], "arch": "x86_64"},
                           "patches": {"patch_available": available, "patch_security": security,
                                       "patch_manager": "apt", "reboot_required": name in scenario.reboot_required},
                           **_metrics_sample(profile, now)}
                try:
                    await client.post("/api/agent/report", json=payload, headers={"Authorization": f"Bearer {token}"})
                except httpx.HTTPError as exc:
                    print(f"[demo] report for {name} failed: {exc}")
            await asyncio.sleep(REPORT_INTERVAL_S)


_DEMO_SHELL_COMMANDS = {
    "help": "Demo commands: uname -a, uptime, whoami, hostname, ls, df -h, clear, exit",
    "uname": "Linux gravitylan-demo 6.1.0-28-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.1.119-1 x86_64 GNU/Linux",
    "uptime": " 21:42:07 up 23 days,  4:12,  1 user,  load average: 0.42, 0.37, 0.31",
    "whoami": "root",
    "hostname": "gravitylan-demo",
    "ls": "backups  docker-compose.yml  notes.txt",
    "df": "Filesystem      Size  Used Avail Use% Mounted on\r\n/dev/sda1        98G   41G   52G  45% /",
}


def _demo_shell(channel) -> None:
    """A tiny line-editing shell so the browser terminal can be tried without any real host."""
    prompt = "\x1b[1;32mroot@gravitylan-demo\x1b[0m:\x1b[1;34m~\x1b[0m# "
    channel.send("GravityLAN demo shell - nothing here reaches a real machine. Type 'help'.\r\n\r\n" + prompt)
    line = ""
    while True:
        data = channel.recv(1024)
        if not data:
            return
        for ch in data.decode(errors="ignore"):
            if ch in "\r\n":
                cmd, line = line.strip(), ""
                channel.send("\r\n")
                if cmd in ("exit", "logout"):
                    channel.send("logout\r\n")
                    channel.send_exit_status(0)
                    channel.close()
                    return
                if cmd == "clear":
                    channel.send("\x1b[2J\x1b[H")
                elif cmd:
                    out = _DEMO_SHELL_COMMANDS.get(cmd.split()[0], f"{cmd.split()[0]}: command not found (demo shell)")
                    channel.send(out + "\r\n")
                channel.send(prompt)
            elif ch in "\x7f\b":
                if line:
                    line = line[:-1]
                    channel.send("\b \b")
            elif ch == "\x03":
                line = ""
                channel.send("^C\r\n" + prompt)
            elif ch >= " ":
                line += ch
                channel.send(ch)


def _start_demo_ssh_server(data_dir: Path) -> int:
    """Serve the demo shell over real SSH on 127.0.0.1 (any user, any password or key); returns the port."""
    import socket
    import threading

    import paramiko

    key_file = data_dir / "demo_ssh_host_key"
    if key_file.exists():
        host_key = paramiko.RSAKey.from_private_key_file(str(key_file))
    else:
        host_key = paramiko.RSAKey.generate(2048)
        host_key.write_private_key_file(str(key_file))

    class DemoServer(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL

        def check_auth_publickey(self, username, key):
            return paramiko.AUTH_SUCCESSFUL

        def get_allowed_auths(self, username):
            return "publickey,password"

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_pty_request(self, *args):
            return True

        def check_channel_window_change_request(self, *args):
            return True

        def check_channel_shell_request(self, channel):
            threading.Thread(target=_demo_shell, args=(channel,), daemon=True).start()
            return True

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)

    def serve() -> None:
        while True:
            conn, _ = listener.accept()
            transport = paramiko.Transport(conn)
            transport.add_server_key(host_key)
            try:
                transport.start_server(server=DemoServer())
            except Exception:
                transport.close()

    threading.Thread(target=serve, name="demo-ssh", daemon=True).start()
    return listener.getsockname()[1]


async def main(reset: bool, fresh: bool, scenario_name: str) -> None:
    data_dir = _prepare_environment(reset, fresh, scenario_name)
    scenario = SCENARIOS[scenario_name]()

    import uvicorn
    from fastapi.responses import JSONResponse

    from app.main import app
    from app.scanner.scheduler import scheduler

    async def _noop(*_args, **_kwargs) -> None:
        return None

    scheduler.start = _noop  # the lifespan awaits scheduler.start(); no background scans in demo mode
    scheduler.stop = _noop

    # Every SSH terminal session lands on the built-in fake shell instead of the target host
    import socket
    import app.services.ssh_terminal as ssh_terminal

    demo_ssh_port = _start_demo_ssh_server(data_dir)
    ssh_terminal._open_socket = lambda _host, _port: socket.create_connection(("127.0.0.1", demo_ssh_port), timeout=5)

    @app.middleware("http")
    async def _demo_guard(request, call_next):
        if _BLOCKED_PATHS.match(request.url.path):
            return JSONResponse({"detail": "Disabled in demo mode (no LAN scans, no SSH)."}, status_code=403)
        return await call_next(request)

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))

    if fresh:
        # Like a new install: no data and no completed setup, so the UI opens the setup wizard
        from app.database import init_db

        await init_db()
        print(f"[demo] fresh install, database: {data_dir} - the setup wizard sets the password")
        print(f"[demo] API on http://{HOST}:{PORT} - start the UI with `cd frontend && npm run dev`")
        await server.serve()
        return

    agents = await _seed(scenario)

    # The scheduler does not run here: fold the seeded metrics into hourly/daily rollups once.
    # This runs before the app's lifespan, so move the metrics of an older demo database first.
    from app.database import async_session
    from app.services.telemetry_rollups import run_telemetry_maintenance
    from app.services.telemetry_store import migrate_legacy_telemetry

    async with async_session() as db:
        await migrate_legacy_telemetry(db)
        await run_telemetry_maintenance(db)

    print(f"[demo] {scenario.name}: {len(scenario.devices)} devices, {len(agents)} simulated agents, database: {data_dir}")
    print(f"[demo] API on http://{HOST}:{PORT} - start the UI with `cd frontend && npm run dev`, log in with the demo password (see README)")
    await asyncio.gather(server.serve(), _simulate_agents(server, scenario, agents))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="wipe the demo database and seed it again")
    parser.add_argument("--fresh", action="store_true", help="start like a new install (empty database, setup wizard)")
    parser.add_argument("--company", action="store_const", const="company", dest="scenario", default="home",
                        help="a small company instead of the homelab: 8 VLANs, Proxmox cluster, ~130 devices (own database)")
    args = parser.parse_args()
    asyncio.run(main(args.reset, args.fresh, args.scenario))
