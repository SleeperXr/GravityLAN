import { describe, expect, it } from 'vitest';
import { alignStations, octilinearPath, snapToNeighbours } from './netzplan';

const link = (source_id: number, target_id: number) => ({ source_id, target_id });

describe('netzplan straight lines', () => {
  it('draws a vertical link straight instead of a jog', () => {
    expect(octilinearPath(100, 0, 100, 200)).toBe('M100,0 L100,200');
  });

  it('puts linked stations a few pixels off on one axis, moving the less connected one', () => {
    // Core switch (id 2) has three links, the gateway (1) and Pi-hole (3) sit 9 and 14 px off its axis
    const pos = new Map([
      [1, { x: 409, y: 0 }],
      [2, { x: 400, y: 160 }],
      [3, { x: 414, y: 330 }],
      [4, { x: 900, y: 160 }],
    ]);
    const out = alignStations(pos, [link(1, 2), link(2, 3), link(2, 4)]);
    expect(out.get(1)).toEqual({ x: 400, y: 0 });
    expect(out.get(3)).toEqual({ x: 400, y: 330 });
    expect(out.get(2)).toEqual({ x: 400, y: 160 });
    // Far apart: a deliberate diagonal stays
    expect(out.get(4)).toEqual({ x: 900, y: 160 });
    // The input is left as it was
    expect(pos.get(1)).toEqual({ x: 409, y: 0 });
  });

  it('aligns a chain on one axis', () => {
    const out = alignStations(new Map([[1, { x: 0, y: 0 }], [2, { x: 10, y: 100 }], [3, { x: 18, y: 200 }]]), [link(1, 2), link(2, 3)]);
    expect(new Set([...out.values()].map((p) => p.x)).size).toBe(1);
  });

  it('drops a dragged station onto the nearest neighbour axis within reach', () => {
    expect(snapToNeighbours({ x: 412, y: 333 }, [{ x: 400, y: 160 }, { x: 700, y: 330 }])).toEqual({ x: 400, y: 330 });
    expect(snapToNeighbours({ x: 500, y: 250 }, [{ x: 400, y: 160 }])).toEqual({ x: 500, y: 250 });
  });
});
