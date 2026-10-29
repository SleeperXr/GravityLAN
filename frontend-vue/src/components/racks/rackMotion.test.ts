import { describe, expect, it } from 'vitest';
import { SETTLE, SWING, stepSpring, type Spring } from './rackMotion';

function settle(spring: Spring, target: number, stiffness = SETTLE.stiffness, damping = SETTLE.damping) {
  let steps = 0;
  let peak = spring.value;
  while (stepSpring(spring, target, 1 / 60, stiffness, damping) && steps < 600) {
    peak = Math.max(peak, spring.value);
    steps++;
  }
  return { steps, peak };
}

describe('springs', () => {
  it('settles a faceplate on its unit within a second, overshooting by a few px only', () => {
    const spring = { value: 0, velocity: 0 };
    const { steps, peak } = settle(spring, 100);
    expect(spring).toEqual({ value: 100, velocity: 0 });
    expect(steps).toBeLessThan(60);
    expect(peak).toBeGreaterThan(100);
    expect(peak).toBeLessThan(106);
  });

  it('can be grabbed mid-flight and sent somewhere else', () => {
    const spring = { value: 0, velocity: 0 };
    for (let i = 0; i < 5; i++) stepSpring(spring, 100, 1 / 60);
    expect(spring.velocity).toBeGreaterThan(0);
    settle(spring, -40);
    expect(spring.value).toBe(-40);
  });

  it('lets a cable swing longer than the faceplate it hangs on', () => {
    const plate = settle({ value: 0, velocity: 0 }, 20);
    const cable = settle({ value: 0, velocity: 0 }, 20, SWING.stiffness, SWING.damping);
    expect(cable.steps).toBeGreaterThan(plate.steps);
  });

  it('reports rest at once when there is nothing to do', () => {
    expect(stepSpring({ value: 5, velocity: 0 }, 5, 1 / 60)).toBe(false);
  });
});
