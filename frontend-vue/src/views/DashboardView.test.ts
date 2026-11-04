import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import DashboardView from './DashboardView.vue';
import { useNetworkStore } from '@/stores/network';

describe('DashboardView Orbit collapse', () => {
  let pinia: ReturnType<typeof createPinia>;
  let router: ReturnType<typeof createRouter>;

  beforeEach(async () => {
    localStorage.clear();
    pinia = createPinia();
    setActivePinia(pinia);
    router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: DashboardView }] });
    await router.push('/');
    await router.isReady();
  });

  function mountView() {
    const store = useNetworkStore();
    store.loaded = true;
    store.devices = [
      {
        id: 1,
        ip: '192.168.100.1',
        mac: 'aa:bb:cc:dd:ee:ff',
        hostname: 'router',
        display_name: 'Router',
        vendor: 'Ubiquiti',
        subnet_id: 1,
        group_id: null,
        is_online: true,
        alert_offline: true,
        services: [],
        interfaces: [],
        has_agent: false,
      } as unknown as (typeof store.devices)[number],
    ];
    store.subnets = [{ id: 1, name: 'LAN', cidr: '192.168.100.0/24', is_enabled: true } as unknown as (typeof store.subnets)[number]];

    return mount(DashboardView, {
      global: {
        plugins: [router, pinia],
        stubs: {
          OrbitMap: { template: '<div data-test="orbit-map" />' },
          ServiceNotices: { template: '<div data-test="service-notices" />' },
          GroupSection: { template: '<div data-test="group-section" />' },
          GatewaysPopover: true,
          NotificationCenter: true,
          ScanDialog: true,
          AgentUpdateCenter: true,
          DeviceEditor: true,
          LineStatusBoard: true,
          NetworkPulse: true,
        },
      },
    });
  }

  it('renders orbit and notices initially and allows collapsing and expanding them', async () => {
    const wrapper = mountView();
    await flushPromises();

    // Initially expanded: grid is visible, banner does not exist
    const gridEl = () => wrapper.find('.grid.gap-4').element as HTMLElement;
    expect(gridEl().style.display).not.toBe('none');
    expect(wrapper.find('button.group\\/toggle').exists()).toBe(false);

    // Find collapse button in orbit header
    const collapseBtn = wrapper.find('button[title*="ollapse"]');
    expect(collapseBtn.exists()).toBe(true);

    await collapseBtn.trigger('click');
    await flushPromises();

    // Orbit grid is hidden (via v-show display: none)
    expect(gridEl().style.display).toBe('none');
    expect(wrapper.find('button.group\\/toggle').exists()).toBe(true);
    expect(localStorage.getItem('gravityui.dashboard.orbit_collapsed')).toBe('true');

    // Click to expand again
    const toggleBtn = wrapper.find('button.group\\/toggle');
    await toggleBtn.trigger('click');
    await flushPromises();

    // Grid is visible again, collapsed banner disappears
    expect(gridEl().style.display).not.toBe('none');
    expect(wrapper.find('button.group\\/toggle').exists()).toBe(false);
    expect(localStorage.getItem('gravityui.dashboard.orbit_collapsed')).toBe('false');
  });
});
