import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import LoginView from './LoginView.vue';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({ api: { login: vi.fn() } }));

async function signIn() {
  const wrapper = mount(LoginView);
  await wrapper.find('input[type="password"]').setValue('a-password');
  await wrapper.find('form').trigger('submit');
  await flushPromises();
  return wrapper;
}

describe('LoginView', () => {
  beforeEach(() => vi.clearAllMocks());

  it('signs in when the session cookie will stick', async () => {
    vi.mocked(api.login).mockResolvedValue({ status: 'ok', secure_cookie_over_http: false });
    const wrapper = await signIn();
    expect(wrapper.emitted('authenticated')).toHaveLength(1);
    expect(wrapper.find('[data-test="secure-cookie-over-http"]').exists()).toBe(false);
  });

  it('explains a Secure cookie over plain HTTP instead of bouncing back to the login', async () => {
    vi.mocked(api.login).mockResolvedValue({ status: 'ok', secure_cookie_over_http: true });
    const wrapper = await signIn();
    expect(wrapper.emitted('authenticated')).toBeUndefined();
    expect(wrapper.find('[data-test="secure-cookie-over-http"]').text()).toContain('GRAVITYLAN_SECURE_COOKIES');
  });
});
