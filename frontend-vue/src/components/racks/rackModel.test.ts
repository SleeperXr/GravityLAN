import { describe, expect, it } from 'vitest';
import type { Device, RackItem, RackPort } from '@/types';
import { cableRoute, cableDefaults, deviceEntry, fitsAt, itemEntry, occupiedUnits, ownerKeyOf, placementIssues, portsOf, portsOnSide, rackSlots, sideOf, spanOf, type RackEntry } from './rackModel';

const dev = (id: number, rack_unit: number | null, rack_height = 1): RackEntry =>
  deviceEntry({ id, ip: `10.0.0.${id}`, rack_id: 1, rack_unit, rack_height, is_online: true } as Device, `Dev ${id}`);

const item = (id: number, rack_unit: number | null, rack_height = 1): RackEntry =>
  itemEntry({ id, rack_id: 1, name: `Item ${id}`, kind: 'blank', rack_unit, rack_height, notes: null } as RackItem);

describe('rackModel', () => {
  it('covers the height downwards from the top unit', () => {
    expect(spanOf(10, 2)).toEqual([10, 9]);
    expect(dev(1, null).unit).toBeNull();
  });

  it('draws one slot per unit and leaves out units under a taller entry', () => {
    const slots = rackSlots(6, [dev(1, 5, 2), dev(2, 2)]);
    expect(slots.map((s) => [s.unit, s.entry?.id ?? null])).toEqual([[6, null], [5, 1], [3, null], [2, 2], [1, null]]);
    expect(occupiedUnits([dev(1, 5, 2), dev(2, 2), dev(3, null, 4)])).toBe(3);
  });

  it('reports entries without position, outside the rack, or on a taken unit', () => {
    const issues = placementIssues(10, [dev(1, 8, 2), dev(2, 7), dev(3, null), dev(4, 12), dev(5, 1, 2)]);
    expect(issues.map((i) => [i.entry.id, i.reason])).toEqual([[4, 'outside'], [2, 'overlap'], [5, 'outside'], [3, 'no_position']]);
    expect(placementIssues(10, [dev(1, 8, 2), dev(2, 6)])).toEqual([]);
  });

  it('fits only inside the rack and on units nothing else uses', () => {
    const entries = [dev(1, 5, 2), item(7, 2)];
    expect(fitsAt(6, entries, 3, 1)).toBe(true);
    expect(fitsAt(6, entries, 4, 1)).toBe(false);
    expect(fitsAt(6, entries, 6, 2)).toBe(false);
    expect(fitsAt(6, entries, 1, 2)).toBe(false);
    // An entry never blocks its own place
    expect(fitsAt(6, entries, 5, 2, 'device-1')).toBe(true);
  });

  it('keeps the ports of one entry in order and finds their owner', () => {
    const ports = [
      { id: 1, device_id: 3, rack_item_id: null, number: 2, kind: 'RJ45' },
      { id: 2, device_id: 3, rack_item_id: null, number: 1, kind: 'RJ45' },
      { id: 3, device_id: null, rack_item_id: 3, number: 1, kind: 'LC' },
    ] as RackPort[];
    expect(portsOf(dev(3, 1), ports).map((p) => p.id)).toEqual([2, 1]);
    expect(portsOf(item(3, 1), ports).map((p) => p.id)).toEqual([3]);
    expect(ownerKeyOf(ports[2])).toBe('item-3');
  });

  it('gives a new cable the usual type and colour of its port kind', () => {
    expect(cableDefaults('LC').cable).toBe('OM4 LC-LC');
    expect(cableDefaults('Unbekannt').cable).toBe('Kabel');
  });
});

describe('front and rear', () => {
  it('splits the ports of an entry by side', () => {
    const ports = [
      { id: 1, device_id: 3, rack_item_id: null, number: 1, kind: 'RJ45', side: 'front' },
      { id: 2, device_id: 3, rack_item_id: null, number: 2, kind: 'RJ45', side: 'rear' },
    ] as RackPort[];
    expect(portsOnSide(dev(3, 1), ports, 'rear').map((p) => p.id)).toEqual([2]);
    expect(sideOf({ side: undefined } as unknown as RackPort)).toBe('front');
  });

  it('draws a cable as a curve through its lane', () => {
    expect(cableRoute({ x: 10, y: 20 }, { x: 30, y: 40 }, 100)).toBe('M 10 20 H 94 Q 100 20 100 26 V 34 Q 100 40 94 40 H 30');
    expect(cableRoute({ x: 10, y: 20 }, { x: 30, y: 20 }, 100)).toBe('M 10 20 H 30');
  });
});
