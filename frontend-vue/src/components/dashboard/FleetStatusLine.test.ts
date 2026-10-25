import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import type { Device } from '@/types';
import { setLocale } from '@/i18n';
import { buildNotices, STALE_AFTER_MS } from '@/lib/notices';
import FleetStatusLine from './FleetStatusLine.vue';

const NOW = new Date('2026-10-25T20:00:00Z').getTime();
const nas = { id: 1, ip: '10.0.0.1', hostname: 'nas', display_name: 'NAS', is_online: false, alert_offline: true, services: [] } as unknown as Device;

function render(devices: Device[], loadedAt: number | null = NOW) {
  return mount(FleetStatusLine, { props: { notices: buildNotices(devices), online: 29, total: 31, loadedAt } });
}

beforeEach(() => {
  setLocale('en');
  vi.useFakeTimers({ now: NOW });
});
afterEach(() => vi.useRealTimers());

describe('FleetStatusLine', () => {
  it('names what is down and opens the most urgent notice', async () => {
    const wrapper = render([nas]);
    expect(wrapper.get('[role="status"]').text()).toBe('1 device offline: NAS');
    expect(wrapper.text()).toContain('29/31 online');

    await wrapper.get('button').trigger('click');
    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({ kind: 'offline', device: { id: 1 } });
  });

  it('has no jump button when nothing is disrupted', () => {
    const wrapper = render([]);
    expect(wrapper.get('[role="status"]').text()).toBe('No disruptions');
    expect(wrapper.find('button').exists()).toBe(false);
  });

  it('warns when the data has not been refreshed for a while', () => {
    expect(render([], NOW).text()).not.toContain('stale');
    expect(render([], NOW - STALE_AFTER_MS - 1000).text()).toContain('data is stale');
  });
});
