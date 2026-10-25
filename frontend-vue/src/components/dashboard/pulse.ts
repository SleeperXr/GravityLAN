import type { Device } from '@/types';
import { isClientStandby } from '@/lib/standby';

/**
 * What a device needs from the operator, the same rule everywhere the overview counts problems:
 * offline only for devices watched 24/7, degraded for an online device with a service down
 * (not for a client in standby, whose closed ports mean it is asleep).
 */
export function deviceAttention(d: Pick<Device, 'is_online' | 'alert_offline' | 'services'>): 'offline' | 'degraded' | null {
  if (!d.is_online) return d.alert_offline !== false ? 'offline' : null;
  return !isClientStandby(d) && d.services.some((s) => !s.is_up) ? 'degraded' : null;
}

export interface NetworkPulse {
  total: number;
  online: number;
  offline: number;
  degraded: number;
}

/** The whole network in one line: online total and what needs attention. */
export function networkPulse(devices: Pick<Device, 'is_online' | 'alert_offline' | 'services'>[]): NetworkPulse {
  const pulse = { total: devices.length, online: 0, offline: 0, degraded: 0 };
  for (const d of devices) {
    if (d.is_online) pulse.online++;
    const attention = deviceAttention(d);
    if (attention) pulse[attention]++;
  }
  return pulse;
}

/** The devices behind the pulse counts, in list order: the status line names them and opens the first. */
export function attentionDevices<T extends Pick<Device, 'is_online' | 'alert_offline' | 'services'>>(devices: T[]): { offline: T[]; degraded: T[] } {
  return {
    offline: devices.filter((d) => deviceAttention(d) === 'offline'),
    degraded: devices.filter((d) => deviceAttention(d) === 'degraded'),
  };
}

/** Names spelled out in the status line before the rest is counted as "+n". */
const NAMED_DEVICES = 2;

/** "NAS, Pi-hole +2": the first names, then how many more. */
export function nameList(names: string[]): string {
  const shown = names.slice(0, NAMED_DEVICES).join(', ');
  return names.length > NAMED_DEVICES ? `${shown} +${names.length - NAMED_DEVICES}` : shown;
}
