---
name: GravityUI
description: Das Heimnetz als Liniennetzplan – Subnetze sind farbige Linien, Geräte sind Stationen.
colors:
  # Nachtnetz (dunkel, Standard)
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
  # Weißer Tagesplan (hell)
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
  station-name:
    fontFamily: "Hanken Grotesk Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: "16px"
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
  station:
    backgroundColor: "{colors.station}"
    rounded: "{rounded.full}"
    size: "18px"
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

GravityUI (`frontend-vue/`) ist die optionale zweite Oberfläche von GravityLAN unter `/frontend-vue/`, neben der unveränderten React-Ansicht (Standard unter `/`). Beide sprechen dasselbe Backend an, teilen den API-Client über den Alias `@shared` und die Texte (i18next aus `frontend/src/locales`; eigene Schlüssel nur unter `gv.*`). Dieses Dokument beschreibt den ausgelieferten Stand (Richtung „Liniennetzplan“, Seed `818d609b`), nicht die Planung. Es ersetzt die frühere Fassung im Antigravity-Look vollständig.

## Overview

**Creative North Star: „Der Liniennetzplan“**

Das Heimnetz wird gelesen wie ein Verkehrsplan, den der Betreiber selbst zeichnet. Jedes Subnetz bzw. VLAN ist eine farbige Linie mit eigenem rundem Linienschild („30“, „H“), Geräte sind Stationen mit Ring, Router und mehrfach angebundene Geräte sind Umsteigestationen. Dieselbe Linienfarbe trägt ein Netz überall: auf dem Netzplan, im Linienschild, im Statusboard, in den Betriebsmeldungen, auf belegten IP-Kacheln, in Rack-Einschüben und in der Subnetz-Auswahl. Auch die Navigation ist eine Strecke: jede Seite hat ihre eigene Linienfarbe, die aktuelle Station ist gefüllt.

Der Standard ist das Nachtnetz: ein tiefblauschwarzer Grund mit flachen Flächen, Haarlinien statt Schatten, hellen Linien und weißen Stationsringen. Das helle Thema ist der weiße Tagesplan mit derselben Linienlogik und eigens abgedunkelten Palettenwerten. Die Oberfläche ist ein Werkzeug für den täglichen Blick: dicht, ruhig, Zahlen und Adressen in Mono, Störungen vorne. Zustand wird nie nur über Farbe getragen: ausgefallene Stationen sind rot umrandet und durchgestrichen („Halt entfällt“), Strecken zu ihnen werden gepunktet („Störung“), Meldungen haben immer einen Text.

Die Richtung lehnt das KPI-Kacheln-plus-Tabelle-Admin-Dashboard ab. Health und Agents tragen diesen Aufbau noch (siehe „Offene Punkte“); er ist kein Vorbild für neue Seiten.

**Key Characteristics:**
- Eine Farbe pro Netz, überall identisch, vom Nutzer umfärbbar (Einstellung `ui.line_colors`).
- Runde Linienschilder mit dunkler Schildtinte; Stationen als Ringe; oktilineare 45°-Strecken mit runden Enden.
- Nachtnetz als Standard, weißer Tagesplan als helles Thema; alle Texte erreichen in beiden Themen 4,5:1.
- Flach: Karten mit Haarlinie, Schatten nur für schwebende Ebenen.
- Hanken Grotesk für die Oberfläche, JetBrains Mono für IPs, MACs, Ports, Latenzen und Zähler.

## Colors

Ein neutraler, leicht blaustichiger Grund trägt eine Palette aus zehn klaren Linienfarben; dazu ein einziger Handlungsakzent (Türkis) und drei Zustandsfarben.

