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

## Submitting to Unraid CA (`ca.unraid.net/submit/new`)

1. Ensure the latest changes (`ca_profile.xml`, `assets/logo.png`, and `templates/gravitylan.xml`) are pushed to `main` on GitHub:
   ```bash
   git add ca_profile.xml assets/logo.png assets/logo.svg templates/gravitylan.xml docs/unraid-template.md
   git commit -m "feat(unraid): add Community Applications template and profile"
   git push origin main
   ```

2. Visit **[ca.unraid.net/submit/new](https://ca.unraid.net/submit/new)**:
   - Log in with your Unraid.net account.
   - Enter your repository URL: `https://github.com/SleeperXr/GravityLAN`
   - Select branch: `main`
   - Click **Validate and Scan**.
   - Review the validation check results and submit.
