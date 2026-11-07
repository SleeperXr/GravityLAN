/**
 * The faceplate and cable steps moved out of RackStage.vue's tick() behave exactly like the inline code did.
 * The inline code as of 0.7.0-rc.7 is copied here and run next to stepFaceplate / stepSag over seeded random
 * states: waiting faceplates, grabbed ones inside and outside the rack, snapping, settling springs, cable pulls.
 */
import { describe, expect, it } from 'vitest';
import { SWING, stepFaceplate, stepSag, stepSpring, type Faceplate, type Spring } from './rackMotion';

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const REST = 18;

/** One faceplate of the old tick loop; returns whether it moved */
function oldFaceplate(m: Faceplate, target: number, dt: number, snap: boolean, grab: { y: number; x: number } | null): boolean {
  if (snap) m.wait = 0;
  if (m.wait > 0) {
    m.wait -= dt;
    return true;
  }
  if (grab) {
    m.y.velocity = dt > 0 ? (grab.y - m.y.value) / dt : 0;
    m.y.value = grab.y;
    stepSpring(m.x, grab.x, dt);
    return true;
  }
  if (snap) {
    m.y = { value: target, velocity: 0 };
    m.x = { value: 0, velocity: 0 };
    return false;
  }
  let moving = false;
  if (stepSpring(m.y, target, dt)) moving = true;
  if (stepSpring(m.x, 0, dt)) moving = true;
  return moving;
}

function oldSag(s: Spring, pull: number, dt: number): boolean {
  s.velocity += ((REST - s.value) * SWING.stiffness - s.velocity * SWING.damping - pull * 5) * dt;
  s.value = clamp(s.value + s.velocity * dt, 3, 64);
  if (Math.abs(s.velocity) > 0.5 || Math.abs(s.value - REST) > 0.3) return true;
  s.value = REST;
  return false;
}

function rng(seed: number) {
  return () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
}

describe('rack motion steps match the inline tick code', () => {
  it('faceplates over 5000 random states, stepped a few frames each', () => {
    for (let seed = 1; seed <= 5000; seed++) {
      const r = rng(seed);
      const make = (): Faceplate => ({
        y: { value: r() * 800 - 50, velocity: r() * 400 - 200 },
        x: { value: r() * 40 - 30, velocity: r() * 100 - 50 },
        wait: r() < 0.3 ? r() * 0.2 : 0,
      });
      const a = make();
      const b: Faceplate = { y: { ...a.y }, x: { ...a.x }, wait: a.wait };
      const target = Math.round(r() * 700);
      const snap = r() < 0.15;
      const grab = r() < 0.25 ? { y: r() * 700, x: r() < 0.5 ? 0 : -22 } : null;
      for (let frame = 0; frame < 4; frame++) {
        const dt = [0, 1 / 120, 1 / 60, 1 / 30][Math.floor(r() * 4)];
        expect(stepFaceplate(b, target, dt, snap, grab), `seed ${seed}`).toBe(oldFaceplate(a, target, dt, snap, grab));
        expect(b).toEqual(a);
      }
    }
  });

  it('cable sags over 5000 random states', () => {
    for (let seed = 1; seed <= 5000; seed++) {
      const r = rng(seed);
      const a: Spring = { value: r() * 70, velocity: r() * 80 - 40 };
      const b: Spring = { ...a };
      for (let frame = 0; frame < 4; frame++) {
        const pull = r() < 0.4 ? 0 : r() * 3000 - 1500;
        const dt = [0, 1 / 120, 1 / 60, 1 / 30][Math.floor(r() * 4)];
        expect(stepSag(b, pull, dt, REST), `seed ${seed}`).toBe(oldSag(a, pull, dt));
        expect(b).toEqual(a);
      }
    }
  });
});
