import { describe, expect, it } from 'vitest';
import type { Device } from '@/types';
import { occupiedUnits, placementIssues, rackSlots, unitsOf } from './rackModel';

const dev = (id: number, rack_unit: number | null, rack_height = 1) => ({ id, rack_id: 1, rack_unit, rack_height }) as Device;

describe('rackModel', () => {
  it('covers rack_height units downwards from rack_unit', () => {
    expect(unitsOf(dev(1, 10, 2))).toEqual([10, 9]);
    expect(unitsOf(dev(1, null))).toEqual([]);
  });

  it('draws one slot per unit and leaves out units under a taller device', () => {
    const slots = rackSlots(6, [dev(1, 5, 2), dev(2, 2)]);
    expect(slots.map((s) => [s.unit, s.device?.id ?? null])).toEqual([[6, null], [5, 1], [3, null], [2, 2], [1, null]]);
    expect(occupiedUnits([dev(1, 5, 2), dev(2, 2)])).toBe(3);
  });

  it('reports devices without position, outside the rack, or on a taken unit', () => {
    const issues = placementIssues(10, [dev(1, 8, 2), dev(2, 7), dev(3, null), dev(4, 12), dev(5, 1, 2)]);
    expect(issues.map((i) => [i.device.id, i.reason])).toEqual([
      [4, 'outside'], [2, 'overlap'], [5, 'outside'], [3, 'no_position'],
    ]);
    expect(placementIssues(10, [dev(1, 8, 2), dev(2, 6)])).toEqual([]);
  });
});
