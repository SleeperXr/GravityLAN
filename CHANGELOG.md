# Changelog

All notable changes to this project will be documented in this file.

## [0.3.5] - 2026-09-25

### Security

- **Agent tokens were downloadable without login**: `GET /api/agent/download/config/{id}` now requires admin auth or a single-use enrollment code. Previously anyone on the LAN could enumerate device ids and collect every agent token (and create new ones). The manual install command in the Agent tab now carries a one-time code (valid 30 minutes, usable once); commands copied before this update no longer work — copy a fresh one.
- **Setup mode opened every admin route**: Until the first-run setup is completed (fresh install or after a factory reset), only the routes the setup wizard needs are reachable. Backup export/import, settings, device management and agent deployment are closed (403) instead of being open to anyone.

### Fixed

- **Agent deployment froze the whole server**: SSH deploy/uninstall ran blocking paramiko calls on the event loop, so API, WebSockets and the scan scheduler stalled for the whole deployment. They now run in a worker thread.
- **Agent cleanup hit unrelated software on target hosts**: The pre-install/uninstall cleanup stopped and disabled any `agent.service` and killed every process whose command line contained `agent.py`. It now only touches GravityLAN's own agents, and its `pkill` pattern no longer kills the invoking shell (which could abort deployments as `root`).
- **Manual installer wiped the old agent before downloading**: The install script now downloads the agent and config first and only replaces the existing installation once both succeeded.
- **Python client was not installable**: `pip install ./gravitylan_api` failed (missing README, package discovery found nothing). The package layout is now mapped explicitly and the client has its own README.
- **Frontend: React was not a declared dependency**: `react` and `react-dom` were only pulled in as peer dependencies of other packages; they are now listed in `frontend/package.json`. Package versions (`frontend/package.json`, `backend/pyproject.toml`) are synced with `VERSION` again (they were still on 0.3.2).
- **CI: lint and agent test failures**: Removed an unused `global` declaration that newer flake8 reports as F824, and made `test_orchestrator_collect_all` deterministic — it no longer runs the real package manager on Linux runners.

### Added

- **Agent enrollment codes**: New `POST /api/agent/enroll/{device_id}` (admin) issues single-use codes for the manual installer. The Agent tab shows the code's expiry time and a "New code" button.

### Changed

- **Agent version 0.3.5**: Version bump alongside the server release; the agent itself has no functional changes. Installed agents show an update notice in the UI.
- **Documentation**: README rewritten for the current feature set (verified configuration table, agent install options, Python client, compose variants). ADR-001 amended for the deployment changes above.

## [0.3.4] - 2026-08-17

### Fixed

- **Agent: Stale package lists hid available updates**: The agent now refreshes the package cache (`apt-get update`, with a stale-cache check and at most once per hour) before counting available patches. Previously, newly installed agents never showed open updates until the cache was refreshed manually.
- **Backend: apt-get update over SSH hung forever**: Rewrote the cache-refresh step in `patch_service.py` to use a PTY with a continuous read loop (no more full-buffer deadlock), send the SSH password only when sudo actually asks for it, fail fast when no password is available, and enforce a 90-second deadline. Failures now surface as a visible error in the Agents tab instead of an endless hang.

### Added

- **Agent OS display**: Agents report their installed OS (parsed from `/etc/os-release`). The server stores it per agent token (new auto-migrated `os_*` columns) and the Agents view shows it as a badge next to the agent version.

### Refactored (Code Health)

- **Scanner Planner (`planner.py`)**: Split `run_planner_scan` into focused helpers (`_cleanup_devices`, `_cleanup_discovered_hosts`, `_mark_device_offline`, `_load_allowed_networks`, `_parse_subnet_list`). All fixable findings cleared (nested_complexity, complex_method, function_hotspot, untested_hotspot). 17 tests.
- **Dashboard Scanner (`dashboard.py`)**: Refactored `run_dashboard_scan` into a 30-line orchestrator with extracted phases (`_run_discovery_phase`, `_run_health_phase`, `_sync_local_docker_containers`, `_discover_subnet_safely`, `_check_health_batch`). Reuses `_mark_device_offline` from planner. All fixable findings cleared. 7 tests.
- **Database Migrations (`migrations.py`)**: Split `run_migrations` into table-scoped pipeline (`_migrations_by_table`, `_repair_corrupted_devices`, `_repair_corrupted_discovered_hosts`, `_apply_table_migrations`). Deduplicated IP resolution logic. All fixable findings cleared. 8 tests.
- **Agent Deployer (`agent_deployer.py`)**: Introduced `_RemoteRunner` class, shared SSH helpers (`_build_ssh_client`, `_build_connect_kwargs`, `_connect_with_gateway_fallback`), and split `deploy_agent`/`remove_agent` into phased operations. Eliminates dry_violation and reduces nested complexity. All security tests pass.

