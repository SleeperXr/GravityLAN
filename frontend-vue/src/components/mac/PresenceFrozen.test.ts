import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import type { Device, DeviceHealthItem } from '@/types';
import { setLocale } from '@/i18n';
import { api } from '@/api/client';
import DeviceList from '@/components/dashboard/DeviceList.vue';
import HealthDetailSheet from '@/components/health/HealthDetailSheet.vue';
import PresenceFrozenBadge from './PresenceFrozenBadge.vue';

vi.mock('@/api/client', () => ({ api: { getDeviceHealthDetail: vi.fn() } }));

/** Renders only the header (meta slot) of the sheet: the badge sits there. */
const SheetStub = defineComponent({ setup: (_, { slots }) => () => h('div', slots.meta?.()) });

const healthItem = (extra: Partial<DeviceHealthItem> = {}): DeviceHealthItem =>
  ({ id: 7, ip: '192.168.1.7', display_name: 'NAS', health_status: 'healthy', health_score: 100, presence_frozen: false, ...extra }) as unknown as DeviceHealthItem;

const device = (id: number, extra: Partial<Device> = {}): Device =>
  ({
    id,
    ip: `192.168.1.${id}`,
    display_name: `Device ${id}`,
    hostname: null,
    is_online: true,
    has_agent: false,
    services: [],
    ...extra,
  }) as unknown as Device;

describe('presence frozen by an open MAC conflict', () => {
  beforeEach(() => setLocale('de'));

  it('names the unconfirmed status and explains it in the title', () => {
    const badge = mount(PresenceFrozenBadge);
    expect(badge.text()).toBe('Status unbestätigt');
    expect(badge.attributes('title')).toContain('andere MAC');
  });

  it('marks only the devices whose state is frozen in the device list', () => {
    const list = mount(DeviceList, {
      props: { devices: [device(1), device(2, { presence_frozen: true }), device(3, { presence_frozen: false })] },
    });
    const badges = list.findAll('[data-testid="presence-frozen"]');
    expect(badges).toHaveLength(1);
    expect(list.findAll('li')[1].find('[data-testid="presence-frozen"]').exists()).toBe(true);
  });

  it('follows the overview row in the open health sheet, not the detail loaded before', async () => {
    // The detail was loaded before the conflict opened; it is not reloaded for the same device and period
    vi.mocked(api.getDeviceHealthDetail).mockResolvedValue({ device: healthItem(), time_series: [], incidents: [] } as never);
    const sheet = mount(HealthDetailSheet, {
      props: { open: false, device: healthItem(), period: '24h' },
      global: { stubs: { Sheet: SheetStub } },
    });
    await sheet.setProps({ open: true }); // HealthView opens the sheet after selecting the row
    await flushPromises();
    expect(api.getDeviceHealthDetail).toHaveBeenCalled();
    expect(sheet.find('[data-testid="presence-frozen"]').exists()).toBe(false);

    await sheet.setProps({ device: healthItem({ presence_frozen: true }) });
    await flushPromises();

    expect(sheet.find('[data-testid="presence-frozen"]').exists()).toBe(true);
  });
});
