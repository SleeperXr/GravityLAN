import { describe, expect, it } from 'vitest';
import type { ScanProgress, SubnetInfo } from '@/types';
import { addCustomNetwork, scanPercent, stepState } from './setupModel';

const lan: SubnetInfo = { interface_name: 'eth0', ip_address: '192.168.1.5', subnet: '192.168.1.0/24', netmask: '255.255.255.0', is_up: true };

describe('setupModel', () => {
  it('marks passed, current, upcoming and a skipped scan step', () => {
    expect([0, 1, 2, 3].map((i) => stepState(i, 2))).toEqual(['done', 'done', 'current', 'todo']);
    expect(stepState(2, 3, 2)).toBe('skipped');
    expect(stepState(2, 2, 2)).toBe('current');
  });

  it('adds a routed network once, selected, and rejects anything wider than /16', () => {
    const added = addCustomNetwork([lan], [lan.subnet], '192.168.110.7/24');
    expect(added?.subnets.map((s) => s.subnet)).toEqual(['192.168.1.0/24', '192.168.110.0/24']);
    expect(added?.selected).toEqual(['192.168.1.0/24', '192.168.110.0/24']);
    expect(addCustomNetwork(added!.subnets, added!.selected, '192.168.110.0/24')).toEqual(added);
    expect(addCustomNetwork([lan], [], '10.0.0.0/8')).toBeNull();
    expect(addCustomNetwork([lan], [], 'kein netz')).toBeNull();
  });

  it('turns scan progress into a percentage, none before the host count is known', () => {
    expect(scanPercent(null)).toBeNull();
    expect(scanPercent({ hosts_scanned: 0, hosts_total: 0 } as ScanProgress)).toBeNull();
    expect(scanPercent({ hosts_scanned: 64, hosts_total: 254 } as ScanProgress)).toBe(25);
  });
});