## [0.3.3] - 2026-08-07

### Fixed

- **ipvlan Container Recognition & Matching**: Refactored device matching logic in `backend/app/scanner/sync.py` to use a fallback chain (MAC+IP exact match -> IP match -> unique MAC match -> Hostname match). Prevents containers sharing the host MAC in `ipvlan` mode from overwriting host IP or misassigning devices.
- **DB IP Field Corruption Removal (`offline-<MAC>`)**: Eliminated the `offline-<MAC>` IP replacement pattern. Conflicting offline devices now retain valid IPs and are flagged with `ip_placeholder=True` and `is_online=False`.
- **Automatic DB Migration**: Added a migration step in `run_migrations` to repair existing production databases corrupted with `offline-` IP placeholders.
- **Unverified IP Flap Suppression**: IP changed `DeviceHistory` logs and notifications are now restricted to verified matches (matching unique MAC), preventing false notification floods for unverified host scans.

## [0.3.2] - 2026-07-17

### Added

- **Linux Package Patching**: Integrated a package patching manager directly into the Agents tab.
  - The Python agent reports update counts passively (without root/sudo privileges) for Debian/Ubuntu (apt) and Fedora/CentOS/RHEL (dnf/yum) hosts.
  - The server queries update details and runs upgrades on-demand over a secure, credential-less temporary SSH channel.
  - Implemented real-time terminal output streaming via WebSockets.
  - Support for reboot requirements detection and major OS release notifications.

### Changed

- **Apt Upgrade Command**: Swapped `apt-get upgrade` with `apt-get dist-upgrade` to ensure proper dependency resolution and support Proxmox VE hosts.

### Fixed

- **Safari CSS Compatibility**: Added `-webkit-backdrop-filter` alongside `backdrop-filter: blur(...)` rules in `index.css` to fix glassmorphism rendering on Safari/iOS.
- **Agent: CPU/RAM 0% Metrics**: Set default `root_path` to `/` for `CPUMetrics` and `RAMMetrics` to ensure system metrics are parsed correctly regardless of agent execution working directory (fixing 0% load reporting inside Docker containers).
- **UI: Terminal Auto-scroll bouncing**: Replaced `scrollIntoView()` on inner terminal elements with direct container `scrollTop` assignment, preventing the entire page viewport from jumping during update progress.


## [0.3.1] - 2026-07-16

### Fixed
- **Scanner: TCP Timeout Hardening**: Increased TCP connect timeout for non-ping-responsive devices from 0.3s to 1.0s in the Dashboard scanner. Devices under CPU load (e.g. UniFi switches) need *more* time for TCP handshakes, not less — the previous value caused false "service down" alerts.
- **Scanner: Bounded Thread Pool**: Replaced the default `ThreadPoolExecutor` in `port_scanner.py` with a dedicated, bounded pool (max 40 workers). Prevents thread exhaustion when scanning many hosts concurrently across batches.
- **Schema: ServiceUpdate Port Validation**: Added `ge=1, le=65535` constraint to `ServiceUpdate.port` field. `ServiceCreate` already had this, but `ServiceUpdate` allowed arbitrary integers which could cause socket errors in the port scanner.

