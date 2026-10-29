---
name: GravityUI
description: Das Heimnetz als Gravitationssystem – Router als Stern, Switches & APs als Planeten, Geräte als Monde auf konzentrischen Orbits, verbunden durch Light-Beams.
colors:
  # Nachtmodus (dunkel, Standard)
  canvas: "#0c0f14"
  chrome: "#090b0f"
  surface: "#11151c"
  raised: "#161b23"
  sunken: "#0e1218"
  control: "#161b23"
  control-hover: "#1d232d"
  hairline: "#1d232c"
  hairline-strong: "#2b323d"
  fg: "#eef1f5"
  fg-muted: "#a3adbb"
  fg-subtle: "#7f8a99"
  station: "#0e1218"
  accent: "#2ec4a6"
  accent-hover: "#4fd6bb"
  accent-fg: "#03201a"
  accent-text: "#45d6b9"
  info: "#5aa9ff"
  info-text: "#8cc3ff"
  warn: "#ffb547"
  warn-text: "#ffc977"
  danger: "#ff6b6b"
  danger-text: "#ff8f8f"
  danger-fg: "#2a0608"
  neutral-dot: "#6b7686"
  sign-ink: "#0c0f14"
  line-1: "#2ec4a6"
  line-2: "#ff9f43"
  line-3: "#5aa9ff"
  line-4: "#ffd23f"
  line-5: "#ff7eb6"
  line-6: "#9be15d"
  line-7: "#4dd4ff"
  line-8: "#e0a370"
  line-9: "#c3cad4"
  line-10: "#f2856d"
  # Tagmodus (hell)
  canvas-day: "#f4f5f7"
  chrome-day: "#ffffff"
  surface-day: "#ffffff"
  raised-day: "#f2f4f7"
  sunken-day: "#eef0f3"
  control-day: "#ffffff"
  control-hover-day: "#f2f4f7"
  hairline-day: "#e2e5ea"
  hairline-strong-day: "#c9ced6"
  fg-day: "#10141b"
  fg-muted-day: "#4a5462"
  fg-subtle-day: "#5d6776"
  station-day: "#ffffff"
  accent-day: "#087a65"
  accent-hover-day: "#066654"
  accent-fg-day: "#ffffff"
  accent-text-day: "#066a57"
  info-day: "#1f6fd1"
  info-text-day: "#1a5fb4"
  warn-day: "#d97706"
  warn-text-day: "#8f4c00"
  danger-day: "#dc3545"
  danger-text-day: "#b42332"
  danger-fg-day: "#ffffff"
  neutral-dot-day: "#a3aab5"
  line-1-day: "#12a88b"
  line-2-day: "#f08a24"
  line-3-day: "#2f86e8"
  line-4-day: "#e5b800"
  line-5-day: "#e8589b"
  line-6-day: "#6fbf3b"
  line-7-day: "#1fb3e0"
  line-8-day: "#b9773f"
  line-9-day: "#8a94a3"
  line-10-day: "#e0644a"
typography:
  display:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.33
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
    lineHeight: 1.43
  body:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.43
    fontFeature: "'ss01', 'cv11'"
  meta:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.33
  label:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.33
  badge:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.45
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.6875rem"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "'zero', 'tnum'"
  line-sign:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontFeature: "'tnum'"
  body-name:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: "16px"
  micro:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "10px"
    fontWeight: 500
    lineHeight: "12px"
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
  xl: "18px"
  full: "9999px"
spacing:
  page-x-phone: "16px"
  page-x: "32px"
  page-y-phone: "20px"
  page-y: "28px"
  section: "24px"
  grid: "16px"
  grid-phone: "12px"
  card-x: "16px"
  card-y: "14px"
  dialog-x: "20px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-fg}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "36px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.control}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "36px"
  button-secondary-hover:
    backgroundColor: "{colors.control-hover}"
  button-ghost:
    textColor: "{colors.fg-muted}"
    rounded: "{rounded.md}"
    padding: "0 14px"
    height: "36px"
  button-ghost-hover:
    backgroundColor: "{colors.control-hover}"
    textColor: "{colors.fg}"
  input:
    backgroundColor: "{colors.sunken}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "36px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "14px 16px"
  subcard:
    backgroundColor: "{colors.raised}"
    rounded: "{rounded.md}"
  badge-neutral:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.fg-muted}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
    typography: "{typography.badge}"
  line-sign:
    textColor: "{colors.sign-ink}"
    rounded: "{rounded.full}"
    typography: "{typography.line-sign}"
    height: "28px"
    padding: "0 6px"
  orbit-body:
    backgroundColor: "{colors.station}"
    rounded: "{rounded.full}"
    size: "22px"
  nav-item-active:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.fg}"
    rounded: "{rounded.md}"
    height: "36px"
  dialog:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.xl}"
    padding: "16px 20px"
