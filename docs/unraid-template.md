# Unraid Community Applications (CA) Integration

GravityLAN provides an official Unraid Community Applications Docker template.

## Files

- [`ca_profile.xml`](../ca_profile.xml): Community Applications author profile and support metadata.
- [`assets/logo.png`](../assets/logo.png): app and profile icon (512×512, transparent), rendered from [`assets/logo.svg`](../assets/logo.svg).
- [`templates/gravitylan.xml`](../templates/gravitylan.xml): Docker application template for Unraid WebGUI.

## Configuration Details

| Parameter | Value | Description |
|---|---|---|
| **Network Mode** | `host` | Essential for Layer-2 ARP sweeps, mDNS discovery, and Nmap subnet scans. |
| **Capabilities** | `NET_RAW`, `NET_ADMIN` | Configured via `<ExtraParams>` for raw socket scanning without `--privileged=true`. |
| **App Data** | `/mnt/user/appdata/gravitylan` | Mapped to `/app/data` inside the container for SQLite DB, backups, and vault. |
| **WebUI Port** | `8000` | Default listening port (`http://[IP]:8000`). |
| **PUID / PGID** | `99` / `100` | IDs the server runs as (`nobody:users`, the Unraid appdata default). On start the container hands `/app/data` to this owner. |

## Troubleshooting: `PERMISSION ERROR: Cannot write to data directory '/app/data'`

Images up to 0.5.2 run as UID 1000 and can't write to an appdata directory that Unraid created as `root` or `nobody:users`, so the start stops with this error. Newer images fix the directory themselves via `PUID`/`PGID`.

**Quick fix for older images**, in the Unraid terminal:

```bash
chown -R 1000:1000 /mnt/user/appdata/gravitylan
```

Then start the container again. Older images run as 1000:1000, which is why the owner here is 1000 and not 99:100.

**With a current image**, nothing needs to be done: keep `PUID=99` and `PGID=100` (template default) and restart. If you pinned another user via `--user` in *Extra Parameters*, remove it, or make the directory belong to that user (`chown -R <uid>:<gid> /mnt/user/appdata/gravitylan`); the container log names the UID/GID it runs as.

### Deutsch

Images bis 0.5.2 laufen als UID 1000 und können nicht in einen Appdata-Ordner schreiben, den Unraid als `root` oder `nobody:users` angelegt hat; der Start bricht dann mit diesem Fehler ab. Neuere Images richten den Ordner über `PUID`/`PGID` selbst ein.

**Sofortlösung für ältere Images** im Unraid-Terminal: `chown -R 1000:1000 /mnt/user/appdata/gravitylan`, danach den Container neu starten. **Mit einem aktuellen Image** ist nichts zu tun: `PUID=99` und `PGID=100` (Vorgabe der Vorlage) lassen und neu starten. Wer per `--user` in *Extra Parameters* einen Benutzer festgelegt hat, entfernt das oder gibt den Ordner diesem Benutzer (`chown -R <uid>:<gid> /mnt/user/appdata/gravitylan`); das Container-Log nennt die UID/GID, mit der der Server läuft.

## Screenshots, icon and texts

- `<Screenshot>` entries are absolute raw URLs on `main`: five of the classic view from `docs/screenshots/react/` and the GravityUI orbit map from `docs/screenshots/vue/`, all palette-compressed PNGs (85 to 475 KB). They only resolve once the branch that adds them is merged.
- `<Icon>` is `assets/logo.png`, square (512×512) and transparent.
- `<Overview>` (shown on the app page) has an English and a German part: features, the Unraid defaults (PUID 99, PGID 100, no privileged mode), the network types and how scanning works. `<Changes>` lists the last releases, `<ReadMe>` points to the README.
- The older screenshots in the root of `docs/screenshots/` (`GravityLanDashboard.png` …) are no longer used by the README or the template. They stay until CA has picked up the new template, because CA caches screenshot URLs; after that they can be deleted.

After a change to the template, check it before it lands on `main`:

```bash
python -c "import xml.etree.ElementTree as E; E.parse('templates/gravitylan.xml')"
```

and once it is on `main`, that every `<Icon>` and `<Screenshot>` URL answers with 200:

```bash
grep -oE 'https://raw[^<]+' templates/gravitylan.xml | xargs -n1 curl -s -o /dev/null -w "%{http_code} %{url_effective}
"
```

## How the template gets into Community Applications

CA does not read this repository on its own. A maintainer submits it once; after that CA re-reads the template from `main` on its own schedule, so later changes to `templates/gravitylan.xml` reach the store after a while without a new submission.

1. Make sure `ca_profile.xml`, `assets/logo.png` and `templates/gravitylan.xml` are on `main` and all URLs in them answer (see above).
2. Open **[ca.unraid.net/submit/new](https://ca.unraid.net/submit/new)** and log in with the Unraid.net account that should own the listing.
3. Enter the repository URL `https://github.com/SleeperXr/GravityLAN`, branch `main`, and click **Validate and Scan**.
4. Go through the validation results (unknown categories, missing fields and dead URLs show up there) and submit.

Submitting is done by the project owner by hand; this document only describes the steps.
