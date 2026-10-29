import { afterEach, describe, expect, it } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import Dialog from './Dialog.vue';

let wrapper: VueWrapper | null = null;

function open(withAutofocus: boolean) {
  const Host = defineComponent({
    setup: () => () =>
      h(Dialog, { open: true, title: 'Item' }, () => [
        h('button', { type: 'button', id: 'first' }, 'First'),
        h('input', { id: 'name', autofocus: withAutofocus || undefined }),
      ]),
  });
  wrapper = mount(Host, { attachTo: document.body });
}

async function settle() {
  await nextTick();
  await flushPromises();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe('Dialog', () => {
  it('starts on the field marked autofocus', async () => {
    open(true);
    await settle();
    expect(document.activeElement?.id).toBe('name');
  });

  it('keeps the usual first focus when no field asks for it', async () => {
    open(false);
    await settle();
    expect(document.activeElement?.id).not.toBe('name');
  });
});
