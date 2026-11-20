import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import type { Device } from '@/types';
import { setLocale } from '@/i18n';
import DeviceList from '@/components/dashboard/DeviceList.vue';
import PresenceFrozenBadge from './PresenceFrozenBadge.vue';

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
});
