# Configuration, Operations & GravityUI Guide

[English](#english) · [Deutsch](#deutsch)

## English

This guide covers environment variables, Docker network modes, reverse proxy setup, backup and rollback procedures, and an overview of GravityUI's views.

### Server & Container Environment Variables

Most runtime options live in the database and are configured in the setup wizard or under **Settings**. The table below covers the server and container environment variables (prefix `GRAVITYLAN_`, defined in [`backend/app/config.py`](../backend/app/config.py), plus container startup variables in [`Dockerfile`](../Dockerfile) and [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh)):

| Variable | Meaning | Default |
|---|---|---|
| `GRAVITYLAN_DATA_DIR` | Persistent data directory (`gravitylan.db`, `telemetry.db`, `ssh_vault.key`, `backups/`) | `/app/data` (container) / `./data` (local) |
| `GRAVITYLAN_DATABASE_URL` | Custom SQLAlchemy database URL. Note: JSON backup export, restore, and database reset in Settings only work with the built-in SQLite database and are refused with external databases | empty |
| `GRAVITYLAN_PORT` / `GRAVITYLAN_HOST` | HTTP listen port and bind address | `8000` / `0.0.0.0` |
| `PUID` / `PGID` | UID and GID the container entrypoint drops to after preparing `/app/data` (Unraid template default: `99` / `100`) | `1000` / `1000` |
| `TZ` | Container time zone used for console log timestamps (e.g. `Europe/Berlin`). Startup logs the active zone and warns if `TZ` is missing | `UTC` |
| `GRAVITYLAN_DEBUG` | Enable verbose debug logging | `false` |
| `GRAVITYLAN_SECURE_COOKIES` | Mark the session cookie `Secure`. Enable behind HTTPS; keep `false` when opening GravityLAN over plain HTTP (otherwise browsers drop the session cookie) | `false` |
| `GRAVITYLAN_TRUSTED_PROXIES` | Comma-separated IP addresses or CIDRs of your reverse proxy (e.g. `172.18.0.0/16`). Evaluated by GravityLAN's `TrustedProxyMiddleware` before rewriting `X-Forwarded-For` and `X-Forwarded-Host` (falls back to `FORWARDED_ALLOW_IPS` if unset); custom Uvicorn launches outside the container must pass `--no-proxy-headers` (or `proxy_headers=False`) so Uvicorn does not rewrite the transport peer first | empty (`127.0.0.1,::1` only) |
| `GRAVITYLAN_CORS_ORIGINS` | Additional allowed origins as a JSON list (e.g. `["https://gravity.example.com"]`). Only needed if a reverse proxy rewrites the `Host` header without sending `X-Forwarded-Host` | empty |
| `GRAVITYLAN_VAULT_KEY` | Fernet key for encrypting stored secrets (SSH keys/passwords, router import, Proxmox, webhook tokens). If empty, generated automatically at `<data_dir>/ssh_vault.key` | empty |
| `GRAVITYLAN_SSH_STRICT_MODE` | Reject unknown SSH host keys during agent deploy and package updates against `/home/gravitylan/.ssh/known_hosts` instead of database TOFU pinning | `false` |
| `GRAVITYLAN_ALLOW_INSECURE_INSTALL` | Allow the manual one-line agent installer to run over plain HTTP without `ALLOW_INSECURE=1` on the target host | `false` |
| `GRAVITYLAN_DOCKER_HOST_IP` | LAN IP of the Docker host running GravityLAN (legacy alias `DOCKER_HOST_IP` is also read). Only unreachable SSH connections to this exact IP may retry via the Docker bridge gateway (useful with macvlan) | empty |
| `GRAVITYLAN_SSH_IDLE_TIMEOUT_MINUTES` | Close idle browser SSH terminal sessions after N minutes (`0` = never) | `30` |
| `GRAVITYLAN_SSH_MAX_SESSIONS` | Maximum concurrent browser SSH terminal sessions | `10` |
| `GRAVITYLAN_HISTORY_RETENTION_DAYS` | Retention period in days (`1` to `365`) for metrics and history | `30` |
| `GRAVITYLAN_SCAN_TIMEOUT` | Per-port socket connect timeout in seconds | `1.5` |
| `GRAVITYLAN_SCAN_WORKERS` | Scanner concurrency (`1` to `200`) | `20` |
| `GRAVITYLAN_SCAN_INTERVAL_MINUTES` | Automatic scan interval in minutes (`0` = disabled, or configured in Settings) | `0` |

*Other scope-specific variables:* `GRAVITYLAN_APP_NAME`, `GRAVITYLAN_APP_VERSION`, and `GRAVITYLAN_BUILD` are internal build/metadata fields in `Settings`; `GRAVITYLAN_BASE_URL`, `GRAVITYLAN_TOKEN`, and `GRAVITYLAN_PASSWORD` belong to the Python API client ([`docs/api-and-integrations.md`](api-and-integrations.md)); compose-file network placeholders (`GRAVITYLAN_IP`, `VLAN_*`, etc.) are covered in [`docs/multi-vlan-setup.md`](multi-vlan-setup.md).

### Data Directory Permissions & Docker Networking

**Data directory permissions:** When started as root (the default), [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh) assigns `PUID` and `PGID` to the internal `gravitylan` user, hands ownership of `/app/data` (excluding nested sub-mounts) to that user, and drops privileges via `setpriv` before starting Uvicorn. Nmap retains only its file capabilities (`cap_net_raw`, `cap_net_admin`, `cap_net_bind_service`). If started with `--user`, the entrypoint makes no ownership changes and exits with an error if `/app/data` is not writable.

**Compose variants:**
- [`docker-compose.yml`](../docker-compose.yml): Bridge networking on port `8000`. Simplest setup, but NAT prevents Layer-2 ARP/MAC discovery outside the bridge.
- [`docker-compose.hostnet.yml`](../docker-compose.hostnet.yml): Host networking (`network_mode: host`). Best Layer-2 visibility (ARP, MAC addresses, mDNS) on Linux hosts.
- [`docker-compose.macvlan.yml`](../docker-compose.macvlan.yml): Gives the container its own LAN IP (`GRAVITYLAN_IP`, `GRAVITYLAN_SUBNET`, `GRAVITYLAN_GATEWAY`, `GRAVITYLAN_INTERFACE`).
- [`docker-compose.multi-vlan.yml`](../docker-compose.multi-vlan.yml): Attaches the container to multiple 802.1Q VLAN sub-interfaces (`eth0.10`, `br0.10`, etc.) for direct Layer-2 discovery across VLANs. Detailed guide: [docs/multi-vlan-setup.md](multi-vlan-setup.md).
- [`docker-compose.unraid.yml`](../docker-compose.unraid.yml): Local source build with host networking and Unraid's `99:100` (`nobody:users`) defaults.

### Updating, Backups & Rollback

1. **Full instance backup (for upgrades and rollbacks):**
   Before upgrading the container image, **stop the container** so SQLite finishes all writes, then copy the entire `/app/data` directory (`gravitylan.db`, `telemetry.db`, and `ssh_vault.key`). If you pass `GRAVITYLAN_VAULT_KEY` via environment variable, back up that key separately; if you use `GRAVITYLAN_DATABASE_URL`, back up that external database with its own tools.
   - *Automatic pre-migration safety net:* When a new GravityLAN version starts and detects a version change (`data/.last_version`), it automatically copies `gravitylan.db` to `data/backups/gravitylan-<prev-version>-<timestamp>.db` and keeps the last three copies (this does not include `telemetry.db` or external databases).
   - *Rolling back:* Downgrading an already migrated database is not supported. Start the previous image tag (e.g. `sleeperxr/gravitylan:0.7.0`) against your stopped-container copy of `/app/data`.

2. **JSON inventory export (for moving to a new host):**
   Under **Settings → Backup** (or during the first-run setup wizard), you can export and import a JSON snapshot. An export is complete or it fails with an error (no partial file); an import refuses files whose table entries are not lists of objects before changing anything (`[]` empties a table on purpose, a missing table is left unchanged).
   - **Included:** `device_groups`, `devices`, `device_interfaces`, `services`, `discovered_hosts`, general `app_settings`, `agent_configs`, `subnets`, `topology_links`, `racks`, `rack_items`, `rack_ports`, and `rack_cables`.
   - **Excluded on purpose:** `api.admin_password`, `api.master_token`, `setup.complete`, `api_tokens`, `agent_tokens` (agents belonging to reassigned devices must be re-enrolled), `ssh_keys`, `ssh_profiles`, `ssh_known_hosts`, `ssh_history`, `router_import_sources`, `proxmox_integration`, `webhook_subscriptions`, `notification_outbox`, `audit_events`, and `telemetry.db` measurement history.

### GravityUI Views at a Glance

GravityUI (`frontend-vue/`, served at `/frontend-vue/` with `/` redirecting to it; see [ADR-003](adr/003-react-retirement.md)) is the single web interface starting with 0.8.0:

| View | Key capabilities |
|---|---|
| **Overview** | Status bar naming offline devices or down services with a **Go to problem** button, per-subnet online summary, system notices (outages, security updates, agent status, IP changes, MAC conflicts), live orbit map, and device groups (tiles or table) with service quick-links (HTTP/S, SMB path copy, `.rdp` download). Global search via `Ctrl+K` (`Cmd+K`) or `/` for the page filter. |
| **Orbit map** | Hierarchical topology around the gateway (star → switches/APs/hosts as planets → clients/VMs as moons). Includes an automatic layout assistant, hop-by-hop path tracing, edit mode for links/roles/port limits, and a **Resilience** view calculating single points of failure and backup link requirements (`Backup needed`) from modelled links and online states (without measuring live traffic). |
| **Racks** | 19-inch and 10-inch rack planner (1–60 U, front and rear view) with hardware faceplates, passive equipment (unmanaged switches, UPS, copper/fibre patch panels, power strips, blanking panels, cable guides), port definitions (RJ45, SFP, SFP+, LC, power, console), interactive cabling, and undo toasts. |
| **Health Radar** | Network health score and availability/latency history over 24 h, 7 d, or 30 d, single points of failure, incident timeline, SSL expiry, and agent patch badges. Non-24/7 client devices do not penalize the score when asleep. A device with an open MAC conflict is not probed until the conflict is adopted or dismissed; it is marked **Status unconfirmed**, and an outage is not noticed meanwhile. |
| **IP addresses** | Per-subnet address grid showing used, free, reserved, online, and offline IPs, connectivity badges (`L2 Direct`, `L3 Routed`, `L2 Probe`), quick actions (reserve, monitor, rename, port-scan, refresh), named ranges, live discovery, and recent findings. |
| **Agents** | Overview of all Linux agents with OS info, live CPU/RAM, 24 h availability, telemetry charts (6 h to 30 d), pending package and security updates with SSH patch installer, and pending token adoption. |
| **SSH terminal** | Multi-tab browser shell (desktop and mobile) with encrypted server-side key vault (OpenSSH, PEM, PuTTY `.ppk`), saved connections, known-host verification, and one-click agent update command insertion. |
| **Device editor** | Slide-over sheet with five tabs: General (name, group, physical host, rack units, 24/7 toggle, DNS 1 / DNS 2 hostname picker, manual MAC correction), Services & ports, Interfaces (multi-VLAN merge suggestions), History & status (timeline and MAC conflict resolution), and Agent (deploy, update, uninstall, config, L2 probe). |
| **Logs & Audit** | Live backend log stream (newest line on top, pause/filter/search, auto-reconnect) and a 90-day **Audit** tab recording logins, step-up actions, terminals, agent installs/updates, credential changes, backups, and resets (never logging secrets). |
| **Settings, Tutorials & About** | Scan intervals, primary/secondary DNS, scan subnets (manual, host-detected, or router import), Proxmox VE sync, telemetry retention and purge, themes (**Night**, **Starlight**, **Aurora**, **Day map**, plus custom JSON designs), browser time zone, password/master-token/API-token management, webhooks (with ntfy/Gotify presets), backup/reset, and 14 built-in bilingual tutorials. |

---

## Deutsch

Dieses Dokument beschreibt die Umgebungsvariablen, Docker-Netzwerkmodi, den Betrieb hinter einem Reverse Proxy, Backup- und Rollback-Abläufe sowie die Ansichten von GravityUI.

### Server- & Container-Umgebungsvariablen

Die meisten Optionen liegen in der Datenbank und werden im Setup-Wizard oder unter **Einstellungen** gepflegt. Die folgende Tabelle umfasst die Server- und Container-Umgebungsvariablen (Präfix `GRAVITYLAN_`, siehe [`backend/app/config.py`](../backend/app/config.py), sowie die Startvariablen aus [`Dockerfile`](../Dockerfile) und [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh)):

| Variable | Bedeutung | Standard |
|---|---|---|
| `GRAVITYLAN_DATA_DIR` | Datenverzeichnis (`gravitylan.db`, `telemetry.db`, `ssh_vault.key`, `backups/`) | `/app/data` (Container) / `./data` (lokal) |
| `GRAVITYLAN_DATABASE_URL` | Eigene SQLAlchemy-Datenbank-URL. Hinweis: JSON-Backup, Wiederherstellung und Datenbank-Reset in den Einstellungen funktionieren nur mit der integrierten SQLite-Datenbank | leer |
| `GRAVITYLAN_PORT` / `GRAVITYLAN_HOST` | HTTP-Port und Bind-Adresse | `8000` / `0.0.0.0` |
| `PUID` / `PGID` | UID und GID, unter denen der Container-Entrypoint nach Vorbereitung von `/app/data` den Server startet (Unraid-Vorlage: `99` / `100`) | `1000` / `1000` |
| `TZ` | Zeitzone des Containers für Konsolen-Logs (z. B. `Europe/Berlin`). Beim Start wird die aktive Zone protokolliert und bei fehlendem `TZ` gewarnt | `UTC` |
| `GRAVITYLAN_DEBUG` | Ausführliche Debug-Logs einschalten | `false` |
| `GRAVITYLAN_SECURE_COOKIES` | Session-Cookie als `Secure` markieren. Hinter HTTPS aktivieren; bei Zugriff über reines HTTP auf `false` lassen (sonst verwirft der Browser das Cookie) | `false` |
| `GRAVITYLAN_TRUSTED_PROXIES` | Kommagetrennte IPs oder Netze deines Reverse Proxys (z. B. `172.18.0.0/16`). Wird von GravityLANs `TrustedProxyMiddleware` vor der Auswertung von `X-Forwarded-For` und `X-Forwarded-Host` geprüft (Fallback auf `FORWARDED_ALLOW_IPS`, falls leer); eigene Uvicorn-Starts außerhalb des Containers müssen `--no-proxy-headers` (`proxy_headers=False`) setzen, damit Uvicorn den Transport-Peer nicht vorab umschreibt | leer (nur `127.0.0.1,::1`) |
| `GRAVITYLAN_CORS_ORIGINS` | Zusätzliche erlaubte Origins als JSON-Liste (z. B. `["https://gravity.example.com"]`). Nur nötig, falls ein Reverse Proxy den `Host`-Header umschreibt und kein `X-Forwarded-Host` mitsendet | leer |
| `GRAVITYLAN_VAULT_KEY` | Fernet-Schlüssel für gespeicherte Geheimnisse (SSH-Keys/-Passwörter, Router-Import, Proxmox, Webhook-Tokens). Falls leer, automatisch unter `<data_dir>/ssh_vault.key` erzeugt | leer |
| `GRAVITYLAN_SSH_STRICT_MODE` | Unbekannte SSH-Host-Keys bei Agent-Deploy und Paket-Updates anhand von `/home/gravitylan/.ssh/known_hosts` ablehnen statt DB-TOFU-Pinning | `false` |
| `GRAVITYLAN_ALLOW_INSECURE_INSTALL` | Manuellen Agent-Installations-Einzeiler über unverschlüsseltes HTTP ohne `ALLOW_INSECURE=1` erlauben | `false` |
| `GRAVITYLAN_DOCKER_HOST_IP` | LAN-IP des Docker-Hosts (das ältere Alias `DOCKER_HOST_IP` wird ebenfalls gelesen). Nur nicht erreichbare SSH-Verbindungen zu genau dieser IP dürfen über das Docker-Bridge-Gateway wiederholt werden (z. B. bei Macvlan) | leer |
| `GRAVITYLAN_SSH_IDLE_TIMEOUT_MINUTES` | Inaktive Browser-SSH-Terminals nach N Minuten schließen (`0` = nie) | `30` |
| `GRAVITYLAN_SSH_MAX_SESSIONS` | Maximal gleichzeitig offene Browser-SSH-Sitzungen | `10` |
| `GRAVITYLAN_HISTORY_RETENTION_DAYS` | Aufbewahrungsdauer in Tagen (`1` bis `365`) für Metriken und Historie | `30` |
| `GRAVITYLAN_SCAN_TIMEOUT` | Port-Verbindungs-Timeout pro Ziel in Sekunden | `1.5` |
| `GRAVITYLAN_SCAN_WORKERS` | Parallelität des Scanners (`1` bis `200`) | `20` |
| `GRAVITYLAN_SCAN_INTERVAL_MINUTES` | Intervall für automatische Scans in Minuten (`0` = aus bzw. über die Einstellungen gesteuert) | `0` |

*Weitere bereichsspezifische Variablen:* `GRAVITYLAN_APP_NAME`, `GRAVITYLAN_APP_VERSION` und `GRAVITYLAN_BUILD` sind interne Build-/Metadatenfelder in `Settings`; `GRAVITYLAN_BASE_URL`, `GRAVITYLAN_TOKEN` und `GRAVITYLAN_PASSWORD` gehören zum Python-API-Client ([`docs/api-and-integrations.md`](api-and-integrations.md#deutsch)); Platzhalter der Compose-Dateien (`GRAVITYLAN_IP`, `VLAN_*` usw.) sind in [`docs/multi-vlan-setup.md`](multi-vlan-setup.md#deutsch) beschrieben.

### Rechte im Datenordner & Docker-Netzwerkmodi

**Rechte im Datenordner:** Startet der Container als `root` (Standard), weist [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh) dem internen Benutzer `gravitylan` die IDs aus `PUID` und `PGID` zu, übergibt ihm `/app/data` (ohne darunter gemountete Fremd-Volumes) und wechselt per `setpriv` zu diesem Benutzer. Nmap behält lediglich seine Datei-Capabilities (`cap_net_raw`, `cap_net_admin`, `cap_net_bind_service`). Bei Start mit `--user` ändert der Container keine Eigentümer und bricht mit einer klaren Meldung ab, falls `/app/data` nicht beschreibbar ist.

**Compose-Varianten:**
- [`docker-compose.yml`](../docker-compose.yml): Bridge-Netzwerk auf Port `8000` (einfachster Start, durch NAT aber keine Layer-2-MAC-Erkennung außerhalb der Bridge).
- [`docker-compose.hostnet.yml`](../docker-compose.hostnet.yml): Host-Netzwerk (`network_mode: host`), beste Layer-2-Sicht (ARP, MAC-Adressen, mDNS) unter Linux.
- [`docker-compose.macvlan.yml`](../docker-compose.macvlan.yml): Eigene LAN-IP für den Container (`GRAVITYLAN_IP`, `GRAVITYLAN_SUBNET`, `GRAVITYLAN_GATEWAY`, `GRAVITYLAN_INTERFACE`).
- [`docker-compose.multi-vlan.yml`](../docker-compose.multi-vlan.yml): Verbindet den Container mit mehreren 802.1Q-VLAN-Schnittstellen (`eth0.10`, `br0.10` usw.) für direkte Layer-2-Erkennung in allen VLANs. Anleitung: [docs/multi-vlan-setup.md](multi-vlan-setup.md#deutsch).
- [`docker-compose.unraid.yml`](../docker-compose.unraid.yml): Lokaler Build mit Host-Netzwerk und Unraid-Standards (`99:100`).

### Updates, Backups & Rollback

1. **Vollständige Instanzsicherung (für Upgrades und Rollbacks):**
   **Stoppe vor einem Update den Container**, damit SQLite alle Schreibvorgänge sauber abschließt, und kopiere das gesamte Verzeichnis `/app/data` (`gravitylan.db`, `telemetry.db` und `ssh_vault.key`). Nutzt du `GRAVITYLAN_VAULT_KEY` als Umgebungsvariable, sichere diesen Schlüssel separat; bei `GRAVITYLAN_DATABASE_URL` sichere die externe Datenbank mit deren Werkzeugen.
   - *Automatische Sicherung vor Migrationen:* Erkennt GravityLAN beim Start einen Versionswechsel (`data/.last_version`), kopiert es `gravitylan.db` automatisch nach `data/backups/gravitylan-<alte-version>-<zeit>.db` und behält die letzten drei Stände (ohne `telemetry.db` und ohne externe Datenbank).
   - *Rollback:* Eine bereits migrierte Datenbank mit einer älteren Version zu starten wird nicht unterstützt. Starte das vorherige Image-Tag (z. B. `sleeperxr/gravitylan:0.7.0`) mit dem zuvor gesicherten `/app/data`-Ordner.

2. **JSON-Inventarexport (für den Umzug auf einen neuen Host):**
   Unter **Einstellungen → Backup** (oder auf der ersten Seite des Setup-Wizards) lässt sich ein JSON-Abzug exportieren und importieren. Ein Export ist vollständig oder schlägt mit einer Fehlermeldung fehl (keine Teildatei); ein Import lehnt Dateien, deren Tabelleneinträge keine Listen aus Objekten sind, ab, bevor etwas geändert wird (`[]` leert eine Tabelle bewusst, eine fehlende Tabelle bleibt unverändert).
   - **Enthalten:** `device_groups`, `devices`, `device_interfaces`, `services`, `discovered_hosts`, allgemeine `app_settings`, `agent_configs`, `subnets`, `topology_links`, `racks`, `rack_items`, `rack_ports` und `rack_cables`.
   - **Bewusst nicht enthalten:** `api.admin_password`, `api.master_token`, `setup.complete`, `api_tokens`, `agent_tokens` (Agents neu zugewiesener Geräte müssen neu angemeldet werden), `ssh_keys`, `ssh_profiles`, `ssh_known_hosts`, `ssh_history`, `router_import_sources`, `proxmox_integration`, `webhook_subscriptions`, `notification_outbox`, `audit_events` sowie die Messdaten in `telemetry.db`.

### GravityUI im Überblick

GravityUI (`frontend-vue/`, ausgeliefert unter `/frontend-vue/` mit Weiterleitung von `/`; siehe [ADR-003](adr/003-react-retirement.md)) ist ab 0.8.0 die einzige Weboberfläche:

| Ansicht | Wichtigste Funktionen |
|---|---|
| **Übersicht** | Statuszeile mit ausgefallenen Geräten/Diensten und **Zum Problem**-Sprung, Online-Status je Subnetz, Systemhinweise (Ausfälle, Sicherheits-Updates, Agent-Status, IP-Wechsel, MAC-Konflikte), Live-Orbit-Netzplan sowie Gerätegruppen (Kacheln oder Tabelle) mit Dienst-Direktlinks (HTTP/S, SMB-Pfad, `.rdp`-Download). Globale Suche per `Strg+K` (`Cmd+K`) oder `/` für den Seitenfilter. |
| **Orbit-Netzplan** | Hierarchische Topologie rund um das Gateway (Stern → Switches/APs/Hosts als Planeten → Endgeräte/VMs als Monde). Mit Layout-Assistent, Hop-für-Hop-Pfadverfolgung, Bearbeitungsmodus für Links/Rollen/Portlimits und der Ansicht **Ausfallsicherheit**, die Single Points of Failure und Backup-Pfade (`Backup needed`) aus den modellierten Verbindungen und dem Online-Status berechnet (ohne Live-Traffic-Messung). |
| **Racks** | 19- und 10-Zoll-Rack-Planer (1–60 HE, Vorder- und Rückseite) mit Hardware-Frontblenden, passiven Einbauten (unmanaged Switches, USV, Kupfer-/Glasfaser-Patchfelder, Steckdosenleisten, Blindblenden, Kabelführungen), Port-Definitionen (RJ45, SFP, SFP+, LC, Strom, Konsole), interaktiver Verkabelung und Undo-Toasts. |
| **Health-Radar** | Netzwerk-Score sowie Verfügbarkeits- und Latenzverlauf über 24 Stunden, 7 oder 30 Tage, Single Points of Failure, Vorfalls-Zeitleiste, SSL-Ablauf und Patch-Badges. Geräte ohne 24/7-Überwachung (Clients) ziehen den Score im Standby nicht herunter. Ein Gerät mit offenem MAC-Konflikt wird nicht geprüft, bis der Konflikt übernommen oder verworfen ist; es trägt die Markierung **Status unbestätigt**, und ein Ausfall wird solange nicht erkannt. |
| **IP-Adressen** | Adressraster je Subnetz (belegt, frei, reserviert, online, offline), Erreichbarkeits-Badges (`L2 Direkt`, `L3 Geroutet`, `L2 Probe`), Direktaktionen (Reservieren, Überwachen, Umbenennen, Port-Scan, Auffrischen), benannte Bereiche, Live-Erkennung und aktuelle Funde. |
| **Agents** | Alle Linux-Agenten mit Betriebssystem, Live-CPU/-RAM, 24h-Verfügbarkeit, Telemetrie-Diagrammen (6h bis 30d), offenen Paket- und Sicherheits-Updates samt SSH-Installer sowie Übernahme geänderter Agent-Keys. |
| **SSH-Terminal** | Multi-Tab-Shell im Browser (Desktop & Mobil) mit verschlüsseltem Key-Store (OpenSSH, PEM, PuTTY `.ppk`), gespeicherten Verbindungen, Host-Key-Prüfung und Knopf zum Einfügen des Agent-Update-Befehls. |
| **Geräte-Editor** | Fünf Reiter: Allgemein (Name, Gruppe, physischer Host, Rack-HE, 24/7-Schalter, Hostname-Auswahl zwischen DNS 1 und DNS 2, manuelle MAC-Korrektur), Dienste & Ports, Schnittstellen (Multi-VLAN-Zusammenführung), Verlauf & Status (Zeitleiste und MAC-Konfliktlösung) sowie Agent (Deploy, Update, Deinstallation, Konfiguration, L2-Probe). |
| **Logs & Audit** | Live-Log des Backends (neueste Zeile oben, Filter, Suche, Pause, Auto-Reconnect) und ein 90-Tage-**Audit**-Log für Anmeldungen, Passwortbestätigungen, Terminals, Agent-Aktionen, Schlüssel-/Token-Änderungen, Backups und Resets (immer ohne Geheimnisse). |
| **Einstellungen, Tutorials & Über** | Scan-Intervalle, primärer/sekundärer DNS, Scan-Subnetze (manuell, Host-erkannt oder Router-Import), Proxmox-VE-Abgleich, Telemetrie-Aufbewahrung, Designs (**Nachtnetz**, **Sternlicht**, **Aurora**, **Tagkarte** sowie eigene JSON-Designs), Browser-Zeitzone, Passwort/Master-Token/API-Tokens, Webhooks (inkl. ntfy/Gotify), Backup/Reset und 14 zweisprachige Tutorials. |
