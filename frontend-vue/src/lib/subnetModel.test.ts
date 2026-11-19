import { describe, expect, it } from 'vitest';
import type { Device, DiscoveredHost } from '@/types';
import { countOnline } from './subnetModel';

const device = (ip: string, extra: Record<string, unknown> = {}) =>
  ({ id: Number(ip.split('.').pop()), ip, is_online: true, interfaces: [], ...extra }) as unknown as Device;
const host = (ip: string) => ({ ip, is_online: true }) as unknown as DiscoveredHost;

describe('countOnline', () => {
  it('counts only addresses of this /24, not of 192.168.10.x or 192.168.100.x', () => {
    const devices = [device('192.168.1.5'), device('192.168.10.5'), device('192.168.100.5')];
    const discovered = [host('192.168.1.9'), host('192.168.11.9')];
    expect(countOnline('192.168.1', devices, discovered)).toBe(2);
  });

  it('accepts a prefix that already ends with a dot', () => {
    expect(countOnline('192.168.1.', [device('192.168.1.5'), device('192.168.10.5')], [])).toBe(1);
  });

  it('counts online interfaces of a device in the subnet', () => {
    const multi = device('10.0.0.2', { interfaces: [{ ip: '192.168.1.7', is_online: true }, { ip: '192.168.12.7', is_online: true }] });
    expect(countOnline('192.168.1', [multi], [])).toBe(1);
  });
});