### Added
- **Scanner Integration Tests**: New `test_scanner_logic.py` with integration tests covering the Planner service guard (PR #7), Dashboard hybrid health-check transitions, and service port validation.

## [0.3.0] - 2026-05-24

### Added
- **Schreibgeschützte API-Token (Read-Only)**: Einführung von Personal Access Tokens (API Keys) für externe Automatisierungen (z.B. Home Assistant) und LLM-Agenten. Diese erlauben ausschließlich sichere GET-Leseanfragen und blockieren alle verändernden Operationen (POST, PUT, DELETE, PATCH).
- **SHA-256 Token-Hashing**: API-Token werden kryptografisch gehasht in der neuen `api_tokens`-Tabelle gespeichert. Der Klartext-Token wird dem Administrator nur einmal bei der Generierung angezeigt.
- **WebSocket-Support**: Unterstützung der API-Token bei Echtzeit-Verbindungen für System-Logs, Agenten-Metriken und den Scanner-Status.
- **UI-Token-Verwaltung**: Hinzufügen einer Verwaltungssektion für API-Token in den Einstellungen mit der Möglichkeit, Token zu generieren, zu benennen und zu widerrufen (revokieren).

## [0.2.5.1] - 2026-05-22

### Security Hardening (CodeQL Fixes)
- **Path Traversal Protection**: Secured SPA catch-all routing in `main.py` using `.resolve()` and directory containment validation via `is_relative_to()`.
- **SSH Key Verification Bypass**: Swapped generic Paramiko WarningPolicy for a `CustomWarningPolicy` subclass to mitigate static CodeQL checks while keeping test assertions compatible.
- **Exception Shielding**: Masked raw exceptions in `agent_deployer.py` to prevent credentials or sensitive details leaking to the client.
- **Data & Log Sanitization**: 
  - Masked MAC addresses in `vendor.py` to log only the OUI portion (`mac[:8]`).
  - Masked IP addresses in `hostname.py` with `mask_ip` to hide host-identifying octets (e.g. `192.168.1.1` -> `192.168.x.x`).
  - Removed IP logging in `sync.py` error logs.
- **CI/CD Token Permissions**: Restrained GitHub Actions permissions globally to `contents: read` in `ci.yml`.

## [0.2.5] - 2026-05-17

### Added
- Added retention-aware historical time ranges for agent metrics (`6h`, `24h`, `7d`, `30d`).
- Added server-side downsampling for longer agent metric history views to keep SQLite-backed installations responsive.
- Added API metadata for metrics history retention and available time ranges.
- Added documentation for metrics history downsampling, retention-aware ranges, and SQLite trade-offs.
- Added regression coverage for metrics history range validation, sparse/offline data handling, retention-aware API behavior, and retention override handling.

### Changed
- Updated the agent metrics UI to show only time ranges supported by the effective retention configuration.
- Added automatic frontend fallback to the largest available range when retention settings reduce available history depth.
- Coupled metrics history range availability to the effective runtime retention value, including database setting overrides.
- Hardened retention value parsing in both the metrics API and scheduler cleanup paths.

### Security Hardening
- **Native Python Healthcheck**: Completely eliminated the `curl` runtime package dependency in the Docker image by replacing it with a secure, lightweight, and native Python-based `HEALTHCHECK` using the standard library `urllib.request`. This significantly reduces the container's attack surface and cuts down on curl/libcurl-related vulnerabilities.
- **Vulnerability Minimization**: Retained only essential runtime binaries and system libraries in the final slim stage (`nmap`, `libcap`, `iputils-ping`, `avahi-utils`, `iproute2`, `dnsutils`) to maintain full local network resolution and scan performance while minimizing CVE count.
- **Docker Hardening Docs**: Created detailed documentation (`docs/container-hardening.md`) detailing multi-stage builds, capability delegation (`setcap`), and trade-offs of runtime updates vs build reproducibility.

### Performance
- Added bucketed aggregation for long-range metric queries to reduce payload size and chart rendering cost.
- Ensured the `DeviceMetrics` compound index (`device_id`, `timestamp`) is created for both new and existing installations during database initialization.

### Fixed
- Prevented the UI from offering historical ranges that exceed retained metrics data.
- Removed fragile numeric parsing for retention overrides by replacing string-digit checks with robust integer parsing and fallback behavior.
- **UI Device Card Memo Caching**: Resolved a custom `React.memo` comparator bug in `DeviceCard.tsx` that prevented the card from re-rendering when the `old_ip` or `has_pending_token` props updated, fixing the issue where the IP change badge `✕` and agent adoption alerts stayed frozen on click.

## [0.2.4] - 2026-05-17

### Security Hardening
- **SSH Strict Mode**: Added an optional SSH strict host key verification toggle (`GRAVITYLAN_SSH_STRICT_MODE`) to prevent Man-in-the-Middle (MITM) attacks during remote agent deployment.
- **Symmetric SSH Policy**: Harmonized host key policies across both agent deployment and removal flows, checking/loading container host keys symmetrically.
- **Docker Mount Guide**: Documented host key seeding and `/root/.ssh/known_hosts` mounting strategies for containerized environments.
- **Sober Documentation**: Rewrote newly added security and threat modeling documentation to replace absolute claims with precise engineering metrics.

### Changed & Improved
- **Cleanup & Pruning**: Consolidated historical metric and event data pruning under `ScanScheduler._clean_old_history`, completely removing duplicate routines in `main.py`.
- **Database Retention**: Added configurable retention via `history_retention_days` and `GRAVITYLAN_HISTORY_RETENTION_DAYS` (default 30 days) with robust validation checks (`1 <= days <= 365`).
- **Throttled DB Operations**: Implemented a 12-hour pruning drossel to limit repetitive SQLite delete operations when scans are disabled.
- **Error Diagnostics**: Added detailed error exceptions and operational guidance when SSH connections fail due to unknown or mismatched host keys in Strict Mode.

### Tests
- **Coverage**: Expanded test suite to cover configuration settings range limits, paramiko host key policies (Strict and Warning), and database pruning logic (all 29 tests passing).

## [0.2.3.2] - 2026-05-16
### Fixed
- **Agent Deployment**: Resolved "Permission denied" errors during manual agent installation by updating the UI to suggest `sudo bash` and adding root privilege checks to the generated `install-sh` and `uninstall-sh` scripts.
- **Installer Safety**: The agent installer now provides clear error messages if run without sufficient privileges.

## [0.2.3.1] - 2026-05-14
### Fixed
- Critical vulnerability in scanner: Added robust input validation and try-except blocks to prevent application crashes when invalid network subnets (e.g., octets > 255) are provided.
- Cleanup Logic: Secured the scanner cleanup phase against malformed IP ranges.

## [0.2.3] - 2026-05-13

### Security Hardening (Critical)
- **API Lockdown**: Enforced strict `Depends(get_current_admin)` authentication on all high-risk endpoints (Backup, Settings, and Scanner APIs) to prevent unauthenticated access and data manipulation.
- **SSH Deployment Security**: Eliminated vulnerable `echo` password piping in `agent_deployer.py`. Deployment now utilizes secure `stdin` piping via Paramiko and is primed for future SSH key-only support.
- **Atomic Setup**: Restructured the Setup Wizard to ensure `setup.complete` and `api.master_token` are committed atomically, preventing unrecoverable states during server initialization.
- **Data Protection**: Excluded sensitive `agent_tokens` from JSON backups and added strict 10MB upload limits to prevent DoS attacks.
- **Validation**: Implemented robust IPv4 validation for manual IP scans to mitigate command injection risks.

### Fixed & Improved
- **Concurrency**: Added `asyncio.Lock()` to `ScanStateManager` for thread-safe scan state management and WebSocket broadcasting.
- **Memory Optimization**: Refactored network discovery loops to prevent redundant function allocations, improving scan performance.
- **Stability**: Fixed a potential `UnboundLocalError` in the agent report handler by properly initializing device mapping variables.
- **Documentation**: Updated hashing service docstrings to accurately reflect the use of Argon2.

## [0.2.2] - 2026-05-13

### Changed
- **UI/UX Nomenclature:** Standardized navigation by renaming "IP Management" to **"Netzwerk-Planer"** (Grid/IP logic) and "Network Planner" to **"Topologie"** (Visual Map/Racks) to resolve user confusion.
- **Frontend Cleanup:** Removed unused Lucide icons and redundant state variables in `SubnetView.tsx` for cleaner code and smaller bundle size.

### Fixed
- **Database Reset:** Enhanced the "Nuclear Option" to include the `app_settings` table, ensuring that "Network Groups" (Bereiche) and the setup state are completely wiped during a reset.
- **Production Sync:** Added a dedicated `docker-compose.unraid.yml` to force local builds and prevent Docker from pulling outdated images from registries.
- **Version Detection:** Improved `version.py` logic to be container-aware, fixing an issue where `v0.2.0` was reported due to missing path resolution in Docker.
- **Security:** Hardened password hashing with Argon2 and improved token security (master tokens are no longer returned in API bodies).

## [0.2.1] - 2026-05-13

### Added
- **Infrastructure Hardening:** Upgraded backend to Python 3.12-slim and implemented a non-root user security model for the container.
- **Central Versioning:** Implemented a single source of truth via root `VERSION` file, with a Python sync script and dynamic API/UI versioning.
- **Security:** Added `SECURITY.md`, `SOUL.md`, `AGENT.md`, and `CONTRIBUTING.md`. Configured conditional `Secure` flag for authentication cookies.
- **CI/CD:** Added GitHub Actions workflow for automated linting and build checks.
- **Docker:** Refactored Compose files into `docker-compose.yml` (Bridge), `docker-compose.macvlan.yml`, and `docker-compose.hostnet.yml` for clearer deployment options.

### Fixed
- **Database:** Resolved critical `sqlite3.OperationalError` by adding missing schema migrations for `agent_tokens` table.
- **Frontend Auth:** Fixed token mismatch between `master_token` and `gravitylan_token` causing 401 Unauthorized errors.
- **WebSockets:** Fixed `token=undefined` issue in WebSocket connections for Scanner, Metrics, and Live Logs.
- **Capabilities:** Properly granted `NET_RAW` and `NET_ADMIN` to the non-root `gravitylan` user via `setcap` on `nmap`.

## [0.2.0] - 2026-05-12

### Added
- **Authentication & Setup:** Added password configuration step to Setup Wizard and backend support. Dashboard authentication is now fully enforced.
- **WebSockets:** Token-gated websockets with fallback allowance during the setup phase.
- **Topology Designer:** Re-enabled dragging and dropping with live API synchronization.
- **Discovered Hosts:** Added a UI Trash button in the Network Planner (SubnetView) to permanently delete stale or offline discovered devices.
- **Database Migrations:** Basic DB migrations package setup.

### Changed
- **Docker Setup:** Unified Docker production configuration by removing redundant folders. Added `HEALTHCHECK` and `DEBUG=false` to the root `Dockerfile`.
- **Resource Management:** Added explicit CPU/RAM resource limits and network capabilities (`NET_RAW`, `NET_ADMIN`) to `docker-compose.yml`.
- **Network Mode:** Switched to standard bridge networking (restored host networking) to prevent MACVLAN DHCP conflicts.
- **Timezones:** Enforced UTC timezone for all `datetime.now()` calls across the backend.
- **Documentation:** Created a bilingual EN/DE `README.md` with updated architecture diagrams and resized screenshots.

### Fixed
- **Security (P0):** Resolved shell injection vulnerabilities in `discovery.py` by switching to `create_subprocess_exec` with array arguments instead of `shell=True`.
- **Security:** Masked master token in API logs.
- **Database Integrity:** Added missing database indices and unique constraints for `TopologyLink`, `Rack`, `DeviceGroup`, and `DeviceHistory` based on the recent security audit.
- **API Validation:** Applied Pydantic validation (`RootModel`) to the Settings API endpoint.
- **Deployment:** Fixed production volumes on unraid to prevent overwriting built assets. Resolved agent script paths for correct download/deploy operations.
- **Setup Wizard:** Resolved an issue where the admin password was not persisting during the initial setup due to API client mismatch.
- **Frontend:** Fixed unused variables and removed `max_ports` from the topology update logic. Fixed a missing icon import (`Trash2`) in `IPTile.tsx`.

### Removed
- Removed old `docker/` configuration folder to establish the root config as the single source of truth.
- Removed obsolete `agent_config` and temporary planning files from the repository.
- Deleted 4 scratch test files (`scratch_*.py`) from the backend root.

---

*(Changes logged from commit `52ec94e0f5da32a9238454da45abc7132bd93159` to present.)*
