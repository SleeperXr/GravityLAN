# GravityUI – Design-System

GravityUI (`frontend-vue/`) ist die zweite Oberfläche von GravityLAN neben der React-Ansicht (`frontend/`). Beide sprechen dasselbe Backend an. Die React-Ansicht bleibt der Standard unter `/`, GravityUI liegt unter `/frontend-vue/`.

## Grundsätze

- **Werkzeug, kein Schaufenster.** Ein Homelab-Inventar wird täglich kurz geprüft. Status und Abweichungen stehen vorne, Dekoration tritt zurück.
- **Eine Akzentfarbe für Handlungen.** Emerald markiert primäre Aktionen und „gesund/online“. Sky ist Information und Fokus. Amber warnt, Rose ist Fehler oder destruktiv. Kein Violett.
- **Status nie nur über Farbe.** Jeder Statuspunkt hat ein Textlabel oder einen `aria-label`.
- **Gleiche Texte wie React.** i18next mit `frontend/src/locales`. Eigene Schlüssel nur unter `gv.*` in `src/locales`.

## Tokens (`src/index.css`)

Komponenten nutzen nur semantische Tailwind-Klassen, nie Hex-Werte.

| Rolle | Klasse | Dunkel | Hell |
|---|---|---|---|
| Seitenhintergrund | `bg-canvas` | #0a0a0c | #f4f5f7 |
| Sidebar/Leisten | `bg-chrome` | #0e0e11 | #ffffff |
| Karten | `bg-surface` / `.gl-card` | #131316 | #ffffff |
| Innenflächen | `bg-raised` / `.gl-subcard` | #1b1b20 | #f4f5f7 |
| Eingabefelder | `bg-sunken` | #0d0d10 | #eceef1 |
| Buttons | `bg-control` | #1f1f25 | #ffffff |
| Linien | `border-line` / `border-line-strong` | 7,5 % / 15 % Weiß | 9 % / 18 % Schwarz |
| Text | `text-fg` / `text-fg-muted` / `text-fg-subtle` | #f4f4f5 / #a1a1aa / #8b8b94 | #18181b / #52525b / #63636c |
| Akzent | `bg-accent` + `text-accent-fg`, Text `text-accent-text` | #10b981 / #34d399 | #059669 / #047857 |
| Info | `text-info-text`, `bg-info` | #7dd3fc / #38bdf8 | #0369a1 / #0284c7 |
| Warnung | `text-warn-text`, `bg-warn` | #fbbf24 / #f59e0b | #b45309 / #d97706 |
| Fehler | `text-danger-text`, `bg-danger` | #fb7185 / #f43f5e | #be123c / #e11d48 |

Textfarben erreichen auf `surface` und `raised` mindestens 4,5:1 (WCAG AA). Tönungen wie `bg-accent/10` sind nur Flächen, Text darauf nutzt immer die `*-text`-Variante.

**Typografie:** IBM Plex Sans (UI) und IBM Plex Mono (IPs, MACs, Ports, Zahlen, mit Tabellenziffern). Stufen: Seitentitel `text-xl` semibold, Kartentitel `text-sm` semibold, Fließtext `text-sm`, Metadaten `text-xs`, Eyebrow `.gl-eyebrow` (11 px, Versalien).

**Abstände:** 4-px-Raster. Karten `p-4`/`p-5`, Abstand zwischen Karten `gap-4` (mobil `gap-3`), Seitenränder `px-4` mobil und `px-8` ab `md`.

**Radien:** `rounded-sm` 6 px (Badges), `rounded-md` 8 px (Buttons, Felder), `rounded-lg` 12 px (Karten), `rounded-xl` 16 px (Dialoge).

**Bewegung:** 150–280 ms, `--ease-out-expo` für Eintritte, nur `opacity`/`transform`. `prefers-reduced-motion` schaltet alles ab.

## Bausteine (`src/components/ui`)

Button (primary, secondary, ghost, danger, danger-ghost), Badge (Töne), Field (Label, Hinweis, Fehler, verknüpft per `aria-describedby`), Input, Textarea, Select (nativ), Switch, Dialog (mobil als Bottom-Sheet), Sheet (Seitenpanel, mobil im Vollbild), Tabs, EmptyState, ErrorState, Skeleton, PageHeader, Toasts (`useToast`) und Bestätigungen (`useConfirm`).

## Mobil

Unter 768 px: obere Leiste mit Seitentitel, untere Tab-Leiste (Übersicht, Health, IP-Adressen, Agents, Mehr) und Safe-Area-Abstände. Eingabefelder haben dort 16 px Schrift, sonst zoomt iOS beim Fokus. Touch-Ziele sind mindestens 44 px hoch.
