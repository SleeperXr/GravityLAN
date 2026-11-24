# Linux Agent & Package Updates

[English](#english) · [Deutsch](#deutsch)

## English

The GravityLAN Linux agent ([`agent/gravitylan-agent.py`](../agent/gravitylan-agent.py), current version `0.3.17`) is an optional, dependency-free Python 3 script that runs as a background service on Linux hosts. Network discovery, orbit topology, racks, and the browser SSH terminal work without it.

### What the Agent Reports

By default, the agent reports every 30 seconds (`POST /api/agent/report` authenticated with its per-device token, stored as a SHA-256 hash on the server):
- **System metrics:** CPU load, RAM usage, monitored disk mount points (including ZFS pools), per-interface network I/O, and CPU temperature.
- **OS & environment metadata:** Distribution name, version, kernel, architecture, and LXC container detection.
- **Pending package updates:** Counts regular and security updates (`apt`, `dnf`, `yum`), whether a system reboot is required, and whether a major OS release upgrade is available.
- **Optional Layer-2 ARP probe:** When enabled for a device inside a routed VLAN, reports local ARP neighbour pairs (`IP` + `MAC`) so GravityLAN resolves real MAC addresses and vendors across routers.

Measurement snapshots are stored in `telemetry.db` (separate from `gravitylan.db`): raw values are kept for 48 hours and then rolled up into hourly (30 days) and daily (365 days) aggregates (see [docs/metrics-history-downsampling.md](metrics-history-downsampling.md)). On `/api/agent/overview`, `uptime_pct` and the 24 hourly `uptime_history` slots report the agent's 24-hour report coverage (received against expected reports since token registration; hours before registration or without reports are `null`). If an installed agent stops reporting for three intervals (at least two minutes) while its host still answers network checks, GravityUI shows an *"agent not reporting"* notice on the Overview page.

### Installation & Enrollment

Open a device in GravityUI (**Device editor → Agent** tab) and confirm your admin password when prompted (remote-access step-up):

1. **Over SSH (recommended):**
   - Select a **saved SSH key connection** for that device (the host's SSH key must already be confirmed in the SSH terminal / `ssh_known_hosts`), or enter a one-time SSH username, password/key, and optional `sudo` password.
   - Typed-in SSH credentials are kept in memory for that request only and never stored.
   - The deployer ([ADR-001](adr/001-agent-deployment-architecture.md)) installs `/opt/gravitylan-agent/gravitylan-agent.py` and `/opt/gravitylan-agent/agent.conf` (owned by `root`, mode `0600`) and configures the service for **systemd**, **Synology `rc.d`**, **Unraid** (persisted to `/boot/config/plugins/gravitylan-agent/` across RAM reboots with `0600` permissions), or a `nohup` background fallback.
2. **One-line manual installer (`curl … | sudo bash`):**
   - Generates a single-use enrollment code (valid for 30 minutes) and a command to run on the target host.
   - The installer verifies the agent script's SHA-256 checksum before installing and writes `/opt/gravitylan-agent/agent.conf` with `0600` permissions.
   - Over plain HTTP, the manual installer requires either `ALLOW_INSECURE=1` on the target host or `GRAVITYLAN_ALLOW_INSECURE_INSTALL=true` on the server, because the enrollment code and agent token cross the network unencrypted.

### Updating & Uninstalling Agents

- **Agent Update Center:** When the server ships a newer agent version than a host is running, the Overview toolbar and the Agents page show how many agents are behind. The Agent Update Center updates multiple outdated hosts in one run (using each device's saved SSH key connection or shared credentials).
- **From the SSH Terminal:** An open browser SSH session shows an **Agent update** button that types the update command into the shell for you to review and run.
- **One-liner or per-device SSH:** Re-running the SSH deploy or the one-line installer in the device editor upgrades the script and restarts the service cleanly.
- **Token adoption:** If an agent reports with a new token (for example after a manual re-install), GravityUI offers it for adoption on the Agents page and device card (requires password confirmation).
- **Host identity pinning (agent 0.3.18):** The agent sends a fingerprint of its host: SHA-256 over `/etc/machine-id` and, when readable, `/sys/class/dmi/id/product_uuid` (readable only as root: an agent running as another user pins by the machine ID alone, and a change between the two counts as another host). The server pins it on the first report. After that, a report from another host (a clone or migrated VM that reuses `agent.conf`) and a report without a host identity are rejected with `409`, and nothing is stored, until you confirm the new host or dismiss the notice on the Agents page (password confirmation). The page shows the address the other host reports from and its fingerprint, and a confirmation only applies to the host you were shown. A new agent configuration or a newly adopted token pins again on the next report. Tokens that are not pinned yet (agents older than 0.3.18, or hosts without a readable identity) report as before.
- **Uninstalling:** Use the **Uninstall** button in the device editor's **Agent** tab (over SSH) or run the uninstall one-liner shown next to the manual installer.

### Installing OS Package Updates over SSH

On the **Agents** page, click a host with pending updates to inspect the package list and install updates over SSH:
- Authenticate with a **saved SSH key connection** (its stored username is used automatically) or type in one-time SSH credentials and an optional `sudo` password.
- Host keys are verified against `ssh_known_hosts` (pinned on first contact or in the terminal; a changed key aborts with HTTP `409` before sending credentials).
- Choose between **Security updates only** or **All updates** and watch the live output stream in the browser.

### Layer-2 Subnet Scanner (Probe)

In a routed VLAN where the GravityLAN container has no Layer-2 interface of its own, any Linux host inside that VLAN running agent `0.3.9` or newer can act as a Layer-2 ARP probe:
1. Ensure the routed VLAN is listed under **Settings → Scan subnets**.
2. In the probe device's editor (**Agent** tab → **Agent Configuration**), switch on **L2 Subnet Scanner (Probe)** and save.
3. Once a minute, the agent sweeps its local IPv4 subnets (up to 512 addresses, `/23` to `/30`) with lightweight UDP packets and a broadcast ping to populate the kernel ARP cache, then sends the discovered `IP` + `MAC` pairs with its regular metrics report.
4. GravityLAN only accepts ARP entries belonging to an enabled scan subnet that also contains the probe's own IP address, fills in missing MAC addresses and vendors, records unexpected MAC changes as MAC conflicts rather than overwriting existing device identities, and labels the subnet **L2 Probe (&lt;device&gt;)**. See [docs/multi-vlan-setup.md](multi-vlan-setup.md#option-b-agent-as-layer-2-probe) for details.

---

## Deutsch

Der GravityLAN-Linux-Agent ([`agent/gravitylan-agent.py`](../agent/gravitylan-agent.py), aktuelle Version `0.3.17`) ist ein optionales Python-3-Skript ohne externe Abhängigkeiten, das als Hintergrunddienst auf Linux-Hosts läuft. Netzwerkerkennung, Orbit-Topologie, Racks und das Browser-SSH-Terminal funktionieren auch ohne Agenten.

### Was der Agent meldet

Standardmäßig sendet der Agent alle 30 Sekunden einen Bericht (`POST /api/agent/report`, authentifiziert mit einem geräteeigenen Token, das auf dem Server als SHA-256-Hash liegt):
- **Systemmetriken:** CPU-Last, RAM-Auslastung, überwachte Laufwerkspfade (inkl. ZFS-Pools), Netzwerk-I/O je Schnittstelle und CPU-Temperatur.
- **Betriebssystem & Umgebung:** Distribution, Version, Kernel, Architektur sowie Erkennung von LXC-Containern.
- **Offene Paket-Updates:** Anzahl regulärer Updates und Sicherheits-Updates (`apt`, `dnf`, `yum`), Hinweis auf einen ausstehenden Neustart (`Reboot required`) sowie verfügbare Distributions-Upgrades.
- **Optionale Layer-2-ARP-Probe:** Meldet in gerouteten VLANs lokale ARP-Nachbarn (`IP` + `MAC`), damit GravityLAN auch hinter einem Router echte MAC-Adressen und Hersteller auflösen kann.

Die Messwerte landen in einer separaten `telemetry.db`: Rohwerte bleiben 48 Stunden erhalten und werden danach in Stundenwerte (30 Tage) und Tageswerte (365 Tage) verdichtet (siehe [docs/metrics-history-downsampling.md](metrics-history-downsampling.md)). Unter `/api/agent/overview` geben `uptime_pct` und die 24 Stundenwerte in `uptime_history` die 24-Stunden-Meldequote des Agenten an (eingetroffene gegen erwartete Berichte seit Token-Registrierung; Stunden vor der Registrierung oder ohne Meldung sind `null`). Meldet sich ein installierter Agent drei Intervalle lang nicht (mindestens zwei Minuten), während das Gerät im Netz weiter antwortet, zeigt GravityUI in der Übersicht den Hinweis *„Agent meldet sich nicht“*.

### Installation & Anmeldung

Öffne das Gerät in GravityUI (**Geräte-Editor → Tab Agent**) und bestätige bei Aufforderung dein Admin-Passwort (Step-up für Fernzugriff):

1. **Per SSH (empfohlen):**
   - Wähle eine **gespeicherte SSH-Key-Verbindung** des Geräts (der Host-Key muss zuvor im SSH-Terminal bestätigt worden sein) oder gib einmalig SSH-Benutzer, Passwort/Key und optional das `sudo`-Passwort ein.
   - Eingegebene Zugangsdaten werden nur im Arbeitsspeicher für diese Anfrage genutzt und nie gespeichert.
   - Der Deployer ([ADR-001](adr/001-agent-deployment-architecture.md)) installiert `/opt/gravitylan-agent/gravitylan-agent.py` und `/opt/gravitylan-agent/agent.conf` (Eigentümer `root`, Rechte `0600`) und richtet den Dienst für **systemd**, **Synology `rc.d`**, **Unraid** (persistiert unter `/boot/config/plugins/gravitylan-agent/` mit `0600`-Rechten über RAM-Neustarts hinweg) oder per `nohup`-Fallback ein.
2. **Manueller Einzeiler (`curl … | sudo bash`):**
   - Erzeugt einen Einmal-Code (30 Minuten gültig) und den Installationsbefehl für den Ziel-Host.
   - Das Skript prüft vor der Installation die SHA-256-Prüfsumme des Agenten und legt `/opt/gravitylan-agent/agent.conf` mit `0600`-Rechten an.
   - Über unverschlüsseltes HTTP verlangt der Einzeiler entweder `ALLOW_INSECURE=1` auf dem Ziel-Host oder `GRAVITYLAN_ALLOW_INSECURE_INSTALL=true` auf dem Server, da Einmal-Code und Agent-Token unverschlüsselt übertragen werden.

### Aktualisieren & Deinstallieren

- **Agent-Update-Center:** Liefert der Server eine neuere Agent-Version mit, zeigen die Werkzeugleiste der Übersicht und die Agents-Seite, wie viele Hosts zurückliegen. Über das Agent-Update-Center aktualisierst du sie gemeinsam (mit ihrer jeweiligen gespeicherten Key-Verbindung oder gemeinsamen Zugangsdaten).
- **Aus dem SSH-Terminal:** In einer offenen Browser-SSH-Sitzung fügt die Schaltfläche **Agent-Update** den Update-Befehl zum Prüfen und Ausführen direkt in die Shell ein.
- **Einzeiler oder Einzel-Deploy:** Ein erneuter SSH-Deploy oder Einzeiler im Geräte-Editor aktualisiert das Skript und startet den Dienst neu.
- **Token-Übernahme (Adoption):** Meldet sich ein Agent mit einem geänderten Token, bietet GravityUI auf der Agents-Seite und im Geräte-Editor die Übernahme an (mit Passwortbestätigung).
- **Host-Identität (Agent 0.3.18):** Der Agent sendet einen Fingerabdruck seines Hosts: SHA-256 über `/etc/machine-id` und, wenn lesbar, `/sys/class/dmi/id/product_uuid` (nur als root lesbar: Ein Agent unter einem anderen Benutzer bindet allein über die Maschinen-ID, und ein Wechsel zwischen beiden gilt als anderer Host). Der Server heftet ihn beim ersten Report an. Danach werden der Report eines anderen Hosts (ein Klon oder eine migrierte VM mit derselben `agent.conf`) und ein Report ohne Host-Identität mit `409` abgelehnt, und nichts wird gespeichert, bis du den neuen Host bestätigst oder den Hinweis auf der Agents-Seite verwirfst (mit Passwortbestätigung). Die Seite zeigt die Adresse, von der der andere Host meldet, und seinen Fingerabdruck; eine Bestätigung gilt nur für den Host, den du gesehen hast. Eine neue Agent-Konfiguration oder ein neu übernommener Token bindet beim nächsten Report erneut. Token, die noch nicht gebunden sind (Agents vor 0.3.18 oder Hosts ohne lesbare Identität), melden wie bisher.
- **Deinstallieren:** Über die Schaltfläche **Deinstallieren** im Tab **Agent** (per SSH) oder mit dem Deinstallations-Einzeiler neben dem manuellen Installer.

### Paket-Updates per SSH einspielen

Klicke auf der Seite **Agents** auf einen Host mit offenen Updates, um die Paketliste zu prüfen und Updates per SSH zu installieren:
- Melde dich mit einer **gespeicherten SSH-Key-Verbindung** (der hinterlegte Benutzer wird automatisch genutzt) oder mit einmalig eingegebenen Zugangsdaten samt optionalem `sudo`-Passwort an.
- Der Host-Key wird gegen `ssh_known_hosts` geprüft (beim ersten Kontakt gelernt bzw. im Terminal bestätigt; ein geänderter Key bricht vor dem Senden von Zugangsdaten mit HTTP `409` ab).
- Wähle zwischen **Nur Sicherheits-Updates** und **Alle Updates** und verfolge die Live-Ausgabe direkt im Browser.

### Layer-2-Subnetz-Scanner (Probe)

In einem gerouteten VLAN, in dem der GravityLAN-Container keine eigene Layer-2-Schnittstelle besitzt, kann ein Linux-Host mit Agent `0.3.9` oder neuer die MAC-Adressen liefern:
1. Trage das geroutete VLAN unter **Einstellungen → Scan-Subnetze** ein.
2. Schalte im Geräte-Editor der Probe (**Tab Agent → Agent-Konfiguration**) die Option **L2 Subnetz-Scanner (Probe)** ein und speichere.
3. Der Agent geht einmal pro Minute seine lokalen IPv4-Subnetze (bis 512 Adressen, `/23` bis `/30`) mit kurzen UDP-Paketen und einem Broadcast-Ping durch und sendet die ARP-Nachbarn (`IP` + `MAC`) mit seinen Metriken mit.
4. GravityLAN akzeptiert nur ARP-Einträge aus aktivierten Scan-Subnetzen, in denen auch die Probe selbst liegt, ergänzt fehlende MAC-Adressen und Hersteller, meldet abweichende MACs kontrolliert als MAC-Konflikt (statt bestehende Geräte ungefragt umzuschreiben) und markiert das Subnetz auf der Seite *IP-Adressen* als **L2 Probe (&lt;Gerät&gt;)**. Details: [docs/multi-vlan-setup.md](multi-vlan-setup.md#weg-b-agent-als-layer-2-probe).
