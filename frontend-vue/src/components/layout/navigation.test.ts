import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({ api: { getSettings: vi.fn().mockResolvedValue({}) } }));

import { router } from '@/router';
import { NAV_ITEMS } from './navigation';

describe('navigation', () => {
  it('every sidebar entry opens its own page, not the catch-all redirect', () => {
    for (const item of NAV_ITEMS) {
      const route = router.resolve(item.to);
      expect(route.name, item.id).toBe(item.id);
      expect(route.meta.navId, item.id).toBe(item.id);
    }
  });

  it('has the About page', () => {
    expect(NAV_ITEMS.some((item) => item.id === 'about')).toBe(true);
  });
});
