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

GravityLAN allows remote deployment of system agents to Linux hosts using SSH. This process supports two distinct validation policies:

### Warning Mode (Default Policy)
*   **Behavior**: Setting `GRAVITYLAN_SSH_STRICT_MODE=False` (default) configures the deployer with Paramiko's `WarningPolicy`. If the host key of the remote host is unknown, a warning is logged, and the deployment proceeds.
*   **Use Case**: Ideal for dynamic Homelabs with frequently changing internal virtual machines, containers, or DHCP addresses where strict key pre-sharing is impractical.

### Strict Mode (Hardened Policy)
*   **Behavior**: Setting `GRAVITYLAN_SSH_STRICT_MODE=True` configures the deployer with Paramiko's `RejectPolicy`. The deployer loads system-wide known hosts (`/root/.ssh/known_hosts` inside the container). If the host key of the remote machine is not pre-registered in the known hosts list, the connection is instantly rejected.
*   **Use Case**: Recommended for stable, hardened environments to significantly mitigate Man-in-the-Middle (MITM) attacks during remote installation or uninstallation.

### SSH Key Seeding inside Docker Containers
When running GravityLAN inside a Docker container, the container filesystem is isolated from the host. To seed host keys in Strict Mode:
1. **Host-to-Container Mount**: You can mount your host machine's `known_hosts` file into the server container.
   In your `docker-compose.yml`, mount the file to `/root/.ssh/known_hosts`:
   ```yaml
   services:
     gravitylan-server:
       # ... other configurations ...
       environment:
         - GRAVITYLAN_SSH_STRICT_MODE=True
       volumes:
         - /home/youruser/.ssh/known_hosts:/root/.ssh/known_hosts:ro
   ```
2. **Container Manual Seeding**: Alternatively, you can seed the key by running `ssh-keyscan` inside the running container:
   ```bash
   docker exec -it gravitylan-server ssh-keyscan -H [target_host_ip] >> /root/.ssh/known_hosts
   ```
   *Note: Ensure the `/root/.ssh` directory exists in the container or mount before appending.*
