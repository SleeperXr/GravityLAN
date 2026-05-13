# Security Policy

GravityLAN is designed as a **homelab tool**. Its primary goal is to provide visibility and management capabilities for your personal, trusted network. 

## Trust Model

By design, GravityLAN assumes it is running in a **friendly network environment**. 

- **Internal Access**: The web interface and APIs are secured via token authentication, but they are not hardened against targeted, advanced attacks typically seen on the public internet.
- **Remote Access**: Do not expose GravityLAN directly to the public internet (e.g., via port forwarding). If you need remote access, use a secure VPN (like WireGuard or Tailscale) or a properly configured reverse proxy with additional authentication layers (like Authelia or Authentik).

## Docker Privileges

The GravityLAN Docker container requires specific capabilities to function correctly:
- `NET_RAW` and `NET_ADMIN`: Required for the underlying `nmap` process to perform high-speed, raw-socket network scans and OS detection.
- By default, the `Dockerfile` uses `setcap` to grant these capabilities specifically to the `nmap` binary, allowing the FastAPI application to run as a non-root user (`gravitylan`).

## Agent Deployment

The GravityLAN Agent deployment feature uses SSH to install the monitoring script on remote hosts.
- SSH credentials (passwords or private keys) are used ephemerally in memory during the deployment process.
- **They are never stored in the database or written to disk.**
- Note: The deployer uses `paramiko.AutoAddPolicy()` for host key verification. This trades strict security for homelab convenience. In highly sensitive networks, consider deploying the agent manually using the provided install script.

## Reporting a Vulnerability

If you discover a security vulnerability that affects the isolation or safety of the host system, please open an issue in the repository or contact the maintainer directly.
