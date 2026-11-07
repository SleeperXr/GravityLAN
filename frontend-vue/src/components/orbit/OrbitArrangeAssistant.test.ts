import { describe, expect, it, vi } from 'vitest';
import { defineComponent, h, type PropType } from 'vue';
import { mount } from '@vue/test-utils';
import type { Device } from '@/types';
import { resolveOrbitSystem, type OrbitLink } from './orbitModel';
import OrbitArrangeAssistant from './OrbitArrangeAssistant.vue';
import type { ArrangePlan } from './orbitArrange';

vi.mock('@/lib/networks', () => ({ networkColor: () => 'var(--line-1)', deviceLabel: (d: Device) => d.display_name }));
vi.mock('@/i18n', () => ({ t: (key: string) => key }));

const dev = (id: number, extra: Partial<Device> = {}): Device =>
  ({ id, ip: `10.0.0.${id}`, display_name: `Dev-${id}`, hostname: null, device_type: 'server', device_subtype: '', is_online: true, services: [], parent_id: null, is_wlan: false, is_ap: false, is_host: false, subnet_id: 1, interfaces: [], ...extra }) as Device;

// Router 1 with a switch 2; Dev-3, Dev-4 and the WLAN client Dev-5 hang on the router
const devices = [dev(1, { device_type: 'router' }), dev(2, { device_type: 'switch' }), dev(3), dev(4), dev(5, { is_wlan: true })];
const links = [{ id: 1, source_id: 1, target_id: 2, link_type: '1GbE' }] as OrbitLink[];
const bodies = resolveOrbitSystem(devices, links, new Set([1]));

// Plain stand-ins: every step rendered at once, a native select per Select
/* eslint-disable vue/one-component-per-file */
const DialogStub = defineComponent({ setup: (_, { slots }) => () => h('div', [slots.default?.(), slots.footer?.()]) });
const TabsStub = defineComponent({
  props: { tabs: { type: Array as PropType<{ value: string }[]>, required: true } },
  setup: (props, { slots }) => () => h('div', props.tabs.map((tab) => h('section', { 'data-tab': tab.value }, slots[tab.value]?.()))),
});
const SelectStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: null, default: null }, options: { type: Array as PropType<{ value: unknown; label: string }[]>, required: true } },
  emits: ['update:modelValue'],
  setup: (props, { emit, attrs }) => () =>
    h(
      'select',
      {
        'aria-label': attrs['aria-label'],
        'data-test': attrs['data-test'],
        onChange: (e: Event) => emit('update:modelValue', props.options[(e.target as HTMLSelectElement).selectedIndex].value),
      },
      props.options.map((o) => h('option', { selected: o.value === props.modelValue }, o.label)),
    ),
});

function render() {
  return mount(OrbitArrangeAssistant, {
    props: { open: true, bodies, links, roles: {} },
    global: { stubs: { Dialog: DialogStub, Tabs: TabsStub, Select: SelectStub } },
  });
}
type Wrapper = ReturnType<typeof render>;

async function choose(select: ReturnType<Wrapper['find']>, label: string) {
  const el = select.element as HTMLSelectElement;
  const index = [...el.options].findIndex((o) => o.text === label);
  expect(index, `option ${label}`).toBeGreaterThanOrEqual(0);
  el.selectedIndex = index;
  await select.trigger('change');
}
/** The kind select of a device row in step 1 */
const kindSelect = (wrapper: Wrapper, name: string) =>
  wrapper.findAll('[data-test="arrange-kinds"] li').find((li) => li.text().startsWith(name))!.find('select');

describe('OrbitArrangeAssistant', () => {
  it('turns a device into an access point and hangs picked clients on it', async () => {
    const wrapper = render();
    expect(wrapper.find('[data-test="arrange-apply"]').attributes('disabled')).toBeDefined();
    await choose(kindSelect(wrapper, 'Dev-3'), 'gv.arrange.kind_ap');
    expect(wrapper.find('[data-test="arrange-apply"]').attributes('disabled')).toBeUndefined();

    // The new AP (Dev-3) is a target now; pick Dev-4 and Dev-5 and assign them
    const target = wrapper.find('[data-test="arrange-target"]');
    await choose(target, 'Dev-3 · gv.arrange.kind_ap');
    const boxes = wrapper.findAll('[data-test="arrange-clients"] input[type="checkbox"]');
    expect(boxes).toHaveLength(2);
    for (const box of boxes) await box.trigger('change');
    await wrapper.find('[data-test="arrange-assign"]').trigger('click');

    await wrapper.find('[data-test="arrange-apply"]').trigger('click');
    const [plan] = wrapper.emitted('apply')![0] as [ArrangePlan];
    expect(plan.roles).toEqual({ 3: 'planet' });
    expect(plan.createLinks).toEqual([
      { source_id: 3, target_id: 4, link_type: 'WLAN' },
      { source_id: 3, target_id: 5, link_type: 'WLAN' },
    ]);
  });

  it('moves a switch to a new uplink and offers the old one-click layout', async () => {
    const wrapper = render();
    await choose(kindSelect(wrapper, 'Dev-3'), 'gv.arrange.kind_switch');
    // Dev-2 hangs on the router; put it behind the new switch Dev-3
    const row = wrapper.findAll('[data-test="arrange-uplinks"] li').find((li) => li.text().startsWith('Dev-2'))!;
    await choose(row.find('select'), 'Dev-3 · gv.arrange.kind_switch');
    await wrapper.find('[data-test="arrange-apply"]').trigger('click');
    const [plan] = wrapper.emitted('apply')![0] as [ArrangePlan];
    expect(plan.removeLinkIds).toEqual([1]);
    expect(plan.createLinks).toEqual([{ source_id: 3, target_id: 2, link_type: '1GbE' }]);

    await wrapper.find('[data-test="arrange-only"]').trigger('click');
    expect(wrapper.emitted('arrangeOnly')).toHaveLength(1);
  });
});
