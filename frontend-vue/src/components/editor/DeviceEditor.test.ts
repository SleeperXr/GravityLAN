import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import type { Device } from '@/types';
import { api } from '@/api/client';
import { t } from '@/i18n';
import DeviceEditor from './DeviceEditor.vue';
import SettingsTab from './SettingsTab.vue';
import ServicesTab from './ServicesTab.vue';
import AgentTab from './AgentTab.vue';

const { showToast, confirm, store } = vi.hoisted(() => ({
  showToast: vi.fn(),
  confirm: vi.fn(),
  store: { devices: [] as unknown[] },
}));

vi.mock('@/api/client', () => ({
  api: {
    getGroups: vi.fn(),
    getRacks: vi.fn(),
    updateDevice: vi.fn(),
    updateService: vi.fn(),
    refreshDeviceInfo: vi.fn(),
    deleteDevice: vi.fn(),
  },
}));
vi.mock('@/stores/network', () => ({ useNetworkStore: () => store }));
vi.mock('@/stores/appearance', () => ({ useAppearance: () => ({ load: vi.fn(async () => {}), orbitVisibility: {} }) }));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('@/composables/useConfirm', () => ({ useConfirm: () => ({ confirm }) }));
vi.mock('@/composables/useAgentPanel', () => ({ useAgentPanel: () => ({}) }));

const mocked = vi.mocked(api);

const SheetStub = defineComponent({
  setup: (_, { slots }) => () => h('div', ['tabs', 'default', 'footer'].map((slot) => h('section', { 'data-slot': slot }, slots[slot]?.()))),
});

const dev = (extra: Record<string, unknown> = {}) =>
  ({ id: 1, ip: '192.0.2.1', display_name: 'nas', hostname: 'nas.lan', vendor: '', is_online: true, group_id: 5, parent_id: null, services: [], interfaces: [], ...extra }) as unknown as Device;

async function render(device: Device = dev(), initialTab?: string) {
  const wrapper = mount(DeviceEditor, {
    props: { open: true, device, initialTab } as never,
    global: {
      stubs: { Sheet: SheetStub, SettingsTab: true, ServicesTab: true, InterfacesTab: true, HistoryTab: true, AgentTab: true, StatusDot: true },
    },
  });
  await flushPromises();
  return wrapper;
}
type Editor = Awaited<ReturnType<typeof render>>;

const settings = (w: Editor) => w.findComponent(SettingsTab);
const closed = (w: Editor) => w.emitted('update:open') ?? [];
const toastKinds = () => showToast.mock.calls.map((call) => call[0]);
const sentToDevice = () => mocked.updateDevice.mock.calls[0][1] as Record<string, unknown>;
const button = (w: Editor, text: string) => w.findAll('button').find((b) => b.text().includes(text))!;

async function submit(w: Editor) {
  settings(w).vm.$emit('submit');
  await flushPromises();
}

beforeEach(() => {
  vi.clearAllMocks();
  store.devices = [];
  mocked.getGroups.mockResolvedValue([]);
  mocked.getRacks.mockResolvedValue([]);
  mocked.updateDevice.mockResolvedValue(dev());
  mocked.updateService.mockResolvedValue({} as never);
  mocked.deleteDevice.mockResolvedValue(undefined as never);
  confirm.mockResolvedValue(true);
});

describe('saving', () => {
  it('sends the form, reports it and closes', async () => {
    const w = await render();
    await submit(w);
    expect(mocked.updateDevice).toHaveBeenCalledWith(1, expect.objectContaining({ display_name: 'nas', group_id: 5 }));
    expect(toastKinds()).toEqual(['success']);
    expect(w.emitted('saved')).toHaveLength(1);
    expect(closed(w)).toEqual([[false]]);
  });

  it('keeps the grid position while the group stays the same', async () => {
    await submit(await render());
    expect(sentToDevice()).not.toHaveProperty('y');
  });

  it('puts a device moved to another group at the bottom of that group', async () => {
    store.devices = [{ id: 2, group_id: 9, y: 2, h: 3 }];
    const w = await render();
    settings(w).vm.$emit('update:form', { ...settings(w).props('form'), group_id: 9 });
    await submit(w);
    expect(sentToDevice()).toMatchObject({ group_id: 9, x: 0, y: 5 });
  });

  it('only clears a pending IP change when there is one', async () => {
    await submit(await render());
    expect(sentToDevice()).not.toHaveProperty('old_ip');

    mocked.updateDevice.mockClear();
    await submit(await render(dev({ old_ip: '192.0.2.9', ip_changed_at: '2026-01-01' })));
    expect(sentToDevice()).toMatchObject({ old_ip: null, ip_changed_at: null });
  });

  it('saves edited services before the device', async () => {
    const service = { id: 7, port: 80, name: 'web', protocol: 'http' };
    const w = await render(dev({ services: [service] }));
    await button(w, t('editor.tabs.services')).trigger('click');
    w.findComponent(ServicesTab).vm.$emit('update:device', dev({ services: [{ ...service, port: 8080 }] }));
    await flushPromises();
    await button(w, t('common.save')).trigger('click');
    await flushPromises();
    expect(mocked.updateService).toHaveBeenCalledWith(7, { port: 8080, name: 'web', protocol: 'http' });
    expect(mocked.updateService.mock.invocationCallOrder[0]).toBeLessThan(mocked.updateDevice.mock.invocationCallOrder[0]);
  });

  it('stays open and says so when saving fails', async () => {
    mocked.updateDevice.mockRejectedValue(new Error('nope'));
    const w = await render();
    await submit(w);
    expect(showToast).toHaveBeenCalledWith('error', t('notifications.save_failed'), 'nope');
    expect(w.emitted('saved')).toBeUndefined();
    expect(closed(w)).toEqual([]);
  });
});

