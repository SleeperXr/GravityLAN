import { describe, expect, it } from 'vitest';
import { busiestPrefix } from './subnetPick';

const subnets = [{ cidr: '192.168.50.0/24' }, { cidr: '192.168.1.0/24' }, { cidr: '10.0.0.0/24' }];

describe('busiestPrefix', () => {
  it('opens on the subnet with the most addresses in use, not the first one', () => {
    const devices = [{ ip: '192.168.1.10' }, { ip: '192.168.1.11' }, { ip: '10.0.0.5' }];
    expect(busiestPrefix(subnets, devices, [])).toBe('192.168.1');
  });

  it('counts interfaces and discovered hosts, each address once', () => {
    const devices = [{ ip: '192.168.1.10' }, { ip: '10.0.0.1', interfaces: [{ ip: '10.0.0.2' }] as never }];
    const discovered = [{ ip: '10.0.0.3' }, { ip: '192.168.1.10' }];
    expect(busiestPrefix(subnets, devices, discovered)).toBe('10.0.0');
  });

  it('does not count 10.0.10.x towards 10.0.1', () => {
    const devices = [{ ip: '10.0.10.4' }, { ip: '10.0.10.5' }, { ip: '10.0.1.9' }];
    expect(busiestPrefix([{ cidr: '10.0.1.0/24' }, { cidr: '10.0.10.0/24' }], devices, [])).toBe('10.0.10');
  });

  it('keeps the subnet order on a tie and when everything is empty', () => {
    expect(busiestPrefix(subnets, [], [])).toBe('192.168.50');
    expect(busiestPrefix(subnets, [{ ip: '192.168.1.2' }, { ip: '10.0.0.2' }], [])).toBe('192.168.1');
  });

  it('falls back to the first device without subnets, and to nothing at all', () => {
    expect(busiestPrefix([], [{ ip: '172.16.4.20' }], [])).toBe('172.16.4');
    expect(busiestPrefix([], [], [])).toBe('');
  });
});
