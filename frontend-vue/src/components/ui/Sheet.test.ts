import { afterEach, describe, expect, it } from 'vitest';
import { defineComponent, h, nextTick, ref } from 'vue';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import Sheet from './Sheet.vue';
import Dialog from './Dialog.vue';
import { TOAST_REGION_ATTR } from '@/lib/overlay';

let wrapper: VueWrapper | null = null;
const open = ref(true);

/** A sheet or dialog next to a toast region and some other page content, as in the app */
function render(panel: typeof Sheet | typeof Dialog) {
  open.value = true;
  const Host = defineComponent({
    setup: () => () => [
      h('button', { id: 'page' }, 'Page'),
      h('section', { [TOAST_REGION_ATTR]: '' }, [h('button', { id: 'toast-close' }, 'x')]),
      h(panel, { open: open.value, 'onUpdate:open': (v: boolean) => (open.value = v), title: 'Device' }, () => h('p', 'body')),
    ],
  });
  wrapper = mount(Host, { attachTo: document.body });
}

async function settle() {
  await nextTick();
  await flushPromises();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function pointerDown(id: string) {
  const el = document.getElementById(id)!;
  el.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  el.dispatchEvent(new Event('click', { bubbles: true }));
  await settle();
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe.each([
  ['Sheet', Sheet],
  ['Dialog', Dialog],
])('%s and toasts', (_name, panel) => {
  it('stays open when a toast is closed', async () => {
    render(panel);
    await settle();
    await pointerDown('toast-close');
    expect(open.value).toBe(true);
  });

  it('still closes on a click elsewhere outside', async () => {
    render(panel);
    await settle();
    await pointerDown('page');
    expect(open.value).toBe(false);
  });
});
