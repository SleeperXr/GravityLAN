<p align="center">
  <img src="./assets/logo.png" alt="GravityLAN Logo" width="200">
</p>

<h1 align="center">GravityLAN</h1>

<p align="center">
  <strong>Network radar and homelab dashboard — discovery, topology, and optional Linux agents.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/React-19-61DAFB.svg" alt="React">
</p>

---

GravityLAN is a **FastAPI + React** app that scans your LAN, keeps a live inventory of hosts and services, and offers an optional **lightweight Python agent** for deeper metrics on Linux machines. It is aimed at **homelab and small office** use: quick visibility without enterprise overhead.

---

## Features

- **Discovery** — Subnet scanning, ARP-aware discovery, hostname resolution, port / service hints.
- **Dashboard** — Customisable layout, device status, groups, and history-oriented views.
- **Network planner** — Manage subnets and how you think about your LAN.
- **Topology** — Racks and links for a physical / logical map of gear.
- **Linux agent** — CPU, RAM, disk, temperature-style metrics; deploy via SSH from the UI (credentials are **not** stored in the database; they exist only for the duration of the deploy request).
- **Backup / restore** — JSON export/import of core tables (import uses a **strict table whitelist**).
- **UI login** — After initial setup, the SPA asks for a password; a **master API token** is created at setup and used for session checks and WebSockets.

---

## Screenshots

| Dashboard | Network planner | Device / agent |
|-----------|-----------------|----------------|
| ![Dashboard](./docs/screenshots/GravityLanDashboard.png) | ![Network](./docs/screenshots/GravityLanNetwork-Planer.png) | ![Device editor](./docs/screenshots/GravitryLanDeviceEditor.png) |

---

## Requirements

- **Docker** (recommended for production-style runs) *or* **Windows/Linux** for development.
- **Nmap** on the host/container (image installs it for Docker).
- **Node 20+** and **npm** (only if you build the frontend yourself).

---

## Quick start (Docker)

The repository includes a unified image build under `docker/Dockerfile` (multi-stage: Vite build + Python runtime). Data and SQLite live under `GRAVITYLAN_DATA_DIR` (default in the image: `/app/data`).

**Minimal `docker run` (adjust publish and volume as needed):**

```bash
docker build -f docker/Dockerfile -t gravitylan:local .
docker run -d --name gravitylan \
  -p 8000:8000 \
  -v gravitylan-data:/app/data \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  gravitylan:local
```

Then open **http://localhost:8000**, complete the **setup wizard**, and log in when prompted. On first successful setup, a **master API token** is generated in the database (see [Security](#security--network-exposure)).

**Compose / advanced networking:** see `docker/docker-compose.yml` for an example using **macvlan** (e.g. Unraid / fixed LAN IP). Tweak `parent`, subnet, and IP to match your environment.

> **Host network mode** (`network_mode: host`) is a valid option when you need the cleanest possible access to local interfaces for discovery; it trades isolation for convenience. The old README example used host mode — still supported if you build/run your own compose file that way.

---

## Development (Windows)

1. Install **Python 3.12+**, **Node 20+**, **Nmap**, and **Git**.
2. From the repo root:

```powershell
.\start_gravitylan.ps1
```

This installs dependencies, starts **uvicorn** on `http://0.0.0.0:8000`, and **Vite** on `http://127.0.0.1:5173`.

- **API + bundled SPA (optional):** build the frontend (`cd frontend && npm run build`) and place output where your backend expects static files, or use the Docker image which serves the built UI from `/app/static`.

---

## Configuration (environment)

| Variable | Meaning | Default |
|----------|---------|--------|
| `GRAVITYLAN_DATA_DIR` | SQLite DB and persistent data directory | `/data` (local); image sets `/app/data` |
| `GRAVITYLAN_DATABASE_URL` | Optional full SQLAlchemy URL (overrides SQLite path) | *(empty → SQLite under data dir)* |
| `GRAVITYLAN_DEBUG` | Verbose logging | `false` |
| `GRAVITYLAN_CORS_ORIGINS` | Allowed CORS origins (dev / split frontend) | `localhost:5173`, `localhost:3000` |
| `GRAVITYLAN_SCAN_TIMEOUT` | Per-target scan timeout (seconds) | `1.5` |
| `GRAVITYLAN_SCAN_WORKERS` | Concurrency hint for scanner | `20` |

Settings are defined in `backend/app/config.py` (`pydantic-settings`, prefix `GRAVITYLAN_`).

Optional setting keys (via UI / database) include:

- **`api.master_token`** — Secret issued at setup; used as default “password” for `/api/auth/login` unless `api.admin_password` is set.
- **`api.admin_password`** — If set, login password must match this; response still returns the master token for the browser session.

---

## Repository layout

```
agent/               # gravitylan-agent.py (+ systemd unit template)
backend/app/         # FastAPI application (api/, models/, scanner/, …)
frontend/            # React (Vite, TypeScript, Tailwind)
docker/              # Dockerfile + compose examples
docs/screenshots/    # README images
```

Interactive API docs: **`/docs`** (Swagger UI) when the server is running.

---

## GravityLAN Agent

- Single **Python** script plus a generated **config** (server URL + per-device token).
- **Reporting** uses `Authorization: Bearer <agent token>` to `POST /api/agent/report`.
- **Dashboard WebSocket** (`/api/agent/ws/{device_id}`) accepts either the **master token** or the **agent token** for that device.

SSH private keys/passwords used in the UI deploy flow are **ephemeral** (request-time only).

---

## Security & network exposure

GravityLAN is **designed for a trusted LAN**, not anonymous internet exposure.

| Layer | What it does |
|-------|----------------|
| **UI (`AuthGuard`)** | Blocks the main dashboard until `/api/auth/login` succeeds; token stored in **`localStorage`** (good enough for homelab UX; XSS on this origin would be a concern as with many SPAs). |
| **REST API** | Most write/admin routes do **not** require `Authorization` on every HTTP call. Anything that can reach the API URL can invoke those endpoints (e.g. `curl` on the LAN). |
| **WebSockets** | Live logs, scanner progress, and agent streaming require a valid **master token** (or agent token where applicable). |
| **Reverse proxy (e.g. Nginx Proxy Manager)** | **Recommended** for any access from outside the LAN: TLS, access control, IP allowlists, or VPN-only paths. Treat NPM (or similar) as the **real gate** for remote users. |

**Practical guidance**

- Do **not** port-forward the container raw to the public internet without an authenticated proxy in front.
- Prefer **VPN** (WireGuard, Tailscale, etc.) or NPM with **strong** access rules for remote administration.
- **Backups** may contain `agent_tokens` and settings — treat export files as **secrets**.

This model is intentional for simplicity in homelab scenarios: **defence in depth = network placement + proxy + optional VPN**, not only the React login screen.

---

## License

Open source under the [MIT License](LICENSE).

Built with Antigravity and care by **SleeperXr**.