---

# Design System: GravityUI

GravityUI (`frontend-vue/`) ist die optionale zweite Oberfläche von GravityLAN unter `/frontend-vue/`, neben der unveränderten React-Ansicht (Standard unter `/`). Beide sprechen dasselbe Backend an, teilen den API-Client über den Alias `@shared` und die Texte (i18next aus `frontend/src/locales`; eigene Schlüssel nur unter `gv.*`). Dieses Dokument beschreibt das Designsystem in der Richtung **„Gravitation / Orbit“** und ersetzt die frühere Liniennetzplan-Fassung.

## Overview

**Creative North Star: „Das Gravitationssystem (Orbit)“**

Passend zum Namen GravityLAN wird das Heimnetz als gravitatives Sonnensystem gelesen und frei gestaltet:
- **Stern:** Der Router bzw. das Gateway steht im Zentrum (`gatewayIds` aus `api.getGateways()`).
- **Planeten:** Switches, Access Points und Hypervisor-Hosts kreisen um den Stern und sind über gerichtete **Light-Beams** (leuchtende Energieverbindungen mit animiertem Puls) verbunden.
- **Monde:** Kabelgeräte laufen auf **durchgezogenen** konzentrischen Bahnen um ihren Switch/Planeten; WLAN-Geräte auf **gestrichelten** Bahnen um ihren Access Point; VMs und Container (`parent_id`) kreisen als Monde um ihren Host.
- **Zustand doppelt kodiert:** Ausgefallene Himmelskörper verlieren ihre geschlossene Umlaufbahn (unterbrochener Orbit-Ring, rot umrandet, durchgestrichen und Text-Badge „Offline“); gestörte Dienste zeigen einen Bernstein-Ring plus `!`-Indikator.
- **Netz-Identität:** Jedes Subnetz bzw. VLAN hat genau eine Farbe (`networkColor()`, überschreibbar über `ui.line_colors`). Sie trägt den Atmosphärenring des Objekts, die Orbit-Bahn, das runde Netz-Schild (`LineBullet`), das Statusboard, die Betriebsmeldungen, IP-Kacheln und Rack-Einschübe.

Der Standard ist der dunkle Nachtmodus (`canvas` `#0c0f14`), das helle Thema (`#f4f5f7`) arbeitet mit derselben Farblogik und eigens abgedunkelten Palettenwerten, sodass alle Texte in beiden Themen mindestens 4,5:1 Kontrast erreichen. Keine Seite nutzt generische KPI-Kachelreihen: Health und Agents fassen ihre Kennzahlen in einer kompakten Statusleiste direkt über der Tabelle zusammen.

**Key Characteristics:**
- Gravitationshierarchie: Stern (Gateway) → Planeten (Switch, AP, Host) → Monde (Clients, WLAN, VMs/Container).
- Konzentrische Orbit-Ringe (durchgezogen = Kabel/VM, gestrichelt = WLAN, unterbrochen = Offline) und Light-Beams zwischen Stern und Planeten.
- Manuell steuerbare Lebendigkeit (`vitalityMode: 'off' | 'subtle' | 'lively'`, gespeichert unter `gravityui.orbit.vitality`, respektiert `prefers-reduced-motion`).
- Nachtmodus als Standard, helles Thema gleichwertig mit ≥ 4,5:1 Kontrast.
- Hanken Grotesk für die Oberfläche, JetBrains Mono für IPs, MACs, Ports, Latenzen und Zähler.

## Colors

Ein neutraler, leicht blaustichiger Grund trägt eine Palette aus zehn klaren Netzfarben; dazu ein einziger Handlungsakzent (Türkis) und drei Zustandsfarben.

