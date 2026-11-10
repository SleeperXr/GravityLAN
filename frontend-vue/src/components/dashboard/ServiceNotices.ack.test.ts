import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ServiceNotices from './ServiceNotices.vue';
import { api } from '@/api/client';
import { t } from '@/i18n';
import type { Device } from '@/types';

const { showToast } = vi.hoisted(() => ({ showToast: vi.fn() }));

vi.mock('@/api/client', () => ({ api: { updateDevice: vi.fn() } }));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));

const mocked = vi.mocked(api);

const moved = () =>
  ({
    id: 7, ip: '192.0.2.8', old_ip: '192.0.2.7', ip_changed_at: '2026-11-10T08:00:00Z', display_name: 'nas',
    has_agent: false, is_online: true, services: [], subnet_id: null,
  }) as unknown as Device;

async function render(devices: Device[]) {
  const wrapper = mount(ServiceNotices, { props: { devices } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => vi.clearAllMocks());

describe('confirming an IP change', () => {
  it('is a button next to the row, never inside another button', async () => {
    const w = await render([moved()]);
    const ack = w.get('[data-test="ack-ip-change"]');
    expect(ack.element.parentElement?.tagName).toBe('LI');
    expect(w.findAll('button button')).toHaveLength(0);
  });

  it('clears the notice once the server stored it, without opening the device', async () => {
    mocked.updateDevice.mockResolvedValue({} as never);
    const device = moved();
    const w = await render([device]);
    await w.get('[data-test="ack-ip-change"]').trigger('click');
    await flushPromises();

    expect(mocked.updateDevice).toHaveBeenCalledWith(7, { old_ip: null, ip_changed_at: null });
    expect(device.old_ip).toBeNull();
    expect(w.emitted('openDevice')).toBeUndefined();
  });

  it('keeps the notice and says so when the server refuses', async () => {
    mocked.updateDevice.mockRejectedValue(new Error('offline'));
    const device = moved();
    const w = await render([device]);
    await w.get('[data-test="ack-ip-change"]').trigger('click');
    await flushPromises();

    expect(device.old_ip).toBe('192.0.2.7');
    expect(showToast).toHaveBeenCalledWith('error', t('common.error'), 'offline');
  });
});
