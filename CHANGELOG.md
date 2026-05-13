# Changelog

All notable changes to this project will be documented in this file.

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