Alle Werte liegen als `--gl-*` und `--line-1..10` in `src/index.css` und werden über `@theme` auf Tailwind-Klassen abgebildet (`bg-canvas`, `bg-chrome`, `bg-surface`, `bg-raised`, `bg-sunken`, `bg-control`, `border-line`, `border-line-strong`, `text-fg`, `text-fg-muted`, `text-fg-subtle`, `bg-station`, `bg-accent`/`text-accent-text`, `info`, `warn`, `danger` jeweils mit `*-text`). Komponenten verwenden nur diese semantischen Namen. Das Thema hängt an `data-theme` auf `<html>`; ein Skript in `index.html` setzt es vor dem ersten Paint (Standard dunkel), `useTheme.ts` schaltet zwischen dunkel, hell und System um und speichert unter `gravityui.theme`.

### Primary
- **Signaltürkis** (`accent`, dunkel `#2ec4a6` / hell `#087a65`): primäre Aktion (Scan, Fertig), Fokusring (2 px, Abstand 2 px), Textcursor, aktive Tab-Unterstreichung, aktive Statusboard-Zeile, „gesund/online“-Punkte, Light-Beam beim Ziehen einer neuen Verbindung im Orbit-Netzplan. Text in Akzentfarbe nutzt immer `accent-text`; Text auf gefülltem Akzent `accent-fg`.

### Secondary
- **Netzpalette** (`--line-1` bis `--line-10`, je Thema eigener Satz): Identität der Subnetze/Orbits und der Seiten. Ohne Nutzerwahl bekommt ein Subnetz den Slot `((id − 1) mod 10) + 1`; ohne Subnetz wird der Slot aus dem `/24`-Präfix gehasht (`networkColor` in `src/lib/networks.ts`). Die Nutzerwahl (Hex, pro Subnetz) hat Vorrang und gilt in beiden Themen. Die helle Palette ist dunkler gestimmt, damit Ringe und Light-Beams auf Weiß tragen.

### Tertiary
- **Zustandsfarben**: Info-Blau (`info`) für Eingabefokus und Hinweise, Bernstein (`warn`) für gestörte Dienste, Signalrot (`danger`) für ausgefallene Geräte, Fehler und destruktive Aktionen. Flächen davon nur als Tönung (`/10`, Rand `/25`–`/30`), Text immer in der `*-text`-Variante.

### Neutral
- **Nachtgrund** (`canvas`): Seitenhintergrund. **Nachtleiste** (`chrome`): Seitenleiste und mobile Tab-Leiste. **Kartenfläche** (`surface`): Karten, Dialoge, Popover. **Innenfläche** (`raised`): Unterkarten, aktive Navigation, Hover von Zeilen. **Senke** (`sunken`): Eingabefelder, Segmentschalter, Rack-Innenraum, Orbit-Grund im Dunkeln. **Bedienfläche** (`control`/`control-hover`): Sekundär-Buttons.
- **Haarlinien** (`hairline` = `--gl-line`, `hairline-strong`): Rahmen, Trenner, Hover-Rahmen, Scrollbalken.
- **Textstufen** (`fg`, `fg-muted`, `fg-subtle`): Inhalt, Beschreibung, Metadaten. Im hellen Thema wurden alle Textstufen so abgedunkelt, dass sie auf ihren eigenen 10–15-%-Tönungen über Weiß 4,5:1 erreichen.
- **Körperkern** (`station`): Füllung der Himmelskörper im Orbit-Netzplan. **Schildtinte** (`sign-ink`, `#0c0f14`): fester Text auf Netzschildern und aktiven Navigationsschildern, in beiden Themen.

### Named Rules
**The Netzfarbe-ist-Identität Rule.** Ein Subnetz hat genau eine Farbe, und die kommt immer aus `networkColor()` (oder `lineVar()` für Seiten). Wer ein Netz zeigt, zeigt es in dieser Farbe; keine zweite Farblogik pro Ansicht, keine Hex-Werte in Komponenten.

**The Tönung-ist-keine-Schrift Rule.** Getönte Flächen (`bg-accent/10`, `bg-danger/10`, `color-mix(… 14–16 %)`) tragen nie Text in der Grundfarbe; Text darauf nutzt `*-text` bzw. `lineInk()` (Netzfarbe 75 % zur Textfarbe gemischt).

