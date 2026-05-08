# HomeLan — Die ultimative Heimnetz-Zentrale

> Docker-basiertes Netzwerk-Dashboard mit Scanner-Agent, Geräte-Management und maximaler Anpassbarkeit.

---

## Projektübersicht

**Was:** Ein selbst-gehosteter Docker-Container, der als Netzwerk-Scanner und Dashboard fungiert — ähnlich wie Homarr, aber mit integrierter Netzwerk-Intelligence.

**Kernidee:** Beim Setup wird das Netzwerk gescannt, Geräte werden automatisch erkannt und klassifiziert. Danach ist alles über den Browser anpassbar — keine Config-Files, kein YAML.

**Inspiration:** Homarr (UI/UX), Grafana (Monitoring-Vibe), deine `remote_access.py` (Scanner-Logik)

---

## User Review Required

> [!IMPORTANT]
> **Tech Stack Entscheidung:** Ich empfehle **Python FastAPI** (Backend) + **React/TypeScript mit Vite** (Frontend). Begründung:
> - Python hat das beste Netzwerk-Scanning-Ökosystem (nmap, scapy, socket)
> - Deine Referenz-Logik (`remote_access.py`) ist bereits in Python — bewährte Patterns
> - FastAPI + Pydantic fängt Fehler automatisch ab (Typen-Validierung)
> - React/TypeScript = Homarr's Stack, TypeScript fängt Frontend-Bugs ab
> - **Rust wäre overkill** — der Bottleneck ist I/O (Netzwerk), nicht CPU. Rust bringt hier keinen Vorteil, verlangsamt aber die Entwicklung erheblich.

> [!WARNING]
> **Macvlan Networking:** Der Container bekommt eine eigene IP im LAN. Das bedeutet:
> - Der Docker-Host muss Promiscuous Mode unterstützen (Unraid: ✅ nativ)
> - Container kann standardmäßig **nicht** mit dem Host kommunizieren (braucht Bridge-Workaround)
> - Switch muss mehrere MACs pro Port erlauben (bei den meisten Home-Switches: ✅)

---

## Entscheidungen (Geklärt)

> [!NOTE]
> **Projektname:** Wird noch offen gelassen — "HomeLan" existiert bereits auf GitHub. Arbeitstitel bis zur Entscheidung: **`homelan`** (intern). Name wird vor erstem Release finalisiert.

> [!NOTE]
> **Auth:** Wird in Phase C nachgerüstet. Phase A+B laufen ohne Login (Heimnetz = vertrauenswürdig).

---

## Architektur

### System-Übersicht

```
┌─────────────────────────────────────────────────────┐
│              Docker Container (Macvlan)              │
│              IP: z.B. 192.168.1.200                 │
│                                                     │
│  ┌─────────────────┐     ┌──────────────────────┐   │
│  │   FastAPI        │     │   React Frontend     │   │
│  │   Backend        │◄───►│   (Vite, Static)     │   │
│  │   Port 80/443    │     │   via FastAPI served  │   │
│  │                  │     └──────────────────────┘   │
│  │  ┌────────────┐  │                               │
│  │  │ Scanner    │  │     ┌──────────────────────┐   │
│  │  │ Agent      │  │     │   SQLite Database    │   │
│  │  │ (async)    │  │────►│   /data/homelan.db   │   │
│  │  └────────────┘  │     └──────────────────────┘   │
│  └─────────────────┘                                │
└─────────────────────────────────────────────────────┘
         │
         ▼  Scannt das LAN
┌─────────────────────┐
│   Heimnetzwerk      │
│  192.168.1.0/24     │
│  10.0.0.0/24  etc.  │
└─────────────────────┘
```

### Tech Stack

