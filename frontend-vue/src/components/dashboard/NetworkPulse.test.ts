import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import type { Device, Service } from '@/types';
import { setLocale } from '@/i18n';
import NetworkPulse from './NetworkPulse.vue';

let nextId = 1;
const dev = (extra: Partial<Device> = {}): Device =>
  ({ id: nextId, ip: `192.0.2.${nextId++}`, hostname: null, display_name: null, is_online: true, alert_offline: true, services: [], ...extra }) as unknown as Device;
const down = { is_up: false } as Service;

function render(devices: Device[]) {
  return mount(NetworkPulse, { props: { devices, updated: new Date(), failed: false } });
}

beforeEach(() => {
  nextId = 1;
  setLocale('en');
});

describe('NetworkPulse', () => {
  it('names the offline and degraded devices', () => {
    const wrapper = render([
      dev({ display_name: 'NAS', is_online: false }),
      dev({ display_name: 'Pi-hole', is_online: false }),
      dev({ display_name: 'Printer', is_online: false }),
      dev({ display_name: 'Web', services: [down] }),
    ]);
    const summary = wrapper.get('[role="status"]').text();
    expect(summary).toContain('3 devices offline: NAS, Pi-hole +1');
    expect(summary).toContain('1 device with a service down: Web');
  });

  it('opens the first offline device, before a degraded one', async () => {
    const wrapper = render([dev({ display_name: 'Web', services: [down] }), dev({ display_name: 'NAS', is_online: false })]);
    const button = wrapper.get('button');
    expect(button.attributes('aria-label')).toBe('Go to problem: NAS');
    await button.trigger('click');
    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({ display_name: 'NAS' });
  });

  it('opens a degraded device when nothing is offline, leaving out clients in standby', async () => {
    const wrapper = render([dev({ display_name: 'Laptop', is_online: false, alert_offline: false }), dev({ display_name: 'Web', services: [down] })]);
    expect(wrapper.get('[role="status"]').text()).toBe('1 device with a service down: Web');
    await wrapper.get('button').trigger('click');
    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({ display_name: 'Web' });
  });

  it('has no jump button when everything is fine', () => {
    const wrapper = render([dev(), dev({ is_online: false, alert_offline: false })]);
    expect(wrapper.find('button').exists()).toBe(false);
  });
});
