import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { THEMES, isThemeId, themeInfo } from './themes';

const css = readFileSync(resolve(__dirname, '../index.css'), 'utf8');
const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');

describe('theme registry', () => {
  it('has a CSS block for every design', () => {
    for (const theme of THEMES) expect(css, theme.id).toMatch(new RegExp(`:root\\[data-theme="${theme.id}"\\]`));
  });

  it('lists every dark design in the dark variant, and no light one', () => {
    const variant = css.match(/@custom-variant dark \((.*)\);/)?.[1] ?? '';
    for (const theme of THEMES) {
      expect(variant.includes(`[data-theme="${theme.id}"]`), theme.id).toBe(theme.scheme === 'dark');
    }
  });

  it('knows the same designs as the script that sets the theme before the first paint', () => {
    const known = html.match(/var known = \[([^\]]*)\]/)?.[1] ?? '';
    expect(known.split(',').map((s) => s.trim().replace(/'/g, ''))).toEqual(THEMES.map((t) => t.id));
  });

  it('accepts only known ids and falls back to the night theme', () => {
    expect(isThemeId('starlight')).toBe(true);
    expect(isThemeId('system')).toBe(false);
    expect(isThemeId('nope')).toBe(false);
    expect(themeInfo('paper').scheme).toBe('light');
    expect(themeInfo('nope' as never).id).toBe('dark');
  });
});
