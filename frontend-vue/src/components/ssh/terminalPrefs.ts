/**
 * Terminal look, chosen per browser and applied live to every open terminal. Same storage key
 * and font/theme ids as the React UI (Ssh/terminalPrefs.ts), so both UIs share the choice.
 */
import { reactive } from 'vue';
import type { ITheme } from '@xterm/xterm';

export interface TerminalPrefs {
  fontFamily: string;
  fontSize: number;
  theme: string;
  foreground: string | null;
  background: string | null;
}

export const FONT_SIZE_MIN = 9;
export const FONT_SIZE_MAX = 28;

interface FontOption {
  id: string;
  label: string;
  css: string;
  /** Bundled fonts are fetched only when chosen */
  load?: () => Promise<unknown>;
}

export const FONT_OPTIONS: FontOption[] = [
  {
    id: 'plex', label: 'IBM Plex Mono', css: "'IBM Plex Mono', monospace",
    load: () => Promise.all([import('@fontsource/ibm-plex-mono/400.css'), import('@fontsource/ibm-plex-mono/700.css')]),
  },
  {
    id: 'cascadia', label: 'Cascadia Code', css: "'Cascadia Code', monospace",
    load: () => Promise.all([import('@fontsource/cascadia-code/400.css'), import('@fontsource/cascadia-code/700.css')]),
  },
  {
    id: 'jetbrains', label: 'JetBrains Mono', css: "'JetBrains Mono', monospace",
    load: () => Promise.all([import('@fontsource/jetbrains-mono/400.css'), import('@fontsource/jetbrains-mono/700.css')]),
  },
  {
    id: 'fira', label: 'Fira Code', css: "'Fira Code', monospace",
    load: () => Promise.all([import('@fontsource/fira-code/400.css'), import('@fontsource/fira-code/700.css')]),
  },
  { id: 'system', label: 'System (Consolas / Menlo)', css: "Consolas, Menlo, 'DejaVu Sans Mono', 'Liberation Mono', monospace" },
  { id: 'courier', label: 'Courier New', css: "'Courier New', Courier, monospace" },
];

/** Unknown or retired ids fall back to the default font (JetBrains Mono, the app mono). */
function fontOption(id: string): FontOption {
  return FONT_OPTIONS.find((f) => f.id === id) ?? FONT_OPTIONS.find((f) => f.id === DEFAULT_PREFS.fontFamily) ?? FONT_OPTIONS[0];
}

export function fontCss(value: TerminalPrefs): string {
  return fontOption(value.fontFamily).css;
}

