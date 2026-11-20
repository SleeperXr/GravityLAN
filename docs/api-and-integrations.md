# REST API, Python Client, AI Assistants & Webhooks

[English](#english) · [Deutsch](#deutsch)

## English

GravityLAN provides a REST API (with interactive Swagger UI at `/docs`), WebSockets for live streams, a lightweight Python client ([`gravitylan_api`](../gravitylan_api)), and an event notification outbox for webhooks, ntfy, and Gotify.

### Authentication & Scoped API Tokens

Every API route and WebSocket declares its access policy in one place ([`backend/app/api/policy.py`](../backend/app/api/policy.py)), and the complete route-by-route table is generated and verified in **[docs/security-matrix.md](security-matrix.md)**.

GravityLAN distinguishes three caller types:
1. **Browser session (`httpOnly` cookie):** Created at login (`POST /api/auth/login`). Sensitive actions require an additional password confirmation (**step-up** grant, valid for 10 minutes by default, configurable 1–60 minutes) for one of three areas:
   - `remote`: Opening SSH terminals, deploying/uninstalling/adopting agents, generating manual install codes, and running SSH package updates. **Only browser sessions with `remote` step-up are allowed here; master and API tokens always receive `403`.**
   - `credentials`: Managing SSH keys/profiles/known hosts, creating/deleting API tokens, rotating the master token, configuring Proxmox or router import credentials, and adding/retrying webhooks.
   - `instance`: Exporting or importing JSON backups, resetting the database, and changing the step-up duration.
2. **Master token (`Authorization: Bearer gl_...`):** Created during setup (stored as a SHA-256 hash) and rotatable under **Settings → Access**. Grants full read/write API access including `credentials` and `instance` endpoints without interactive step-up, but **cannot** open SSH shells, use stored SSH keys, read stored secrets, or perform `remote` actions.
3. **Scoped API tokens (`Authorization: Bearer gl_pat_...`):** Created under **Settings → API Tokens (Read-Only)** or via `POST /api/auth/tokens` (unique name required).
   - Tokens created in the Settings UI receive the default read-only scopes:
     `devices:read`, `topology:read`, `network:read`, `agent:read`, `settings:read`, `backup:read`, `scanner:read`.
   - When created via `POST /api/auth/tokens`, finer or write scopes (such as `devices:write`, `topology:write`, `network:write`, `agent:write`, `settings:write`, `scanner:start`) can be assigned.
   - **Hard boundaries for API tokens (regardless of scopes):**
     - **No SSH or remote actions:** Every `/api/ssh/*` route, agent deploy/uninstall/enroll/adopt, agent config file download (`/api/agent/download/config/{id}`), and package update route refuses API tokens with `403`. (Note: `agent:write` only allows updating monitoring parameters via `PATCH /api/agent/config/{id}`.)
     - **No credential or instance changes:** API tokens cannot create/delete tokens, export/import backups, reset the database, change Proxmox/router/webhook credentials, or change `security.stepup_minutes`.

Check which scopes your token holds at any time via `GET /api/auth/me`.

### Using the API with AI Assistants & Agents

Read-only API tokens are ideal for giving AI assistants or automation agents (such as Hermes, Clawdbot, or MCP scripts) visibility into your network without allowing them to modify anything or open shells:

1. Create a token under **Settings → API Tokens (Read-Only)** and store it in the assistant's secret store.
2. Pass it in the `Authorization` header:

```bash
curl -s -H "Authorization: Bearer gl_pat_..." http://gravitylan.local:8000/api/devices
```

**Useful read endpoints:**
- `GET /api/summary` — High-level counts of online/offline devices, subnets, and active issues.
- `GET /api/devices` — Full inventory with status, services, interfaces, and latest agent metrics.
- `GET /api/devices/mac-conflicts` — Open MAC conflict observations grouped by documented and observed MAC.
- `GET /api/health/summary` & `GET /api/health/overview` — Network health score, SLA availability, latency, and single points of failure.
- `GET /api/topology/map` & `GET /api/topology/racks` — Topology nodes/links and rack layouts.
- `GET /api/network/subnets` & `GET /api/network/gateways` — Configured subnets (with L2/L3 reachability mode) and gateways.

### Python Client (`gravitylan_api`)

For Python scripts and agents, install the bundled client from the repository checkout (requires only `requests`; see [`gravitylan_api/README.md`](../gravitylan_api/README.md)):

```bash
pip install ./gravitylan_api
```

```python
from gravitylan_api import GravityLANClient

client = GravityLANClient(
    base_url="http://gravitylan.local:8000",
    token="gl_pat_...",  # or set GRAVITYLAN_BASE_URL and GRAVITYLAN_TOKEN
)

for device in client.devices.list():
    print(device["display_name"], device["ip"], device["is_online"])
```

### Webhooks & Notification Outbox

Under **Settings → Webhooks**, GravityLAN can send event notifications to custom HTTP/HTTPS webhooks or via built-in **ntfy** and **Gotify** presets (optional bearer/access tokens are stored encrypted in the secret vault).
- **Supported events:** `device.offline`, `device.new`, `device.ip_changed`, and `scan.complete`.
- **Reliable delivery:** Events are queued in a persistent notification outbox (`notification_outbox`) and retried up to three times on failure; HTTP `3xx` redirects are not followed and count as failed deliveries.
- **SSRF & DNS-rebinding protection:** Webhook targets cannot point to the GravityLAN host itself, loopback, link-local addresses, or cloud metadata endpoints (`169.254.169.254`), and requests connect directly to the IP address verified during the safety check. Private LAN addresses are allowed so local ntfy, Gotify, or Home Assistant instances work out of the box.

---

## Deutsch

GravityLAN bietet eine REST-API (mit interaktiver Swagger UI unter `/docs`), WebSockets für Live-Daten, einen schlanken Python-Client ([`gravitylan_api`](../gravitylan_api)) sowie eine persistente Benachrichtigungs-Outbox für Webhooks, ntfy und Gotify.

### Authentifizierung & gescopte API-Tokens

Jede API-Route und jeder WebSocket deklariert seine Zugriffsregel zentral ([`backend/app/api/policy.py`](../backend/app/api/policy.py)); die vollständige, durch Tests verifizierte Übersicht aller Endpunkte steht in **[docs/security-matrix.md](security-matrix.md)**.

GravityLAN unterscheidet drei Aufrufer-Arten:
1. **Browser-Sitzung (`httpOnly`-Cookie):** Entsteht beim Login (`POST /api/auth/login`). Kritische Aktionen verlangen eine erneute Passwortbestätigung (**Step-up**, standardmäßig 10 Minuten gültig, einstellbar von 1 bis 60 Minuten) für einen von drei Bereichen:
   - `remote`: SSH-Terminals öffnen, Agenten installieren/deinstallieren/übernehmen, manuelle Installations-Codes erzeugen und Paket-Updates per SSH einspielen. **Hier sind ausschließlich Browser-Sitzungen mit `remote`-Bestätigung erlaubt; Master- und API-Tokens erhalten immer `403`.**
   - `credentials`: SSH-Keys/-Profile/Known-Hosts verwalten, API-Tokens anlegen/löschen, Master-Token rotieren, Proxmox- oder Router-Import-Zugangsdaten speichern sowie Webhooks anlegen oder erneut zustellen.
   - `instance`: JSON-Backups exportieren/importieren, Datenbank zurücksetzen und Step-up-Dauer ändern.
2. **Master-Token (`Authorization: Bearer gl_...`):** Wird beim Setup erzeugt (nur als SHA-256-Hash gespeichert) und lässt sich unter **Einstellungen → Zugriff** ersetzen. Hat vollen Lese-/Schreibzugriff auf die API inklusive `credentials`- und `instance`-Endpunkten ohne Passwortabfrage, kann aber **keine** SSH-Shells öffnen, keine gespeicherten SSH-Keys nutzen, keine Geheimnisse auslesen und keine `remote`-Aktionen ausführen.
3. **Gescopte API-Tokens (`Authorization: Bearer gl_pat_...`):** Werden unter **Einstellungen → API-Token (Read-Only)** oder über `POST /api/auth/tokens` (eindeutiger Name erforderlich) erstellt.
   - Über die Einstellungs-UI erstellte Tokens erhalten standardmäßig reine Lese-Scopes:
     `devices:read`, `topology:read`, `network:read`, `agent:read`, `settings:read`, `backup:read`, `scanner:read`.
   - Über `POST /api/auth/tokens` lassen sich gezielte Einzel- oder Schreib-Scopes vergeben (z. B. `devices:write`, `topology:write`, `network:write`, `agent:write`, `settings:write`, `scanner:start`).
   - **Feste Grenzen für API-Tokens (unabhängig vom Scope):**
     - **Kein SSH und keine Remote-Aktionen:** Alle `/api/ssh/*`-Routen, Agent-Installation/-Deinstallation/-Enrollment/-Übernahme, das Herunterladen der Agent-Konfigurationsdatei (`/api/agent/download/config/{id}`) sowie Paket-Updates lehnen API-Tokens mit `403` ab. (Hinweis: `agent:write` erlaubt lediglich das Anpassen der Überwachungsparameter über `PATCH /api/agent/config/{id}`.)
     - **Keine Zugangsdaten- oder Instanz-Änderungen:** API-Tokens können keine Tokens verwalten, keine Backups exportieren/importieren, die Datenbank nicht zurücksetzen, keine Proxmox-/Router-/Webhook-Zugangsdaten ändern und `security.stepup_minutes` nicht anpassen.

Mit `GET /api/auth/me` kann ein Token jederzeit abfragen, welche Scopes es besitzt.

### API-Nutzung für KI-Assistenten & Agenten

Schreibgeschützte API-Tokens eignen sich ideal, um KI-Assistenten oder Automatisierungs-Agenten (z. B. Hermes, Clawdbot oder eigenen Skripten) Einblick in dein Netz zu geben, ohne dass sie Einstellungen ändern oder Shells öffnen können:

1. Erstelle ein Token unter **Einstellungen → API-Token (Read-Only)** und hinterlege es im Secret-Speicher des Assistenten.
2. Sende es bei jeder Anfrage im `Authorization`-Header mit:

```bash
curl -s -H "Authorization: Bearer gl_pat_..." http://gravitylan.local:8000/api/devices
```

**Wichtige Lese-Endpunkte:**
- `GET /api/summary` — Kompakte Übersicht (Online-/Offline-Zähler, Subnetze, aktive Probleme).
- `GET /api/devices` — Komplettes Inventar mit Status, Diensten, Schnittstellen und aktuellen Agent-Metriken.
- `GET /api/devices/mac-conflicts` — Offene MAC-Konflikte, gruppiert nach dokumentierter und beobachteter MAC.
- `GET /api/health/summary` & `GET /api/health/overview` — Netzwerk-Health-Score, Verfügbarkeit, Latenz und Single Points of Failure.
- `GET /api/topology/map` & `GET /api/topology/racks` — Topologie-Knoten/-Verbindungen und Rack-Belegung.
- `GET /api/network/subnets` & `GET /api/network/gateways` — Konfigurierte Subnetze (inkl. L2/L3-Erreichbarkeit) und Gateways.

### Python-Client (`gravitylan_api`)

Für Python-Skripte und Agenten lässt sich der mitgelieferte Client direkt aus dem Repository installieren (benötigt nur `requests`; siehe [`gravitylan_api/README.md`](../gravitylan_api/README.md)):

```bash
pip install ./gravitylan_api
```

```python
from gravitylan_api import GravityLANClient

client = GravityLANClient(
    base_url="http://gravitylan.local:8000",
    token="gl_pat_...",  # oder über GRAVITYLAN_BASE_URL und GRAVITYLAN_TOKEN
)

for device in client.devices.list():
    print(device["display_name"], device["ip"], device["is_online"])
```

### Webhooks & Benachrichtigungs-Outbox

Unter **Einstellungen → Webhooks** verschickt GravityLAN Ereignisse an eigene HTTP/HTTPS-Webhooks oder über Vorlagen für **ntfy** und **Gotify** (optionale Zugriffs-Tokens werden verschlüsselt im Vault gespeichert).
- **Unterstützte Ereignisse:** `device.offline`, `device.new`, `device.ip_changed` und `scan.complete`.
- **Zuverlässige Zustellung:** Ereignisse landen in einer persistenten Outbox (`notification_outbox`) mit bis zu drei Zustellversuchen; `3xx`-Weiterleitungen werden nicht verfolgt und zählen als Fehlversuch.
- **SSRF- & DNS-Rebinding-Schutz:** Webhooks dürfen weder den GravityLAN-Host selbst noch Loopback-, Link-Local- oder Cloud-Metadaten-Adressen (`169.254.169.254`) ansprechen, und die Zustellung verbindet sich direkt mit der bei der Sicherheitsprüfung aufgelösten IP-Adresse. Private LAN-Adressen sind erlaubt, sodass lokale ntfy-, Gotify- oder Home-Assistant-Instanzen direkt erreichbar sind.