Alle Werte liegen als `--gl-*` und `--line-1..10` in `src/index.css` und werden über `@theme` auf Tailwind-Klassen abgebildet (`bg-canvas`, `bg-chrome`, `bg-surface`, `bg-raised`, `bg-sunken`, `bg-control`, `border-line`, `border-line-strong`, `text-fg`, `text-fg-muted`, `text-fg-subtle`, `bg-station`, `bg-accent`/`text-accent-text`, `info`, `warn`, `danger` jeweils mit `*-text`). Komponenten verwenden nur diese semantischen Namen. Das Thema hängt an `data-theme` auf `<html>`; ein Skript in `index.html` setzt es vor dem ersten Paint (Standard dunkel), `useTheme.ts` schaltet zwischen dunkel, hell und System um und speichert unter `gravityui.theme`.

### Primary
- **Signaltürkis** (`accent`, dunkel #2ec4a6 / hell #087a65): primäre Aktion (Scan, Fertig), Fokusring (2 px, Abstand 2 px), Textcursor, aktive Tab-Unterstreichung, aktive Statusboard-Zeile, „gesund/online“-Punkte, Verbindungslinie beim Zeichnen im Netzplan. Text in Akzentfarbe nutzt immer `accent-text`; Text auf gefülltem Akzent `accent-fg`.

### Secondary
- **Linienpalette** (`--line-1` bis `--line-10`, je Thema eigener Satz): Identität der Netze und der Seiten. Ohne Nutzerwahl bekommt ein Subnetz den Slot `((id − 1) mod 10) + 1`; ohne Subnetz wird der Slot aus dem /24-Präfix gehasht (`networkColor` in `src/lib/networks.ts`). Die Nutzerwahl (Hex, pro Subnetz) hat Vorrang und gilt in beiden Themen. Die helle Palette ist dunkler gestimmt, damit Linien auf Weiß tragen.

### Tertiary
- **Zustandsfarben**: Info-Blau (`info`) für Eingabefokus und Hinweise, Bernstein (`warn`) für gestörte Dienste und blinkende Stationsringe, Signalrot (`danger`) für ausgefallene Stationen, Fehler und destruktive Aktionen. Flächen davon nur als Tönung (`/10`, Rand `/25`–`/30`), Text immer in der `*-text`-Variante.

### Neutral
- **Nachtgrund** (`canvas`): Seitenhintergrund. **Nachtleiste** (`chrome`): Seitenleiste und mobile Tab-Leiste. **Kartenfläche** (`surface`): Karten, Dialoge, Popover. **Innenfläche** (`raised`): Unterkarten, aktive Navigation, Hover von Zeilen. **Senke** (`sunken`): Eingabefelder, Segmentschalter, Rack-Innenraum, Netzplan-Grund im Dunkeln. **Bedienfläche** (`control`/`control-hover`): Sekundär-Buttons.
- **Haarlinien** (`hairline` = `--gl-line`, `hairline-strong`): Rahmen, Trenner, Hover-Rahmen, Scrollbalken.
- **Textstufen** (`fg`, `fg-muted`, `fg-subtle`): Inhalt, Beschreibung, Metadaten. Im hellen Thema wurden alle Textstufen so abgedunkelt, dass sie auf ihren eigenen 10–15-%-Tönungen über Weiß 4,5:1 erreichen.
- **Stationspapier** (`station`): Füllung der Stationsringe. **Schildtinte** (`sign-ink`, #0c0f14): fester Text auf Linienschildern und aktiven Navigationsschildern, in beiden Themen.

### Named Rules
**The Linienfarbe-ist-Identität Rule.** Ein Netz hat genau eine Farbe, und die kommt immer aus `networkColor()` (oder `lineVar()` für Seiten). Wer ein Netz zeigt, zeigt es in dieser Farbe; keine zweite Farblogik pro Ansicht, keine Hex-Werte in Komponenten.

**The Tönung-ist-keine-Schrift Rule.** Getönte Flächen (`bg-accent/10`, `bg-danger/10`, `color-mix(… 14–16 %)`) tragen nie Text in der Grundfarbe; Text darauf nutzt `*-text` bzw. `lineInk()` (Linienfarbe 75 % zur Textfarbe gemischt).

**The Schildtinte Rule.** Auf vollflächigen Linienfarben steht immer die dunkle Schildtinte (#0c0f14), nie Weiß, unabhängig vom Thema.

## Typography

**Display Font:** Hanken Grotesk Variable (mit ui-sans-serif, system-ui)
**Body Font:** Hanken Grotesk Variable, Stilsätze `ss01`, `cv11`
**Label/Mono Font:** JetBrains Mono (mit ui-monospace), Null mit Strich, Tabellenziffern

**Character:** Eine sachliche, leicht kantige Grotesk wie auf Verkehrsschildern, gepaart mit einer technischen Mono für alles, was man abliest oder abtippt.

### Hierarchy
- **Display** (700, 1,5 rem, eng gesperrt): nur der Willkommensschritt der Ersteinrichtung.
- **Headline** (600, 1,25 rem): Seitentitel im `PageHeader`; auf Telefonen nur für Screenreader, weil die App-Leiste den Titel zeigt. Einrichtungsschritte nutzen dieselbe Größe in 700.
- **Title** (700, 0,875 rem): Karten- und Abschnittstitel, Linienname im Statusboard, Meldungstitel. Dialogtitel 1 rem in 600.
- **Body** (400–500, 0,875 rem): Fließtext, Navigation, Buttons (500, primär 600), Beschreibungen (`max-w-2xl`).
- **Meta** (0,75 rem): Hilfetexte, Zähler, Zeitangaben.
- **Label** (600, 0,75 rem, `fg-subtle`, normale Schreibung; Klasse `.gl-eyebrow`): Beschriftung direkt über einem Messwert oder einer Definitionsliste und kleine Listengruppen-Überschriften. Kein Versal-Satz, kein Vorspann über Seiten- oder Abschnittstiteln.
- **Badge** (500, 11 px): Badges, mobile Tab-Beschriftungen, Versionsnummer.
- **Mono** (11 px bis 0,875 rem): IPs, CIDRs, MACs, Ports, Latenzen („2,4 ms“), Online-Zähler („14/15“), Linktypen.
- **Linienschild** (800, 10 px / 12 px / 14 px in sm/md/lg): VLAN-ID oder Anfangsbuchstabe.
- **Stationsname** (700, 13 px) mit Mono-Zeile (10,5 px) darunter: nur im Netzplan.

### Named Rules
**The Abgelesen-in-Mono Rule.** Alles, was eine Adresse, ein Zähler oder ein Messwert ist, steht in JetBrains Mono mit Tabellenziffern; Fließtext und Namen nie.

## Layout

- **Hülle:** Desktop ab 768 px mit fester Seitenleiste (240 px, `chrome`, rechte Haarlinie); darunter eine obere App-Leiste mit Seitentitel und eine untere Tab-Leiste (vier Ziele plus „Mehr“, Mindesthöhe 56 px, `chrome` 95 % mit Unschärfe, Safe-Area-Abstand). „Mehr“ öffnet die volle Navigation als Bottom-Sheet.
- **Seiten:** `max-w-[1800px]`, zentriert; Rand 16 px mobil / 32 px ab `md`; oben 20 px / 28 px; 24 px zwischen Blöcken. Kopfzeile: Titel und Einzeiler links, Aktionen rechts, umbrechend.
- **Raster:** 16 px zwischen Karten (12 px in dichten Gerätegittern); Karten-Innenabstand 16 px horizontal, 12–14 px vertikal; Dialoge 20 px.
- **Statusboard:** eine Zelle pro Linie, `auto-fit` mit mindestens 16 rem, auf Telefonen gestapelt mit Trennern.
- **Netzplan:** füllt seinen Rahmen, `fitView` mit 15 % Rand, Zoom 0,2–2,5; Bedienknöpfe unten rechts, Bearbeitungspanels unten links. Grund: dunkel `sunken`, hell `surface` (Weiß), jeweils mit Punktraster (28 px).
- **Touch:** Ziele mindestens 44 px auf Telefonen; Eingaben dort 16 px Schrift, sonst zoomt iOS.

## Elevation & Depth

Das System ist flach und tonal geschichtet: `canvas` → `surface` → `raised`, Senken (`sunken`) für Eingaben. Tiefe entsteht durch Haarlinien und Tonstufen, nicht durch Schatten.

### Shadow Vocabulary
- **Kartenkante** (`--gl-shadow-card`; dunkel `0 1px 0 0 rgb(255 255 255 / 0.025) inset`, hell `0 1px 2px rgb(16 20 27 / 0.04)`): auf jeder `.gl-card`, kaum sichtbar.
- **Schwebend** (`--gl-shadow-pop`; dunkel `0 24px 48px -12px rgb(0 0 0 / 0.65), 0 0 0 1px rgb(255 255 255 / 0.04)`, hell `0 20px 40px -12px rgb(16 20 27 / 0.2), 0 0 0 1px rgb(16 20 27 / 0.06)`): Dialoge, Sheets, Popover, Netzplan-Bedienelemente und -Panels, Linktyp-Etikett.
- Dialog-Overlay: Schwarz 55 % mit 2 px Unschärfe.

### Named Rules
**The Flach-auf-dem-Plan Rule.** Was auf der Seite liegt, hat keinen Schatten außer der Kartenkante; nur was über anderem schwebt, bekommt `shadow-pop`.

## Shapes

Runde Formen gehören dem Netz, weich gerundete Rechtecke der Bedienung. Linienschilder, Stationen, Umsteigekapseln, Statuspunkte, Fortschrittsbalken und Streckenenden sind voll rund. Badges 6 px, Buttons, Felder, Navigationseinträge und Kacheln 10 px, Karten 14 px, Dialoge 18 px (auf Telefonen nur oben). Navigations-Seitenschilder sind gerundete Quadrate (7 px), Rack-Einschübe und Segmentschalter-Knöpfe 5 px. Rahmen sind 1 px Haarlinien; gestrichelte Rahmen bedeuten „frei“ oder „reserviert“ (IP-Kacheln, leere Rack-Einheiten).

Strecken im Netzplan sind oktilinear: gerade entlang der längeren Achse, eine 45°-Diagonale, wieder gerade; 8 px Strich (ausgewählt 11 px), runde Enden und Knicke.

**The Gerade-bleibt-gerade Rule.** Verbundene Stationen, deren x- oder y-Wert um höchstens 24 px (`ALIGN_TOLERANCE`) abweicht, liegen auf einer Achse: `alignStations()` zieht beim Zeichnen die weniger verbundene Station auf die Achse (nur Anzeige), `snapToNeighbours()` rastet eine abgelegte Station vor dem Speichern auf die Achse des nächsten verbundenen Nachbarn ein. Diagonalen entstehen nur als bewusste 45°-Abzweige.

## Components

### Buttons
Sachlich und kompakt.
- **Shape:** sanft gerundet (10 px), Höhen 32 / 36 / 44 px (sm/md/lg), Icons 16 px.
- **Primary:** Akzentfläche mit `accent-fg`, 600; Hover `accent-hover`.
- **Secondary (Standard):** `control` mit Haarlinie; Hover `control-hover` und `hairline-strong`.
- **Ghost:** transparent, `fg-muted`; Hover Fläche und `fg`.
- **Danger / Danger-ghost:** gefülltes Rot mit `danger-fg` (dunkle Tinte im Nachtnetz, Weiß im Tagesplan; wie `accent-fg` beim Primär-Button) bzw. roter Text mit Tönung im Hover. Gefüllte Info-Flächen tragen Text in `canvas`.
- **States:** Farbübergang 150 ms; deaktiviert 50 % Deckkraft; Laden mit drehendem Loader und `aria-busy`. Fokus über den globalen Akzentring.

### Chips
- **Badges:** 11 px, 6 px Radius, Tönung + `*-text` + getönter Rand (neutral, accent, info, warn, danger), optional Mono.
- **Linienschild (`LineBullet`):** rund, Linienfarbe, Schildtinte, 800; Größen 20 / 28 / 40 px. Text ist die VLAN-ID, sonst der Anfangsbuchstabe des Subnetzes (`lineLabel`), „·“ wenn unbekannt; Meldungen ohne Gerät tragen ein neutrales Schild in `fg-muted`. Das Schild ist dekorativ (`aria-hidden`), der Netzname steht immer als Text daneben.
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
- **Seitenleiste:** Einträge 36 px, 10 px Radius. Jede Seite trägt ein 26-px-Schild in ihrer Linienfarbe (`navigation.ts`, `line`): inaktiv 16 % Tönung mit Icon in `lineInk`, aktiv voll gefüllt mit Schildtinte, Eintrag `raised` und 600. Zwischen den Schildern verbindet ein kurzer Verlauf von Linie zu Linie die Seiten zur Strecke. Zähler (online/gesamt, SSH-Sitzungen) rechts in Mono.
- **Mobil:** Tab-Leiste mit 20-px-Icons und 11-px-Beschriftung; aktiv `fg`, Icon in `lineInk` und ein 3-px-Balken in Linienfarbe an der Oberkante. „Mehr“ öffnet das Navigations-Sheet mit denselben Schildern.
- **Tabs:** 40 px, `fg-muted`; aktiv `fg` mit 2-px-Unterstreichung in Akzent.

### Dialoge und Sheets
`Dialog` ist ab 640 px zentriert (18 px Radius), darunter ein Bottom-Sheet über volle Breite mit Safe-Area. Kopf mit Titel (1 rem, 600), Schließen-Knopf, Trennlinie; Fuß rechtsbündig. Eintritt 220 ms mit `--ease-out-expo`, Overlay 160 ms ein / 120 ms aus. `Sheet` ist das Seitenpanel (mobil Vollbild). Toasts und Bestätigungen laufen über `useToast`/`useConfirm`.

### Netzplan (Signaturkomponente)
`src/components/netzplan/`, gebaut auf Vue Flow, teilt Positionen und Links mit dem React-Topologie-Editor.
- **Ankerbox:** jede Station sitzt mittig in derselben 28×28-px-Box, unabhängig von Marker- und Namensbreite; so fluchten Stationen auf einer Achse.
- **Station:** 18-px-Ring (3,5 px) auf Stationspapier. Online: Ring in `fg`. Gestört: Ring `warn` mit stufig blinkender Füllung (1,2 s). Ausgefallen: Ring `danger`, rot durchgestrichen, Name und „Halt entfällt“ in `danger-text`. Hover vergrößert auf 110 % (200 ms); Auswahl 4-px-Akzentring.
- **Umsteigestation:** Kapsel (28 px hoch, mindestens 48 px breit) mit bis zu vier Punkten in den Farben der dort treffenden Linien; für Gateways und Geräte in mehreren Netzen.
- **Strecke:** oktilinear, Linienfarbe, 8 px; gepunktet (`1 13`), wenn ein Endpunkt ausgefallen ist. Farbe: gewählte Linkfarbe, sonst Linien-Slot aus `lineSlots()`, sonst Netzfarbe.
- **Bearbeiten:** Stationen ziehen (Ablage rastet auf die Achse des nächsten verbundenen Nachbarn ein, siehe Gerade-bleibt-gerade), an Griffen (10 px, Akzent) neue Strecken ziehen, pro Strecke Farbe und Linktyp (10GbE, 2.5GbE, 1GbE, WLAN, Fiber) im Panel unten links, automatisch anordnen (eine Zeile pro Netz, Gateway vorn).

### Linien-Statusboard und Betriebsmeldungen
Das Statusboard zeigt eine Zelle pro Linie: großes Linienschild, Name (700), Zustandstext in Zustandsfarbe, rechts „online/gesamt“ in Mono; ein Klick filtert die Geräte, die aktive Zelle ist `raised` mit Akzent-Unterkante. Betriebsmeldungen sind eine Karte mit Trennern: kleines Linienschild des betroffenen Geräts, Titel in Zustandsfarbe, Detail in Mono, relative Zeit, Pfeil erscheint im Hover.

### Weitere Linienträger
- **IP-Kacheln:** belegt und online = Rahmen 55 % und Fläche 14 % in der Linienfarbe; offline rot getönt; frei Haarlinie; reserviert gestrichelt. Adressen in Mono.
- **Rack:** Einschübe als `raised`-Leisten mit kleinem Linienschild statt Farbstreifen; leere Einheiten gestrichelt; Rahmen 6 px in gedämpfter Haarlinie.
- **Ersteinrichtung:** die vier Schritte als Stationen auf einer 5-px-Linie (erledigt Akzent, offen `hairline-strong`), Hintergrund mit Punktraster.
- **Linienfarben (Einstellungen):** pro Subnetz Linienschild, Palettenvorschläge des aktuellen Themas und freier Farbwähler; Zurücksetzen auf den Palettenslot.

### Leer-, Fehler- und Ladezustände
`EmptyState`, `ErrorState` (mit Wiederholen) und `Skeleton` in Kartenform; jede Liste und jede Karte hat alle drei.

## Do's and Don'ts

### Do:
- **Do** jede Netzfarbe über `networkColor()` bzw. `lineVar()`/`lineInk()` holen und sie überall gleich zeigen.
- **Do** neben jedem Linienschild den Netznamen als Text führen; das Schild ist Zierde, nicht Information.
- **Do** Zustand doppelt kodieren: Ring plus Durchstreichung, gepunktete Strecke, Text („Halt entfällt“, „Störung“).
- **Do** Text auf Tönungen in `*-text` setzen und neue Textfarben in beiden Themen gegen 4,5:1 prüfen.
- **Do** Adressen, Zähler und Messwerte in JetBrains Mono mit Tabellenziffern setzen.
- **Do** Bewegung auf `opacity`/`transform` (bzw. Strichbreite) begrenzen, 150–400 ms, Eintritte mit `--ease-out-expo`; `prefers-reduced-motion` schaltet global ab, Netzplan-Tweens (Einpassen, Zoom) laufen dann mit Dauer 0 über `motion()`.

### Don't:
- **Don't** Hex-Werte in Komponenten schreiben; Ausnahme ist die Schildtinte auf Linienfarben.
- **Don't** Weiß auf Linienfarben setzen.
- **Don't** eine zweite Farblogik für Netze erfinden (etwa Farbstreifen, Gruppenfarben oder Gerätekürzel statt Linienschild).
- **Don't** Schatten auf ruhende Karten legen; `shadow-pop` gehört schwebenden Ebenen.
- **Don't** `.gl-eyebrow` als Vorspann über Titel setzen oder in Versalien; sie beschriftet Werte.
- **Don't** neue Seiten als KPI-Kachelreihe plus Tabelle bauen.

### Offene Punkte (Stand Abschluss-Review, nicht erledigt)
- Netzplan-Farben folgen Ästen (`lineSlots`: jede Abzweigung vom Kern oder von einem Switch eröffnet eine neue Linie), nicht streng einem Subnetz pro Linie.
- Stationen ohne Links schweben neben den Linien statt auf ihnen.
- Beschriftungen im Netzplan sind beim eingepassten Zoom zu klein (13 px / 10,5 px vor Skalierung).
- Health und Agents nutzen noch KPI-Leiste plus Tabelle.
- Die Suche sitzt nicht in der oberen Leiste (Ctrl K), sondern als Filter über den Gruppen.
- Gerätekarten in der Übersicht haben ungleiche Höhen.
