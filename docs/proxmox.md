# Proxmox VE integration

GravityLAN can read guest names and addresses from one Proxmox VE server or cluster and use them to name devices. It only sends GET requests to Proxmox: it cannot start, stop or change a guest.

## Configure

1. Create a dedicated Proxmox user and API token, for example `gravitylan@pve!inventory`.
2. Grant read access to the guests. A token created with **Privilege Separation** ticked (the default) has no permissions of its own, even for `root@pam`: add one under Datacenter → Permissions → Add → API Token Permission (path `/`, role `PVEAuditor`, propagate). Without it Proxmox answers with an empty guest list, not an error. Unticking the separation also works, but the token then has every right of its user. `PVEAuditor` on `/` with propagation covers the inventory and the configuration. Current Proxmox versions also need `VM.GuestAgent.Audit` on the VMs for `network-get-interfaces`, so assign a custom read role that contains it; older versions may need `VM.Monitor` for that call. Check the API viewer of your version. With token privilege separation, both the user and the token need the permissions, and the token cannot have more than the user.
3. Enable the QEMU Guest Agent in each VM's Proxmox options, install it in the guest and make sure it runs. LXC containers need no agent.
4. In GravityLAN open **Settings → Proxmox VE**. Enter the HTTPS address (for example `https://192.168.1.2:8006`), the token ID and the token secret, switch the integration on and save. Saving or removing the connection asks for your password again, like other credentials.
5. Select **Sync now**. After that GravityLAN reads the guests every five minutes once the setup is complete. Read access to the cluster list alone does not guarantee access to each guest; the result counts skipped guests separately.

The GravityLAN backend must reach the API address. Redirects are not followed, so enter the direct HTTPS address. No extra Python or frontend dependency is needed.

## Self-signed certificates

Certificate checks are on by default. For a trusted server on your own network with a self-signed certificate, switch on **Accept self-signed certificates**. This turns off the certificate chain and host name checks for this connection only; the connection stays encrypted, but the server's identity is no longer verified.

## Names and addresses

- Running VMs: addresses come from the QEMU Guest Agent (`network-get-interfaces`). A stopped VM or one without a readable agent is skipped.
- Running LXC containers: runtime addresses from `/interfaces`, DHCP addresses included. Both the older `inet`/`inet6` and the newer `ip-addresses` answers are understood.
- Stopped LXC containers: the static `ip`/`ip6` entries of their network configuration. DHCP addresses of a stopped container are unknown.
- Loopback, link-local, multicast and unspecified addresses are left out, and templates are ignored. If two guests report the same address, that address is skipped instead of being given to one of them.
- Devices are matched by exact IP. A device's display name is replaced only while it is still automatic (its IP, its hostname or the previous Proxmox name of the same guest); a name you gave stays. The hostname stays the one the scanner found by DNS, so the name does not flip between DNS and Proxmox on every scan. A discovered host without a DNS name gets the guest name as its hostname; your own name for it stays.
- New guests appear under discovered hosts and in the IP address view and are added to the dashboard the usual way.
- A sync never marks a device online and never changes when it was last seen: a running guest is not proof that its address answers. Imported addresses stay listed as offline while the integration is on; a network scan that misses them does not delete them.
- Switching the integration off or removing the connection stops the imports; names already set stay. A sync never deletes devices or merges several addresses into one device.
- Only addresses in the scan networks (Settings → Scan subnets, else the auto-detected local networks) or of a device you already have are used. Docker bridges such as `172.17.0.1`, internal container networks and IPv6 addresses outside them are only listed.
- **Last sync** below the form lists each guest with what happened to every address, the address conflicts with both guests, and the skipped guests with the reason. It is kept in memory and rebuilt by every sync, so after a restart it appears with the next sync (at most five minutes).
- If the settings change while a sync is running, its result is discarded; sync again.

The token secret is stored encrypted with GravityLAN's vault key and never sent back to the browser. Leave the secret field empty to keep it. Changing the address or the token ID requires entering the secret again, so a stored token is never sent to a server it was not entered for. **Remove connection** deletes the address and the encrypted token. The connection is not part of the JSON backup, and a factory reset removes it. Keep the vault key when you copy the data directory. Saving and removing the connection are recorded in the audit log, without the secret.

## Deutsch

Unter **Einstellungen → Proxmox VE** API-Adresse (`https://pve:8006`), Token-ID (`gravitylan@pve!inventory`) und Token-Secret eintragen, die Anbindung einschalten und speichern; dabei fragt GravityLAN wie bei anderen Zugangsdaten noch einmal nach dem Passwort. Danach **Jetzt abgleichen** wählen. Anschließend läuft der Abgleich alle fünf Minuten.

Für selbstsignierte Zertifikate gibt es **Selbstsignierte Zertifikate akzeptieren**. Damit entfällt für diese Verbindung die Prüfung von Zertifikat und Hostname; verschlüsselt bleibt sie. Standardmäßig ist die Option aus.

Der Proxmox-Benutzer und – bei Privilegientrennung – sein Token brauchen Leserechte auf die Gäste. Ein Token mit angehakter „Privilege Separation“ (Standard) hat auch bei `root@pam` keine eigenen Rechte: Datacenter → Permissions → Add → API Token Permission, Pfad `/`, Rolle `PVEAuditor`. Ohne diese Berechtigung liefert Proxmox eine leere Gästeliste statt eines Fehlers. `PVEAuditor` deckt Inventar und Konfiguration ab. Für VM-Adressen ist auf aktuellen Versionen zusätzlich `VM.GuestAgent.Audit` nötig, ältere Versionen verlangen dafür eventuell `VM.Monitor`. Der QEMU Guest Agent muss in der VM laufen und in Proxmox aktiviert sein. Container brauchen keinen Agent. Gestoppte Container werden über ihre statischen Adressen erkannt, DHCP-Adressen gestoppter Gäste sind nicht bekannt.

Zugeordnet wird über die IP-Adresse. Der Anzeigename eines Geräts wird nur ersetzt, solange er automatisch ist (IP, Hostname oder der bisherige Proxmox-Name); eigene Namen bleiben. Der Hostname bleibt der per DNS gefundene, damit der Name nicht bei jedem Scan zwischen DNS und Proxmox wechselt. Ein gefundener Host ohne DNS-Namen bekommt den Gastnamen als Hostnamen. Neue Gäste erscheinen bei den gefundenen Hosts und in der IP-Ansicht und lassen sich wie gewohnt zum Dashboard hinzufügen. Übernommen werden nur Adressen aus den Scan-Netzen oder von bekannten Geräten; Docker-Bridges und IPv6 außerhalb davon werden nur angezeigt. **Letzter Abgleich** unter dem Formular zeigt pro Gast, was mit jeder Adresse passiert ist, dazu Adresskonflikte und übersprungene Gäste mit Grund. Ein Abgleich setzt kein Gerät auf „online“. Fehlende Leserechte, fehlende Agenten und doppelte Adressen werden als übersprungene Gäste bzw. Adresskonflikte gemeldet.

Das Secret wird verschlüsselt gespeichert. Ein leeres Secret-Feld behält den gespeicherten Wert. Wer Adresse oder Token-ID ändert, muss das Secret neu eingeben. **Verbindung entfernen** löscht die Zugangsdaten. JSON-Backups enthalten keine Proxmox-Zugangsdaten; den Vault-Schlüssel beim Kopieren des Datenverzeichnisses mitsichern.
