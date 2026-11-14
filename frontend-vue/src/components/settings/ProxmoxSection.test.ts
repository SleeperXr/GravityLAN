import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ProxmoxSection from './ProxmoxSection.vue';
import { api, type ProxmoxSettings } from '@/api/client';

const { showToast, confirm } = vi.hoisted(() => ({ showToast: vi.fn(), confirm: vi.fn() }));

vi.mock('@/api/client', () => ({
  api: { getProxmoxSettings: vi.fn(), saveProxmoxSettings: vi.fn(), deleteProxmoxSettings: vi.fn(), syncProxmox: vi.fn() },
}));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('@/composables/useConfirm', () => ({ useConfirm: () => ({ confirm }) }));

const STORED: ProxmoxSettings = {
  enabled: true,
  url: 'https://pve:8006',
  token_id: 'reader@pve!inventory',
  verify_tls: true,
  has_token_secret: true,
  last_sync: null,
  last_error: null,
};

async function mountWith(settings: ProxmoxSettings) {
  vi.mocked(api.getProxmoxSettings).mockResolvedValue(settings);
  const wrapper = mount(ProxmoxSection);
  await flushPromises();
  return wrapper;
}

const button = (wrapper: Awaited<ReturnType<typeof mountWith>>, name: string) => wrapper.find(`[data-test="proxmox-${name}"]`);

describe('ProxmoxSection', () => {
  beforeEach(() => vi.clearAllMocks());

  it('keeps the stored secret: a save without a new one sends no token_secret', async () => {
    vi.mocked(api.saveProxmoxSettings).mockResolvedValue({ ...STORED, verify_tls: false });
    const wrapper = await mountWith(STORED);
    await wrapper.find('[data-test="proxmox-url"]').setValue('https://pve:8006');
    await wrapper.findAll('button[role="switch"]')[1].trigger('click'); // accept self-signed
    await wrapper.find('form').trigger('submit');
    await flushPromises();
    expect(api.saveProxmoxSettings).toHaveBeenCalledWith({ enabled: true, url: 'https://pve:8006', token_id: 'reader@pve!inventory', verify_tls: false });
  });

  it('asks for the secret again before the stored one would go to another server', async () => {
    const wrapper = await mountWith(STORED);
    await wrapper.find('[data-test="proxmox-url"]').setValue('https://other:8006');
    expect(button(wrapper, 'save').attributes('disabled')).toBeDefined();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    await wrapper.find('[data-test="proxmox-secret"]').setValue('new-secret');
    expect(button(wrapper, 'save').attributes('disabled')).toBeUndefined();
  });

  it('syncs only the saved settings and reports the counts', async () => {
    vi.mocked(api.syncProxmox).mockResolvedValue({ guests: 3, addresses: 4, updated_devices: 1, skipped: 1, conflicts: 0 });
    const wrapper = await mountWith(STORED);
    await button(wrapper, 'sync').trigger('click');
    await flushPromises();
    expect(api.syncProxmox).toHaveBeenCalledOnce();
    expect(showToast).toHaveBeenCalledWith('success', expect.any(String), expect.stringContaining('3'));

    await wrapper.find('[data-test="proxmox-token-id"]').setValue('other@pve!inventory');
    expect(button(wrapper, 'sync').attributes('disabled')).toBeDefined();
  });

  it('shows the last error of the server', async () => {
    const wrapper = await mountWith({ ...STORED, last_error: 'Proxmox denied access.' });
    expect(wrapper.find('[data-test="proxmox-error"]').text()).toContain('Proxmox denied access.');
  });
});
