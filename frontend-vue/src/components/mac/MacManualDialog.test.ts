import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import type { Device } from '@/types';
import { ApiError, api } from '@/api/client';
import MacManualDialog from './MacManualDialog.vue';

const { showToast } = vi.hoisted(() => ({ showToast: vi.fn() }));

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/core')>('@/api/core');
  return {
    ApiError: actual.ApiError,
    api: { setDeviceMac: vi.fn() },
  };
});
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));

const DialogStub = defineComponent({
  props: { open: Boolean, title: String, description: String },
  setup: (props, { slots }) => () =>
    props.open ? h('div', { 'data-dialog': true }, [slots.default?.(), slots.footer?.()]) : null,
});

const device = { id: 7, ip: '192.168.1.7', mac: 'aa:bb:cc:dd:ee:01', display_name: 'nas' } as Device;
const mocked = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.setDeviceMac.mockResolvedValue({ changed_device_ids: [7] });
});

describe('MacManualDialog', () => {
  it('submits a manually entered MAC and emits changed', async () => {
    const wrapper = mount(MacManualDialog, {
      props: { open: true, device },
      global: { stubs: { Dialog: DialogStub } },
    });

    await wrapper.get('input').setValue('aa-bb-cc-dd-ee-ff');
    await wrapper.get('form').trigger('submit');
    await flushPromises();

    expect(mocked.setDeviceMac).toHaveBeenCalledWith(7, { mac: 'aa-bb-cc-dd-ee-ff', apply_to_shared: false });
    expect(wrapper.emitted('changed')).toEqual([['aa:bb:cc:dd:ee:ff']]);
  });

  it('shows 422 validation errors inline and stays open', async () => {
    mocked.setDeviceMac.mockRejectedValueOnce(new ApiError('Not a usable MAC address.', 422));
    const wrapper = mount(MacManualDialog, {
      props: { open: true, device },
      global: { stubs: { Dialog: DialogStub } },
    });

    await wrapper.get('input').setValue('not-a-mac');
    await wrapper.get('form').trigger('submit');
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain('Not a usable MAC address.');
    expect(wrapper.emitted('changed')).toBeUndefined();
    expect(wrapper.emitted('update:open')).toBeUndefined();
  });
});
