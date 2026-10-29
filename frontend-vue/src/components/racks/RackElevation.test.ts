import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import type { Device, RackPort } from '@/types';
import { setLocale } from '@/i18n';
import RackElevation from './RackElevation.vue';
import { deviceEntry, type RackEntry } from './rackModel';

const dev = (id: number, rack_unit: number, extra: Partial<Device> = {}): RackEntry =>
  deviceEntry({ id, ip: `10.0.0.${id}`, rack_id: 1, rack_unit, rack_height: 1, is_online: true, ...extra } as Device, `Dev ${id}`);

const ports = [
  { id: 1, device_id: 1, rack_item_id: null, number: 1, kind: 'RJ45', side: 'front' },
  { id: 2, device_id: 1, rack_item_id: null, number: 2, kind: 'RJ45', side: 'front' },
] as RackPort[];

function render(entries: RackEntry[], extra: { placing?: RackEntry | null } = {}, attach = false) {
  return mount(RackElevation, {
    attachTo: attach ? document.body : undefined,
    props: {
      ...extra,
      name: 'Rack',
      units: 6,
      width: 19,
      entries,
      candidates: [],
      selectedKey: null,
      portStats: {},
      side: 'front',
      ports,
      cables: [],
      colourOfPort: {},
      cableTargets: { 1: 'cable to Core · port 5' },
    },
  });
}

let mounted: VueWrapper | null = null;
beforeEach(() => setLocale('en'));
afterEach(() => {
  mounted?.unmount();
  mounted = null;
});

describe('RackElevation', () => {
  it('lists each entry as a list item holding a button named with its state and place', () => {
    const wrapper = render([dev(1, 5), dev(2, 3, { is_online: false })]);
    expect(wrapper.findAll('[role="listitem"]')).toHaveLength(2);
    expect(wrapper.find('button[role="listitem"]').exists()).toBe(false);
    const names = wrapper.findAll('[role="listitem"] > button').map((b) => b.attributes('aria-label'));
    expect(names[0]).toMatch(/^Dev 1, Online, /);
    expect(names[1]).toMatch(/^Dev 2, Offline, /);
  });

  it('makes the jacks one tab stop with names that say where the cable goes', () => {
    const wrapper = render([dev(1, 5)]);
    const jacks = wrapper.findAll('[data-port]');
    expect(jacks.map((j) => j.element.tagName)).toEqual(['BUTTON', 'BUTTON']);
    expect(jacks.map((j) => j.attributes('tabindex'))).toEqual(['0', '-1']);
    expect(jacks[0].attributes('aria-label')).toBe('Port 1, RJ45, Front, cable to Core · port 5');
    expect(jacks[1].attributes('aria-label')).toContain('free');
  });

  it('asks for a cable from a jack', async () => {
    const wrapper = render([dev(1, 5)]);
    await wrapper.get('[data-port="2"]').trigger('click');
    expect(wrapper.emitted('pickPort')?.[0]).toEqual(['device-1', ports[1]]);
  });

  it('draws overlapping entries side by side and keeps every unit number once', () => {
    const wrapper = render([dev(1, 4), dev(2, 4)]);
    const units = wrapper.findAll('[role="list"] > div > span:first-child').map((s) => Number(s.text()));
    expect(units).toEqual([6, 5, 4, 3, 2, 1]);
    const names = wrapper.findAll('[role="listitem"] > button').map((b) => b.attributes('aria-label'));
    expect(names.every((n) => n?.includes('overlaps another device'))).toBe(true);
  });

  it('lists the free units as items while placing, each a button that places there', async () => {
    const tray = { ...dev(9, 0), unit: null };
    const wrapper = render([dev(1, 5)], { placing: tray });
    const targets = wrapper.findAll('[role="listitem"] > button[data-place-unit]');
    expect(targets.map((b) => Number(b.attributes('data-place-unit')))).toEqual([6, 4, 3, 2, 1]);
    await targets[1].trigger('click');
    expect(wrapper.emitted('place')?.[0]).toEqual(['device-9', 4]);
  });

  it('hands focus to the placed entry once it is drawn, also after a click', async () => {
    const tray = { ...dev(9, 0), unit: null };
    mounted = render([dev(1, 5)], { placing: tray }, true);
    await mounted.get('[data-place-unit="3"]').trigger('click');
    await mounted.setProps({ entries: [dev(1, 5), dev(9, 3)], placing: null });
    await flushPromises();
    expect(document.activeElement?.getAttribute('data-key')).toBe('device-9');
  });

  it('keeps focus on an entry that the arrow keys move to another row', async () => {
    mounted = render([dev(1, 5)], {}, true);
    const button = mounted.get<HTMLButtonElement>('[data-key="device-1"]');
    button.element.focus();
    await button.trigger('keydown', { key: 'ArrowUp' });
    expect(mounted.emitted('move')?.[0]).toEqual(['device-1', 6]);
    await mounted.setProps({ entries: [dev(1, 6)] });
    await flushPromises();
    expect(document.activeElement?.getAttribute('data-key')).toBe('device-1');
  });

  it('does not take focus for a move that cannot fit', async () => {
    mounted = render([dev(1, 6)], {}, true);
    await mounted.get('[data-key="device-1"]').trigger('keydown', { key: 'ArrowUp' });
    expect(mounted.emitted('move')?.[0]).toEqual(['device-1', 7]);
    const outside = document.createElement('button');
    document.body.append(outside);
    outside.focus();
    await mounted.setProps({ entries: [dev(1, 6)] });
    await flushPromises();
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });
});
