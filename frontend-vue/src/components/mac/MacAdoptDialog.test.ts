import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import type { MacConflictGroup } from '@/types';
import { api } from '@/api/client';
import { t } from '@/i18n';
import MacAdoptDialog from './MacAdoptDialog.vue';

const { showToast } = vi.hoisted(() => ({ showToast: vi.fn() }));

vi.mock('@/api/client', () => ({
  api: {
    setDeviceMac: vi.fn(),
  },
}));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));

const DialogStub = defineComponent({
  props: { open: Boolean, title: String, description: String },
  setup: (props, { slots }) => () =>
    props.open ? h('div', { 'data-dialog': true }, [slots.default?.(), slots.footer?.()]) : null,
});

const singleGroup: MacConflictGroup = {
  documented_mac: 'aa:bb:cc:dd:ee:01',
  observed_mac: 'aa:bb:cc:dd:ee:02',
  first_seen: '2026-11-20T08:00:00Z',
  last_seen: '2026-11-20T09:00:00Z',
  devices: [{ id: 10, ip: '192.168.1.10', name: 'nas', source: 'relay' }],
};

const sharedGroup: MacConflictGroup = {
  documented_mac: '11:22:33:44:55:01',
  observed_mac: '11:22:33:44:55:02',
  first_seen: '2026-11-20T08:00:00Z',
  last_seen: '2026-11-20T09:30:00Z',
  devices: [
    { id: 20, ip: '192.168.1.20', name: 'pihole', source: 'relay' },
    { id: 21, ip: '192.168.1.21', name: 'nginx', source: 'scan' },
  ],
};

const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.setDeviceMac.mockResolvedValue({ changed_device_ids: [10] });
});

describe('MacAdoptDialog', () => {
  it('does not offer apply_to_shared for a single-device group', async () => {
    const wrapper = mount(MacAdoptDialog, {
      props: { open: true, group: singleGroup, device: singleGroup.devices[0] },
      global: { stubs: { Dialog: DialogStub } },
    });

    expect(wrapper.findAll('input[type="radio"]')).toHaveLength(0);
    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes(t('gv.mac_conflicts.adopt_confirm')))!;
    await confirmBtn.trigger('click');
    await flushPromises();

    expect(mocked.setDeviceMac).toHaveBeenCalledWith(10, {
      mac: 'aa:bb:cc:dd:ee:02',
      apply_to_shared: false,
      targets: [{ id: 10, ip: '192.168.1.10', documented_mac: 'aa:bb:cc:dd:ee:01' }],
    });
    expect(wrapper.emitted('adopted')).toEqual([[[10]]]);
    expect(wrapper.emitted('refresh')).toHaveLength(1);
  });

  it('lists all devices in a shared group and lets the user pick single or all', async () => {
    mocked.setDeviceMac.mockResolvedValue({ changed_device_ids: [20, 21] });
    const wrapper = mount(MacAdoptDialog, {
      props: { open: true, group: sharedGroup, device: sharedGroup.devices[0], defaultScope: 'single' },
      global: { stubs: { Dialog: DialogStub } },
    });

    expect(wrapper.text()).toContain('pihole');
    expect(wrapper.text()).toContain('192.168.1.20');
    expect(wrapper.text()).toContain('nginx');
    expect(wrapper.text()).toContain('192.168.1.21');

    const radios = wrapper.findAll<HTMLInputElement>('input[type="radio"]');
    expect(radios).toHaveLength(2);
    expect(radios[0].element.checked).toBe(true);

    await radios[1].setValue(true);
    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes(t('gv.mac_conflicts.adopt_confirm')))!;
    await confirmBtn.trigger('click');
    await flushPromises();

    expect(mocked.setDeviceMac).toHaveBeenCalledWith(20, {
      mac: '11:22:33:44:55:02',
      apply_to_shared: false,
      targets: [
        { id: 20, ip: '192.168.1.20', documented_mac: '11:22:33:44:55:01' },
        { id: 21, ip: '192.168.1.21', documented_mac: '11:22:33:44:55:01' },
      ],
    });
    expect(wrapper.emitted('adopted')).toEqual([[[20, 21]]]);
    expect(wrapper.emitted('refresh')).toHaveLength(1);
  });
});