**The Schildtinte Rule.** Auf vollflächigen Netzfarben steht immer die dunkle Schildtinte (`#0c0f14`), nie Weiß, unabhängig vom Thema.

## Typography

**Display Font:** Hanken Grotesk Variable (mit `ui-sans-serif`, `system-ui`)
**Body Font:** Hanken Grotesk Variable, Stilsätze `ss01`, `cv11`
**Label/Mono Font:** JetBrains Mono (mit `ui-monospace`), Null mit Strich, Tabellenziffern

**Character:** Eine sachliche, leicht kantige Grotesk für klare Orientierung, gepaart mit einer technischen Mono für alles, was man abliest oder abtippt.

### Hierarchy
- **Display** (700, 1,5 rem, eng gesperrt): nur der Willkommensschritt der Ersteinrichtung.
- **Headline** (600, 1,25 rem): Seitentitel im `PageHeader`; auf Telefonen nur für Screenreader, weil die App-Leiste den Titel zeigt. Einrichtungsschritte nutzen dieselbe Größe in 700.
- **Title** (700, 0,875 rem): Karten- und Abschnittstitel, Netzname im Statusboard, Meldungstitel. Dialogtitel 1 rem in 600.
- **Body** (400–500, 0,875 rem): Fließtext, Navigation, Buttons (500, primär 600), Beschreibungen (`max-w-2xl`).
- **Meta** (0,75 rem): Hilfetexte, Zähler, Zeitangaben.
- **Label** (600, 0,75 rem, `fg-subtle`, normale Schreibung; Klasse `.gl-eyebrow`): Beschriftung direkt über einem Messwert oder einer Definitionsliste und kleine Listengruppen-Überschriften. Kein Versal-Satz, kein Vorspann über Seiten- oder Abschnittstiteln.
- **Badge / Micro** (500, 11 px, Utility `text-micro`): Badges und Zähl-Pillen, mobile Tab-Beschriftungen, Versionsnummer, Rack-Höheneinheiten, Achsenbeschriftungen von Diagrammen und dichte Mono-Metadaten (IP/HE-Zeile im Rack-Einschub). Das ist die Untergrenze: nichts wird kleiner gesetzt.
- **Mono** (11 px bis 0,875 rem): IPs, CIDRs, MACs, Ports, Latenzen („2,4 ms“), Online-Zähler („14/15“), Linktypen. In Listen, Hilfezeilen und Popovers 12 px (`text-xs`); 11 px nur dort, wo ein dichtes Raster sonst bricht.
- **Netzschild** (800, 11 px / 12 px / 14 px in sm/md/lg): VLAN-ID oder Anfangsbuchstabe.
- **Körpername** (700, 12 px) mit Mono-Zeile (11 px) darunter: im Orbit-Netzplan auf Pille mit halbtransparentem Hintergrund für optimale Lesbarkeit bei jedem Zoom.

### Named Rules
**The Untergrenze Rule.** Fließtext, Hilfetexte, Beschriftungen, Buttons und Listen-Unterzeilen stehen mindestens in 12 px (`text-xs`); 11 px (`text-micro`) nur für die oben genannten Mikro-Beschriftungen, nie kleiner, keine freien Pixelwerte (`text-[10px]`). Passt eine Größe nicht in ein dichtes Raster (IP-Kacheln, Rack-Zeilen, Port-Leiste), wird Inhalt gekürzt oder ausgeblendet, nicht die Schrift verkleinert.

**The Abgelesen-in-Mono Rule.** Alles, was eine Adresse, ein Zähler oder ein Messwert ist, steht in JetBrains Mono mit Tabellenziffern; Fließtext und Namen nie.

## Layout

