import { describe, expect, it } from 'vitest';
import type { Device, Service } from '@/types';
import { attentionDevices, deviceAttention, nameList, networkPulse } from './pulse';

const svc = (is_up: boolean) => ({ is_up }) as Service;
const dev = (extra: Partial<Device> = {}): Device => ({ is_online: true, alert_offline: true, services: [], ...extra }) as Device;

describe('deviceAttention', () => {
  it('reports watched devices that are offline', () => {
    expect(deviceAttention(dev({ is_online: false }))).toBe('offline');
  });

  it('leaves out offline devices that are not watched 24/7', () => {
    expect(deviceAttention(dev({ is_online: false, alert_offline: false }))).toBeNull();
  });

  it('reports online devices with a service down, but not clients in standby', () => {
    expect(deviceAttention(dev({ services: [svc(true), svc(false)] }))).toBe('degraded');
    expect(deviceAttention(dev({ alert_offline: false, services: [svc(false)] }))).toBeNull();
    expect(deviceAttention(dev({ services: [svc(true)] }))).toBeNull();
  });
});

describe('networkPulse', () => {
  it('counts what needs attention next to the online total', () => {
    const pulse = networkPulse([dev(), dev({ is_online: false }), dev({ services: [svc(false)] }), dev({ is_online: false, alert_offline: false })]);
    expect(pulse).toEqual({ total: 4, online: 2, offline: 1, degraded: 1 });
  });

  it('is empty for no devices', () => {
    expect(networkPulse([])).toEqual({ total: 0, online: 0, offline: 0, degraded: 0 });
  });
});

describe('attentionDevices', () => {
  it('lists offline and degraded devices in their original order', () => {
    const a = dev({ is_online: false, display_name: 'a' });
    const b = dev({ services: [svc(false)], display_name: 'b' });
    const c = dev({ is_online: false, display_name: 'c' });
    expect(attentionDevices([a, dev(), b, c])).toEqual({ offline: [a, c], degraded: [b] });
  });
});

describe('nameList', () => {
  it('names the first two and counts the rest', () => {
    expect(nameList(['NAS'])).toBe('NAS');
    expect(nameList(['NAS', 'Pi-hole'])).toBe('NAS, Pi-hole');
    expect(nameList(['NAS', 'Pi-hole', 'Printer', 'Proxmox'])).toBe('NAS, Pi-hole +2');
  });
});
