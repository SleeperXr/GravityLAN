import { describe, expect, it } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { mount, flushPromises } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { queryCodecs, useQueryState } from './useQueryState';

async function setup(path = '/') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
  await router.push(path);
  let state!: {
    q: ReturnType<typeof useQueryState<string>>;
    status: ReturnType<typeof useQueryState<'all' | 'online' | 'offline'>>;
    net: ReturnType<typeof useQueryState<number | null>>;
  };
  const Host = defineComponent({
    setup() {
      state = {
        q: useQueryState('q', '', queryCodecs.string),
        status: useQueryState('status', 'all', queryCodecs.oneOf(['all', 'online', 'offline'] as const)),
        net: useQueryState<number | null>('net', null, queryCodecs.nullableInt),
      };
      return () => h('div');
    },
  });
  mount(Host, { global: { plugins: [router] } });
  return { router, state };
}

describe('useQueryState', () => {
  it('reads the values from the URL', async () => {
    const { state } = await setup('/?q=nas&status=offline&net=3');
    expect(state.q.value).toBe('nas');
    expect(state.status.value).toBe('offline');
    expect(state.net.value).toBe(3);
  });

  it('reads a value it does not accept as the default', async () => {
    const { state } = await setup('/?status=bogus&net=abc');
    expect(state.status.value).toBe('all');
    expect(state.net.value).toBeNull();
  });

  it('writes to the URL and leaves the default out', async () => {
    const { router, state } = await setup('/?q=old');
    state.q.value = 'nas';
    state.status.value = 'online';
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ q: 'nas', status: 'online' });

    state.q.value = '';
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ status: 'online' });
  });

  it('keeps every value when several change in one tick, and shows them before the navigation lands', async () => {
    const { router, state } = await setup('/?q=nas&status=offline&net=3');
    state.q.value = '';
    state.status.value = 'all';
    state.net.value = null;
    expect([state.q.value, state.status.value, state.net.value]).toEqual(['', 'all', null]);
    await nextTick();
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({});
  });

  it('keeps query keys it does not own', async () => {
    const { router, state } = await setup('/?view=rack');
    state.q.value = 'pve';
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ view: 'rack', q: 'pve' });
  });
});
