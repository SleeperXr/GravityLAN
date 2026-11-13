import { describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import CookieSecurityNotice from './CookieSecurityNotice.vue';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: { getCookieSecurity: vi.fn() },
}));

async function render(status: { secure_cookies: boolean; https: boolean } | Error) {
  if (status instanceof Error) vi.mocked(api.getCookieSecurity).mockRejectedValue(status);
  else vi.mocked(api.getCookieSecurity).mockResolvedValue(status);
  const wrapper = mount(CookieSecurityNotice);
  await flushPromises();
  return wrapper.find('[data-test="cookie-insecure"]').exists();
}

describe('CookieSecurityNotice', () => {
  it('warns over HTTPS when cookies are not Secure', async () => {
    expect(await render({ secure_cookies: false, https: true })).toBe(true);
  });

  it('stays quiet once Secure cookies are on', async () => {
    expect(await render({ secure_cookies: true, https: true })).toBe(false);
  });

  it('stays quiet over plain HTTP', async () => {
    expect(await render({ secure_cookies: false, https: false })).toBe(false);
  });

  it('stays quiet when the status cannot be read', async () => {
    expect(await render(new Error('403'))).toBe(false);
  });
});
