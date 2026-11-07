/**
 * Feedback motion of the rack: a moved faceplate settles onto its unit with a little overshoot, a cable swings
 * when an end moves, and either can be grabbed again mid-flight. Nothing runs while everything is at rest.
 */
import { onBeforeUnmount } from 'vue';
import { useStorage } from '@vueuse/core';

export interface Spring {
  value: number;
  velocity: number;
}

/** Stiff enough to feel immediate, damped a little under critical so a faceplate overshoots by a few px. */
export const SETTLE = { stiffness: 420, damping: 30 };
/** Softer and less damped: cables swing a moment longer than the faceplate they hang on. */
export const SWING = { stiffness: 140, damping: 8 };

/**
 * One step of a damped spring towards `target`. Returns whether it still moves; at rest it lands exactly on the
 * target, so a settled faceplate sits on whole pixels.
 */
export function stepSpring(spring: Spring, target: number, dt: number, stiffness = SETTLE.stiffness, damping = SETTLE.damping): boolean {
  spring.velocity += ((target - spring.value) * stiffness - spring.velocity * damping) * dt;
  spring.value += spring.velocity * dt;
  if (Math.abs(target - spring.value) < 0.25 && Math.abs(spring.velocity) < 0.5) {
    spring.value = target;
    spring.velocity = 0;
    return false;
  }
  return true;
}

/** A faceplate in motion: its springs and the seconds before it starts falling into place. */
export interface Faceplate {
  y: Spring;
  x: Spring;
  /** Seconds before it starts falling into place when the rack first fills */
  wait: number;
}

/**
 * One frame of a faceplate. `grab` is where a grabbed one goes (pointer height, sideways offset: 0 in the rack,
 * pulled aside outside it), or null. `snap` puts everything straight where it belongs (a hidden or busy page,
 * reduced motion). Returns whether it still moves.
 */
export function stepFaceplate(m: Faceplate, target: number, dt: number, snap: boolean, grab: { y: number; x: number } | null): boolean {
  if (snap) m.wait = 0;
  if (m.wait > 0) {
    m.wait -= dt;
    return true;
  }
  if (grab) {
    // A grabbed faceplate follows the pointer; pulled out of the rack it slides aside
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
  const movedY = stepSpring(m.y, target, dt);
  const movedX = stepSpring(m.x, 0, dt);
  return movedY || movedX;
}

/**
 * One frame of a cable's sag. A cable lags behind its moving ends (`pull`: their mean vertical speed): it hangs
 * deeper while they rise and bunches while they fall. Returns whether it still swings; at rest it lands on `rest`.
 */
export function stepSag(s: Spring, pull: number, dt: number, rest: number): boolean {
  s.velocity += ((rest - s.value) * SWING.stiffness - s.velocity * SWING.damping - pull * 5) * dt;
  s.value = Math.min(64, Math.max(3, s.value + s.velocity * dt));
  if (Math.abs(s.velocity) > 0.5 || Math.abs(s.value - rest) > 0.3) return true;
  s.value = rest;
  return false;
}

/**
 * Calls `tick` on every animation frame while it returns true; `kick()` starts it again after a change. The
 * time step is capped, so a tab that was in the background does not fling everything at once; `stalled` says
 * frames came far apart (a hidden or throttled page), where motion should jump to its end rather than crawl.
 */
export function useFrameLoop(tick: (dt: number, stalled: boolean) => boolean) {
  let frame = 0;
  let last = 0;
  function run(now: number) {
    const elapsed = Math.max(0, (now - last) / 1000);
    last = now;
    frame = tick(Math.min(0.034, elapsed), elapsed > 0.2) ? requestAnimationFrame(run) : 0;
  }
  let watchdog = 0;
  function kick() {
    if (frame) return;
    last = performance.now();
    frame = requestAnimationFrame(run);
    // A page that is not drawn gets no frames at all: settle at once instead of waiting for them
    window.clearTimeout(watchdog);
    watchdog = window.setTimeout(() => {
      if (!frame || performance.now() - last < 250) return;
      if (!tick(0, true)) stop();
    }, 300);
  }
  function stop() {
    cancelAnimationFrame(frame);
    window.clearTimeout(watchdog);
    frame = 0;
  }
  onBeforeUnmount(stop);
  return { kick, stop };
}

export type Vitality = 'off' | 'subtle' | 'lively';
export const prefersReducedMotion = (): boolean => Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);

/**
 * Ambient motion (breathing LEDs, the pulse on a selected cable): the same setting as the orbit map, so one
 * choice applies to both. Feedback motion (settling, swinging) only stops under reduced motion.
 */
export function useVitality() {
  const vitality = useStorage<Vitality>('gravityui.orbit.vitality', prefersReducedMotion() ? 'off' : 'subtle');
  function cycle() {
    const order: Vitality[] = ['off', 'subtle', 'lively'];
    vitality.value = order[(order.indexOf(vitality.value) + 1) % order.length];
  }
  return { vitality, cycle };
}
