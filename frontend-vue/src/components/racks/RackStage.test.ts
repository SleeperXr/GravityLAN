import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { mount } from '@vue/test-utils';
import type { RackCable, RackPort } from '@/types';
import { t } from '@/i18n';
import RackStage from './RackStage.vue';
import RackCables from './RackCables.vue';
import RackFaceplate from './RackFaceplate.vue';
import { faceHeight, faceLayout, faceTop, jackCentre, rackFrame } from './rackGeometry';
import type { RackEntry } from './rackModel';

const env = vi.hoisted(() => ({
  reduced: true,
  observe: null as null | ((entries: { contentRect: { width: number; height: number } }[]) => void),
}));

vi.mock('@vueuse/core', () => ({
  useResizeObserver: (_target: unknown, callback: typeof env.observe) => {
    env.observe = callback;
  },
}));
vi.mock('./rackMotion', async (original) => ({
  ...(await original<typeof import('./rackMotion')>()),
  prefersReducedMotion: () => env.reduced,
  useFrameLoop: () => ({ kick: vi.fn(), stop: vi.fn() }),
}));

const BOX = { width: 800, height: 600 };
const UNITS = 12;
const FRAME = rackFrame(UNITS, 19, { width: BOX.width - 32, height: BOX.height - 52 }, false);

const entry = (id: number, unit: number | null, label = `dev${id}`) =>
  ({ key: `device-${id}`, kind: 'device', id, label, detail: '', online: true, itemKind: null, unit, height: 1, face: 'switch', subnetId: null }) as unknown as RackEntry;
const port = (id: number, device_id: number, side = 'front') => ({ id, device_id, rack_item_id: null, number: id, kind: 'RJ45', side }) as RackPort;
const cable = (id: number, a_port_id: number, b_port_id: number) => ({ id, a_port_id, b_port_id, cable: 'Cat6', color: null, notes: null, created_at: '' }) as RackCable;

async function render(extra: Record<string, unknown> = {}) {
  const wrapper = mount(RackStage, {
    props: {
      rackName: 'Main',
      units: UNITS,
      inches: 19,
      entries: [entry(1, 10), entry(2, 5)],
      ports: [],
      cables: [],
      side: 'front',
      selectedKey: null,
      colourOfPort: {},
      downPorts: new Set<number>(),
      accentOf: {},
      ownerLabel: { 'device-1': 'sw1', 'device-2': 'sw2' },
      elsewhere: () => ({ label: '', rackId: null }),
      ambient: false,
      pendingPortId: null,
      highlightCableId: null,
      drag: null,
      detail: false,
      peerOfPort: {},
      ...extra,
    } as never,
    global: { stubs: { RackFaceplate: true, RackCables: true } },
  });
  env.observe!([{ contentRect: BOX }]);
  await nextTick();
  await nextTick();
  return wrapper;
}
type Stage = Awaited<ReturnType<typeof render>>;

