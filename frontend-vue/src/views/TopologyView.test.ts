import { describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import TopologyView from './TopologyView.vue';

/** The racks must stay reachable from the topology page (they went missing once without anyone noticing). */
async function mountAt(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/topology', component: TopologyView }] });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(TopologyView, {
    global: {
      plugins: [router, createPinia()],
      stubs: {
        OrbitMap: { template: '<div data-test="orbit" />' },
        RackView: { template: '<div data-test="racks" />' },
        DeviceEditor: true,
      },
    },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('TopologyView', () => {
  it('offers the rack view next to the map and shows it for ?view=rack', async () => {
    const { wrapper } = await mountAt('/topology?view=rack');
    const toggles = wrapper.findAll('button[aria-pressed]');
    expect(toggles).toHaveLength(2);
    expect(wrapper.find('[data-test="racks"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="orbit"]').exists()).toBe(false);
  });

  it('switches from the map to the racks with the toggle', async () => {
    const { wrapper, router } = await mountAt('/topology');
    expect(wrapper.find('[data-test="orbit"]').exists()).toBe(true);
    await wrapper.findAll('button[aria-pressed]')[1].trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.query.view).toBe('rack');
    expect(wrapper.find('[data-test="racks"]').exists()).toBe(true);
  });
});
