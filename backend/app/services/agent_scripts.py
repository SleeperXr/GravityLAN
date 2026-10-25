"""Agent Scripts Service — Shell script and configuration templates for remote agent installation/uninstallation."""

import json
import logging
import shlex
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

INSTALL_CODE_REJECTED_SCRIPT = """#!/bin/bash
echo "Error: this GravityLAN install command is invalid, expired or was already used." >&2
echo "Copy a fresh install command from the device's Agent tab in the GravityLAN UI." >&2
exit 1
"""

_PREFERRED_IFACE_KEYWORDS = ["eth", "eno", "ens", "enp", "wlan", "wlp"]
_AVOID_IFACE_KEYWORDS = ["docker", "br-", "veth", "tailscale", "tun"]


def _pick_best_subnet(subnets) -> Any | None:
    """Pick the local subnet most likely to be the server's real interface.

    Prioritizes physical NICs and private 192.168./10. ranges while
    penalizing virtual/Docker bridge interfaces. ``None`` when no subnet
    could be selected.
    """
    if not subnets:
        return None

    def ip_priority(s):
        ip = s.ip_address
        iface = s.interface_name.lower()
        score = 0
        if any(x in iface for x in _PREFERRED_IFACE_KEYWORDS):
            score += 100
        if ip.startswith("192.168."):
            score += 50
        if ip.startswith("10."):
            score += 40
        if any(x in iface for x in _AVOID_IFACE_KEYWORDS):
            score -= 100
        return score

    return max(subnets, key=ip_priority)


def _server_url_from_ip(ip: str) -> str:
    """Build the server URL for a detected IP (port 80 omits the port)."""
    port = settings.port
    return f"http://{ip}:{port}" if port != 80 else f"http://{ip}"


async def _detect_server_url(db: AsyncSession) -> str:
    """Resolve the server URL from settings, falling back to local IP detection."""
    from app.models.setting import Setting
    from app.api.settings import check_server_url

    # Check for server_url_override (used by the settings UI) or server.url (used in API/tests)
    res = await db.execute(select(Setting).where(Setting.key.in_(("server_url_override", "server.url"))))
    setting_val = None
    if hasattr(res, "scalars"):
        try:
            settings_map = {s.key: s.value for s in res.scalars().all() if s and s.value}
            setting_val = settings_map.get("server_url_override") or settings_map.get("server.url")
        except Exception:
            pass
    if not setting_val and hasattr(res, "scalar_one_or_none"):
        mock_setting = res.scalar_one_or_none()
        if mock_setting:
            setting_val = getattr(mock_setting, "value", None)

    if setting_val:
        try:
            check_server_url(setting_val)
            return setting_val.rstrip("/")
        except ValueError as e:
            logger.warning("Ignoring unsafe server URL setting (%s); falling back to auto-detection", e)

    from app.scanner.utils import get_local_subnets
    best = _pick_best_subnet(get_local_subnets())
    if best:
        logger.info("Auto-detected server URL: %s (via %s)", _server_url_from_ip(best.ip_address), best.interface_name)
        return _server_url_from_ip(best.ip_address)

    port = settings.port
    return f"http://localhost:{port}" if port != 80 else "http://localhost"


def build_agent_config_json(server_url: str, raw_token: str, device_id: int, interval: int = 30) -> str:
    """Generate agent.conf JSON string for a specific device."""
    config_data = {
        "server_url": server_url,
        "token": raw_token,
        "device_id": device_id,
        "interval": interval,
    }
    return json.dumps(config_data, indent=2)


