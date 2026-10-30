import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import AppSidebar from './AppSidebar.vue';

/** A :dev image says it is a test build, so it is never mistaken for the release. */
async function mountWith(props: { version?: string; build?: string }) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] });
  await router.push('/');
  await router.isReady();
  return mount(AppSidebar, { props, global: { plugins: [router, createPinia()], stubs: { NavPreferences: true } } });
}

describe('AppSidebar', () => {
  it('shows the build label of a test build', async () => {
    const wrapper = await mountWith({ version: '0.7.0', build: 'dev+abc1234' });
    expect(wrapper.text()).toContain('v0.7.0');
    expect(wrapper.text()).toContain('dev+abc1234');
  });

  it('shows only the version for a release', async () => {
    const wrapper = await mountWith({ version: '0.7.0' });
    expect(wrapper.text()).toContain('v0.7.0');
    expect(wrapper.text()).not.toContain('dev+');
  });
});