- **Hülle:** Desktop ab 768 px mit fester Seitenleiste (240 px, `chrome`, rechte Haarlinie); darunter eine obere App-Leiste mit Seitentitel und eine untere Tab-Leiste (vier Ziele plus „Mehr“, Mindesthöhe 56 px, `chrome` 95 % mit Unschärfe, Safe-Area-Abstand). „Mehr“ öffnet die volle Navigation als Bottom-Sheet.
- **Seiten:** `max-w-[1800px]`, zentriert; Rand 16 px mobil / 32 px ab `md`; oben 20 px / 28 px; 24 px zwischen Blöcken. Kopfzeile: Titel und Einzeiler links, globale Suche (`Strg+K`) und Aktionen rechts, umbrechend.
- **Raster:** 16 px zwischen Karten (12 px in dichten Gerätegittern); Karten-Innenabstand 16 px horizontal, 12–14 px vertikal; Gerätekarten innerhalb einer Gruppe erhalten einheitliche Standardhöhen (`groupDefaultH`).
- **Statusboard:** eine Zelle pro Subnetz/Orbit, `auto-fit` mit mindestens 16 rem, auf Telefonen gestapelt mit Trennern.
- **Orbit-Netzplan:** füllt seinen Rahmen, `fitView` mit 16 % Rand, Zoom 0,22–2,6; Bedienknöpfe (Zoom, Einpassen, Lebendigkeit) unten rechts, Inspektor-Panels unten links. Grund: dunkel `sunken`, hell `surface` (Weiß), jeweils mit feinem Koordinatenraster (28 px).
- **Touch:** Ziele mindestens 44 px auf Telefonen; Eingaben dort 16 px Schrift, sonst zoomt iOS.

## Elevation & Depth

Das System ist flach und tonal geschichtet: `canvas` → `surface` → `raised`, Senken (`sunken`) für Eingaben. Tiefe entsteht durch Haarlinien und Tonstufen, nicht durch Schatten.

### Shadow Vocabulary
- **Kartenkante** (`--gl-shadow-card`; dunkel `0 1px 0 0 rgb(255 255 255 / 0.025) inset`, hell `0 1px 2px rgb(16 20 27 / 0.04)`): auf jeder `.gl-card`, kaum sichtbar.
- **Schwebend** (`--gl-shadow-pop`; dunkel `0 24px 48px -12px rgb(0 0 0 / 0.65), 0 0 0 1px rgb(255 255 255 / 0.04)`, hell `0 20px 40px -12px rgb(16 20 27 / 0.2), 0 0 0 1px rgb(16 20 27 / 0.06)`): Dialoge, Sheets, Popover, Orbit-Bedienelemente und -Inspektorpanels.
- Kleine Bedienelemente auf der Orbit-Karte (Suche, Zoom-/Bewegungsleiste, Hinweis- und Touch-Pillen) tragen nur `shadow-pop` ohne eigene Rahmenlinie: dessen 1-px-Ring ist ihre Kante. Fokus zeigt ein Akzent-Ring (in der Leiste nach innen, weil sie beschneidet).
- Dialog-Overlay: Schwarz 55 % mit 2 px Unschärfe.

### Named Rules
**The Flach-auf-dem-Plan Rule.** Was auf der Seite liegt, hat keinen Schatten außer der Kartenkante; nur was über anderem schwebt, bekommt `shadow-pop`.

## Shapes

Runde Formen gehören dem Gravitationssystem (Sterne, Planeten, Monde, konzentrische Umlaufbahnen, Netzschilder, Statuspunkte), weich gerundete Rechtecke der Bedienung. Badges 6 px, Buttons, Felder, Navigationseinträge und Kacheln 10 px, Karten 14 px, Dialoge 18 px (auf Telefonen nur oben). Navigations-Seitenschilder sind gerundete Quadrate (7 px), Rack-Einschübe und Segmentschalter-Knöpfe 5 px. Rahmen sind 1 px Haarlinien; gestrichelte Rahmen bedeuten „frei“, „reserviert“ oder „WLAN-Orbit“.

**The Orbit-Snapping Rule.** Geschwister-Monde desselben Eltern-Planeten oder -Sterns, deren Abstand zum Elternobjekt sich um höchstens 18 px (`ORBIT_SNAP_TOLERANCE`) unterscheidet, teilen sich automatisch denselben konzentrischen Orbit-Ring (`snapToOrbitRing()` / `computeOrbitRings()`).

## Components

