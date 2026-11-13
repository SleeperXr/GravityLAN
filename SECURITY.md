# Security Policy

GravityLAN is designed as a **homelab tool**. Its primary goal is to provide visibility and management capabilities for your personal, trusted network. 

## Trust Model

By design, GravityLAN assumes it is running in a **friendly network environment**. 

- **Internal Access**: The web interface and APIs are secured via token authentication, but they are not hardened against targeted, advanced attacks typically seen on the public internet.
- **Logs**: The backend log contains IP and MAC addresses of your devices on purpose (they are the inventory, and needed to debug device matching). It never contains passwords, keys or tokens. Review logs before sharing them, e.g. in a bug report.
- **Remote Access**: Do not expose GravityLAN directly to the public internet (e.g., via port forwarding). If you need remote access, use a secure VPN (like WireGuard or Tailscale) or a properly configured reverse proxy with additional authentication layers (like Authelia or Authentik).

## Docker Privileges

The GravityLAN Docker container requires specific capabilities to function correctly:
- `NET_RAW` and `NET_ADMIN`: Required for the underlying `nmap` process to perform high-speed, raw-socket network scans and OS detection.
- By default, the `Dockerfile` uses `setcap` to grant these capabilities specifically to the `nmap` binary, allowing the FastAPI application to run as a non-root user (`gravitylan`).

## Admin Login

- The admin password is stored as an Argon2 hash; signing in sets an `httpOnly` session cookie (7 days).
- Change it under **Settings → Access**. The current password must be entered, only a logged-in browser session can do this (not API or master tokens), and every other session is logged out.
- The generic settings endpoint (`POST /api/settings`) rejects the password and the master token, so they cannot be overwritten without the current password.
- The **master token** is created during setup and stored only as a SHA-256 hash (older instances convert it on the next start); it is not shown anywhere and is only replaced by a database reset. A copied database therefore holds no working token. Whoever does know it has full API access without the password confirmation for credentials and instance actions (API tokens, webhooks, SSH keys, backups, reset), but cannot open shells, use stored SSH keys or read any secret. For scripts, create an API token with the scopes they need instead.
- A logged-in session alone does not open remote access or change credentials: before terminals, agent installs, removals, manual install codes and package updates, before changes to SSH keys, saved connections, known host keys, API tokens and webhooks, and before backup export, import and the database reset, GravityLAN asks for the admin password again. A confirmation lasts 10 minutes by default (Settings → System, 1 to 60; changing it needs a confirmation itself), covers one of the three areas (remote access, credentials, instance) in that browser only, and wrong passwords count against the login limit. Terminals already open stay open. Remote actions (terminals, agent installs, removals, manual install codes and package updates) are only accepted from a browser session with this confirmation; API and master tokens receive 403 and are logged as denied.

## Agent Deployment

The GravityLAN Agent deployment feature uses SSH to install the monitoring script on remote hosts.
- SSH credentials (passwords or private keys) entered for a deployment or package update are used in memory for that request only.
- **They are not stored in the database or written to disk.**
- Host keys are trusted on first use (homelab convenience): the first deployment, removal or package update learns the host's key without asking and pins it; later, a different key aborts the connection before any credential is sent. Someone who intercepts that very first connection would receive the credentials typed in for it. The SSH terminal instead shows an unknown key for confirmation. Set `GRAVITYLAN_SSH_STRICT_MODE=true` to reject unknown keys for deployments and updates (keys already pinned, for example confirmed in the terminal, keep working), or deploy the agent manually with the provided install script.

## SSH Terminal

The browser SSH terminal is the one place where GravityLAN stores SSH credentials, on purpose (see [docs/adr/002-ssh-keystore.md](docs/adr/002-ssh-keystore.md)):
- Private keys, passphrases and saved passwords are encrypted (Fernet) with `data/ssh_vault.key` or `GRAVITYLAN_VAULT_KEY` and never sent back to the browser. Whoever controls the server or its data directory controls these keys; keep the vault key out of the data volume if that matters to you.
- What the encryption protects against: by default the vault key sits in the same data directory as the database. It then only helps when the database file alone leaks. A copy of the whole data directory (for example an appdata backup on a NAS or in the cloud) contains every stored key in usable form. To change that, set `GRAVITYLAN_VAULT_KEY` to the content of `ssh_vault.key` (or a new key from `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` before keys are stored), keep it outside that backup and then delete `ssh_vault.key` from the data directory; the variable takes precedence over the file. It does not help against root on the host, the Docker group (`docker inspect` shows environment variables) or code running in the container.
- GravityLAN holds SSH access to every host it manages, which makes its server the most valuable machine to an attacker. Use keys made only for GravityLAN, a user with narrow `sudo` rights instead of root where possible, and `from="<GravityLAN address>"` in `authorized_keys`, so a stolen key does not work from elsewhere.
- Only logged-in browser sessions can open shells; read-only API tokens and the master token cannot.
- Host keys are checked on first use and a changed key blocks the connection.
- Use the terminal over HTTPS: over plain HTTP, keystrokes (including passwords typed into the shell) cross the network unencrypted.

## Audit Log

Logs → Audit records who opened terminals, installed, updated or removed agents, changed SSH keys, saved connections,
API tokens, webhooks or the password, exported or imported backups, reset the database, and every login attempt:
time, caller (browser session, master token or the API token's name), source IP, target and result. Passwords,
keys, token values and terminal input are never recorded. Entries are kept 90 days, are not part of backups, and
survive a database reset. Behind a reverse proxy the source IP is the proxy's.

## Reporting a Vulnerability

If you discover a security vulnerability that affects the isolation or safety of the host system, please open an issue in the repository or contact the maintainer directly.

GravityLAN is maintained by one person in their spare time. A report may wait longer than usual during a break from
the project; it is read and answered when work resumes. Fixes ship as described in
[docs/RELEASING.md](docs/RELEASING.md).