| Layer | Technologie | Begründung |
|-------|-------------|------------|
| **Backend** | Python 3.12 + FastAPI | Beste Netzwerk-Libs, Pydantic-Validierung, async |
| **Frontend** | React 19 + TypeScript + Vite | Homarr-Stil, TypeScript = Bug-Schutz |
| **Database** | SQLite (Default) | Embedded, kein extra Service, einfaches Backup |
| **ORM** | SQLAlchemy 2.0 (async) | Robustes ORM, SQLite↔PostgreSQL portabel |
| **Layout Engine** | Gridstack.js | Drag & Drop wie Homarr |
| **Styling** | CSS Modules + CSS Custom Properties | Theming über CSS-Variablen |
| **Container** | Docker + Macvlan | Eigene IP im LAN |
| **Scanner** | Python socket + nmap (optional) | Bewährt aus deiner `remote_access.py` |

---

## Proposed Changes — Phasen-Roadmap

### Übersicht

```
Phase A (MVP)          Phase B (Customize)      Phase C (Full Vision)
─────────────          ───────────────────       ─────────────────────
Scanner + Dashboard    + Drag & Drop Layout     + Service Monitoring
Geräte-Erkennung      + Custom Labels/Icons     + Externe Agents
Direkter Zugriff       + Theme System           + Notifications
Auto-Gruppierung       + Settings Page          + Plugin System
Setup Wizard           + Service Editor         + Multi-User / Auth
```

---

### Phase A: Scanner + Dashboard (MVP)

#### Projektstruktur

```
homelan/
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── entrypoint.sh
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI App + Static Files
│   │   ├── config.py               # Settings (Pydantic BaseSettings)
│   │   ├── database.py             # SQLAlchemy Engine + Session
│   │   │
│   │   ├── models/                 # SQLAlchemy Models
│   │   │   ├── __init__.py
│   │   │   ├── device.py           # Device, DeviceGroup
│   │   │   ├── service.py          # Service (Port-basiert)
│   │   │   ├── settings.py         # App Settings (Key-Value)
│   │   │   └── scan.py             # ScanJob, ScanResult
│   │   │
│   │   ├── schemas/                # Pydantic Request/Response
│   │   │   ├── __init__.py
│   │   │   ├── device.py
│   │   │   ├── service.py
│   │   │   ├── scan.py
│   │   │   └── settings.py
│   │   │
│   │   ├── api/                    # API Routes
│   │   │   ├── __init__.py
│   │   │   ├── devices.py          # CRUD Geräte
│   │   │   ├── services.py         # CRUD Services
│   │   │   ├── scanner.py          # Scan starten/stoppen/status
│   │   │   ├── settings.py         # App-Einstellungen
│   │   │   └── setup.py            # Setup Wizard API
│   │   │
│   │   └── scanner/                # Netzwerk-Scanner Engine
│   │       ├── __init__.py
│   │       ├── discovery.py        # Host Discovery (Ping/ARP)
│   │       ├── port_scanner.py     # TCP Port Scan
│   │       ├── classifier.py       # Geräte-Klassifizierung
│   │       ├── hostname.py         # DNS/Hostname Resolution
│   │       └── scheduler.py        # Periodische Scans
│   │
│   ├── requirements.txt
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── index.css               # Design System / CSS Variables
│   │   │
│   │   ├── components/
│   │   │   ├── Dashboard/
│   │   │   │   ├── Dashboard.tsx    # Haupt-Dashboard
│   │   │   │   ├── DeviceCard.tsx   # Geräte-Kachel
│   │   │   │   ├── GroupSection.tsx # Geräte-Gruppe
│   │   │   │   └── ServiceBadge.tsx # Service-Button (RDP, SSH, etc.)
│   │   │   │
│   │   │   ├── Setup/
│   │   │   │   ├── SetupWizard.tsx  # Ersteinrichtung
│   │   │   │   ├── SubnetPicker.tsx # Subnet-Auswahl
│   │   │   │   └── ScanProgress.tsx # Scan-Fortschritt
│   │   │   │
│   │   │   └── common/
│   │   │       ├── Header.tsx
│   │   │       ├── Sidebar.tsx
│   │   │       └── StatusBar.tsx
│   │   │
│   │   ├── hooks/
│   │   │   ├── useDevices.ts
│   │   │   ├── useScanner.ts
│   │   │   └── useSettings.ts
│   │   │
│   │   ├── api/
│   │   │   └── client.ts           # API Client (fetch wrapper)
│   │   │
│   │   └── types/
│   │       └── index.ts            # TypeScript Interfaces
│   │
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
└── data/                           # Docker Volume Mount
    └── homelan.db                  # SQLite DB
```

