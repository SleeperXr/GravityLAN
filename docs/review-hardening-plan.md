# GravityLAN — Technical Review & Hardening Plan

This document details the concrete plan to harden and optimize GravityLAN across key architectural domains: Scanner stability, SSH deployment security, historical data retention, API/WebSocket resilience, and documentation completeness.

---

## 1. Scanner-Stabilität & Fehler-Resilienz (Scheduler)

### Assessment & Problemstellen
*   **Duplicate run_dashboard_scan**: In `backend/app/scanner/dashboard.py` lines 22-29 contains a duplicate dead-code stub definition that is shadowed by the full implementation starting at line 31.
*   **Implicit Failures in batch execution**: The scheduler runs four concurrent async loops (`_loop`, `_arp_loop`, `_quick_loop`, `_docker_loop`). While exceptions inside individual iterations are logged and handled via generic catch blocks, any deadlock or infinite block inside sub-tasks could stall a scheduler thread.
*   **Database connection isolation**: The background worker threads execute queries within active database contexts. Unhandled database locks or timeouts in one thread must not disrupt the other asynchronous loop threads.

### Maßnahmen
1.  **Duplicate clean**: Remove the dead duplicate stub of `run_dashboard_scan` in `backend/app/scanner/dashboard.py`.
2.  **Safeguard loops**: Refactor `ScanScheduler` loops to enforce strict, safe database connection disposal in all fallback paths.
3.  **Saubere Log-Kapselung**: Enhance error logging inside `scheduler.py` loops with traceback outputs to pinpoint exactly where jobs fail, without terminating the background tasks.

---

## 2. SSH Host-Key-Verifikation & Härtung

### Assessment & Problemstellen
*   **WarningPolicy by Default**: Paramiko currently uses `WarningPolicy` during agent deployment, which prints a warning to logs but automatically connects. This is perfect for dynamic Homelabs but poses a minor MITM risk.
*   **No configuration toggle**: There is currently no way to enforce strict host key checking (`RejectPolicy`) if a user desires high security.

### Maßnahmen
1.  **Strict Mode Config Option**: Add `ssh_strict_mode: bool = False` to `Settings` in [config.py](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/backend/app/config.py) (via environment variable `GRAVITYLAN_SSH_STRICT_MODE`).
2.  **Toggle in Deployer**: Update `deploy_agent` and `remove_agent` in [agent_deployer.py](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/backend/app/services/agent_deployer.py):
    *   If `settings.ssh_strict_mode` is `True`, set missing host key policy to `RejectPolicy`.
    *   Load system host keys via `client.load_system_host_keys()`.
3.  **Document Security Implications**: Record the trade-off in `docs/security-baseline.md` and `docs/threat-model.md` to guide users on custom hardening options.

---

## 3. Historien- & Metriken-Bereinigung (Pruning)

### Assessment & Problemstellen
*   **Incomplete Pruning**: `ScanScheduler._clean_old_history` only deletes entries from `DeviceHistory`. The potentially much larger time-series metrics table `DeviceMetrics` is never pruned, leading to eventual database bloat on low-power devices.
*   **Hardcoded defaults**: The default retention period of 7 days is hardcoded inside the loop.

### Maßnahmen
1.  **Configurable Retention**: Add `history_retention_days: int = 30` to `Settings` in [config.py](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/backend/app/config.py) (overridable via `GRAVITYLAN_HISTORY_RETENTION_DAYS`).
2.  **Complete Pruning Loop**: Update `_clean_old_history()` in [scheduler.py](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/backend/app/scanner/scheduler.py) to:
    *   Load the retention period from `settings.history_retention_days` as the fallback if no database override exists.
    *   Delete old entries from BOTH `DeviceHistory` and `DeviceMetrics`.
    *   Ensure configuration, active settings, and device state records remain untouched.
3.  **Trigger-Pfad & Ausführungssicherheit**:
    *   Der Pruning-Prozess wird deterministisch als erster Schritt beim Eintritt in die Hauptschleife `ScanScheduler._loop()` getriggert.
    *   *Sicherheit bei inaktiven Scans*: Auch wenn automatische Scans deaktiviert sind (`scan_interval = 0`), wacht die Schleife alle 60 Sekunden auf, führt den Pruning-Check durch und legt sich wieder schlafen.
    *   *Effizienz (SQLite-Schutz)*: Ein 12-Stunden-Sicherheitsfilter (`self._last_cleanup_time`) verhindert unnötige minütliche Datenbankzugriffe. Beim Applikationsstart (z. B. nach Container-Neustarts) oder bei manueller Forcierung wird die Bereinigung sofort und ohne Verzögerung ausgeführt.
    *   *Sicherheit der Daten*: Es werden ausschließlich historische Aufzeichnungen (`DeviceHistory` und `DeviceMetrics`) bereinigt. Aktuelle Gerätezustände (`Device`), Subnetz-Konfigurationen und Credentials sind zu keinem Zeitpunkt betroffen.

---

## 4. API & WebSockets-Konsistenz / WebSocket-Härtung

### Assessment & Problemstellen
*   **Graceful fallback on auth failures**: Secure WebSocket auth is crucial. When authentication fails on a WS connect, it should close with a distinct websocket close code (e.g., `4003` for forbidden/invalid credentials) to let the frontend react gracefully instead of leaking raw tracebacks or hanging.

### Maßnahmen
1.  **WS Close Codes**: Ensure `backend/app/api/auth.py` and websocket route handlers in `backend/app/main.py` explicitly close invalid/unauthorized connections with code `4008` (Policy Violation) or `4003` (Forbidden).

---

## 5. Dokumentation & Tests

### Maßnahmen
1.  **Doku**:
    *   Create [docs/security-baseline.md](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/docs/security-baseline.md).
    *   Create [docs/threat-model.md](file:///e:/Users/Oliver/Etc/Projekte/Antigravity/GravityLAN/docs/threat-model.md).
    *   Add system boundaries documentation explaining what is core (Discovery, Inventory, Topology) and what is out of scope.
2.  **Tests**:
    *   Write regression tests for the scheduler database-retention pruning loop.
    *   Write tests for the SSH host key policy selector.
