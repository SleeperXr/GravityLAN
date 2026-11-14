import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ProxmoxSection from './ProxmoxSection.vue';
import { api, type ProxmoxSettings } from '@/api/client';

const { showToast, confirm } = vi.hoisted(() => ({ showToast: vi.fn(), confirm: vi.fn() }));

vi.mock('@/api/client', () => ({
  api: { getProxmoxSettings: vi.fn(), saveProxmoxSettings: vi.fn(), deleteProxmoxSettings: vi.fn(), syncProxmox: vi.fn(), getProxmoxReport: vi.fn(), addProxmoxGuestsToDashboard: vi.fn() },
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
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getProxmoxReport).mockResolvedValue({ report: null });
  });

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
    vi.mocked(api.syncProxmox).mockResolvedValue({ guests: 3, addresses: 4, updated_devices: 1, skipped: 1, conflicts: 0, outside: 2 });
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

  it('explains an empty guest list instead of reporting success', async () => {
    vi.mocked(api.syncProxmox).mockResolvedValue({ guests: 0, addresses: 0, updated_devices: 0, skipped: 0, conflicts: 0, outside: 0 });
    const wrapper = await mountWith(STORED);
    await button(wrapper, 'sync').trigger('click');
    await flushPromises();
    expect(showToast).toHaveBeenCalledWith('info', expect.any(String), expect.stringMatching(/Privilege Separation/));
  });

  it('shows conflicts, skipped guests and addresses outside the scan networks', async () => {
    vi.mocked(api.getProxmoxReport).mockResolvedValue({
      report: {
        synced_at: '2026-11-14T01:11:17+00:00',
        subnets: ['192.168.100.0/24'],
        guests: [{ guest: 'lxc/101', name: 'docker', addresses: [{ ip: '192.168.100.20', status: 'conflict' }, { ip: '172.17.0.1', status: 'outside' }] }],
        skipped: [{ guest: 'qemu/104', name: 'win', reason: 'vm_stopped' }],
        conflicts: [{ ip: '192.168.100.20', guests: ['docker', 'other'] }],
      },
    });
    const wrapper = await mountWith(STORED);
    const report = wrapper.find('[data-test="proxmox-report"]');
    expect(report.attributes('open')).toBeDefined(); // a conflict opens it
    expect(report.text()).toContain('docker, other');
    expect(report.text()).toContain('qemu/104');
    expect(report.text()).toContain('172.17.0.1');
  });

  describe('adding guests to the dashboard', () => {
    const REPORT = {
      synced_at: '2026-11-14T01:11:17+00:00',
      subnets: ['192.168.100.0/24'],
      guests: [
        { guest: 'qemu/100', name: 'nas', addresses: [{ ip: '192.168.100.10', status: 'new_host' as const }] },
        { guest: 'lxc/101', name: 'dns', addresses: [{ ip: '192.168.100.11', status: 'host' as const }] },
        { guest: 'lxc/102', name: 'known', addresses: [{ ip: '192.168.100.12', status: 'device' as const }] },
      ],
      skipped: [],
      conflicts: [],
    };

    beforeEach(() => {
      vi.mocked(api.getProxmoxReport).mockResolvedValue({ report: REPORT });
      vi.mocked(api.addProxmoxGuestsToDashboard).mockResolvedValue({ added: [{ ip: '192.168.100.10', id: 7, name: 'nas' }] });
    });

    it('adds one guest with its button, without asking', async () => {
      const wrapper = await mountWith(STORED);
      expect(wrapper.find('[data-test="proxmox-add-192.168.100.12"]').exists()).toBe(false); // already a device
      await wrapper.find('[data-test="proxmox-add-192.168.100.10"]').trigger('click');
      await flushPromises();
      expect(confirm).not.toHaveBeenCalled();
      expect(api.addProxmoxGuestsToDashboard).toHaveBeenCalledWith(['192.168.100.10']);
      expect(showToast).toHaveBeenCalledWith('success', expect.any(String), expect.stringContaining('nas'));
    });

    it('asks before adding all new ones and adds nothing when cancelled', async () => {
      confirm.mockResolvedValue(false);
      const wrapper = await mountWith(STORED);
      await wrapper.find('[data-test="proxmox-add-all"]').trigger('click');
      await flushPromises();
      expect(confirm).toHaveBeenCalledOnce();
      expect(api.addProxmoxGuestsToDashboard).not.toHaveBeenCalled();

      confirm.mockResolvedValue(true);
      await wrapper.find('[data-test="proxmox-add-all"]').trigger('click');
      await flushPromises();
      expect(api.addProxmoxGuestsToDashboard).toHaveBeenCalledWith(['192.168.100.10', '192.168.100.11']);
    });
  });
});
