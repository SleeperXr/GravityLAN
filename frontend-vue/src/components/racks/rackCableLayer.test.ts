import { describe, expect, it } from 'vitest';
import type { RackCable, RackPort } from '@/types';
import { buildCableLayer, type CableLayerInput } from './rackCableLayer';
import { REST_SAG, channelEdge, type Point, type RackFrame } from './rackGeometry';

const frame: RackFrame = { units: 42, unitPx: 20, railPx: 40, facePx: 400, channelPx: 80, padPx: 10 };
const port = (id: number, device_id: number, kind = 'RJ45') => ({ id, device_id, rack_item_id: null, number: id, kind, side: 'front' }) as RackPort;
const cable = (id: number, a_port_id: number, b_port_id: number, color: string | null = null) => ({ id, a_port_id, b_port_id, cable: 'Cat6', color, notes: null, created_at: '' }) as RackCable;

const PORTS = new Map([1, 2, 3, 4, 5].map((id) => [id, port(id, id < 4 ? 1 : 2)]));
const place = (id: string, text = id) => ({ id, text, target: { ownerKey: 'device-9', side: null, rackId: null } });

function layer(cables: RackCable[], points: Record<number, Point>, extra: Partial<CableLayerInput> = {}) {
  return buildCableLayer({
    frame,
    cables,
    portOf: (id) => PORTS.get(id),
    jackPoint: (id) => points[id] ?? null,
    sagOf: () => REST_SAG,
    laneOf: () => 0,
    selectedKey: null,
    focus: null,
    placeOf: () => place('rear'),
    ...extra,
  });
}

const near = { 1: { x: 100, y: 100 }, 4: { x: 200, y: 120 } };
const far = { 1: { x: 100, y: 100 }, 4: { x: 200, y: 400 } };

describe('buildCableLayer', () => {
  it('skips a cable with an unknown port or no end drawn here', () => {
    expect(layer([cable(1, 1, 99)], near).draws).toEqual([]);
    expect(layer([cable(1, 2, 3)], near).draws).toEqual([]);
  });

  it('hangs nearby jacks in a loop and sends distant ones through the channel', () => {
    const [loop] = layer([cable(1, 1, 4)], near).draws;
    const [run] = layer([cable(1, 1, 4)], far).draws;
    expect(loop).toMatchObject({ id: 1, dashed: false });
    expect(run).toMatchObject({ id: 1, dashed: false });
    expect(loop.d).not.toBe(run.d);
  });

  it('uses the lane it is given only for a channel run', () => {
    const path = (points: Record<number, Point>, lane: number) => layer([cable(1, 1, 4)], points, { laneOf: () => lane }).draws[0].d;
    expect(path(far, 0)).not.toBe(path(far, 3));
    expect(path(near, 0)).toBe(path(near, 3));
  });

  it('prefers the colour of the cable over the default of its port', () => {
    expect(layer([cable(1, 1, 4, '#abcdef')], near).draws[0].colour).toBe('#abcdef');
    expect(layer([cable(1, 1, 4)], near).draws[0].colour).toBe('#2ec4a6');
  });

  describe('state', () => {
    const stateWith = (extra: Partial<CableLayerInput>) => layer([cable(7, 1, 4)], near, extra).draws[0].state;

    it('is normal with nothing in focus', () => {
      expect(stateWith({})).toBe('normal');
    });

    it('is active for the focused cable and dim for the others', () => {
      expect(stateWith({ focus: 7 })).toBe('active');
      expect(stateWith({ focus: 8 })).toBe('dim');
    });

    it('is active when either end belongs to the selection', () => {
      const [a, b] = [PORTS.get(1)!, PORTS.get(4)!];
      expect(a.device_id).not.toBe(b.device_id);
      expect(stateWith({ selectedKey: 'device-1' })).toBe('active');
      expect(stateWith({ selectedKey: 'device-2' })).toBe('active');
      expect(stateWith({ selectedKey: 'device-3' })).toBe('dim');
    });
  });

  describe('stubs', () => {
    const one = { 1: { x: 100, y: 100 } };

    it('dashes a cable with one end here and labels where it goes', () => {
      const result = layer([cable(1, 1, 4)], one);
      expect(result.draws[0]).toMatchObject({ dashed: true });
      expect(result.labels).toEqual([{ key: 'device-1|rear', x: channelEdge(frame), y: 95, text: 'rear' }]);
      expect(result.targets.get('device-1|rear')).toEqual(place('rear').target);
    });

    it('asks for the place of the far end, whichever end is drawn', () => {
      const asked: number[] = [];
      const placeOf = (p: RackPort) => {
        asked.push(p.id);
        return place('rear');
      };
      layer([cable(1, 1, 4)], { 1: { x: 100, y: 100 } }, { placeOf });
      layer([cable(1, 1, 4)], { 4: { x: 100, y: 100 } }, { placeOf });
      expect(asked).toEqual([4, 1]);
    });

    it('bundles the cables of one owner going to the same place', () => {
      const points = { 1: { x: 100, y: 100 }, 2: { x: 120, y: 180 } };
      const { labels, draws } = layer([cable(1, 1, 4), cable(2, 2, 5)], points);
      expect(labels).toEqual([{ key: 'device-1|rear', x: channelEdge(frame), y: 95, text: 'rear · 2' }]);
      expect(draws[0].d).not.toBe(draws[1].d);
    });

    it('keeps different places and different owners apart', () => {
      const placeOf = (p: RackPort) => place(p.id === 4 ? 'rear' : 'loose');
      expect(layer([cable(1, 1, 4), cable(2, 2, 5)], { 1: { x: 0, y: 0 }, 2: { x: 0, y: 0 } }, { placeOf }).labels.map((l) => l.key)).toEqual(['device-1|rear', 'device-1|loose']);
      expect(layer([cable(1, 1, 2), cable(2, 4, 3)], { 1: { x: 0, y: 0 }, 4: { x: 0, y: 0 } }).labels.map((l) => l.key)).toEqual(['device-1|rear', 'device-2|rear']);
    });

    it('stops spreading a bundle after five cables', () => {
      const cables = [1, 2, 3, 4, 5, 6, 7].map((id) => cable(id, 1, 4));
      const { draws } = layer(cables, { 1: { x: 100, y: 100 } });
      expect(new Set(draws.slice(5).map((d) => d.d)).size).toBe(1);
      expect(new Set(draws.slice(0, 6).map((d) => d.d)).size).toBe(6);
    });
  });
});
