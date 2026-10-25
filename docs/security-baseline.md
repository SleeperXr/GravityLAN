# GravityLAN — Security Baseline

This document defines the core security posture and baseline guidelines for deploying GravityLAN in Homelab and production networks.

---

## 1. System Boundaries & Scope

GravityLAN is designed as a centralized, high-performance network intelligence dashboard and telemetry aggregator for local homelabs. Its system boundaries are explicitly defined as:

### In-Scope (Protected Zones)
*   **Discovery Engine**: Asynchronous ARP/ICMP scanning and targeted service discovery on local subnets.
*   **Inventory Database**: Persistent SQLite storage containing active network device inventories, hardware MAC addresses, discovered TCP services, and hostnames.
*   **Telemetry Aggregator**: WebSocket endpoints consuming authenticated system telemetry (CPU, RAM, Disks, Network loads) from deployed GravityLAN Linux agents.
*   **User Interface / Controller**: Secure local administrator dashboard for topology creation, subnet planning, and remote agent management.

### Out-of-Scope (Excluded Zones)
*   **External/Internet Facing expose**: GravityLAN is **not** designed to be exposed directly to the public internet without an upstream reverse proxy enforcing HTTPS/TLS and additional OAuth/SSO layers.
*   **Host-Level Intrusion Prevention**: GravityLAN monitors network state and host resource metrics. It does not actively secure or firewall client hosts.
*   **Enterprise-Grade Network Access Control (NAC)**: The tool provides network topology layout visualizers but does not govern network switches, dynamic VLAN assignments, or active traffic filtering.

---

## 2. Authentication & Session Security

*   **Cookie-Based Browser Authentication**: Admin sessions are protected via a secure, local cryptographically unique `gravitylan_token` cookie stored on the browser.
*   **No Cleartext Token Transmission**: Browser sessions are kept separate from persistent API master tokens. API access via third-party integrations uses strict header token validation.
*   **WebSocket Authentication**: WebSockets (logs, scan progress) are strictly protected using the centralized `authenticate_websocket()` middleware, enforcing cookie/master/agent validation before connection upgrade. Unauthorized connections are immediately closed with dedicated close codes (`4003` / `4001`).

---

## 3. SSH Agent Deployment Policies

GravityLAN allows remote deployment of system agents to Linux hosts using SSH. With typed-in credentials, this process supports two distinct validation policies (saved key connections use a pinned host key instead, see below):

### Trust on First Use (Default Policy)
*   **Behavior**: With `GRAVITYLAN_SSH_STRICT_MODE=False` (default) the deployer pins the key stored for the host in `ssh_known_hosts`. Without an entry, the first key the host presents is accepted and stored (TOFU), as for the SSH terminal and package updates. A changed key aborts the connection after the key exchange and before authentication, so no credential is sent; the user removes the entry under SSH → Known hosts and confirms the new key in the terminal (ADR-002, decision 10). Until 0.5.4 this mode used Paramiko's `WarningPolicy` and accepted any key (issue #45).
*   **Use Case**: Homelabs where pre-sharing host keys is impractical, while still noticing a key that changes later.

### Docker Host Bypass
*   **Behavior**: Only an SSH login to the address in `GRAVITYLAN_DOCKER_HOST_IP` (the machine running the container) is retried over the Docker bridge gateway when the direct connection fails. For every other device a failed connection stays failed; until 0.5.4 any failure was retried on the gateway, so an action meant for a switched-off device could run on the Docker host (issue #46).

### Strict Mode (Hardened Policy)
*   **Behavior**: Setting `GRAVITYLAN_SSH_STRICT_MODE=True` configures the deployer with Paramiko's `RejectPolicy`. The deployer loads system-wide known hosts (`/home/gravitylan/.ssh/known_hosts` inside the container). If the host key of the remote machine is not pre-registered in the known hosts list, the connection is instantly rejected. Additionally, patch management and terminal connections leverage automated DB-backed Trust-On-First-Use (TOFU) host-key pinning in the `ssh_known_hosts` SQLite table.
*   **Use Case**: Recommended for stable, hardened environments to significantly mitigate Man-in-the-Middle (MITM) attacks during remote installation or uninstallation.

### Saved Key Connections (Pinned Host Key)
*   **Behavior**: Deploy and uninstall with a saved key connection of the SSH terminal (ADR-002, decision 9) ignore both policies above. Only a host whose key is already trusted in the terminal's known hosts (`ssh_known_hosts`) is contacted, and exactly that key is accepted; it is checked after the key exchange and before authentication, so a changed key never receives a credential. Unknown hosts have to be connected to once in the SSH terminal and their key confirmed.
*   **Scope**: Key logins only (stored passwords are not used), only for the connection's own device, and only from a logged-in browser session (API and master tokens get 403). Package updates (patching) still take typed-in credentials.

### SSH Key Seeding inside Docker Containers
When running GravityLAN inside a Docker container, the container filesystem is isolated from the host. To seed host keys in Strict Mode:
1. **Host-to-Container Mount**: You can mount your host machine's `known_hosts` file into the server container.
   In your `docker-compose.yml`, mount the file to `/home/gravitylan/.ssh/known_hosts`:
   ```yaml
   services:
     gravitylan-server:
       # ... other configurations ...
       environment:
         - GRAVITYLAN_SSH_STRICT_MODE=True
       volumes:
         - /home/youruser/.ssh/known_hosts:/home/gravitylan/.ssh/known_hosts:ro
   ```
2. **Container Manual Seeding**: Alternatively, you can seed the key by running `ssh-keyscan` inside the running container:
   ```bash
   docker exec -it gravitylan-server ssh-keyscan -H [target_host_ip] >> /home/gravitylan/.ssh/known_hosts
   ```
   *Note: Ensure the `/home/gravitylan/.ssh` directory exists in the container or mount before appending.*

