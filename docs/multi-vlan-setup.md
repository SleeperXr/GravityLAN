# Multi-VLAN and routed subnets

[English](#english) · [Deutsch](#deutsch)

## English

GravityLAN can scan subnets it only reaches through a router, such as your other VLANs: it finds the hosts there, their names and their open services. What a scan through a router cannot deliver is the MAC address, and with it the vendor. This guide explains why and shows the ways to get them.

### Why MAC addresses go missing behind a router

- MAC addresses are resolved with ARP, and ARP only works inside one broadcast domain, that is one subnet or VLAN.
- A router forwards packets between subnets and puts its own MAC address into every frame it sends on. When GravityLAN sits in `192.168.1.0/24` and scans `192.168.20.0/24`, no ARP reply from a host in `192.168.20.0/24` ever reaches it.
- So a routed host has no MAC address at all, or, if the router answers ARP on behalf of the other subnet (proxy ARP), every routed host seems to have the router's MAC address.

GravityLAN guards against the second case: when the ARP entry of a routed address carries a MAC address that also belongs to an address in one of its own subnets (usually the gateway), or one that shows up in several /24 networks, GravityLAN drops it for that routed address instead of storing the router's MAC address.

On the **IP addresses** page a badge on every subnet shows how GravityLAN reaches it: **L2 Direct (&lt;interface&gt;)** through one of its own interfaces, **L3 Routed** through a router, or **L2 Probe (&lt;device&gt;)** through an agent inside it.

| Option | How GravityLAN gets the MAC addresses | Status |
|---|---|---|
| [A: one container interface per VLAN](#option-a-one-container-interface-per-vlan-macvlan) | The container joins every VLAN through macvlan and resolves MAC addresses itself. | Available: [`docker-compose.multi-vlan.yml`](../docker-compose.multi-vlan.yml) |
| [B: agent as layer-2 probe](#option-b-agent-as-layer-2-probe) | A Linux host with the GravityLAN agent inside the VLAN reports its ARP table. | Available: agent 0.3.8 or newer |
| [C: the router's ARP table](#option-c-the-routers-arp-table-outlook) | GravityLAN reads the ARP table of the router that connects all VLANs. | Planned, not available yet |

### Option A: one container interface per VLAN (macvlan)

The container joins each VLAN through its own macvlan network and gets an address in each of them. Every VLAN is then directly attached, so GravityLAN resolves MAC addresses there itself. This needs a Docker host whose network port carries the VLANs tagged (802.1Q trunk on the switch port).

#### Prepare the host

Debian, Ubuntu and other Linux hosts: create one VLAN interface per VLAN on the physical interface, here VLAN 20 on `eth0`:

```bash
sudo modprobe 8021q
sudo ip link add link eth0 name eth0.20 type vlan id 20
sudo ip link set dev eth0.20 up
```

These commands do not survive a reboot. To keep the VLAN interfaces, add them to your distribution's network configuration (`/etc/network/interfaces`, netplan or systemd-networkd).

Unraid: under **Settings → Network Settings** set *Enable VLANs* to *Yes* and add the VLAN numbers. With bridging switched on (the default) the VLAN interfaces are called `br0.10`, `br0.20` and so on.

#### Start the container

The template [`docker-compose.multi-vlan.yml`](../docker-compose.multi-vlan.yml) has three VLANs: main, IoT and server. Put your values into a `.env` file next to it:

```bash
VLAN_MAIN_IFACE=eth0.10
VLAN_MAIN_SUBNET=192.168.10.0/24
VLAN_MAIN_GATEWAY=192.168.10.1
GRAVITYLAN_MAIN_IP=192.168.10.250

VLAN_IOT_IFACE=eth0.20
VLAN_IOT_SUBNET=192.168.20.0/24
VLAN_IOT_GATEWAY=192.168.20.1
GRAVITYLAN_IOT_IP=192.168.20.250

VLAN_SERVER_IFACE=eth0.30
VLAN_SERVER_SUBNET=192.168.30.0/24
VLAN_SERVER_GATEWAY=192.168.30.1
GRAVITYLAN_SERVER_IP=192.168.30.250
```

Each `GRAVITYLAN_*_IP` must be a free address outside your DHCP range. For fewer VLANs, delete the network both under `services.gravitylan.networks` and under the top-level `networks`; for more, copy a block in both places. Then start it:

```bash
docker compose -f docker-compose.multi-vlan.yml up -d
```

The web interface answers on port 8000 of each of these addresses, for example `http://192.168.10.250:8000`; macvlan needs no port mapping. The template keeps its data in `./data` like the other compose files, so an existing installation moves over with its database when you stop the old container and start this one from the same folder.

#### What GravityLAN does with it

- **Scan subnets:** GravityLAN reads the container's interfaces itself. What it scans is the list under **Settings → Scan subnets**, and every subnet in that list gets a tab on the **IP addresses** page. In a new installation the setup wizard shows the detected VLANs and puts the ones you scan into the list. A VLAN added later is offered in the same place under **Detected on this host but not scanned** and goes in with one click. While the list is empty, GravityLAN scans all networks of its own interfaces.
- **Badge:** on the IP addresses page each of these VLANs shows **L2 Direct (&lt;interface&gt;)**.

#### Pitfalls

- **The Docker host cannot reach the container.** Macvlan keeps the host and its macvlan containers apart: the web interface is reachable from every other device, but not from the Docker host itself, and an agent on the Docker host cannot report to GravityLAN through these addresses. That takes an extra macvlan interface on the host.
- **One macvlan network per parent interface.** Docker refuses a second macvlan network on an interface that already has one ("already using parent interface"). Unraid, for example, creates one for every VLAN enabled in its Docker settings. Use that existing network in the compose file (`external: true`) instead of creating a new one.
- **172.x addresses on `eth0`.** GravityLAN takes an interface named `eth0` with an address starting with `172.` for the Docker bridge and ignores it. A VLAN in that range on `eth0` is therefore not offered under **Detected on this host but not scanned** and shows **L3 Routed**; add it by hand under **Settings → Scan subnets**.

### Option B: agent as layer-2 probe

When the GravityLAN host cannot join a VLAN (no tagged port, a separate building or site), a Linux host inside that VLAN that runs the GravityLAN agent can supply the MAC addresses instead: a Raspberry Pi, a VM or an LXC container with an address in that VLAN.

#### Requirements

- The host is a device in GravityLAN with the agent installed (device editor, **Agent** tab), agent 0.3.8 or newer. The active sweep described below came with agent 0.3.9.
- The host has an address in the VLAN you want to see. The agent only sees the subnets it is attached to, so you need one probe per VLAN.
- The VLAN is one of the scan subnets: add it under **Settings → Scan subnets** or with **Add Subnet** on the **IP addresses** page (both write to the same list). GravityLAN then also scans it through the router for hosts, names and services, and the page gets a tab for it.
- Nothing else has to be opened: the agent uses the same connection to GravityLAN as for its metrics.

#### Switch it on

In the device editor's **Agent** tab, under **Agent Configuration**, set **L2 Subnet Scanner (Probe)** to **Activated** and save. The agent picks the setting up with its next report.

#### What the agent does

- Once a minute it sweeps each of its own IPv4 subnets with at most 512 addresses (`/23` to `/30`): it sends one small UDP packet to every address, which makes its kernel resolve that address via ARP, plus one broadcast ping. Larger subnets are not swept; for those it reports only what is already in its ARP cache.
- With every report it reads its neighbour table (`/proc/net/arp` and `ip neigh`) and sends the IP and MAC pairs along with its metrics. There is no nmap, no port scan and no extra connection.

#### What GravityLAN does with it

- A device on the dashboard with one of these IP addresses gets the reported MAC address (a different stored one is replaced), its vendor if none is set yet, and is marked online.
- An unknown IP address becomes a discovered host with MAC address and vendor. It shows up on the **IP addresses** page, in the address map and under **Recent Findings**; its address tile can add it to the dashboard.
- On the **IP addresses** page the VLAN's tab shows **L2 Probe (&lt;device&gt;)**: it contains the probe's address and is not directly attached to GravityLAN.

### Import subnets and VLANs from the router

Instead of typing every VLAN in by hand, GravityLAN can ask the router which networks it routes: **Settings → Scan subnets → Import from router → Ask router**. The router answers with its own address in each network, which gives the subnet, the gateway and, where the router names it, the VLAN.

- **Fetch** only shows a preview. Nothing is written until you pick networks and press **Apply**.
- New networks become scan subnets with gateway and VLAN. For networks you already have, only an empty gateway or VLAN is filled in. Names and values you set are never overwritten.
- Only private networks are listed. The WAN address, loopback and link-local addresses are skipped. Networks larger than a /16 are shown but cannot be imported, just like when you enter them by hand.

#### Via SNMP (most routers)

Enable read-only SNMP (v1, v2c or v3) on the router and enter its address and the community, or the v3 user and passwords. GravityLAN reads:

- the router's interface addresses and masks (IP-MIB `ipAddrTable`, or `ipAddressTable` on newer agents), which give subnet and gateway,
- the interface names (IF-MIB `ifName`, `ifAlias`), which give the network's name,
- the VLAN ID from interface names such as `br10`, `eth0.10`, `switch0.10`, `vlan10` or `igb1_vlan10`, and a VLAN's name from Q-BRIDGE-MIB where the router offers it.

This works with OPNsense and pfSense (SNMP service), OpenWrt (`snmpd` package), MikroTik, Sophos, most business routers and firewalls, and consumer routers whose firmware offers SNMP. A FRITZ!Box has no SNMP; dedicated connectors for FRITZ!Box, OPNsense/pfSense, OpenWrt and others are planned on top of the same interface. If a router names its interfaces differently, the VLAN stays empty and you can set it on the subnet by hand.

#### Via the UniFi console (Cloud Gateway, UDM, UXG)

UniFi consoles offer an official local API. GravityLAN reads the networks with their names, VLAN IDs and gateway addresses from the network configuration:

1. In UniFi Network, create an API key under **Settings → Control Plane → Integrations**.
2. Choose **UniFi console (API key)**, enter the console's address and the key, and press **Fetch**. The site is optional; with a single site, or one called `default`, it is found automatically.
3. The console uses a self-signed certificate. On the first fetch GravityLAN shows its SHA-256 fingerprint and stops **before** sending the key. Compare the fingerprint with the one your browser shows for the console, then press **Trust fingerprint and fetch**. GravityLAN stores the fingerprint and from then on only talks to a console that presents this certificate. If the certificate changes (renewal, or someone intercepting), you are asked again.

The calls used are `GET /proxy/network/integration/v1/sites`, `…/sites/{siteId}/networks` and `…/sites/{siteId}/networks/{networkId}` (`ipv4Configuration.hostIpAddress` and `prefixLength`), as documented on developer.ui.com (Network API). Older UniFi Network versions without the networks endpoint report "does not offer this part of the UniFi Network Integration API"; update UniFi Network, or use SNMP.

UniFi Network can also switch on SNMP (v1/v2c with a community, v3 with SHA and AES-128), so the SNMP way works too. UniFi gateways are reported to name their VLAN networks `br<VLAN-ID>` (`br0` is the default network). This has not been checked against a UCG Ultra yet. The API is the better choice for UniFi anyway, because names and VLAN IDs come straight from the configuration.

#### Credentials and safety

- Community, SNMPv3 passwords and the UniFi API key are stored encrypted with the same key as the SSH key store, and only after a successful fetch. They are never sent back to the browser, never logged and not part of the JSON backup. **Delete stored credentials** removes them; a factory reset does too.
- A stored secret is only used for the router it was entered for. Pointing the import at another address requires entering it again.
- The import only contacts private LAN addresses (10/8, 172.16/12, 192.168/16, IPv6 ULA). A host name must resolve to such addresses only. Loopback, link-local, cloud metadata, carrier-grade NAT and public addresses are refused.
- API tokens need `network:read` to see the saved connection and `network:write` to fetch and apply.

### Option C: the router's ARP table (outlook)

**Not available yet.** In many homelabs one firewall or router (OPNsense, pfSense, UniFi, MikroTik and others) is the gateway of every VLAN, so its ARP table and DHCP leases already hold every active IP and MAC pair. A connector that reads them regularly over SNMP or the router's API is planned; it will build on the router connection of the subnet import above. Until then, use option A or B.

## Deutsch

GravityLAN kann Subnetze scannen, die es nur über einen Router erreicht, etwa deine anderen VLANs: Es findet dort die Hosts, ihre Namen und ihre offenen Dienste. Was ein Scan über einen Router nicht liefern kann, ist die MAC-Adresse und damit der Hersteller. Diese Anleitung erklärt, warum, und zeigt die Wege, wie GravityLAN sie trotzdem bekommt.

### Warum MAC-Adressen hinter einem Router fehlen

- MAC-Adressen werden per ARP aufgelöst, und ARP funktioniert nur innerhalb einer Broadcast-Domäne, also eines Subnetzes oder VLANs.
- Ein Router leitet Pakete zwischen Subnetzen weiter und setzt in jeden weitergeleiteten Frame seine eigene MAC-Adresse. Steht GravityLAN in `192.168.1.0/24` und scannt `192.168.20.0/24`, erreicht es keine einzige ARP-Antwort eines Hosts aus `192.168.20.0/24`.
- Ein gerouteter Host hat deshalb gar keine MAC-Adresse, oder, wenn der Router stellvertretend für das andere Subnetz auf ARP antwortet (Proxy-ARP), scheinen alle gerouteten Hosts die MAC-Adresse des Routers zu haben.

Den zweiten Fall fängt GravityLAN ab: Trägt der ARP-Eintrag einer gerouteten Adresse eine MAC-Adresse, die auch zu einer Adresse in einem seiner eigenen Subnetze gehört (meist dem Gateway), oder eine, die in mehreren /24-Netzen auftaucht, verwirft GravityLAN sie für diese geroutete Adresse, statt die MAC-Adresse des Routers zu speichern.

Auf der Seite **IP-Adressen** zeigt ein Badge an jedem Subnetz, wie GravityLAN es erreicht: **L2 Direkt (&lt;Schnittstelle&gt;)** über eine eigene Schnittstelle, **L3 Geroutet** über einen Router oder **L2 Probe (&lt;Gerät&gt;)** über einen Agenten darin.

| Weg | Wie GravityLAN an die MAC-Adressen kommt | Stand |
|---|---|---|
| [A: eine Container-Schnittstelle pro VLAN](#weg-a-eine-container-schnittstelle-pro-vlan-macvlan) | Der Container hängt per Macvlan in jedem VLAN und löst MAC-Adressen selbst auf. | Verfügbar: [`docker-compose.multi-vlan.yml`](../docker-compose.multi-vlan.yml) |
| [B: Agent als Layer-2-Probe](#weg-b-agent-als-layer-2-probe) | Ein Linux-Host mit GravityLAN-Agent im VLAN meldet seine ARP-Tabelle. | Verfügbar: Agent 0.3.8 oder neuer |
| [C: ARP-Tabelle des Routers](#weg-c-arp-tabelle-des-routers-ausblick) | GravityLAN liest die ARP-Tabelle des Routers, der alle VLANs verbindet. | Geplant, noch nicht verfügbar |

### Weg A: eine Container-Schnittstelle pro VLAN (Macvlan)

Der Container hängt über je ein eigenes Macvlan-Netz in jedem VLAN und bekommt in jedem eine eigene Adresse. Jedes VLAN ist damit direkt angebunden, GravityLAN löst die MAC-Adressen dort selbst auf. Voraussetzung ist ein Docker-Host, an dessen Netzwerkanschluss die VLANs getaggt ankommen (802.1Q-Trunk am Switch-Port).

#### Host vorbereiten

Debian, Ubuntu und andere Linux-Hosts: pro VLAN eine VLAN-Schnittstelle auf der physischen Schnittstelle anlegen, hier VLAN 20 auf `eth0`:

```bash
sudo modprobe 8021q
sudo ip link add link eth0 name eth0.20 type vlan id 20
sudo ip link set dev eth0.20 up
```

Diese Befehle überstehen keinen Neustart. Damit die VLAN-Schnittstellen bleiben, gehören sie in die Netzwerkkonfiguration deiner Distribution (`/etc/network/interfaces`, netplan oder systemd-networkd).

Unraid: unter **Settings → Network Settings** *Enable VLANs* auf *Yes* stellen und die VLAN-Nummern eintragen. Mit eingeschaltetem Bridging (Standard) heißen die VLAN-Schnittstellen `br0.10`, `br0.20` usw.

#### Container starten

Die Vorlage [`docker-compose.multi-vlan.yml`](../docker-compose.multi-vlan.yml) hat drei VLANs: Main, IoT und Server. Deine Werte kommen in eine `.env`-Datei daneben:

```bash
VLAN_MAIN_IFACE=eth0.10
VLAN_MAIN_SUBNET=192.168.10.0/24
VLAN_MAIN_GATEWAY=192.168.10.1
GRAVITYLAN_MAIN_IP=192.168.10.250

VLAN_IOT_IFACE=eth0.20
VLAN_IOT_SUBNET=192.168.20.0/24
VLAN_IOT_GATEWAY=192.168.20.1
GRAVITYLAN_IOT_IP=192.168.20.250

VLAN_SERVER_IFACE=eth0.30
VLAN_SERVER_SUBNET=192.168.30.0/24
VLAN_SERVER_GATEWAY=192.168.30.1
GRAVITYLAN_SERVER_IP=192.168.30.250
```

Jede `GRAVITYLAN_*_IP` muss eine freie Adresse außerhalb deines DHCP-Bereichs sein. Für weniger VLANs das Netz sowohl unter `services.gravitylan.networks` als auch unter dem obersten `networks` löschen, für mehr an beiden Stellen einen Block kopieren. Dann starten:

```bash
docker compose -f docker-compose.multi-vlan.yml up -d
```

Die Weboberfläche antwortet auf Port 8000 jeder dieser Adressen, zum Beispiel `http://192.168.10.250:8000`; Macvlan braucht keine Portfreigabe. Die Vorlage legt ihre Daten wie die anderen Compose-Dateien in `./data` ab. Eine bestehende Installation zieht deshalb mit ihrer Datenbank um, wenn du den alten Container stoppst und diesen aus demselben Ordner startest.

#### Was GravityLAN daraus macht

- **Scan-Subnetze:** GravityLAN liest die Schnittstellen des Containers selbst aus. Gescannt wird die Liste unter **Einstellungen → Scan-Subnetze**, und jedes Subnetz darin bekommt einen Tab auf der Seite **IP-Adressen**. Bei einer neuen Installation zeigt der Einrichtungsassistent die erkannten VLANs und trägt die gescannten in die Liste ein. Ein später hinzugekommenes VLAN bietet dieselbe Stelle unter **Auf diesem Host erkannt, aber nicht gescannt** an, ein Klick nimmt es auf. Solange die Liste leer ist, scannt GravityLAN alle Netze seiner eigenen Schnittstellen.
- **Badge:** Auf der Seite IP-Adressen zeigt jedes dieser VLANs **L2 Direkt (&lt;Schnittstelle&gt;)**.

#### Stolperfallen

- **Der Docker-Host erreicht den Container nicht.** Macvlan trennt den Host von seinen Macvlan-Containern: Die Weboberfläche ist von jedem anderen Gerät erreichbar, aber nicht vom Docker-Host selbst, und ein Agent auf dem Docker-Host kann über diese Adressen nicht an GravityLAN melden. Dafür braucht der Host eine zusätzliche eigene Macvlan-Schnittstelle.
- **Ein Macvlan-Netz pro Eltern-Schnittstelle.** Docker lehnt ein zweites Macvlan-Netz auf einer Schnittstelle ab, die schon eines hat („already using parent interface“). Unraid zum Beispiel legt für jedes in seinen Docker-Einstellungen aktivierte VLAN eines an. Dann dieses vorhandene Netz in der Compose-Datei verwenden (`external: true`), statt ein neues anzulegen.
- **172.x-Adressen auf `eth0`.** GravityLAN hält eine Schnittstelle namens `eth0` mit einer Adresse, die mit `172.` beginnt, für die Docker-Bridge und ignoriert sie. Ein VLAN aus diesem Bereich auf `eth0` wird deshalb nicht unter **Auf diesem Host erkannt, aber nicht gescannt** angeboten und zeigt **L3 Geroutet**; dann von Hand unter **Einstellungen → Scan-Subnetze** eintragen.

### Weg B: Agent als Layer-2-Probe

Kann der GravityLAN-Host einem VLAN nicht beitreten (kein getaggter Port, anderes Gebäude oder anderer Standort), kann ein Linux-Host in diesem VLAN mit GravityLAN-Agent die MAC-Adressen liefern: ein Raspberry Pi, eine VM oder ein LXC-Container mit einer Adresse im VLAN.

#### Voraussetzungen

- Der Host ist ein Gerät in GravityLAN mit installiertem Agenten (Geräte-Editor, Tab **Agent**), Agent 0.3.8 oder neuer. Den unten beschriebenen aktiven Durchlauf gibt es seit Agent 0.3.9.
- Der Host hat eine Adresse in dem VLAN, das du sehen willst. Der Agent sieht nur die Subnetze, in denen er selbst hängt; pro VLAN braucht es also eine Probe.
- Das VLAN ist eines der Scan-Subnetze: unter **Einstellungen → Scan-Subnetze** oder mit **Subnetz hinzufügen** auf der Seite **IP-Adressen** eintragen (beides schreibt in dieselbe Liste). GravityLAN scannt es dann zusätzlich über den Router nach Hosts, Namen und Diensten, und die Seite bekommt einen Tab dafür.
- Freigeben musst du sonst nichts: Der Agent nutzt dieselbe Verbindung zu GravityLAN wie für seine Metriken.

#### Einschalten

Im Tab **Agent** des Geräte-Editors unter **Agent-Konfiguration** **L2 Subnetz-Scanner (Probe)** auf **Aktiviert** stellen und speichern. Der Agent übernimmt die Einstellung mit seiner nächsten Meldung.

#### Was der Agent macht

- Einmal pro Minute geht er jedes seiner eigenen IPv4-Subnetze mit höchstens 512 Adressen durch (`/23` bis `/30`): Er schickt an jede Adresse ein kleines UDP-Paket, wodurch sein Kernel die Adresse per ARP auflöst, und dazu einen Broadcast-Ping. Größere Subnetze geht er nicht durch; für sie meldet er nur, was ohnehin in seinem ARP-Cache steht.
- Mit jeder Meldung liest er seine Nachbartabelle (`/proc/net/arp` und `ip neigh`) und schickt die IP-MAC-Paare mit seinen Metriken mit. Es gibt kein nmap, keinen Portscan und keine zusätzliche Verbindung.

#### Was GravityLAN daraus macht

- Ein Gerät im Dashboard mit einer dieser IP-Adressen bekommt die gemeldete MAC-Adresse (eine andere gespeicherte wird ersetzt), den Hersteller, falls noch keiner gesetzt ist, und wird als online markiert.
- Eine unbekannte IP-Adresse wird zu einem gefundenen Host mit MAC-Adresse und Hersteller. Er erscheint auf der Seite **IP-Adressen**, in der Adresskarte und unter **Aktuelle Funde**; über seine Adresskachel lässt er sich ins Dashboard übernehmen.
- Auf der Seite **IP-Adressen** zeigt der Tab des VLANs **L2 Probe (&lt;Gerät&gt;)**: Er enthält die Adresse der Probe und hängt nicht direkt an GravityLAN.

### Subnetze und VLANs vom Router importieren

Statt jedes VLAN von Hand einzutragen, kann GravityLAN den Router fragen, welche Netze er routet: **Einstellungen → Scan-Subnetze → Vom Router importieren → Router abfragen**. Der Router meldet seine eigene Adresse in jedem Netz. Daraus ergeben sich Subnetz, Gateway und, wenn der Router es benennt, das VLAN.

- **Abrufen** zeigt nur eine Vorschau. Geschrieben wird erst, wenn du Netze auswählst und **Übernehmen** drückst.
- Neue Netze werden als Scan-Subnetze mit Gateway und VLAN angelegt. Bei vorhandenen Netzen wird nur ein leeres Gateway oder VLAN ergänzt. Namen und Werte, die du gesetzt hast, werden nie überschrieben.
- Aufgeführt werden nur private Netze. WAN-Adresse, Loopback- und Link-Local-Adressen fallen weg. Netze größer als /16 werden angezeigt, lassen sich aber wie bei der Eingabe von Hand nicht übernehmen.

#### Per SNMP (die meisten Router)

Am Router lesendes SNMP (v1, v2c oder v3) einschalten und Adresse sowie Community bzw. v3-Benutzer und -Passwörter eintragen. GravityLAN liest:

- die Adressen und Masken der Router-Schnittstellen (IP-MIB `ipAddrTable`, bei neueren Agenten `ipAddressTable`), daraus Subnetz und Gateway,
- die Schnittstellennamen (IF-MIB `ifName`, `ifAlias`), daraus den Namen des Netzes,
- die VLAN-ID aus Schnittstellennamen wie `br10`, `eth0.10`, `switch0.10`, `vlan10` oder `igb1_vlan10`, und den Namen eines VLANs aus der Q-BRIDGE-MIB, wenn der Router sie anbietet.

Das funktioniert mit OPNsense und pfSense (SNMP-Dienst), OpenWrt (Paket `snmpd`), MikroTik, Sophos, den meisten Business-Routern und Firewalls sowie mit Consumer-Routern, deren Firmware SNMP anbietet. Eine FRITZ!Box hat kein SNMP. Eigene Konnektoren für FRITZ!Box, OPNsense/pfSense, OpenWrt und weitere sind auf derselben Schnittstelle geplant. Benennt ein Router seine Schnittstellen anders, bleibt das VLAN leer und lässt sich am Subnetz von Hand eintragen.

#### Per UniFi-Konsole (Cloud Gateway, UDM, UXG)

UniFi-Konsolen bieten eine offizielle lokale API. GravityLAN liest daraus die Netze mit Namen, VLAN-IDs und Gateway-Adressen aus der Netzwerkkonfiguration:

1. In UniFi Network unter **Einstellungen → Control Plane → Integrationen** einen API-Key erstellen.
2. **UniFi-Konsole (API-Key)** wählen, Adresse der Konsole und Key eintragen, **Abrufen** drücken. Die Site ist optional; bei nur einer Site oder einer namens `default` wird sie automatisch gefunden.
3. Die Konsole nutzt ein selbstsigniertes Zertifikat. Beim ersten Abruf zeigt GravityLAN dessen SHA-256-Fingerabdruck und bricht ab, **bevor** der Key gesendet wird. Fingerabdruck mit dem vergleichen, den dein Browser für die Konsole anzeigt, dann **Fingerabdruck vertrauen und abrufen** drücken. GravityLAN speichert den Fingerabdruck und spricht danach nur noch mit einer Konsole, die genau dieses Zertifikat zeigt. Ändert sich das Zertifikat (Erneuerung oder jemand fängt die Verbindung ab), wird erneut gefragt.

Verwendet werden `GET /proxy/network/integration/v1/sites`, `…/sites/{siteId}/networks` und `…/sites/{siteId}/networks/{networkId}` (`ipv4Configuration.hostIpAddress` und `prefixLength`), wie auf developer.ui.com (Network API) dokumentiert. Ältere UniFi-Network-Versionen ohne den Netzwerk-Endpunkt melden „does not offer this part of the UniFi Network Integration API“; dann UniFi Network aktualisieren oder SNMP nutzen.

UniFi Network kann auch SNMP einschalten (v1/v2c mit Community, v3 mit SHA und AES-128), der SNMP-Weg geht also ebenfalls. UniFi-Gateways benennen ihre VLAN-Netze nach Berichten aus der Community `br<VLAN-ID>` (`br0` ist das Standardnetz). An einem UCG Ultra ist das noch nicht geprüft. Für UniFi ist die API ohnehin die bessere Wahl, weil Namen und VLAN-IDs direkt aus der Konfiguration kommen.

#### Zugangsdaten und Sicherheit

- Community, SNMPv3-Passwörter und der UniFi-API-Key werden mit demselben Schlüssel wie der SSH-Key-Store verschlüsselt gespeichert, und zwar erst nach einem erfolgreichen Abruf. Sie gehen nie an den Browser zurück, landen nicht in Logs und sind nicht Teil des JSON-Backups. **Gespeicherte Zugangsdaten löschen** entfernt sie, ein Werksreset ebenfalls.
- Ein gespeichertes Geheimnis wird nur für den Router benutzt, für den es eingegeben wurde. Für eine andere Adresse muss es neu eingegeben werden.
- Der Import kontaktiert nur private LAN-Adressen (10/8, 172.16/12, 192.168/16, IPv6-ULA). Ein Hostname muss ausschließlich auf solche Adressen auflösen. Loopback, Link-Local, Cloud-Metadaten, Carrier-Grade-NAT und öffentliche Adressen werden abgelehnt.
- API-Tokens brauchen `network:read`, um die gespeicherte Verbindung zu sehen, und `network:write` zum Abrufen und Übernehmen.

### Weg C: ARP-Tabelle des Routers (Ausblick)

**Noch nicht verfügbar.** In vielen Homelabs ist eine Firewall bzw. ein Router (OPNsense, pfSense, UniFi, MikroTik u. a.) das Gateway aller VLANs; ihre ARP-Tabelle und DHCP-Leases enthalten deshalb schon jedes aktive IP-MAC-Paar. Ein Konnektor, der sie regelmäßig per SNMP oder über die API des Routers ausliest, ist geplant; er baut auf der Router-Verbindung des Subnetz-Imports oben auf. Bis dahin Weg A oder B nutzen.