def build_install_script(
    server_url: str, device_id: int, enroll_code: str | None, allow_insecure: bool | None = None,
) -> str:
    """Generate the 'curl | bash' installer shell script for an agent.

    Over plain HTTP the script stops unless ALLOW_INSECURE=1 is set on the device, or the
    server allows it for every install (``GRAVITYLAN_ALLOW_INSECURE_INSTALL``, #44).
    """
    if allow_insecure is None:
        allow_insecure = settings.allow_insecure_install
    insecure_default = '\nALLOW_INSECURE="${ALLOW_INSECURE:-1}"  # GRAVITYLAN_ALLOW_INSECURE_INSTALL' if allow_insecure else ""
    quoted_server_url = shlex.quote(server_url)
    quoted_device_id = shlex.quote(str(device_id))
    quoted_enroll_code = shlex.quote(enroll_code or "")
    # From an HTTPS server, curl must not follow a redirect down to plain HTTP (#44)
    https_only = "--proto '=https' " if server_url.lower().startswith("https://") else ""

    return f"""#!/bin/bash
set -e
echo "--- GravityLAN Agent Installer ---"

INSTALL_DIR="/opt/gravitylan-agent"
SERVER_URL={quoted_server_url}
DEVICE_ID={quoted_device_id}
ENROLL_CODE={quoted_enroll_code}{insecure_default}

# Over plain HTTP the agent (run as root) and its token could be replaced or read on the way (#44)
case "$SERVER_URL" in
  http://*)
    if [ "${{ALLOW_INSECURE:-0}}" != "1" ]; then
      echo "Error: the GravityLAN server address is $SERVER_URL (plain HTTP, unencrypted)." >&2
      echo "The agent runs as root and its token is downloaded with it, so anyone on the network path could replace or read both." >&2
      echo "Recommended: set the server URL (Settings) to an HTTPS address, e.g. behind a reverse proxy," >&2
      echo "or install the agent via SSH from the device's Agent tab." >&2
      echo "To install over HTTP anyway, run the command with ALLOW_INSECURE=1:" >&2
      echo "  curl -sSL '$SERVER_URL/api/agent/download/install-sh/$DEVICE_ID?code=$ENROLL_CODE' | sudo env ALLOW_INSECURE=1 bash" >&2
      echo "(or allow it for every install on the server: GRAVITYLAN_ALLOW_INSECURE_INSTALL=true)" >&2
      exit 1
    fi
    echo "WARNING: installing over plain HTTP (ALLOW_INSECURE=1). The agent and its token are not protected on the way." >&2
    ;;
esac

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: This script must be run as root to install the agent."
  echo "Please run the command with sudo bash:"
  echo "curl {https_only}-sSL '$SERVER_URL/api/agent/download/install-sh/$DEVICE_ID?code=$ENROLL_CODE' | sudo ${{ALLOW_INSECURE:+env ALLOW_INSECURE=$ALLOW_INSECURE }}bash"
  exit 1
fi

# Check prerequisites before anything of the current installation is touched.
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "Error: Python 3 was not found on this host. Install it first (on Unraid e.g. via a Python 3 plugin) and run the command again." >&2
  exit 1
fi
if [ -d /run/systemd/system ]; then
  START_MODE="systemd"
elif [ -f /etc/synoinfo.conf ] && [ -d /usr/local/etc/rc.d ]; then
  START_MODE="synology"
else
  # e.g. Unraid (Slackware, no systemd) or OpenRC distributions
  START_MODE="background"
fi

# Download first, so an expired install code never leaves the host without its current agent.
echo "1. Downloading agent and config..."
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
curl {https_only}-fsSL "$SERVER_URL/api/agent/download/agent" -o "$TMP_DIR/gravitylan-agent.py" || {{
  echo "Error: could not download the agent from $SERVER_URL - is the GravityLAN server reachable from this host?" >&2
  exit 1
}}
curl {https_only}-fsSL "$SERVER_URL/api/agent/download/config/$DEVICE_ID?code=$ENROLL_CODE" -o "$TMP_DIR/agent.conf" || {{
  echo "Error: the install code is invalid, expired or was already used." >&2
  echo "Copy a fresh install command from the device's Agent tab in the GravityLAN UI." >&2
  exit 1
}}

echo "2. Cleaning up old versions..."
if command -v systemctl >/dev/null 2>&1; then
  systemctl stop gravitylan-agent.service 2>/dev/null || true
fi
pkill -9 -f '[g]ravitylan-agent\\.py' 2>/dev/null || true
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mv "$TMP_DIR/gravitylan-agent.py" "$TMP_DIR/agent.conf" "$INSTALL_DIR/"

echo "3. Starting the agent ($START_MODE)..."
if [ "$START_MODE" = "systemd" ]; then
cat > /etc/systemd/system/gravitylan-agent.service <<EOF
[Unit]
Description=GravityLAN System Monitor Agent
After=network-online.target

[Service]
Type=simple
ExecStart=$PYTHON_BIN $INSTALL_DIR/gravitylan-agent.py
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=10
PrivateTmp=true
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable gravitylan-agent
  systemctl restart gravitylan-agent
elif [ "$START_MODE" = "synology" ]; then
  cat > /usr/local/etc/rc.d/S99gravitylan-agent.sh <<EOF
#!/bin/sh
# GravityLAN Agent start script for Synology
case "\\$1" in
  start) cd $INSTALL_DIR && $PYTHON_BIN $INSTALL_DIR/gravitylan-agent.py > $INSTALL_DIR/gravitylan-agent.log 2>&1 < /dev/null & ;;
  stop) pkill -f '[g]ravitylan-agent\\.py' ;;
  restart) "\\$0" stop; sleep 2; "\\$0" start ;;
esac
exit 0
EOF
  chmod +x /usr/local/etc/rc.d/S99gravitylan-agent.sh
  /usr/local/etc/rc.d/S99gravitylan-agent.sh start
else
  # stdin from /dev/null: under `curl ... | bash` stdin is the script itself. No subshell,
  # so nothing keeps waiting on the agent or holding the terminal/pipe open.
  cd "$INSTALL_DIR"
  nohup "$PYTHON_BIN" "$INSTALL_DIR/gravitylan-agent.py" > "$INSTALL_DIR/gravitylan-agent.log" 2>&1 < /dev/null &
  cd - > /dev/null
fi

if [ -f /etc/unraid-version ]; then
  # Unraid runs from RAM (/opt is empty after a reboot): keep a copy on the flash drive
  # and start it from /boot/config/go. The marked block is replaced on every install.
  PERSIST_DIR="/boot/config/gravitylan-agent"
  mkdir -p "$PERSIST_DIR"
  cp "$INSTALL_DIR/gravitylan-agent.py" "$INSTALL_DIR/agent.conf" "$PERSIST_DIR/"
  touch /boot/config/go
  sed -i '/^# >>> gravitylan-agent/,/^# <<< gravitylan-agent/d' /boot/config/go
  cat >> /boot/config/go <<'GOEOF'
# >>> gravitylan-agent (added by the GravityLAN installer; delete this block to disable)
( for i in $(seq 1 60); do command -v python3 >/dev/null 2>&1 && break; sleep 5; done
  mkdir -p /opt/gravitylan-agent && cp /boot/config/gravitylan-agent/* /opt/gravitylan-agent/
  cd /opt/gravitylan-agent && exec nohup python3 gravitylan-agent.py > gravitylan-agent.log 2>&1 ) < /dev/null > /dev/null 2>&1 &
# <<< gravitylan-agent
GOEOF
  echo "   Unraid: a copy is kept on the flash drive and starts from /boot/config/go after a reboot."
elif [ "$START_MODE" = "background" ]; then
  echo "   Note: no systemd found - the agent runs in the background but will not start again by itself after a reboot."
fi

sleep 2
if pgrep -f '[g]ravitylan-agent\\.py' >/dev/null 2>&1; then
  echo "--- Installation Complete: the agent is running ---"
else
  echo "Warning: the agent does not seem to be running. See $INSTALL_DIR/gravitylan-agent.log or the service status." >&2
fi
if [ "$START_MODE" = "systemd" ]; then
  systemctl status gravitylan-agent --no-pager || true
fi
"""