---

#### [NEW] Backend Components

##### [NEW] `backend/app/main.py` — FastAPI Application
- FastAPI App mit CORS, Static Files (React Build), WebSocket
- Lifespan: DB-Init, Scanner-Scheduler starten
- Static Files: React-Build wird direkt von FastAPI served (Single-Container)

##### [NEW] `backend/app/scanner/discovery.py` — Host Discovery
- Portiert aus deiner `remote_access.py`:
  - Stage 1: Fast Discovery (Quick TCP Connect auf 445, 135, 80, 22)
  - Stage 2: Priority Probe (Server/Firewalls zuerst)
  - Stage 3: General Probe (Rest)
- **Async** mit `asyncio` statt `threading.Thread`
- WebSocket für Live-Updates an das Frontend

##### [NEW] `backend/app/scanner/classifier.py` — Geräte-Klassifizierung
- Direkt aus deiner `_classify_device()` und `_is_client_hostname()` portiert
- Erkennung: Firewalls (Sophos, Securepoint, pfSense...), Server, NAS, Hypervisors
- Hostname-Patterns + Port-Fingerprints
- **Erweiterbar** über DB (Custom Rules via Browser hinzufügbar in Phase B)

##### [NEW] `backend/app/models/device.py` — Datenbank-Modelle
```python
# Konzept:
class Device:
    id: int
    ip: str
    mac: str | None
    hostname: str | None
    display_name: str          # Vom User anpassbar
    device_type: str           # firewall, server, nas, client, unknown
    device_subtype: str        # Sophos, Proxmox, Synology, etc.
    group_id: int | None       # FK zu DeviceGroup
    icon: str | None           # Custom Icon
    sort_order: int
    is_pinned: bool
    last_seen: datetime
    first_seen: datetime

class DeviceGroup:
    id: int
    name: str                  # "Firewalls", "Server", etc.
    icon: str | None
    sort_order: int
    color: str | None

class Service:
    id: int
    device_id: int             # FK zu Device
    name: str                  # "RDP", "SSH", "Sophos Admin"
    protocol: str              # rdp, ssh, http, https, smb, scp
    port: int
    url_template: str          # z.B. "https://{ip}:{port}"
    color: str | None
    is_auto_detected: bool
```

##### [NEW] `backend/app/api/setup.py` — Setup Wizard API
- `GET /api/setup/status` — Prüft ob Setup abgeschlossen
- `GET /api/setup/subnets` — Verfügbare Netzwerk-Interfaces + Subnetze
- `POST /api/setup/scan` — Startet initialen Scan für gewählte Subnetze
- `WS /api/setup/scan/live` — WebSocket für Live-Scan-Updates

---

#### [NEW] Frontend Components

##### [NEW] `frontend/src/components/Setup/SetupWizard.tsx`
- Schritt 1: Willkommen + Netzwerk-Interfaces anzeigen
- Schritt 2: **Subnetze auswählen** (Checkboxen, manuelle Eingabe)
- Schritt 3: Scan läuft — Live-Fortschritt mit gefundenen Geräten
- Schritt 4: Ergebnis prüfen — Geräte bestätigen/umbenennen/gruppieren
- Schritt 5: Dashboard fertig! 🎉

##### [NEW] `frontend/src/components/Dashboard/Dashboard.tsx`
- Homarr-inspiriertes Grid-Layout
- Geräte-Gruppen als Sektionen (Firewalls, Server, NAS, Web Interfaces)
- Jede Gruppe zeigt ihre Geräte als Kacheln
- Responsive: Desktop = Grid, Mobile = Stack

