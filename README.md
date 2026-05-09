<p align="center">
  <img src="./assets/logo.png" alt="GravityLAN Logo" width="500">
</p>

<p align="center">
  <strong>The Essential Network Radar for Homelab Enthusiasts.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg" alt="React Version">
</p>

---

**GravityLAN** is a modern, lightweight network dashboard designed to provide an immediate overview of your local infrastructure. No complex configuration, no enterprise bloat—just a beautiful, reactive radar for your Homelab.

> [!TIP]
> **100% Vibe Coded** — This project is the result of focused AI pair programming, designed to be practical, aesthetic, and incredibly easy to deploy.

---

## ⚡ Key Features

- **Instant Discovery**: Automatically scans multiple subnets and resolves hostnames.
- **ARP Turbo Mode**: Real-time device detection using local ARP tables.
- **Service Fingerprinting**: Automatically identifies services like Proxmox, Home Assistant, and more.
- **Dynamic Dashboard**: A fully customizable drag-and-drop interface that persists your layout.
- **System Agent**: Optional lightweight agent for deep Linux system metrics (CPU, RAM, Temp).

---

## 📸 Visuals

### Live Dashboard
A responsive, interactive overview of your entire network.
![Dashboard](./docs/screenshots/GravityLanDashboard.png)

### Network Planner
Discover and manage your subnets with ease.
![Network Planner](./docs/screenshots/GravityLanNetwork-Planer.png)

### Device Management
Fine-tune device details and deploy agents with a single click.
![Device Editor](./docs/screenshots/GravitryLanDeviceEditor.png)

---

## 🚀 Getting Started

### Docker (Recommended)
Deploy GravityLAN in seconds using Docker Compose:

```yaml
services:
  gravitylan:
    image: sleeperxr/gravitylan:latest
    container_name: GravityLAN
    network_mode: host
    volumes:
      - ./data:/app/backend/data
    restart: unless-stopped
```

> [!IMPORTANT]
> **Host Network Mode** is required for raw socket access and accurate network discovery.

### Windows Development
1. **Prerequisites**: Install [Nmap](https://nmap.org/), Python 3.12+, and Node.js 18+.
2. **Start**: Run `.\start_gravitylan.ps1` from the root directory.

---

## 🤖 GravityLAN Agent

The GravityLAN Agent is a zero-dependency Python script that provides deep system insights for your Linux nodes.

- **One-Click Deploy**: Deploy via SSH directly from the UI.
- **Metrics**: Real-time CPU, RAM, Disk, and Temperature data.
- **Security**: Designed to be lightweight and non-intrusive.

---

## 🔍 Technical Details

### The Scanning Engine
1. **Layer 2 (ARP)**: Finds devices even if they ignore ICMP (Ping).
2. **Layer 3 (ICMP)**: Continuous health monitoring.
3. **Port Scanning**: High-performance async scanner for service fingerprinting.

### Tech Stack
- **Backend**: FastAPI, SQLAlchemy 2.0, Nmap.
- **Frontend**: React 18, TypeScript, Vite.

---

## 📜 License & Community

GravityLAN is open-source under the [MIT License](LICENSE). 

Built with ❤️ by **SleeperXr**
