import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import type { MacConflictDevice, MacConflictGroup } from '@/types';
import { ApiError } from '@/api/core';
import MacAdoptDialog from './MacAdoptDialog.vue';
import MacConflictsPanel from './MacConflictsPanel.vue';

const setDeviceMac = vi.fn();
const dismissMacObservation = vi.fn();
const showToast = vi.fn();
const confirm = vi.fn(async () => true);

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/core')>('@/api/core');
  return {
    ApiError: actual.ApiError,
    api: {
      setDeviceMac: (...args: unknown[]) => setDeviceMac(...args),
      dismissMacObservation: (...args: unknown[]) => dismissMacObservation(...args),
    },
  };
});

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast }),
}));

vi.mock('@/composables/useConfirm', () => ({
  useConfirm: () => ({ confirm }),
}));

const DialogStub = defineComponent({
  props: { open: Boolean, title: String, description: String },
  emits: ['update:open'],
  setup: (props, { slots }) => () =>
    props.open ? h('div', { class: 'dialog-stub' }, [slots.default?.(), slots.footer?.()]) : null,
});

function makeGroup(devices: MacConflictDevice[] = [
  { id: 10, ip: '192.168.1.10', name: 'c1', source: 'relay' },
  { id: 11, ip: '192.168.1.11', name: 'c2', source: 'scan' },
]): MacConflictGroup {
  return {
    documented_mac: '02:00:00:00:00:01',
    observed_mac: '02:00:00:00:00:02',
    first_seen: '2026-11-20T08:00:00Z',
    last_seen: '2026-11-20T09:00:00Z',
    devices,
  };
}

