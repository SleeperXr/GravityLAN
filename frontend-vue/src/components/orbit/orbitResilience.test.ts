import { describe, expect, it } from 'vitest';
import type { Device } from '@/types';
import type { OrbitLink } from './orbitModel';
import { analyseResilience, failoverState } from './orbitResilience';

const device = (id: number, extra: Partial<Device> = {}) =>
  ({ id, ip: `10.0.0.${id}`, is_online: true, virtual_type: null, parent_id: null, ...extra }) as Device;
const link = (id: number, source_id: number, target_id: number, role: 'primary' | 'backup' = 'primary') =>
  ({ id, source_id, target_id, link_type: 'Fiber', role }) as OrbitLink;

// Firewall 1 → core 2 → aggregation 3 → client 4; VM 5 runs on client 4
const devices = [device(1), device(2), device(3), device(4), device(5, { virtual_type: 'vm', parent_id: 4 })];
const chain = [link(10, 1, 2), link(11, 2, 3), link(12, 3, 4)];
const fallback = link(20, 1, 3, 'backup');

describe('analyseResilience', () => {
  it('finds every device that cuts others off, biggest impact first, guests included', () => {
    const { singlePoints, dependsOn } = analyseResilience(devices, chain, [1]);
    expect(singlePoints.map((s) => [s.id, [...s.cutOff].sort()])).toEqual([
      [2, [3, 4, 5]],
      [3, [4, 5]],
    ]);
    expect(dependsOn.get(4)).toEqual([3, 2]);
    expect(dependsOn.get(5)).toEqual([4, 3, 2]);
  });

  it('a backup path removes the single point it bypasses', () => {
    const { singlePoints, dependsOn } = analyseResilience(devices, [...chain, fallback], [1]);
    expect(singlePoints.map((s) => s.id)).toEqual([3]);
    expect(dependsOn.get(3)).toBeUndefined();
    expect(dependsOn.get(4)).toEqual([3]);
  });

  it('reports devices no link connects to a star', () => {
    const { unconnectedIds } = analyseResilience([...devices, device(6)], chain, [1]);
    expect([...unconnectedIds]).toEqual([6]);
  });
});

describe('failoverState', () => {
  it('leaves backups idle while the primary path works', () => {
    const state = failoverState(devices, [...chain, fallback], [1]);
    expect(state.activeBackupIds.size).toBe(0);
    expect(state.cutOffIds.size).toBe(0);
  });

  it('lights the backup up when the primary path fails', () => {
    const coreDown = devices.map((d) => (d.id === 2 ? { ...d, is_online: false } : d));
    const state = failoverState(coreDown, [...chain, fallback], [1]);
    expect([...state.activeBackupIds]).toEqual([20]);
    expect(state.cutOffIds.size).toBe(0);
  });

  it('lists online devices that nothing reaches any more', () => {
    const aggDown = devices.map((d) => (d.id === 3 ? { ...d, is_online: false } : d));
    const state = failoverState(aggDown, [...chain, fallback], [1]);
    expect([...state.cutOffIds]).toEqual([4]);
    // The backup ends at the failed device, so it cannot take over
    expect(state.activeBackupIds.size).toBe(0);
  });
});
