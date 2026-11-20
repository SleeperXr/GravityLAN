import { describe, expect, it } from 'vitest';
import type { MacConflictGroup } from '@/types';
import {
  buildAdoptPayload,
  conflictsForDevice,
  groupSources,
  hasSharedDevices,
  macConflictGroupKey,
  sourceLabel,
} from './macConflicts';

const singleGroup: MacConflictGroup = {
  documented_mac: 'aa:bb:cc:dd:ee:01',
  observed_mac: 'aa:bb:cc:dd:ee:02',
  first_seen: '2026-11-20T08:00:00Z',
  last_seen: '2026-11-20T09:00:00Z',
  devices: [{ id: 10, ip: '192.168.1.10', name: 'nas', source: 'relay' }],
};

const sharedGroup: MacConflictGroup = {
  documented_mac: '11:22:33:44:55:01',
  observed_mac: '11:22:33:44:55:02',
  first_seen: '2026-11-20T08:00:00Z',
  last_seen: '2026-11-20T09:30:00Z',
  devices: [
    { id: 20, ip: '192.168.1.20', name: 'pihole', source: 'relay' },
    { id: 21, ip: '192.168.1.21', name: 'nginx', source: 'scan' },
  ],
};

describe('macConflicts helpers', () => {
  it('identifies single vs shared groups', () => {
    expect(hasSharedDevices(singleGroup)).toBe(false);
    expect(hasSharedDevices(sharedGroup)).toBe(true);
  });

  it('never enables apply_to_shared for single-device groups', () => {
    expect(buildAdoptPayload(singleGroup, true)).toEqual({
      mac: 'aa:bb:cc:dd:ee:02',
      apply_to_shared: false,
    });
    expect(buildAdoptPayload(sharedGroup, false)).toEqual({
      mac: '11:22:33:44:55:02',
      apply_to_shared: false,
    });
    expect(buildAdoptPayload(sharedGroup, true)).toEqual({
      mac: '11:22:33:44:55:02',
      apply_to_shared: true,
    });
  });

  it('finds all open conflicts for a given device', () => {
    expect(conflictsForDevice([singleGroup, sharedGroup], 21)).toEqual([
      { group: sharedGroup, device: sharedGroup.devices[1] },
    ]);
    expect(conflictsForDevice([singleGroup, sharedGroup], 999)).toEqual([]);
  });

  it('deduplicates group sources and formats labels with unknown fallback', () => {
    expect(groupSources(sharedGroup)).toEqual(['relay', 'scan']);
    expect(sourceLabel('relay')).not.toBe('relay');
    expect(sourceLabel('scan')).not.toBe('scan');
    expect(sourceLabel('future_probe')).toBe('future_probe');
    expect(macConflictGroupKey(singleGroup)).toBe('aa:bb:cc:dd:ee:01->aa:bb:cc:dd:ee:02');
  });
});
