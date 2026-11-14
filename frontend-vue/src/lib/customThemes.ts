import { ref } from 'vue';
import { themeInfo, type ThemePreview } from './themes';

/**
 * Designs the user uploads as a JSON file. A design names a built-in base ("dark" or "light")
 * and overrides any of the colour tokens below; what it leaves out comes from the base. Only
 * these keys and plain hex colours are accepted, and the values are set one custom property at a
 * time (style.setProperty), never as CSS text, so a file cannot bring rules, url() or anything
 * else into the page. Stored in this browser, like the design choice itself.
 */

/** Colour tokens a design may set: `--gl-<key>`, and `line-1` .. `line-10` for `--line-<n>`. */
export const DESIGN_TOKENS = [
  'canvas', 'chrome', 'surface', 'raised', 'sunken', 'control', 'control-hover', 'popover', 'hover',
  'line', 'line-strong', 'field-line',
  'fg', 'fg-muted', 'fg-subtle', 'station',
  'primary', 'primary-hover', 'primary-fg',
  'accent', 'accent-hover', 'accent-fg', 'accent-text',
  'info', 'info-text', 'maint', 'maint-text', 'warn', 'warn-text', 'danger', 'danger-fg', 'danger-text',
  'neutral-dot', 'mark-ok', 'mark-warn', 'mark-danger', 'badge', 'badge-text', 'badge-line', 'orbit-canvas',
  ...Array.from({ length: 10 }, (_, i) => `line-${i + 1}`),
] as const;

export type DesignToken = (typeof DESIGN_TOKENS)[number];
export type DesignBase = 'dark' | 'light';

export interface CustomTheme {
  /** Preference value is `custom:<id>` */
  id: string;
  name: string;
  base: DesignBase;
  colors: Partial<Record<DesignToken, string>>;
}

export const DESIGN_FORMAT = 'gravityui-design';
export const MAX_DESIGNS = 10;
export const MAX_FILE_BYTES = 20_000;
const MAX_NAME = 40;
const STORAGE_KEY = 'gravityui.custom_themes';
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const TOKENS = new Set<string>(DESIGN_TOKENS);

export function cssVar(token: DesignToken): string {
  return /^line-\d+$/.test(token) ? `--${token}` : `--gl-${token}`;
}

/** Why a file was not accepted: an i18n key under gv.design and its parameters. */
export interface DesignError {
  key: 'not_json' | 'not_object' | 'name' | 'base' | 'colors' | 'unknown_keys' | 'bad_value' | 'too_large';
  params?: Record<string, string | number>;
}

export type ParseResult = { ok: true; theme: Omit<CustomTheme, 'id'> } | { ok: false; error: DesignError };

/**
 * Read and check a design file. Expected shape:
 * { "format": "gravityui-design", "name": "…", "base": "dark" | "light", "colors": { "surface": "#121416", … } }
 * ("format" is optional; it lets the file say what it is.)
 */
export function parseDesign(text: string): ParseResult {
  if (text.length > MAX_FILE_BYTES) return { ok: false, error: { key: 'too_large', params: { max: MAX_FILE_BYTES / 1000 } } };
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { ok: false, error: { key: 'not_json' } };
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return { ok: false, error: { key: 'not_object' } };
  const raw = data as Record<string, unknown>;

  const name = typeof raw.name === 'string' ? raw.name.trim() : '';
  if (!name || name.length > MAX_NAME) return { ok: false, error: { key: 'name', params: { max: MAX_NAME } } };
  if (raw.base !== 'dark' && raw.base !== 'light') return { ok: false, error: { key: 'base' } };
  if (!raw.colors || typeof raw.colors !== 'object' || Array.isArray(raw.colors)) return { ok: false, error: { key: 'colors' } };

  const entries = Object.entries(raw.colors as Record<string, unknown>);
  const unknown = entries.map(([k]) => k).filter((k) => !TOKENS.has(k));
  if (unknown.length) return { ok: false, error: { key: 'unknown_keys', params: { keys: unknown.slice(0, 5).join(', ') } } };
  const bad = entries.find(([, v]) => typeof v !== 'string' || !HEX.test(v));
  if (bad) return { ok: false, error: { key: 'bad_value', params: { key: bad[0] } } };

  const colors = Object.fromEntries(entries.map(([k, v]) => [k, (v as string).toLowerCase()])) as CustomTheme['colors'];
  return { ok: true, theme: { name, base: raw.base, colors } };
}

function readStored(): CustomTheme[] {
  try {
    const list = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as unknown;
    if (!Array.isArray(list)) return [];
    // Stored designs pass the same check as an upload: an edited localStorage gets no further than a file
    return list.flatMap((item) => {
      const id = item && typeof item === 'object' ? (item as { id?: unknown }).id : undefined;
      if (typeof id !== 'string' || !/^[a-z0-9]{1,16}$/.test(id)) return [];
      const checked = parseDesign(JSON.stringify(item));
      return checked.ok ? [{ id, ...checked.theme }] : [];
    });
  } catch {
    return [];
  }
}

/** The uploaded designs of this browser */
export const customThemes = ref<CustomTheme[]>(readStored());

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(customThemes.value));
  } catch {
    // Private mode or full storage: the design lasts for this page view
  }
}

export function addCustomTheme(theme: Omit<CustomTheme, 'id'>): CustomTheme {
  const created: CustomTheme = { id: Math.random().toString(36).slice(2, 10), ...theme };
  customThemes.value = [...customThemes.value, created].slice(-MAX_DESIGNS);
  persist();
  return created;
}

export function removeCustomTheme(id: string) {
  customThemes.value = customThemes.value.filter((t) => t.id !== id);
  persist();
}

export function findCustomTheme(id: string): CustomTheme | undefined {
  return customThemes.value.find((t) => t.id === id);
}

/** An uploaded design's preview for the design menu: its own colours, the rest from its base */
export function customPreview(theme: CustomTheme): ThemePreview {
  const base = themeInfo(theme.base).preview;
  const c = theme.colors;
  return {
    canvas: c.canvas ?? base.canvas,
    surface: c.surface ?? base.surface,
    line: c['line-strong'] ?? c.line ?? base.line,
    text: c.fg ?? base.text,
    accent: c.accent ?? base.accent,
    primary: c.primary ?? c.accent ?? base.primary,
    network: c['line-1'] ?? base.network,
  };
}

/** Set a design's colours on <html>, and remove any colour a previous design set but this one does not. */
export function applyCustomColors(colors: CustomTheme['colors'] | null, root: HTMLElement = document.documentElement) {
  for (const token of DESIGN_TOKENS) {
    const value = colors?.[token];
    if (value && HEX.test(value)) root.style.setProperty(cssVar(token), value);
    else root.style.removeProperty(cssVar(token));
  }
}

/** The design on screen as a file to start from: every token with its current value. */
export function designTemplate(name: string, base: DesignBase, root: HTMLElement = document.documentElement): string {
  const style = getComputedStyle(root);
  const colors: Record<string, string> = {};
  for (const token of DESIGN_TOKENS) {
    const value = style.getPropertyValue(cssVar(token)).trim().toLowerCase();
    if (HEX.test(value)) colors[token] = value;
  }
  return JSON.stringify({ format: DESIGN_FORMAT, name, base, colors }, null, 2) + '\n';
}
