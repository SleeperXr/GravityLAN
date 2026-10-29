import { describe, expect, it } from 'vitest';
import type { Device } from '@/types';
import { deviceEntry, type RackEntry } from './rackModel';
import { placeTargets, stepTarget } from './rackPlacement';

const dev = (id: number, rack_unit: number | null, rack_height = 1): RackEntry =>
  deviceEntry({ id, ip: `10.0.0.${id}`, rack_id: 1, rack_unit, rack_height, is_online: true } as Device, `Dev ${id}`);

describe('rackPlacement', () => {
  it('offers every free unit for a one-unit entry, top first', () => {
    const placed = [dev(1, 5), dev(2, 2)];
    expect(placeTargets(6, placed, dev(3, null))).toEqual([6, 4, 3, 1]);
  });

  it('offers only units where a taller entry fits downwards', () => {
    // Free: 6, 4, 3, 1. A 2U entry needs its top unit and the one below it free
    const placed = [dev(1, 5), dev(2, 2)];
    expect(placeTargets(6, placed, dev(3, null, 2))).toEqual([4]);
    expect(placeTargets(6, placed, dev(3, null, 3))).toEqual([]);
  });

  it('treats a device from another rack like any other entry', () => {
    const unracked = { ...dev(9, 7), unit: null };
    expect(placeTargets(3, [dev(1, 2)], unracked)).toEqual([3, 1]);
  });

  it('walks the targets with the arrow keys and stays put at the ends', () => {
    const targets = [6, 4, 3, 1];
    expect(stepTarget(targets, 6, 'down')).toBe(4);
    expect(stepTarget(targets, 4, 'up')).toBe(6);
    expect(stepTarget(targets, 1, 'down')).toBe(1);
    expect(stepTarget(targets, 6, 'up')).toBe(6);
    // From a unit that is no target, the nearest target in that direction
    expect(stepTarget(targets, 5, 'down')).toBe(4);
    expect(stepTarget(targets, 2, 'up')).toBe(3);
    expect(stepTarget([], 3, 'down')).toBeNull();
  });
});