beforeEach(() => {
  setDeviceMac.mockReset();
  dismissMacObservation.mockReset();
  showToast.mockReset();
  confirm.mockReset();
  confirm.mockResolvedValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MacAdoptDialog (AP 5a)', () => {
  it('freezes the confirmed target snapshot even if the group prop grows while open', async () => {
    setDeviceMac.mockResolvedValueOnce({ changed_device_ids: [10, 11], skipped_device_ids: [] });
    const group = makeGroup();

    const wrapper = mount(MacAdoptDialog, {
      props: { open: true, group, defaultScope: 'all' },
      global: { stubs: { Dialog: DialogStub } },
    });

    // Background poll adds a 3rd device while the dialog is open
    await wrapper.setProps({
      group: makeGroup([
        ...group.devices,
        { id: 12, ip: '192.168.1.12', name: 'c3-late', source: 'relay' },
      ]),
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(setDeviceMac).toHaveBeenCalledWith(10, {
      mac: '02:00:00:00:00:02',
      apply_to_shared: false,
      targets: [
        { id: 10, ip: '192.168.1.10', documented_mac: '02:00:00:00:00:01' },
        { id: 11, ip: '192.168.1.11', documented_mac: '02:00:00:00:00:01' },
      ],
    });
    expect(showToast).toHaveBeenCalledWith('success', expect.any(String), expect.any(String));
    expect(wrapper.emitted('adopted')).toEqual([[[10, 11]]]);
    expect(wrapper.emitted('refresh')).toHaveLength(1);
    wrapper.unmount();
  });

  it('reports no update (never "1 updated") and emits refresh without adopted when changed_device_ids is empty', async () => {
    setDeviceMac.mockResolvedValueOnce({ changed_device_ids: [], skipped_device_ids: [10, 11] });

    const wrapper = mount(MacAdoptDialog, {
      props: { open: true, group: makeGroup(), defaultScope: 'all' },
      global: { stubs: { Dialog: DialogStub } },
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(showToast).toHaveBeenCalledWith('info', expect.any(String), expect.any(String));
    expect(wrapper.emitted('adopted')).toBeUndefined();
    expect(wrapper.emitted('refresh')).toHaveLength(1);
    wrapper.unmount();
  });

  it('reports partial outcome when some targets changed and some were skipped', async () => {
    setDeviceMac.mockResolvedValueOnce({ changed_device_ids: [10], skipped_device_ids: [11] });

    const wrapper = mount(MacAdoptDialog, {
      props: { open: true, group: makeGroup(), defaultScope: 'all' },
      global: { stubs: { Dialog: DialogStub } },
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(showToast).toHaveBeenCalledWith('info', expect.any(String), expect.stringContaining('1'));
    expect(wrapper.emitted('adopted')).toEqual([[[10]]]);
    expect(wrapper.emitted('refresh')).toHaveLength(1);
    wrapper.unmount();
  });

  it('emits refresh without adopted and closes dialog on technical error', async () => {
    setDeviceMac.mockRejectedValueOnce(new ApiError('Server error', 500));

    const wrapper = mount(MacAdoptDialog, {
      props: { open: true, group: makeGroup(), defaultScope: 'all' },
      global: { stubs: { Dialog: DialogStub } },
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(showToast).toHaveBeenCalledWith('error', expect.any(String), 'Server error');
    expect(wrapper.emitted('adopted')).toBeUndefined();
    expect(wrapper.emitted('refresh')).toHaveLength(1);
    expect(wrapper.emitted('update:open')).toEqual([[false]]);
    wrapper.unmount();
  });
});

describe('MacConflictsPanel group dismiss (AP 5a)', () => {
  it('continues past an individual failure, reports partial outcome, and still emits resolved', async () => {
    dismissMacObservation
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new ApiError('No such MAC observation', 404))
      .mockResolvedValueOnce(undefined);

    const group = makeGroup([
      { id: 10, ip: '192.168.1.10', name: 'c1', source: 'relay' },
      { id: 11, ip: '192.168.1.11', name: 'c2', source: 'scan' },
      { id: 12, ip: '192.168.1.12', name: 'c3', source: 'relay' },
    ]);

    const wrapper = mount(MacConflictsPanel, {
      props: { groups: [group] },
      global: { stubs: { Dialog: DialogStub, RelativeTime: true } },
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(dismissMacObservation).toHaveBeenCalledTimes(3);
    expect(showToast).toHaveBeenCalledWith('info', expect.any(String), expect.stringContaining('2'));
    expect(wrapper.emitted('resolved')).toHaveLength(1);
    wrapper.unmount();
  });

  it('stops sending remaining requests on 401/403 auth failure and still emits resolved', async () => {
    dismissMacObservation.mockRejectedValueOnce(new ApiError('Session expired', 401));

    const group = makeGroup([
      { id: 10, ip: '192.168.1.10', name: 'c1', source: 'relay' },
      { id: 11, ip: '192.168.1.11', name: 'c2', source: 'scan' },
      { id: 12, ip: '192.168.1.12', name: 'c3', source: 'relay' },
    ]);

    const wrapper = mount(MacConflictsPanel, {
      props: { groups: [group] },
      global: { stubs: { Dialog: DialogStub, RelativeTime: true } },
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(dismissMacObservation).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith('error', expect.any(String), 'Session expired');
    expect(wrapper.emitted('resolved')).toHaveLength(1);
    wrapper.unmount();
  });

  it('emits resolved even when all requests fail with non-auth errors', async () => {
    dismissMacObservation.mockRejectedValue(new ApiError('Device not found', 404));

    const wrapper = mount(MacConflictsPanel, {
      props: { groups: [makeGroup()] },
      global: { stubs: { Dialog: DialogStub, RelativeTime: true } },
    });

    const buttons = wrapper.findAll('button');
    await buttons[buttons.length - 1].trigger('click');
    await flushPromises();

    expect(dismissMacObservation).toHaveBeenCalledTimes(2);
    expect(showToast).toHaveBeenCalledWith('error', expect.any(String), 'Device not found');
    expect(wrapper.emitted('resolved')).toHaveLength(1);
    wrapper.unmount();
  });
});
