<p align="center">
  <img src="./assets/logo_simple.png" alt="GravityLAN Logo" width="180">
</p>

<h1 align="center">GravityLAN 🌌</h1>

<p align="center">
  <strong>The minimalist Homelab network radar.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/React-18-61DAFB.svg" alt="React Version">
</p>

---

**GravityLAN** is a lightweight network dashboard built for Homelab enthusiasts. It provides an immediate overview of your infrastructure with zero tedious setup.

> [!NOTE]
> **100% Vibe Coded** — Built with AI to keep Homelab monitoring simple and aesthetic.

---

## ✨ Features

- **⚡ Zero-Config Discovery**: Automatic subnet scanning and hostname resolution.
- **🚀 ARP Turbo Mode**: Real-time discovery via local ARP tables.
- **🧠 Smart Fingerprinting**: Automatic port-based device classification.
- **🎨 Drag-&-Drop UI**: Fully customizable and persistent dashboard layout.
- **📱 Responsive**: Optimized for desktop, tablet, and mobile.

---

## 📸 Screenshots

### 🖥️ Dashboard
The central hub for all your monitored devices.
![Dashboard](./docs/screenshots/GravityLanDashboard.png)

### 🗺️ Network Planner & Editor
Discover new devices and customize their details.
![Network Planner](./docs/screenshots/GravityLanNetwork-Planer.png)
![Device Editor](./docs/screenshots/GravitryLanDeviceEditor.png)

### 🤖 System Agent
Deep system insights for Linux machines.
![Agent Dashboard](./docs/screenshots/GravityLanDeviceEditorAgent.png)

---

## 🚀 Quick Start

### 🐳 Docker
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
> Use **Host Network Mode** to allow the scanner to see your local LAN devices.

---

## 🏗️ Architecture

1.  **Planner**: Fast discovery (ARP/Ping).
2.  **Dashboard**: Health & service monitoring.
3.  **Sync**: MAC-based identity persistence.

---

## 🤝 Contributing & License

[MIT License](LICENSE) • [GitHub Issues](https://github.com/SleeperXr/GravityLAN/issues)

---

<p align="center">
  Made with ❤️ by <strong>SleeperXr</strong>
</p>