### Buttons
Sachlich und kompakt.
- **Shape:** sanft gerundet (10 px), Höhen 32 / 36 / 44 px (sm/md/lg), Icons 16 px.
- **Primary:** Akzentfläche mit `accent-fg`, 600; Hover `accent-hover`.
- **Secondary (Standard):** `control` mit Haarlinie; Hover `control-hover` und `hairline-strong`.
- **Ghost:** transparent, `fg-muted`; Hover Fläche und `fg`.
- **Danger / Danger-ghost:** gefülltes Rot mit `danger-fg` (dunkle Tinte im Nachtmodus, Weiß im Tagmodus) bzw. roter Text mit Tönung im Hover. Gefüllte Info-Flächen tragen Text in `canvas`.
- **States:** Farbübergang 150 ms; deaktiviert 50 % Deckkraft; Laden mit drehendem Loader und `aria-busy`. Fokus über den globalen Akzentring.

### Chips
- **Badges:** 11 px, 6 px Radius, Tönung + `*-text` + getönter Rand (neutral, accent, info, warn, danger), optional Mono.
- **Netzschild (`LineBullet`):** rund, Netzfarbe, Schildtinte, 800; Größen 20 / 28 / 40 px. Text ist die VLAN-ID, sonst der Anfangsbuchstabe des Subnetzes (`lineLabel`), „·“ wenn unbekannt; Meldungen ohne Gerät tragen ein neutrales Schild in `fg-muted`. Das Schild ist dekorativ (`aria-hidden`), der Netzname steht immer als Text daneben.
- **Segmentschalter:** `sunken`-Wanne mit 2 px Innenabstand, aktiver Knopf `control`.

### Cards / Containers
- **Corner Style:** 14 px (`.gl-card`), Unterkarten 10 px (`.gl-subcard`).
- **Background:** `surface`; Unterkarten `raised`.
- **Shadow Strategy:** Kartenkante (siehe Elevation & Depth).
- **Border:** 1 px Haarlinie.
- **Internal Padding:** 16 px horizontal, 12–14 px vertikal; Listen in Karten mit Trennlinien und Zeilen-Hover `raised`.

### Inputs / Fields
- **Style:** `sunken`, Haarlinie, 10 px, 36 px hoch, Platzhalter `fg-subtle`.
- **Focus:** Rahmen Info-Blau plus 2 px Ring `info/25`.
- **Error / Disabled:** Rahmen `danger` über `aria-invalid`; deaktiviert 60 %. `Field` verknüpft Label, Hinweis und Fehler per `aria-describedby`. Selects sind nativ.

### Navigation
- **Seitenleiste:** Einträge 36 px, 10 px Radius. Jede Seite trägt ein 26-px-Schild in ihrer Farbe (`navigation.ts`, `line`): inaktiv 16 % Tönung mit Icon in `lineInk`, aktiv voll gefüllt mit Schildtinte, Eintrag `raised` und 600. Zähler (online/gesamt, SSH-Sitzungen) rechts in Mono.
- **Mobil:** Tab-Leiste mit 20-px-Icons und 11-px-Beschriftung; aktiv `fg`, Icon in `lineInk` und ein 3-px-Balken in Seitenfarbe an der Oberkante. „Mehr“ öffnet das Navigations-Sheet.
- **Tabs:** 40 px, `fg-muted`; aktiv `fg` mit 2-px-Unterstreichung in Akzent.

### Dialoge und Sheets
`Dialog` ist ab 640 px zentriert (18 px Radius), darunter ein Bottom-Sheet über volle Breite mit Safe-Area. Kopf mit Titel (1 rem, 600), Schließen-Knopf, Trennlinie; Fuß rechtsbündig. Eintritt 220 ms mit `--ease-out-expo`, Overlay 160 ms ein / 120 ms aus. `Sheet` ist das Seitenpanel (mobil Vollbild). Toasts und Bestätigungen laufen über `useToast`/`useConfirm`.

