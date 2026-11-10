import { beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';

/** useTheme reads the stored choice at import time, so every test loads a fresh copy. */
async function load() {
  vi.resetModules();
  return (await import('./useTheme')).useTheme();
}

const applied = () => document.documentElement.getAttribute('data-theme');

describe('useTheme', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('starts dark when nothing is stored', async () => {
    const { preference } = await load();
    expect(preference.value).toBe('dark');
    expect(applied()).toBe('dark');
  });

  it('applies and stores aurora', async () => {
    const { setPreference, resolved } = await load();
    setPreference('aurora');
    await nextTick();
    expect(resolved.value).toBe('aurora');
    expect(applied()).toBe('aurora');
    expect(localStorage.getItem('gravityui.theme')).toBe('aurora');
  });

  it('keeps aurora after a reload', async () => {
    localStorage.setItem('gravityui.theme', 'aurora');
    const { preference } = await load();
    expect(preference.value).toBe('aurora');
    expect(applied()).toBe('aurora');
  });

  it('falls back to dark for an unknown stored value', async () => {
    localStorage.setItem('gravityui.theme', 'neon');
    const { preference } = await load();
    expect(preference.value).toBe('dark');
  });

  it('cycles through every choice and back to dark', async () => {
    const { preference, cycle } = await load();
    const seen = [];
    for (let i = 0; i < 4; i++) {
      cycle();
      seen.push(preference.value);
    }
    expect(seen).toEqual(['aurora', 'light', 'system', 'dark']);
  });
});
