# Übergabe: GravityUI (`frontend-vue/`) – Stand 22.10.2026

Für den nächsten Agenten (Gemini) und für Oliver. Kurz: **Alle Seiten der React-Oberfläche sind nach Vue portiert. Das Liniennetz-Design (Bahnplan) wird verworfen. Nächster Schritt ist die neue Richtung „Gravitation / Orbit“ für den Netzplan und die visuelle Identität.**

---

## 1. Rahmenbedingungen (bitte einhalten)

- **React bleibt Standard** unter `/` (`frontend/`). GravityUI ist optional unter `/frontend-vue/`. Nichts umschalten, React nicht entfernen.
- **Gleicher Funktionsumfang wie React, aber eigenes Design** (nicht 1:1 React, nicht der alte Antigravity-/8starlabs-Look). Dunkel ist Standard, Hell muss gleichwertig funktionieren.
- **Alles anpassbar**: Der Nutzer entscheidet, wo Dinge sitzen und wie sie verbunden sind.
- **Git**: Arbeit direkt auf `main`. Nur eigene Dateien stagen, **nie `git add -A`**. **`VERSION` nicht anfassen.** Push und Merge nur nach Olivers OK. Änderungen von Oliver oder anderen Agenten nicht zurückdrehen.
- **CHANGELOG**: Jede sichtbare Änderung bekommt im selben Commit einen Eintrag unter `## [Unreleased]` in `CHANGELOG.md` (auf Englisch, wie die bestehenden Einträge).
- **Sprache**: Mit Oliver auf Deutsch sprechen. Code-Kommentare und Commit-Messages auf Englisch.
- **Demo-Login**: Das lokale Demo-Backend nutzt das Passwort `demo` (aus `scripts/dev_demo.py`). Nur lokal verwenden.

## 2. Git-Stand

- Branch `main`. **15 lokale Commits, nicht gepusht** (`origin/main` = `1cf4952`). Arbeitsbaum ist sauber, bis auf diese Datei.
- Commits dieser Migration (alt → neu):
  `2050a9b` Fundament, Übersicht, Editor · `b6c6735` IP-Übersicht · `4013e1d` Einstellungen · `18fc071` Liniennetz-Identität und Netzplan · `3c5a5df` Changelog · `932fbf0` Kopf der Übersicht · `144b1d2` Health · `e579882` Agents · `5275e84` SSH-Terminal · `e8f2b94` Logs · `cd77864` Setup-Assistent · `fda7d3f` Racks · `754473f` Navigation, Linienfarben, Kontrast · `12e5cbb` gerade Linien und Review-Befunde · `778ce9d` DESIGN.md
- Außerhalb von `frontend-vue/` geändert: nur `frontend/src/api/client.ts` (exportiert jetzt `authHandlers` und `ApiError`, das Verhalten in React ist unverändert), `CHANGELOG.md`, `Dockerfile` (die Vue-Stufe kopiert `frontend/src`), `.github/workflows/ci.yml` und `.claude/launch.json`.

## 3. Starten und prüfen

```bash
backend/.venv/Scripts/python.exe scripts/dev_demo.py          # Demo-Backend :8000 (Daten in .demo-data/)
backend/.venv/Scripts/python.exe scripts/dev_demo.py --fresh  # leere Neuinstallation -> Setup-Assistent
npm --prefix frontend-vue run dev                             # http://localhost:5174/frontend-vue/
npm --prefix frontend-vue run typecheck                       # vue-tsc
npm --prefix frontend-vue run lint                            # eslint (eslint.config.js nicht ändern)
npm --prefix frontend-vue test                                # vitest, aktuell 27 Tests grün
```

Das Demo blockiert echte LAN-Scans und SSH (Antwort 403). Das SSH-Terminal landet in einer Fake-Shell.

## 4. Architektur von `frontend-vue/`

- **Stack**: Vue 3.5 mit `<script setup>`, Pinia, vue-router 4 (Basis `/frontend-vue/`), Tailwind v4 (Tokens über `@theme` in `src/index.css`), reka-ui, lucide-vue-next, @vueuse/core, gridstack, @vue-flow/core (nur im aktuellen Netzplan), @xterm/xterm, i18next.
- **Geteilter Code**: Der Alias `@shared` zeigt auf `../frontend/src` und liefert API-Client, Typen, Locales und reine Modelle wie `Dashboard/overview/layout.ts`, `Dashboard/editor/deviceForm.ts`, `Network/subnet/model.ts` und `utils/version.ts`. **Keine `.tsx`-Dateien und nichts, was `react` importiert, über `@shared` holen.**
- **Texte**: Die React-Locales werden mitgenutzt. Eigene Schlüssel stehen nur unter `gv.*` in `src/locales/de.json` und `en.json`; ein Test prüft, dass beide dieselben Schlüssel haben.
- **Zentrale Dateien**:
  - `src/App.vue`: Bootzustände checking → setup (`SetupView`) → login (`LoginView`) → ready. Außerdem KeepAlive nur für `SshView`, damit Terminals beim Seitenwechsel weiterlaufen.
  - `src/router/index.ts`: alle Routen.
  - `src/components/layout/` mit `navigation.ts`: Navigation, jede Seite mit Linienfarbe.
  - `src/stores/`:
    - `network` mit Geräten, Gruppen, Subnetzen und Scan
    - `appearance` mit den Linienfarben pro Subnetz aus der Einstellung `ui.line_colors`
    - `sshSessions` mit dem Zähler laufender Sitzungen
    - `discovery`
  - `src/lib/networks.ts`: `networkColor()`, `lineLabel()` und `lineLabelFor()`. Das ist die eine Quelle für Netzfarben.
  - Seiten liegen in `src/views/*`, Komponenten je Bereich in `src/components/<bereich>/`, reine Logik in `*Model.ts`, jeweils mit `*.test.ts`.
  - Der Ordner für Logs heißt `components/logstream`, weil `.gitignore` alle Ordner namens `logs` ignoriert.
