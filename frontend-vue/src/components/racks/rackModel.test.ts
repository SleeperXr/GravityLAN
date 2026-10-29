import { describe, expect, it } from 'vitest';
import type { Device, RackItem, RackPort } from '@/types';
import { cableRoute, cableDefaults, deviceEntry, fitsAt, itemEntry, occupiedUnits, ownerKeyOf, placementIssues, portsOf, portsOnSide, rackSlots, sideOf, spanOf, type RackEntry } from './rackModel';
import { isRackMountable, nearestFreeUnit, overlappingKeys, rackCandidates } from './rackModel';

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

  it('draws overlapping entries on their real units, in one row, without shifting the units below', () => {
    // Dev 1 covers 8 and 7, dev 2 sits on 7: one row from 8 down to 7 holds both
    const slots = rackSlots(10, [dev(1, 8, 2), dev(2, 7), dev(3, 5)]);
    expect(slots.map((s) => [s.unit, s.height, s.entries.map((e) => e.id)])).toEqual([
      [10, 1, []],
      [9, 1, []],
      [8, 2, [1, 2]],
      [6, 1, []],
      [5, 1, [3]],
      [4, 1, []],
      [3, 1, []],
      [2, 1, []],
      [1, 1, []],
    ]);
    // Every unit is drawn exactly once
    expect(slots.reduce((sum, s) => sum + s.height, 0)).toBe(10);
    // A chain of overlaps grows the row: 8-7, 7-6 and 6-5 make one row of four units
    expect(rackSlots(8, [dev(1, 8, 2), dev(2, 7, 2), dev(3, 6, 2)]).map((s) => [s.unit, s.height])).toEqual([[8, 4], [4, 1], [3, 1], [2, 1], [1, 1]]);
  });

  it('leaves out entries that start outside the rack and keeps a row inside it', () => {
    const slots = rackSlots(4, [dev(1, 9), dev(2, 1, 3)]);
    expect(slots.map((s) => [s.unit, s.height, s.entries.map((e) => e.id)])).toEqual([[4, 1, []], [3, 1, []], [2, 1, []], [1, 1, [2]]]);
  });

  it('counts a unit once, however many entries overlap on it', () => {
    expect(occupiedUnits([dev(1, 8, 2), dev(2, 7), dev(3, 5)])).toBe(3);
    // Units outside the rack do not count when the rack size is known
    expect(occupiedUnits([dev(1, 1, 3), dev(2, 12)], 10)).toBe(1);
  });

  it('names every entry that shares a unit with another', () => {
    expect([...overlappingKeys([dev(1, 8, 2), dev(2, 7), dev(3, 5), dev(4, null)])].sort()).toEqual(['device-1', 'device-2']);
    expect(overlappingKeys([dev(1, 8, 2), dev(2, 6)]).size).toBe(0);
  });

  it('finds the nearest free place for an entry, preferring the higher one on a tie', () => {
    const entries = [dev(1, 8, 2), dev(2, 7), dev(3, 5)];
    // Dev 2 overlaps dev 1; unit 6 is free and next to it
    expect(nearestFreeUnit(10, entries, entries[1])).toBe(6);
    // A 2 U entry from unit 7: nothing fits within two units; 10 and 4 are both three away, the higher wins
    expect(nearestFreeUnit(10, entries, dev(9, 7, 2))).toBe(10);
    // Without a unit it starts looking at the top
    expect(nearestFreeUnit(10, entries, dev(9, null))).toBe(10);
    // Nowhere to go
    expect(nearestFreeUnit(2, [dev(1, 2, 2)], dev(9, 2))).toBeNull();
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

describe('rack candidates', () => {
  const device = (id: number, extra: Partial<Device>): Device =>
    ({ id, device_type: 'unknown', device_subtype: 'Unknown', virtual_type: null, is_wlan: false, is_ap: false, is_host: false, ...extra }) as Device;
  const devices = [
    device(1, { device_type: 'server', device_subtype: 'Proxmox', is_host: true }),
    device(2, { device_type: 'firewall' }),
    device(3, { device_type: 'webui', is_wlan: true }), // smart speaker
    device(4, { is_wlan: true }), // phone
    device(5, { device_type: 'server', virtual_type: 'vm' }),
    device(6, { device_type: 'webui', virtual_type: 'docker' }),
    device(7, { device_type: 'webui', is_ap: true }),
    device(8, {}), // wired, unknown: could be anything, so it is offered
    device(9, { device_subtype: 'Switch', is_wlan: true }),
  ];

  it('offers rack gear and wired devices, not VMs, containers, access points or wireless clients', () => {
    expect(devices.filter(isRackMountable).map((d) => d.id)).toEqual([1, 2, 8, 9]);
    expect(rackCandidates(devices, false).map((d) => d.id)).toEqual([1, 2, 8, 9]);
  });

  it('offers every device when asked to show all', () => {
    expect(rackCandidates(devices, true)).toHaveLength(devices.length);
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
