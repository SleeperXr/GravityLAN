import { describe, expect, it } from 'vitest';
import {
  computeFocusSet,
  easeInOutCubic,
  fitTransform,
  findPath,
  focusSetFromIds,
  matchBodies,
  zoomAround,
} from './orbitFocus';
import type { LightBeam, OrbitBody } from './orbitModel';

function body(id: number, parentId: number | null, ip = `10.0.0.${id}`): OrbitBody {
  return {
    id,
    parentId,
    kind: parentId == null ? 'star' : 'moon',
    device: { id, ip } as OrbitBody['device'],
  } as OrbitBody;
}

const bodies = new Map<number, OrbitBody>([
  [1, body(1, null)],
  [2, body(2, 1)],
  [3, body(3, 2)],
  [4, body(4, 2)],
  [5, body(5, 1)],
]);

const beams = [
  { id: 10, sourceId: 1, targetId: 2 },
  { id: 11, sourceId: 2, targetId: 3 },
  { id: 12, sourceId: 2, targetId: 4 },
  { id: 13, sourceId: 1, targetId: 5 },
] as LightBeam[];

describe('computeFocusSet', () => {
  it('contains the hub, its parent, its moons and their beams', () => {
    const { bodyIds, beamIds } = computeFocusSet(2, bodies, beams);
    expect([...bodyIds].sort()).toEqual([1, 2, 3, 4]);
    expect([...beamIds].sort()).toEqual([10, 11, 12]);
  });

  it('returns empty sets for an unknown id', () => {
    expect(computeFocusSet(99, bodies, beams).bodyIds.size).toBe(0);
  });
});

describe('focusSetFromIds', () => {
  it('only keeps beams between members', () => {
    const { beamIds } = focusSetFromIds([1, 2], beams);
    expect([...beamIds]).toEqual([10]);
  });
});

describe('matchBodies', () => {
  const label = (b: OrbitBody) => `dev-${b.id}`;
  it('matches label and ip case-insensitively', () => {
    expect(matchBodies('DEV-3', bodies.values(), label).map((b) => b.id)).toEqual([3]);
    expect(matchBodies('10.0.0.4', bodies.values(), label).map((b) => b.id)).toEqual([4]);
  });
  it('returns nothing for a blank query', () => {
    expect(matchBodies('  ', bodies.values(), label)).toEqual([]);
  });
});

describe('fitTransform', () => {
  it('centers a single point', () => {
    const v = fitTransform([{ x: 100, y: 100 }], 800, 600)!;
    expect(v.x + 100 * v.zoom).toBeCloseTo(400, 0);
    expect(v.y + 100 * v.zoom).toBeCloseTo(300, 0);
  });
  it('zooms out far enough to fit a wide system into a phone-sized map', () => {
    const v = fitTransform([{ x: -1200, y: 0 }, { x: 1200, y: 0 }], 340, 300)!;
    expect(v.zoom).toBeLessThan(0.22);
    expect(v.x + -1200 * v.zoom).toBeGreaterThanOrEqual(0);
    expect(v.x + 1200 * v.zoom).toBeLessThanOrEqual(340);
  });
  it('returns null without points or size', () => {
    expect(fitTransform([], 800, 600)).toBeNull();
    expect(fitTransform([{ x: 0, y: 0 }], 0, 600)).toBeNull();
  });
});

describe('zoomAround', () => {
  it('keeps the anchor fixed in world space', () => {
    const start = { x: 40, y: 20, zoom: 1 };
    const next = zoomAround(start, { x: 200, y: 100 }, 1.5);
    const worldBefore = (200 - start.x) / start.zoom;
    const worldAfter = (200 - next.x) / next.zoom;
    expect(worldAfter).toBeCloseTo(worldBefore, 5);
  });
  it('clamps to the zoom range', () => {
    expect(zoomAround({ x: 0, y: 0, zoom: 2.4 }, { x: 0, y: 0 }, 10).zoom).toBe(2.5);
  });
});

describe('easeInOutCubic', () => {
  it('is 0 at start, 1 at end', () => {
    expect(easeInOutCubic(0)).toBe(0);
    expect(easeInOutCubic(1)).toBe(1);
  });
});

describe('findPath', () => {
  const link = (id: number, sourceId: number, targetId: number, interrupted = false) =>
    ({ id, sourceId, targetId, interrupted }) as LightBeam;

  it('finds the shortest hop route in travel order', () => {
    const path = findPath(3, 5, beams)!;
    expect(path.bodyIds).toEqual([3, 2, 1, 5]);
    expect(path.beamIds).toEqual([11, 10, 13]);
    expect(path.broken).toBe(false);
  });

  it('returns a single node for identical endpoints', () => {
    expect(findPath(2, 2, beams)).toEqual({ bodyIds: [2], beamIds: [], broken: false });
  });

  it('prefers a healthy detour over an interrupted shortcut', () => {
    const graph = [link(1, 1, 2, true), link(2, 1, 3), link(3, 3, 2)];
    const path = findPath(1, 2, graph)!;
    expect(path.bodyIds).toEqual([1, 3, 2]);
    expect(path.broken).toBe(false);
  });

  it('falls back to a broken route when no healthy one exists', () => {
    const path = findPath(1, 2, [link(1, 1, 2, true)])!;
    expect(path.broken).toBe(true);
  });

  it('returns null for disconnected bodies', () => {
    expect(findPath(1, 99, beams)).toBeNull();
  });
});