- **Design-Doku**:
  - `frontend-vue/DESIGN.md` und `.impeccable/design.json` beschreiben das **Liniennetz**-System. Beide müssen bei der neuen Richtung neu geschrieben werden.
  - `frontend-vue/PRODUCT.md` (Produktbrief) bleibt gültig.
  - Der alte Richtungsvertrag liegt in `.impeccable/surfaces/src-views-dashboardview-vue.md`.

## 5. Fertig und geprüft

- **Funktionen**: Alle Seiten haben React-Parität: Übersicht, Geräte-Editor (5 Tabs), IP-Übersicht, Topologie mit Racks, Health, Agents (Telemetrie, Patching), SSH-Terminal (Schlüssel, Profile, Verlauf, Known Hosts, Agent-Update), Logs, Einstellungen (alle Bereiche plus Linienfarben), Setup-Assistent und Login.
- **Qualität**:
  - Kein horizontales Scrollen bei 375 px auf allen Seiten.
  - Jeder Text erreicht in Hell und Dunkel mindestens 4,5:1 Kontrast (gemessen).
  - Typecheck, Lint und Tests sind grün.
  - Reduzierte Bewegung wird respektiert.
- **Finish-Review**: Screenshots aller Seiten liegen in `.impeccable/review/*.png` (gitignored). Die offenen Befunde stehen in `DESIGN.md` unter „Offene Punkte“.

## 6. Offen

1. **Neue Richtung „Gravitation / Orbit“** umsetzen (siehe Abschnitt 7). Das ist die nächste Aufgabe.
2. Danach `DESIGN.md` und `.impeccable/design.json` für Orbit neu schreiben. Die Bahn-Begriffe raus: „Halt entfällt“, „Strecke“, „Linie“, „Netzplan“. Betroffen sind `src/locales/*.json` unter `gv.plan.*` und `gv.lines.*` sowie die Texte in `ServiceNotices`, `LineStatusBoard`, `StationNode` und `SetupView`.
3. Aus dem Review, unabhängig von der Richtung:
   - Health und Agents ohne KPI-Kachelreihe
   - Suche mit Strg+K in die Kopfzeile der Übersicht
   - gleichmäßige Gerätekarten
4. Docker-Build testen (`docker build .`). Die Vue-Stufe braucht `frontend/src` und das neue `package-lock.json` (xterm, Fonts).
5. Paritäts-Checkliste React ↔ Vue als Dokument schreiben.
6. Push und Merge erst nach Olivers OK.

## 7. Nächste Aufgabe: Netzplan als Gravitationssystem („Orbit“)

**Oliver hat sich dafür entschieden** (Zitat: „Das ist geil wenn es komplett anpassbar ist“). Der Grund: Switches und WLAN ließen sich im Bahnplan nicht gut darstellen, und „Gravitation“ passt zum Namen GravityLAN.

### Konzept
- **Stern**: Der Router oder das Gateway steht in der Mitte (`gatewayIds` aus `api.getGateways()`).
- **Planeten**: Switches und Access Points kreisen um den Stern.
- **Kabelgeräte**: Sie laufen auf **durchgezogenen** Bahnen um ihren Switch.
- **WLAN-Geräte**: Sie sind Monde auf **gestrichelten** Bahnen um ihren Access Point. Wechselt ein Gerät den AP, wandert es zum anderen Planeten.
- **VMs und Container**: Sie sind Monde ihres Hosts (`parent_id`).
- **Offline**: Das Objekt verliert seine Bahn und verblasst, die Bahn wird unterbrochen. Zustand **nie nur über Farbe** zeigen; Form oder Text gehören dazu.
- **VLAN/Subnetz**: Es wird zum farbigen Ring am Objekt bzw. zur Bahnfarbe. Die Farbe kommt immer aus `networkColor()`, eigene Farben aus `ui.line_colors` haben Vorrang.
- **Komplett anpassbar**:
  - Planeten frei verschieben; ihre Monde wandern mit.
  - Monde auf ihrer Bahn verschieben, das ändert Winkel und Radius.
  - Ein Gerät per Drag auf einen anderen Planeten ziehen, um ihm die Bahn zuzuweisen. Dabei wird ein Topologie-Link erzeugt oder umgehängt.
  - Farben pro Netz und pro Bahn bleiben wählbar.
  - „Automatisch anordnen“ erzeugt saubere Bahnen.