##### [NEW] `frontend/src/components/Dashboard/DeviceCard.tsx`
- Geräte-Kachel mit:
  - Icon + Display Name
  - IP-Adresse (optional einblendbar)
  - Service-Buttons (RDP, SSH, HTTPS, SMB, etc.)
  - Online-Status Indikator (grüner/roter Punkt)
  - Klick → Service-Links öffnen

##### [NEW] Design System (`index.css`)
- Homarr-inspiriertes Dark Theme als Default
- CSS Custom Properties für komplette Anpassbarkeit:
  ```css
  :root {
    --bg-primary: #1a1b2e;
    --bg-card: #242538;
    --bg-card-hover: #2a2b42;
    --accent: #4fd1c5;
    --text-primary: #e2e8f0;
    --text-secondary: #a0aec0;
    --border-radius: 12px;
    /* ... */
  }
  ```
- Smooth Animations, Hover-Effects, Transitions

---

#### [NEW] Docker Setup

##### [NEW] `docker/Dockerfile`
```dockerfile
# Multi-stage Build
# Stage 1: Frontend Build (Node)
# Stage 2: Backend Runtime (Python slim)
# - Installiert nmap, net-tools
# - Kopiert Frontend-Build als Static Files
# - Entrypoint: uvicorn
```

##### [NEW] `docker/docker-compose.yml`
```yaml
# Macvlan Network Config
# - Eigene IP im LAN
# - Volume für /data (SQLite + Config)
# - CAP_NET_RAW + CAP_NET_ADMIN für Scanning
```

---

### Phase B: Customization (nach MVP)

| Feature | Beschreibung |
|---------|-------------|
| **Drag & Drop** | Gridstack.js — Kacheln frei positionieren und resizen |
| **Custom Labels** | Geräte umbenennen, eigene Beschreibung |
| **Custom Icons** | Icon-Picker mit tausenden Icons (Dashboard Icons, Simple Icons) |
| **Service Editor** | Services pro Gerät hinzufügen/entfernen/bearbeiten |
| **Theme System** | Light/Dark Mode + Custom CSS Variables über UI |
| **Settings Page** | Alle Einstellungen im Browser: Scan-Intervall, Default-Ports, etc. |
| **Custom Groups** | Eigene Gruppen erstellen, Geräte zuordnen |

### Phase C: Full Vision (langfristig)

| Feature | Beschreibung |
|---------|-------------|
| **Service Health** | Periodischer Port-Check → Online/Offline Status |
| **Externe Agents** | Lightweight Python-Agent für Remote-Subnetze |
| **Notifications** | Gerät offline → Push/Email/Webhook |
| **Multi-User** | Login + Rollen (Admin/Viewer) |
| **Widgets** | CPU/RAM/Uptime Widgets (SNMP/API) |
| **Plugin System** | Custom Widgets als Plugins |
| **PostgreSQL** | Migration-Path für Enterprise-Setups |
| **Backup/Restore** | Ein-Klick Backup der gesamten Config |

---

## Verification Plan

### Automated Tests

```bash
# Backend Tests
cd backend && pytest tests/ -v

# Frontend Tests
cd frontend && npm run test

# Docker Build Test
docker build -t homelan:dev -f docker/Dockerfile .

# Integration: Container starten und API Health-Check
docker run -d --name homelan-test homelan:dev
curl http://localhost:8080/api/health
```

### Manual Verification

1. **Setup Wizard:** Container starten → Browser öffnen → Wizard durchlaufen
2. **Scan:** Netzwerk scannen → Geräte werden erkannt und klassifiziert
3. **Dashboard:** Geräte werden als Kacheln angezeigt mit korrekten Service-Buttons
4. **Service Access:** Klick auf "HTTPS" → Browser öffnet WebUI des Geräts
5. **Persistence:** Container neustarten → Daten bleiben erhalten (SQLite Volume)

---

## Nächste Schritte nach Approval

1. Projektstruktur anlegen (Scaffold)
2. Backend: FastAPI + SQLite + Scanner-Engine
3. Frontend: React + Vite + Dashboard UI
4. Docker: Dockerfile + Compose mit Macvlan
5. Setup Wizard implementieren
6. Testing + Polish
