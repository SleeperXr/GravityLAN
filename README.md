<p align="center">
  <img src="./assets/logo.png" alt="GravityLAN Logo" width="250">
</p>

<h1 align="center">GravityLAN 🌌</h1>

<p align="center">
  <strong>The modern, lightweight, and incredibly practical Homelab network radar.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg" alt="React Version">
  <img src="https://img.shields.io/badge/Vibe--Coded-100%25-FF69B4.svg" alt="Vibe Coded">
</p>

---

**GravityLAN** is a network dashboard designed to give you an immediate overview of your network without the tedious, hours-long setup typical of enterprise monitoring solutions. It's built for Homelab enthusiasts who want a beautiful, functional radar for their infrastructure.

> [!NOTE]
> **100% Vibe Coded** — This tool was generated entirely through "vibe coding" with AI. I just wanted a practical, good-looking tool to keep an overview of my Homelab without having to play sysadmin for 3 days straight.

---

## ✨ Core Features

| Feature | Description |
| :--- | :--- |
| **⚡ Zero-Config Discovery** | Automatically scans multiple subnets to find devices and resolve hostnames. |
| **🚀 ARP Turbo Mode** | Ultra-fast discovery engine monitoring the local ARP table in real-time. |
| **🧠 Smart Fingerprinting** | Automatically classifies devices by open ports (Proxmox, Home Assistant, etc.). |
| **🎨 Drag-&-Drop UI** | Fully customizable dashboard layout that remembers your preferences. |
| **📱 Mobile-First** | Fully responsive interface optimized for smartphones and tablets. |
| **🌍 Multi-Language** | Full support for English and German out of the box. |

---

## 📸 Visuals

### Dashboard & Network Planner
<p align="center">
  <img src="./docs/screenshots/GravityLanDashboard.png" width="800" alt="Dashboard">
</p>

<p align="center">
  <img src="./docs/screenshots/GravityLanNetwork-Planer.png" width="400" alt="Network Planner">
  <img src="./docs/screenshots/GravitryLanDeviceEditor.png" width="400" alt="Device Editor">
</p>

### Agent Monitoring
<p align="center">
  <img src="./docs/screenshots/GravityLanDeviceEditorAgent.png" width="800" alt="Agent Dashboard">
</p>

---

## 🚀 Getting Started

### 🐳 Docker (Recommended)
The easiest way to run GravityLAN is via Docker Compose.

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
> Always run GravityLAN in **Host Network Mode**. Bridged networks will prevent the ARP scanner from seeing other devices on your LAN.

### 🛠️ Local Development (Windows)
1.  **Install Nmap**: Download from [nmap.org](https://nmap.org/download.html) and ensure it's in your **PATH**.
2.  **Run Startup Script**:
    ```powershell
    .\start_gravitylan.ps1
    ```

---

## 🏗️ Architecture

GravityLAN uses a modular scanner architecture to ensure stability and performance:

1.  **Planner Engine**: Fast discovery using ARP and lightweight ICMP/TCP probes.
2.  **Dashboard Engine**: Continuous health and service monitoring for confirmed devices.
3.  **Sync Logic**: MAC-based identity tracking to handle DHCP renewals automatically.

---

## 🔍 Under the Hood

- **Layer 2 Discovery:** Uses `arp-scan` to find devices even if they block ICMP.
- **Service Detection:** Async TCP scanner checks common Homelab ports (80, 443, 8006, 8123, etc.).
- **Optional Agent:** A lightweight Python agent for deep Linux system insights (CPU, RAM, Temp).

---

## 🤝 Contributing & License

GravityLAN is open-source under the [MIT License](LICENSE). Feel free to open issues or pull requests!

---

<p align="center">
  Made with ❤️ by <strong>SleeperXr</strong>
</p>

