import { describe, expect, it } from 'vitest';
import { buildSlots, fitSlots, slotStatus } from './statusMonitor';

describe('slotStatus', () => {
  it('classifies full, partial, down and missing slots', () => {
    expect(slotStatus(100)).toBe('normal');
    expect(slotStatus(99)).toBe('normal');
    expect(slotStatus(40)).toBe('warning');
    expect(slotStatus(0)).toBe('error');
    expect(slotStatus(null)).toBe('empty');
    expect(slotStatus(-1)).toBe('empty');
  });

  it('honours a stricter threshold, as the agent strip uses', () => {
    expect(slotStatus(99.5, 100)).toBe('warning');
    expect(slotStatus(100, 100)).toBe('normal');
  });
});

describe('buildSlots', () => {
  it('splits the window ending now into equal slots, oldest first', () => {
    const end = new Date('2026-10-23T12:00:00Z');
    const slots = buildSlots([100, null, 0, -1], 24, end);
    expect(slots.map((s) => s.status)).toEqual(['normal', 'empty', 'error', 'empty']);
    expect(slots[0].start.toISOString()).toBe('2026-10-22T12:00:00.000Z');
    expect(slots[0].end.toISOString()).toBe('2026-10-22T18:00:00.000Z');
    expect(slots[3].end.toISOString()).toBe(end.toISOString());
    expect(slots[3].pct).toBeNull();
  });
});

describe('fitSlots', () => {
  it('keeps every slot when there is room and drops the oldest when there is not', () => {
    expect(fitSlots(24, 400)).toBe(24);
    expect(fitSlots(24, 54)).toBe(11);
    expect(fitSlots(24, 1)).toBe(1);
    expect(fitSlots(24, 0)).toBe(24);
  });
});