const faceplate = (w: Stage, id: number) => w.get(`[data-entry="device-${id}"]`);
const offsetOf = (w: Stage, id: number) => Number(/translate3d\([^,]+, ([-\d.]+)px/.exec(faceplate(w, id).attributes('style') ?? '')![1]);
const cables = (w: Stage) => w.findComponent(RackCables);

/** Where a jack of an entry sits on an empty, settled rack with these ports */
function jackAt(ports: RackPort[], portId: number, unit: number) {
  const layout = faceLayout(ports, FRAME.facePx, faceHeight(FRAME, 1));
  return jackCentre(layout.jacks.find((j) => j.portId === portId)!, { x: FRAME.railPx, y: faceTop(FRAME, unit) });
}

beforeEach(() => {
  env.reduced = true;
  document.elementsFromPoint = () => [];
  Element.prototype.scrollTo = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('faceplates arriving', () => {
  it('sits at rest at once with reduced motion', async () => {
    const w = await render();
    expect(offsetOf(w, 1)).toBe(faceTop(FRAME, 10));
    expect(faceplate(w, 2).classes()).not.toContain('is-waiting');
  });

  it('lets the rack fill from the top, one after the other', async () => {
    env.reduced = false;
    const w = await render();
    expect(offsetOf(w, 1)).toBe(faceTop(FRAME, 10) - 26);
    expect(faceplate(w, 1).classes()).not.toContain('is-waiting');
    expect(faceplate(w, 2).classes()).toContain('is-waiting');
  });

  it('flashes a faceplate added later, and only briefly', async () => {
    env.reduced = false;
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    const w = await render();
    await w.setProps({ entries: [entry(1, 10), entry(2, 5), entry(3, 2)] });
    await nextTick();
    expect(faceplate(w, 3).classes()).toContain('is-arriving');
    expect(offsetOf(w, 3)).toBe(faceTop(FRAME, 2));
    vi.advanceTimersByTime(450);
    await nextTick();
    expect(faceplate(w, 3).classes()).not.toContain('is-arriving');
  });

  it('does not flash with reduced motion', async () => {
    const w = await render();
    await w.setProps({ entries: [entry(1, 10), entry(2, 5), entry(3, 2)] });
    await nextTick();
    expect(faceplate(w, 3).classes()).not.toContain('is-arriving');
  });

  it('settles something dragged in from where it was let go', async () => {
    env.reduced = false;
    const w = await render();
    await w.setProps({ drag: { key: 'device-3', from: 'palette', lifted: true, zone: 'stage', x: 50, y: 77, height: 1, target: null } as never });
    await w.setProps({ drag: null });
    await w.setProps({ entries: [entry(1, 10), entry(2, 5), entry(3, 2)] });
    await nextTick();
    expect(offsetOf(w, 3)).toBe(77);
    expect(faceplate(w, 3).classes()).not.toContain('is-arriving');
  });

  it.each([
    ['moved within the rack', { from: 'rack', zone: 'stage' }],
    ['let go outside the rack', { from: 'palette', zone: 'store' }],
  ])('does not remember a drag %s', async (_name, drag) => {
    env.reduced = false;
    const w = await render();
    await w.setProps({ drag: { key: 'device-3', lifted: true, x: 50, y: 77, height: 1, target: null, ...drag } as never });
    await w.setProps({ drag: null });
    await w.setProps({ entries: [entry(1, 10), entry(2, 5), entry(3, 2)] });
    await nextTick();
    expect(offsetOf(w, 3)).toBe(faceTop(FRAME, 2));
  });

  it('starts over for an entry that left and came back', async () => {
    const w = await render();
    await w.setProps({ entries: [entry(1, 10)] });
    await nextTick();
    expect(w.find('[data-entry="device-2"]').exists()).toBe(false);
    await w.setProps({ entries: [entry(1, 10), entry(2, 3)] });
    await nextTick();
    expect(offsetOf(w, 2)).toBe(faceTop(FRAME, 3));
  });
});

describe('cables', () => {
  const PORTS = [port(1, 1), port(2, 2)];

  it('draws a cable between two drawn jacks and lights up the selection', async () => {
    const w = await render({ ports: PORTS, cables: [cable(5, 1, 2)], selectedKey: 'device-1' });
    expect(cables(w).props('cables')).toMatchObject([{ id: 5, dashed: false, state: 'active' }]);
  });

  it('lights up a cable from outside', async () => {
    const w = await render({ ports: PORTS, cables: [cable(5, 1, 2)], highlightCableId: 6 });
    expect(cables(w).props('cables')).toMatchObject([{ id: 5, state: 'dim' }]);
  });

  it('leads a stub label to the other side of the rack', async () => {
    const w = await render({ ports: [port(1, 1), port(2, 2, 'rear')], cables: [cable(5, 1, 2)] });
    expect(cables(w).props('cables')).toMatchObject([{ dashed: true }]);
    const [label] = cables(w).props('labels');
    expect(label.text).toBe(t('gv.rack.stub_rear'));
    cables(w).vm.$emit('stub', label.key);
    expect(w.emitted('stub')).toEqual([[{ ownerKey: 'device-2', side: 'rear', rackId: null }]]);
  });

  it('leads a stub label to the rack the other end is in, shortening its name', async () => {
    const elsewhere = () => ({ label: 'A very long rack name', rackId: 4 });
    const w = await render({ entries: [entry(1, 10)], ports: PORTS, cables: [cable(5, 1, 2)], elsewhere });
    const [label] = cables(w).props('labels');
    expect(label.text).toBe('→ A very long…');
    cables(w).vm.$emit('stub', label.key);
    expect(w.emitted('stub')).toEqual([[{ ownerKey: 'device-2', side: 'front', rackId: 4 }]]);
  });

  it('names both ends of the cable under the pointer', async () => {
    const w = await render({ ports: PORTS, cables: [cable(5, 1, 2)] });
    cables(w).vm.$emit('hover', 5, { clientX: 30, clientY: 40 });
    await nextTick();
    expect(w.get('[role="tooltip"]').text()).toContain('sw1 1 ↔ sw2 2');
    cables(w).vm.$emit('hover', null, { clientX: 30, clientY: 40 });
    await nextTick();
    expect(w.find('[role="tooltip"]').exists()).toBe(false);
  });

  it('forgets a hover on a cable that is gone', async () => {
    const w = await render({ ports: PORTS, cables: [cable(5, 1, 2)] });
    cables(w).vm.$emit('hover', 5, { clientX: 30, clientY: 40 });
    await w.setProps({ cables: [] });
    expect(w.find('[role="tooltip"]').exists()).toBe(false);
  });
});

describe('plugging in a cable', () => {
  const PORTS = [port(1, 1), port(2, 2)];
  const press = (w: Stage, portId: number) => w.findAllComponents(RackFaceplate)[0].vm.$emit('jackDown', portId, { button: 0, clientX: 0, clientY: 0 });
  const pointer = (type: string, x: number, y: number) => window.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y }));
  const repaint = async (w: Stage) => {
    await w.setProps({ ambient: true });
    await w.setProps({ ambient: false });
  };

  it('shows nothing while no cable is being plugged in', async () => {
    expect(cables(await render({ ports: PORTS })).props('live')).toBeNull();
  });

  it('draws from the waiting port to the pointer', async () => {
    const w = await render({ ports: PORTS, pendingPortId: 1 });
    await w.get('.rack-stage').trigger('pointermove', { clientX: 300, clientY: 300 });
    expect(cables(w).props('live')).toMatchObject({ snapped: false, colour: '#2ec4a6', target: null });
  });

  it('snaps a waiting port to a free jack nearby', async () => {
    const w = await render({ ports: PORTS, pendingPortId: 1 });
    const at = jackAt([PORTS[1]], 2, 5);
    await w.get('.rack-stage').trigger('pointermove', { clientX: at.x, clientY: at.y });
    expect(cables(w).props('live')).toMatchObject({ snapped: true, target: 2 });
    expect(w.get('.rack-chip').text()).toBe(t('gv.rack.patch_target', { label: 'sw2', port: 2 }));
  });

  it('connects when a pull from a free jack ends on another one', async () => {
    const w = await render({ ports: PORTS });
    const at = jackAt([PORTS[1]], 2, 5);
    press(w, 1);
    pointer('pointermove', at.x, at.y);
    await repaint(w);
    expect(cables(w).props('live')).toMatchObject({ snapped: true, target: 2 });
    pointer('pointerup', at.x, at.y);
    await nextTick();
    expect(w.emitted('connect')).toEqual([[1, 2]]);
    expect(cables(w).props('live')).toBeNull();
  });

  it('treats a press without a pull as picking the port', async () => {
    const w = await render({ ports: PORTS });
    press(w, 1);
    pointer('pointerup', 0, 0);
    expect(w.emitted('pick')).toEqual([[1]]);
    expect(w.emitted('connect')).toBeUndefined();
  });

  it('will not connect to a jack that already has a cable', async () => {
    const ports = [...PORTS, port(3, 2)];
    const w = await render({ ports, cables: [cable(5, 2, 3)] });
    press(w, 1);
    const at = jackAt([ports[1], ports[2]], 2, 5);
    pointer('pointermove', at.x, at.y);
    await repaint(w);
    expect(cables(w).props('live')).toMatchObject({ snapped: false, target: null });
    pointer('pointerup', at.x, at.y);
  });
});

describe('reveal', () => {
  it('scrolls a placed faceplate into view', async () => {
    const w = await render();
    (w.vm as unknown as { reveal: (key: string) => void }).reveal('device-2');
    expect(Element.prototype.scrollTo).toHaveBeenCalledWith({ top: expect.any(Number), behavior: 'auto' });
  });

  it.each([['an unknown entry', 'device-9'], ['an entry without a unit', 'device-3']])('ignores %s', async (_name, key) => {
    const w = await render({ entries: [entry(1, 10), entry(3, null)] });
    (w.vm as unknown as { reveal: (key: string) => void }).reveal(key);
    expect(Element.prototype.scrollTo).not.toHaveBeenCalled();
  });
});