- **Wow-Moment**: Eine dezente Bewegung bei `prefers-reduced-motion: no-preference`, zum Beispiel Bahnen, die sich beim Laden einzeichnen, oder ein optionaler langsamer Umlauf. Bei reduzierter Bewegung gibt es keine Animation.

### Was die Daten hergeben (geprüft)
- `Device` (Typ in `frontend/src/types/index.ts`) hat:
  - `is_ap`, `is_wlan` und `is_host`
  - `parent_id` und `virtual_type` (`'vm' | 'docker' | 'lxc'`) für VMs und Container auf einem Host
  - `device_type`
  - `topology_x`/`topology_y` (absolute Position, wird mit React geteilt)
  - `topology_config` (JSON-String, React nutzt darin `top_handle_type`/`bottom_handle_type`; zusätzliche Schlüssel wären möglich, dann aber auf React-Kompatibilität achten)
- **Links**: `api.getTopologyLinks()` liefert `{source_id, target_id, link_type ('10GbE'|'2.5GbE'|'1GbE'|'WLAN'|'Fiber'), color?}`. Anlegen, Ändern und Löschen laufen über `api.createTopologyLink`, `updateTopologyLink` und `deleteTopologyLink`.
- **Demo-Daten** (`scripts/dev_demo.py`):
  - UniFi Gateway (Stern) → Core Switch → {Proxmox, Unraid, Synology, Pi-hole, AP Obergeschoss, AP Erdgeschoss, Drucker}
  - VMs: Docker VM und Home Assistant auf Proxmox, Nextcloud auf Unraid, Grafana auf Docker VM
  - WLAN-Geräte ohne Link: MacBook, iPhone (offline), Shelly (offline)
  - Hue Bridge und Shelly liegen im IoT-Subnetz
- **Vorschlag für die Zuordnung, wer um wen kreist** (Reihenfolge):
  1. `parent_id` (VM oder Container) → Host.
  2. Ein expliziter Link → der Nachbar näher am Stern (Breitensuche vom Gateway über die Links). Bei `link_type === 'WLAN'` wird die Bahn gestrichelt.
  3. `is_wlan` ohne Link → ein Access Point im selben Subnetz (oder der vom Nutzer zugewiesene), gestrichelt.
  4. Sonst → der Stern des eigenen Subnetzes.
- **Positionen speichern**: Absolute `topology_x/y` behalten (kompatibel mit React). Den Bahnradius aus dem Abstand zum Elternobjekt ableiten. Wird ein Planet bewegt, die Kinder um dasselbe Delta mitverschieben und mitspeichern (`api.updateDevice`).

### Wo einbauen
- Der heutige Netzplan ist `src/components/netzplan/` (Vue Flow, `NetzPlan.vue`, `StationNode.vue`, `TransitEdge.vue`, `netzplan.ts` mit Tests). Er wird in `views/TopologyView.vue` (bearbeitbar) und in der Übersicht (`views/DashboardView.vue`, nur lesend) verwendet.
- **Empfehlung**: Eine neue Komponente `src/components/orbit/` (eigenes SVG ist für Kreisbahnen einfacher als Vue Flow) mit derselben Schnittstelle bauen: Props `editable`, `startEditing`, `flowId`; Event `openDevice`. Dann in beiden Views austauschen. Den alten Netzplan erst löschen, wenn Oliver Orbit abgenommen hat.
- Lohnt sich zum Mitnehmen:
  - die Snapping-Idee aus `alignStations`/`snapToNeighbours` (auf Bahnen übertragen)
  - das Link-Panel (Farbe, Typ, Löschen)
  - die Linien- bzw. Netzfarben-Logik
  - `motion()` für reduzierte Bewegung

## 8. Fallstricke

- `npm run lint` und `typecheck` vor jedem Commit. `eslint.config.js` ist geschützt und darf nicht verändert werden.
- Der Netzplan in der Übersicht nutzt `flow-id="dashboard-plan"`, die Topologie `flow-id="topology"`. Getrennte IDs sind nötig.
- `useTheme.ts`: Die Vorgabe ist dunkel, `data-theme` sitzt auf `<html>`. Die GravityLAN-Farben im Terminal und die Palettenvorschau hängen vom aufgelösten Thema ab.
- Bei Farben: Text auf getönten Flächen immer in der `*-text`-Variante. Auf vollen Linienfarben nur die dunkle Tinte `#0c0f14`. Gefüllte Danger-Flächen nutzen `text-danger-fg`, gefüllte Info-Flächen `text-canvas`. Neue Farben in beiden Themen auf 4,5:1 prüfen.
- Die Übergabe-Notizen der Claude-Sitzungen liegen außerhalb des Repos und sind für Gemini nicht nötig; alles Wichtige steht hier.
