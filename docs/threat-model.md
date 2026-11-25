# GravityLAN — Threat Model & Security Trade-offs

This document details the threat modeling, potential attack vectors, security compromises, and mitigations designed into the GravityLAN architecture.

---

## 1. Threat Scenarios & Mitigations

### Threat A: Rogue Agent Telemetry Spoofing
*   **Attack Vector**: An attacker on the local network discovers the agent reporting API endpoints and attempts to send spoofed telemetry data (CPU/RAM spikes) or register fake devices.
*   **Mitigation**: GravityLAN enforces strong, unique cryptographically-random tokens for each remote agent (`AgentToken`). Reports must include both the specific device ID and the secret agent token. Telemetry ingestion validates the token-device relationship before committing any metric data to SQLite.
*   **Trade-off**: The agent's token is stored in `/opt/gravitylan-agent/agent.conf` (`chmod 600`) on the monitored host. Access to this file is restricted to root, but local privilege escalation on the target machine could compromise the token.

### Threat B: SSH Man-in-the-Middle (MITM) during Deployment
*   **Attack Vector**: An attacker performs ARP spoofing or DNS hijacking on the local subnet to intercept the admin's remote deployment connection, capturing the target host's credentials or deploying a malicious system daemon.
*   **Mitigation**:
    *   In default mode, GravityLAN uses DB-backed host-key pinning (`ssh_known_hosts`): if a host already has a pinned key (for example confirmed in the browser SSH terminal or learned on an earlier deployment/update), `PinnedHostKeyPolicy` enforces it before any credentials are sent; if no key is pinned yet, `TofuHostKeyPolicy` learns and pins the first key.
    *   With opt-in SSH Strict Mode (`GRAVITYLAN_SSH_STRICT_MODE=true`), unknown hosts are no longer learned via TOFU: Paramiko loads `/home/gravitylan/.ssh/known_hosts` and enforces `RejectPolicy` for unknown host keys (keys already pinned in `ssh_known_hosts` continue to be verified against their pinned entry).
    *   The deployer stages the agent script and its `agent.conf` (which carries the agent token) over the SSH exec channel with a quoted heredoc. The content is written to a fresh `mktemp` file in `/tmp` (created exclusively, owner-only via `umask 077`) and then published under its predictable name with `ln`, after a leftover of an earlier run is removed. `ln` fails if a file, a FIFO or a link to a file exists at that name; a directory (or a link to one) planted there would make `ln` create the link inside it and succeed, so the deployer then checks with a single `lstat` (`ls -di`) that the name now refers to the inode of its own mktemp file. Anything a local user of the target host plants there in between makes the deploy stop instead of redirecting the write. Once the check passes, the name refers to a file owned by the SSH user, which no other user may remove or rename in the sticky `/tmp`; the token is never written through a path another user can influence. The file only exists under its predictable name once it is complete. The deployer checks the SHA-256 of the staged script on the host before it removes or replaces anything, and error messages never contain the command text. A sudo password is passed on the standard input of `sudo -S`, not in the command line.
*   **Trade-off**: Under TOFU, the very first unverified connection remains exposed to an active MITM. When Strict Mode is active, admins must pre-seed host keys in `/home/gravitylan/.ssh/known_hosts` or confirm them in the SSH terminal first.


### Threat C: Local Database & Data Directory Exposure
*   **Attack Vector**: An unauthorized user with access to the host server, Docker host permissions, or a backup reads files from `/app/data` (`gravitylan.db`, `telemetry.db`, and by default `ssh_vault.key`).
*   **Mitigation**:
    *   The admin password (Argon2) as well as the master token, API tokens, and agent tokens (SHA-256) are stored only as hashes, so a leaked copy of `gravitylan.db` alone does not yield working login or API tokens.
    *   Stored SSH keys/passwords and integration secrets (Proxmox, router import) are encrypted with Fernet (`GRAVITYLAN_VAULT_KEY`, falling back to `<data_dir>/ssh_vault.key`).
*   **Trade-off**: A Docker volume or bind mount (`/app/data`) is **not** a security boundary against host root, members of the `docker` group, or anyone who can read a full appdata backup. Because `ssh_vault.key` sits in `/app/data` by default, a copy of the entire data directory contains both the encrypted database entries and the key to decrypt them. To separate database copies from decryption keys, configure `GRAVITYLAN_VAULT_KEY` outside the data backup and remove `ssh_vault.key` from `/app/data` (see [SECURITY.md](../SECURITY.md)). Device inventories and telemetry in `gravitylan.db` / `telemetry.db` are not encrypted on disk.

---

## 2. Security Trade-off Matrix

| Feature | Homelab/Default Mode | Hardened / Strict Mode | Trade-off Impact |
| :--- | :--- | :--- | :--- |
| **SSH Key Policy** | DB-backed pinning + TOFU (`PinnedHostKeyPolicy` / `TofuHostKeyPolicy` in `ssh_known_hosts`) | DB-pinned keys + `RejectPolicy` against `/home/gravitylan/.ssh/known_hosts` (`GRAVITYLAN_SSH_STRICT_MODE=true`) | TOFU learns the key on first contact and blocks later key changes without manual file seeding, but remains exposed on the very first unverified connection. Strict mode rejects unknown hosts unless pre-seeded in `known_hosts` or previously confirmed in `ssh_known_hosts`. |
| **CORS Origins** | Strict Origin Isolation (Production) / Configurable List | Custom whitelist only | Limits public web dashboard access unless explicitly permitted by the administrator. |
| **SQLite Retention** | Configurable Retention (Default 30 days) | Compact historical retention | Keeps databases small and highly performance-optimized, at the cost of losing historical time-series metric tracking for deep retroactive analysis. |