### Cosmic Constellation Netzplan (Signaturkomponente)
`src/components/orbit/` (`OrbitMap.vue` + `orbitModel.ts`), interaktives Deep-Space-SVG mit Pan/Zoom, teilt `topology_x`/`topology_y` und `TopologyLink`-Einträge kompatibel mit dem React-Topologie-Editor.
- **Himmelskörper (`OrbitBody`):**
  - **Stern (`star`, Radius 22 px):** Router/Gateways im Zentrum als Fusionskern mit 4-Punkt optischen Diffraction Spikes (astronomischer Lens-Flare), Korona-Ring und sanftem Plasma-Pulsieren.
  - **Planet (`planet`, Radius 16 px):** Switches, Access Points (`is_ap`) und Hypervisor-Hosts (`is_host`) mit Atmosphärenring in Subnetzfarbe, subtiler Gravitationsaura und Rollen-Badge (`SW`, `AP`, `HOST`).
  - **Mond (`moon`, Radius 10.5 px):** Kabel-Clients, WLAN-Geräte (`is_wlan` mit dezenter Radio-Beacon-Aura) und VMs/Container (`parent_id`).
- **Sternbild-Vektoren (`LightBeam`):** Zweischichtige leuchtende Sternbild-Linien (Stardust-Aura + laser-scharfer Vektorkern + wandernde Photonen-Pulse + Spektral-Etikett `10GbE`/`2.5GbE`/`1GbE`/`WLAN`/`Fiber`).
- **Deep-Space Starfield & Nebulae:** Hintergrund mit mikroskopischem Sternenfeld (twinkling stars mit unterschiedlicher Magnitude) und weichen, lokalen kosmischen Gasnebeln pro Subnetz-Hub, ohne störende Gitterlinien.
- **Kontextuelle Orbit-Bahnen:** Umlaufbahnen werden gezielt nur um den aktuell fokussierten oder gehoverten Hub eingeblendet – dadurch entfallen die vorherigen 20+ globalen, sich überkreuzenden Drahtkreise vollständig.
- **Aufmerksamkeit zuerst:** Offline und gestörte Körper behalten ihr Label auch in der Gesamtansicht, tragen einen mit dem Zoom gegenskalierten Halo in Zustandsfarbe (offline gestrichelt) und liegen über ihren Nachbarn. Der Knopf über den Zoom-Steuerelementen zählt sie und fokussiert sie nacheinander. Labels weichen bei Platzmangel weiter nach außen aus, statt sich zu überlagern.
- **Komplett anpassbar (Bearbeitungsmodus):**
  - **Gruppenbewegung:** Wird ein Planet oder Stern verschoben, wandern alle seine Monde (inkl. Kind-Hierarchie) synchron mit (`moveWithDescendants`).
  - **Orbit-Zuweisung per Drag & Drop:** Zieht man ein Gerät auf einen anderen Planeten/Switch/AP/Stern, erscheint ein **visueller Drop-Highlight-Ring** sowie das Banner `Orbit → <Ziel>`. Beim Loslassen wird der Topologie-Link automatisch umgehängt bzw. angelegt und das Gerät auf einer freien Umlaufbahn um das neue Elternobjekt platziert (mit Zyklusschutz).
  - **Sternbild-Linien zeichnen:** Über den `+`-Griff am Rand eines ausgewählten Körpers lässt sich direkt eine neue Verbindung zu einem anderen Körper ziehen.
  - **Inspektor-Panels (unten links):** Erlauben für Verbindungen die Wahl von Farbe und Linktyp (`10GbE`, `2.5GbE`, `1GbE`, `WLAN`, `Fiber`) sowie für Himmelskörper den direkten Wechsel des Eltern-Hubs per Auswahlfeld.
  - **Galaktische Dynamik (`vitalityMode`):** Über den Sparkles-Button unten rechts umschaltbar zwischen `Aus`, `Dezent` (Standard) und `Lebendig`.
  - **Bewegung liegt unter den Körpern:** Das Sternenfeld funkelt in drei Gruppen (`TWINKLE_GROUPS`), der Plasma-Puls eines Sterns sitzt in seinem Nebel, Photonen laufen auf den Beams. Die Körper selbst schweben und pulsieren nicht: Jedes animierte Element zwischen ihnen wird eine eigene Compositor-Ebene, und Chrome sortiert alles danach Gemalte bei jedem gescrollten Frame neu (zwei davon kosteten auf der Übersicht 40 ms je Frame). Außerhalb des sichtbaren Bereichs ruht jede Bewegung des Plans.

