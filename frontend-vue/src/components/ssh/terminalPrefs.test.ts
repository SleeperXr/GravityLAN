import { afterEach, describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'gravitylan.terminal';

async function freshPrefs() {
  vi.resetModules();
  return import('./terminalPrefs');
}

describe('terminalPrefs', () => {
  afterEach(() => localStorage.clear());

  it('defaults to JetBrains Mono, the mono of the design system', async () => {
    const { DEFAULT_PREFS, fontCss, terminalPrefs } = await freshPrefs();

    expect(DEFAULT_PREFS.fontFamily).toBe('jetbrains');
    expect(terminalPrefs.fontFamily).toBe('jetbrains');
    expect(fontCss(terminalPrefs)).toContain('JetBrains Mono');
  });

  it('keeps a font the user saved earlier, including the former default', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ fontFamily: 'plex', fontSize: 15 }));

    const { fontCss, terminalPrefs } = await freshPrefs();

    expect(terminalPrefs.fontFamily).toBe('plex');
    expect(terminalPrefs.fontSize).toBe(15);
    expect(fontCss(terminalPrefs)).toContain('IBM Plex Mono');
  });

  it('falls back to the default font for an unknown id', async () => {
    const { DEFAULT_PREFS, fontCss } = await freshPrefs();

    expect(fontCss({ ...DEFAULT_PREFS, fontFamily: 'gone' })).toContain('JetBrains Mono');
  });
});
