/**
 * freeOrbitSlot (moved out of OrbitMap.vue's assignOrbitToTarget) picks the same spot as the inline code did:
 * the sibling ring's radius (or the default for an empty orbit) at the free angle furthest from the siblings.
 */
import { describe, expect, it } from 'vitest';
import { freeOrbitSlot, type Point } from './orbitModel';

function oldSlot(tPos: Point, siblings: Point[], emptyRadius: number): Point {
  const radius = siblings.length ? Math.round(Math.hypot(siblings[0].x - tPos.x, siblings[0].y - tPos.y)) : emptyRadius;
  const taken = siblings.map((s) => Math.atan2(s.y - tPos.y, s.x - tPos.x));
  let best = -Math.PI / 2;
  let bestGap = -1;
  for (let k = 0; k < 24; k++) {
    const a = -Math.PI + (k * Math.PI) / 12;
    const gap = taken.length ? Math.min(...taken.map((x) => Math.abs(Math.atan2(Math.sin(a - x), Math.cos(a - x))))) : Math.PI;
    if (gap > bestGap) {
      bestGap = gap;
      best = a;
    }
  }
  return { x: Math.round(tPos.x + radius * Math.cos(best)), y: Math.round(tPos.y + radius * Math.sin(best)) };
}

function rng(seed: number) {
  return () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
}

describe('free orbit slot', () => {
  it('matches the inline code over 10000 random orbits', () => {
    for (let seed = 1; seed <= 10000; seed++) {
      const r = rng(seed);
      const center = { x: Math.round(r() * 2000 - 1000), y: Math.round(r() * 2000 - 1000) };
      const siblings = Array.from({ length: Math.floor(r() * 9) }, () => ({
        x: center.x + Math.round(r() * 400 - 200),
        y: center.y + Math.round(r() * 400 - 200),
      }));
      if (r() < 0.05 && siblings.length) siblings[0] = { ...center }; // a sibling sitting on the centre
      const emptyRadius = r() < 0.5 ? 140 : 90;
      expect(freeOrbitSlot(center, siblings, emptyRadius), `seed ${seed}`).toEqual(oldSlot(center, siblings, emptyRadius));
    }
  });
});