def build_uninstall_script() -> str:
    """Generate the 'curl | bash' uninstaller shell script for an agent."""
    return """#!/bin/bash
echo "--- GravityLAN Agent Uninstaller ---"

INSTALL_DIR="/opt/gravitylan-agent"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: This script must be run as root to uninstall the agent."
  echo "Please run the command with sudo bash (e.g. curl -sSL ... | sudo bash)"
  exit 1
fi

echo "1. Stopping the agent..."
if command -v systemctl >/dev/null 2>&1; then
  systemctl stop gravitylan-agent.service 2>/dev/null || true
  systemctl disable gravitylan-agent.service 2>/dev/null || true
fi
if [ -x /usr/local/etc/rc.d/S99gravitylan-agent.sh ]; then
  /usr/local/etc/rc.d/S99gravitylan-agent.sh stop 2>/dev/null || true
fi
pkill -9 -f '[g]ravitylan-agent\\.py' 2>/dev/null || true

echo "2. Removing files..."
rm -f /etc/systemd/system/gravitylan-agent.service /usr/local/etc/rc.d/S99gravitylan-agent.sh
rm -rf "$INSTALL_DIR"
# Unraid: the boot hook in /boot/config/go and the copy on the flash drive
if [ -f /boot/config/go ]; then
  sed -i '/^# >>> gravitylan-agent/,/^# <<< gravitylan-agent/d' /boot/config/go
fi
rm -rf /boot/config/gravitylan-agent

if command -v systemctl >/dev/null 2>&1; then
  echo "3. Reloading systemd..."
  systemctl daemon-reload 2>/dev/null || true
fi

echo "--- Uninstallation Complete ---"
"""
