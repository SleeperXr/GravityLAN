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