### Netz-Statusboard und Betriebsmeldungen
Die Übersicht beginnt mit der Statuszeile (`NetworkPulse.vue`): „Alles in Ordnung · 29 von 31 Geräten online“ in Akzent oder die Zahl der offline bzw. gestörten Geräte in Zustandsfarbe mit den ersten zwei Namen („2 Geräte offline: NAS, Pi-hole“, weitere als „+n“), dahinter „Stand vor …“ (nach einem fehlgeschlagenen Neuladen in Bernstein) und bei Problemen „Zum Problem“, das das erste betroffene Gerät öffnet (offline vor gestört). Die Zählregel steht in `components/dashboard/pulse.ts` und gilt für Statuszeile und Statusboard. Danach folgen Statusboard, Betriebsmeldungen und Orbit-Karte; ab 1280 px stehen die Meldungen links neben der Karte (22 rem, innen scrollend), darunter über ihr mit den vier dringendsten und „Alle anzeigen“.

Das Statusboard (`LineStatusBoard.vue`) zeigt eine Zelle pro Subnetz/Orbit: rundes Netzschild, Name (700), Zustandstext in Zustandsfarbe („Keine Geräte“ in `fg-subtle` für ein leeres Netz), rechts „online/gesamt“ in Mono; ein Klick filtert die Übersicht. Betriebsmeldungen (`ServiceNotices.vue`) zeigen das Netzschild des betroffenen Geräts, Titel in Zustandsfarbe, Detail in Mono und relative Zeit.

### Weitere Netzfarbträger
- **IP-Kacheln:** belegt und online = Rahmen 55 % und Fläche 14 % in der Netzfarbe; offline rot getönt; frei Haarlinie; reserviert gestrichelt. Adressen in Mono.
- **Rack:** Einschübe als `raised`-Leisten mit kleinem Netzschild; leere Einheiten gestrichelt; Rahmen 6 px in gedämpfter Haarlinie.
- **Ersteinrichtung:** die vier Schritte entlang einer 5-px-Trajektorie (erledigt Akzent, offen `hairline-strong`), Hintergrund mit Koordinatenraster.
- **Netzfarben (Einstellungen):** pro Subnetz Netzschild, Palettenvorschläge des aktuellen Themas und freier Farbwähler; Zurücksetzen auf den Palettenslot.

### Leer-, Fehler- und Ladezustände
`EmptyState`, `ErrorState` (mit Wiederholen) und `Skeleton` in Kartenform; jede Liste und jede Karte hat alle drei.

## Do's and Don'ts

### Do:
- **Do** jede Netzfarbe über `networkColor()` bzw. `lineVar()`/`lineInk()` holen und sie überall gleich zeigen.
- **Do** neben jedem Netzschild den Netznamen als Text führen; das Schild ist Zierde, nicht alleinige Information.
- **Do** Zustand doppelt kodieren: Ring plus Durchstreichung, unterbrochene Umlaufbahn und Text-Badge („Offline“, „Störung“).
- **Do** Text auf Tönungen in `*-text` setzen und neue Textfarben in beiden Themen gegen 4,5:1 prüfen.
- **Do** Adressen, Zähler und Messwerte in JetBrains Mono mit Tabellenziffern setzen.
- **Do** Bewegung auf `opacity`/`transform` begrenzen; `prefers-reduced-motion` schaltet kontinuierliche Orbit-/Puls-Animationen automatisch ab. Fortschritts- und Messbalken füllen sich über `fillShift()`/`fillScale()`/`stackedLayers()` aus `lib/meter.ts`, nie über `width`.

### Don't:
- **Don't** Hex-Werte in Komponenten schreiben; Ausnahme ist die Schildtinte (`#0c0f14`) auf vollen Netzfarben.
- **Don't** Weiß auf vollen Netzfarben setzen.
- **Don't** Schatten auf ruhende Karten legen; `shadow-pop` gehört schwebenden Ebenen.
- **Don't** `.gl-eyebrow` als Vorspann über Titel setzen oder in Versalien; sie beschriftet Werte.
- **Don't** Seiten als KPI-Kachelreihe plus Tabelle bauen (kompakte Statusleisten nutzen).
- **Don't** Dauerbewegung an einzelne Himmelskörper oder Sterne hängen; die Zahl animierter Elemente im Orbit-Plan darf nicht mit dem Netz wachsen.
