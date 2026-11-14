import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const api = vi.hoisted(() => ({ getSettings: vi.fn(), updateSettings: vi.fn() }));
vi.mock('@/api/client', () => ({ api }));

import { networkColor } from './networks';
import { useAppearance } from '@/stores/appearance';

describe('networkColor', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    api.getSettings.mockReset();
    api.updateSettings.mockReset().mockResolvedValue(undefined);
  });

  it('takes the palette slot by subnet id without a colour of its own', () => {
    expect(networkColor(1)).toBe('var(--line-1)');
    expect(networkColor(12)).toBe('var(--line-2)');
  });

  it('resolves a palette reference to that slot, so it follows the theme', () => {
    useAppearance().lineColors = { '1': 'line:8' };
    expect(networkColor(1)).toBe('var(--line-8)');
  });

  it('keeps a free colour as it is', () => {
    useAppearance().lineColors = { '1': '#123456' };
    expect(networkColor(1)).toBe('#123456');
  });

  it('loads palette references and hex colours and drops anything else', async () => {
    api.getSettings.mockResolvedValue({
      'ui.line_colors': JSON.stringify({ '1': 'line:8', '2': '#abcdef', '3': 'line:11', '4': 'red', '5': 'line:0' }),
    });
    const appearance = useAppearance();
    await appearance.load();
    expect(appearance.lineColors).toEqual({ '1': 'line:8', '2': '#abcdef' });
  });

  it('saves a palette pick as a reference and clears an invalid one', async () => {
    const appearance = useAppearance();
    await appearance.setLineColor(3, 'line:4');
    expect(appearance.lineColors).toEqual({ '3': 'line:4' });
    await appearance.setLineColor(3, 'line:42');
    expect(appearance.lineColors).toEqual({});
    expect(api.updateSettings).toHaveBeenLastCalledWith({ 'ui.line_colors': '{}' });
  });
});