describe('deleting', () => {
  it('does nothing without confirmation', async () => {
    confirm.mockResolvedValue(false);
    const w = await render();
    await button(w, t('common.delete')).trigger('click');
    await flushPromises();
    expect(mocked.deleteDevice).not.toHaveBeenCalled();
    expect(closed(w)).toEqual([]);
  });

  it('deletes and closes once confirmed', async () => {
    const w = await render();
    await button(w, t('common.delete')).trigger('click');
    await flushPromises();
    expect(mocked.deleteDevice).toHaveBeenCalledWith(1);
    expect(w.emitted('saved')).toHaveLength(1);
    expect(closed(w)).toEqual([[false]]);
  });

  it('stays open when deleting fails', async () => {
    mocked.deleteDevice.mockRejectedValue(new Error('nope'));
    const w = await render();
    await button(w, t('common.delete')).trigger('click');
    await flushPromises();
    expect(toastKinds()).toEqual(['error']);
    expect(w.emitted('saved')).toBeUndefined();
    expect(closed(w)).toEqual([]);
  });
});

describe('details from the network', () => {
  it('acknowledges an IP change right away', async () => {
    const w = await render(dev({ old_ip: '192.0.2.9' }));
    expect(w.text()).toContain('192.0.2.9');
    await button(w, t('dashboard.ip_changed_ack')).trigger('click');
    await flushPromises();
    expect(mocked.updateDevice).toHaveBeenCalledWith(1, { old_ip: null, ip_changed_at: null });
    expect(w.text()).not.toContain('192.0.2.9');
    expect(w.emitted('saved')).toHaveLength(1);
  });

  it('applies a picked DNS server to the device', async () => {
    mocked.updateDevice.mockResolvedValue(dev({ hostname: 'other.lan', hostname_source: 'dns2' }));
    const w = await render();
    settings(w).vm.$emit('hostnameSource', 'dns2');
    await flushPromises();
    expect(mocked.updateDevice).toHaveBeenCalledWith(1, { hostname_source: 'dns2' });
    expect(settings(w).props('device')).toMatchObject({ hostname: 'other.lan', hostname_source: 'dns2' });
    expect(settings(w).props('savingSource')).toBe(false);
    expect(w.emitted('saved')).toHaveLength(1);
  });

  it('keeps the device as it was when the pick cannot be saved', async () => {
    mocked.updateDevice.mockRejectedValue(new Error('nope'));
    const w = await render();
    settings(w).vm.$emit('hostnameSource', 'dns2');
    await flushPromises();
    expect(settings(w).props('device')).toMatchObject({ hostname: 'nas.lan' });
    expect(settings(w).props('savingSource')).toBe(false);
    expect(w.emitted('saved')).toBeUndefined();
  });

  it('names a device still called by its IP after a refresh', async () => {
    mocked.refreshDeviceInfo.mockResolvedValue(dev({ hostname: 'nas.lan', vendor: 'Acme' }));
    const w = await render(dev({ display_name: '192.0.2.1' }));
    settings(w).vm.$emit('refreshInfo');
    await flushPromises();
    expect(settings(w).props('form')).toMatchObject({ display_name: 'nas', vendor: 'Acme' });
  });

  it('keeps a name the user chose after a refresh', async () => {
    mocked.refreshDeviceInfo.mockResolvedValue(dev({ hostname: 'other.lan' }));
    const w = await render(dev({ display_name: 'my nas' }));
    settings(w).vm.$emit('refreshInfo');
    await flushPromises();
    expect(settings(w).props('form')).toMatchObject({ display_name: 'my nas' });
  });

  it('treats an unusable rack list as empty', async () => {
    mocked.getRacks.mockResolvedValue({} as never);
    expect(settings(await render()).props('racks')).toEqual([]);
  });
});

describe('tabs', () => {
  const nav = (w: Editor) => w.get('[data-slot="tabs"] nav');

  it('wraps around with the arrow keys', async () => {
    const w = await render();
    await nav(w).trigger('keydown', { key: 'ArrowLeft' });
    expect(w.findComponent(AgentTab).exists()).toBe(true);
    await nav(w).trigger('keydown', { key: 'ArrowRight' });
    expect(settings(w).exists()).toBe(true);
  });

  it('ignores other keys', async () => {
    const w = await render();
    await nav(w).trigger('keydown', { key: 'ArrowDown' });
    expect(settings(w).exists()).toBe(true);
  });

  it('counts the primary address along with further interfaces', async () => {
    const tabText = async (extra: Record<string, unknown>) => button(await render(dev(extra)), t('editor.tabs.interfaces')).text();
    expect(await tabText({ interfaces: [{}, {}] })).toContain('3');
    expect(await tabText({})).toBe(t('editor.tabs.interfaces'));
  });

  it('starts over when another device is opened', async () => {
    const w = await render(dev(), 'agent');
    expect(w.findComponent(AgentTab).exists()).toBe(true);
    await w.setProps({ device: dev({ id: 2, display_name: 'router' }), initialTab: 'settings' });
    expect(settings(w).props('form')).toMatchObject({ display_name: 'router' });
  });
});