function hasFontFace(name: string): boolean {
  let found = false;
  document.fonts.forEach((face) => {
    if (face.family.replace(/['"]/g, '') === name) found = true;
  });
  return found;
}

/**
 * Load the chosen font before handing it to xterm: xterm measures the glyph size when the font
 * is set, and measuring a font that is still downloading would use the fallback.
 */
export async function loadTerminalFont(value: TerminalPrefs): Promise<void> {
  const option = fontOption(value.fontFamily);
  const family = option.css.split(',')[0].trim();
  const name = family.replace(/['"]/g, '');
  try {
    if (option.load) {
      await option.load();
      // The stylesheet can register its @font-face rules a moment after the import resolves
      for (let i = 0; i < 40 && !hasFontFace(name); i++) await new Promise((r) => setTimeout(r, 25));
    }
    await Promise.all([document.fonts.load(`${value.fontSize}px ${family}`, 'Mg'), document.fonts.load(`bold ${value.fontSize}px ${family}`, 'Mg')]);
  } catch {
    // Font unavailable: xterm falls back to the next family in the list
  }
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

// ANSI palettes for the presets; 'gravitylan' follows the app's colours (night network / daytime map)
export const THEMES: { id: string; label: string; theme: () => ITheme }[] = [
  {
    id: 'gravitylan',
    label: 'GravityLAN',
    theme: () => ({
      background: cssVar('--gl-sunken', '#080a0e'),
      foreground: cssVar('--gl-fg', '#e8edf3'),
      cursor: cssVar('--gl-accent', '#2ec4a6'),
      cursorAccent: cssVar('--gl-sunken', '#080a0e'),
      selectionBackground: 'rgba(46, 196, 166, 0.3)',
    }),
  },
  {
    id: 'classic',
    label: 'Classic (green on black)',
    theme: () => ({ background: '#000000', foreground: '#33FF66', cursor: '#33FF66', cursorAccent: '#000000', selectionBackground: 'rgba(51, 255, 102, 0.3)' }),
  },
  {
    id: 'solarized-dark',
    label: 'Solarized Dark',
    theme: () => ({
      background: '#002B36', foreground: '#839496', cursor: '#93A1A1', cursorAccent: '#002B36', selectionBackground: 'rgba(147, 161, 161, 0.3)',
      black: '#073642', red: '#DC322F', green: '#859900', yellow: '#B58900', blue: '#268BD2', magenta: '#D33682', cyan: '#2AA198', white: '#EEE8D5',
      brightBlack: '#586E75', brightRed: '#CB4B16', brightGreen: '#93A1A1', brightYellow: '#839496', brightBlue: '#839496', brightMagenta: '#6C71C4', brightCyan: '#93A1A1', brightWhite: '#FDF6E3',
    }),
  },
  {
    id: 'dracula',
    label: 'Dracula',
    theme: () => ({
      background: '#282A36', foreground: '#F8F8F2', cursor: '#F8F8F2', cursorAccent: '#282A36', selectionBackground: 'rgba(68, 71, 90, 0.8)',
      black: '#21222C', red: '#FF5555', green: '#50FA7B', yellow: '#F1FA8C', blue: '#BD93F9', magenta: '#FF79C6', cyan: '#8BE9FD', white: '#F8F8F2',
      brightBlack: '#6272A4', brightRed: '#FF6E6E', brightGreen: '#69FF94', brightYellow: '#FFFFA5', brightBlue: '#D6ACFF', brightMagenta: '#FF92DF', brightCyan: '#A4FFFF', brightWhite: '#FFFFFF',
    }),
  },
  {
    id: 'light',
    label: 'Light',
    theme: () => ({
      background: '#FAFAFA', foreground: '#383A42', cursor: '#526FFF', cursorAccent: '#FAFAFA', selectionBackground: 'rgba(82, 111, 255, 0.25)',
      black: '#383A42', red: '#E45649', green: '#50A14F', yellow: '#986801', blue: '#4078F2', magenta: '#A626A4', cyan: '#0184BC', white: '#A0A1A7',
      brightBlack: '#696C77', brightRed: '#E45649', brightGreen: '#50A14F', brightYellow: '#C18401', brightBlue: '#4078F2', brightMagenta: '#A626A4', brightCyan: '#0184BC', brightWhite: '#383A42',
    }),
  },
];

export const DEFAULT_PREFS: TerminalPrefs = { fontFamily: 'jetbrains', fontSize: 13, theme: 'gravitylan', foreground: null, background: null };

const STORAGE_KEY = 'gravitylan.terminal';

export function clampFontSize(size: number): number {
  if (!Number.isFinite(size)) return DEFAULT_PREFS.fontSize;
  return Math.min(FONT_SIZE_MAX, Math.max(FONT_SIZE_MIN, Math.round(size)));
}

function load(): TerminalPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const parsed = { ...DEFAULT_PREFS, ...JSON.parse(raw) } as TerminalPrefs;
    parsed.fontSize = clampFontSize(Number(parsed.fontSize));
    return parsed;
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

/** Reactive prefs; every terminal watches this object. */
export const terminalPrefs = reactive<TerminalPrefs>(load());

export function setTerminalPrefs(update: Partial<TerminalPrefs>) {
  Object.assign(terminalPrefs, update, { fontSize: clampFontSize(update.fontSize ?? terminalPrefs.fontSize) });
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(terminalPrefs));
  } catch {
    // storage blocked: keep for this page
  }
}

export function resetTerminalPrefs() {
  setTerminalPrefs(DEFAULT_PREFS);
}

export function resolveTheme(value: TerminalPrefs): ITheme {
  const base = (THEMES.find((th) => th.id === value.theme) ?? THEMES[0]).theme();
  return {
    ...base,
    ...(value.foreground ? { foreground: value.foreground } : {}),
    ...(value.background ? { background: value.background, cursorAccent: value.background } : {}),
  };
}
