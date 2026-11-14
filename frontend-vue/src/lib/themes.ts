/**
 * The built-in designs of GravityUI, in the order the design menu shows them. Each one is a
 * `:root[data-theme="<id>"]` block in index.css; this list adds what the menu and the browser need.
 * The preview colours are the theme's own values, kept here so a card can show a theme that is
 * not active. Dark ones also belong in the `dark` custom variant at the top of index.css.
 */
export type ThemeId = 'dark' | 'starlight' | 'aurora' | 'light';
export type ThemeScheme = 'dark' | 'light';

export interface ThemePreview {
  canvas: string;
  surface: string;
  line: string;
  text: string;
  /** State colour (online, healthy) */
  accent: string;
  /** The primary button */
  primary: string;
  /** First network colour */
  network: string;
}

export interface ThemeInfo {
  id: ThemeId;
  /** i18n keys under gv.theme */
  label: string;
  description: string;
  scheme: ThemeScheme;
  /** The theme's ground, for the browser bar (theme-color) */
  browserBar: string;
  preview: ThemePreview;
}

export const THEMES: ThemeInfo[] = [
  {
    id: 'dark',
    label: 'gv.theme.dark',
    description: 'gv.theme.dark_desc',
    scheme: 'dark',
    browserBar: '#0c0f14',
    preview: { canvas: '#0c0f14', surface: '#11151c', line: '#2b323d', text: '#eef1f5', accent: '#2ec4a6', primary: '#2ec4a6', network: '#4dd4ff' },
  },
  {
    id: 'starlight',
    label: 'gv.theme.starlight',
    description: 'gv.theme.starlight_desc',
    scheme: 'dark',
    browserBar: '#0b0c0e',
    preview: { canvas: '#0b0c0e', surface: '#121416', line: '#414447', text: '#f2f4f5', accent: '#5edb81', primary: '#f0ebd9', network: '#4dd4ff' },
  },
  {
    id: 'aurora',
    label: 'gv.theme.aurora',
    description: 'gv.theme.aurora_desc',
    scheme: 'dark',
    browserBar: '#08090d',
    preview: { canvas: '#08090d', surface: '#0e1017', line: '#35508f', text: '#f5f7ff', accent: '#00f5a0', primary: '#00f5a0', network: '#00e5ff' },
  },
  {
    id: 'light',
    label: 'gv.theme.light',
    description: 'gv.theme.light_desc',
    scheme: 'light',
    browserBar: '#f4f6f8',
    preview: { canvas: '#f4f6f8', surface: '#ffffff', line: '#a5acb2', text: '#12161d', accent: '#007563', primary: '#007563', network: '#1fb3e0' },
  },
];

const IDS = new Set<string>(THEMES.map((t) => t.id));

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && IDS.has(value);
}

export function themeInfo(id: ThemeId): ThemeInfo {
  return THEMES.find((t) => t.id === id) ?? THEMES[0];
}
