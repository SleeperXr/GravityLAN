import type { Device } from '@/types';

/**
 * A client device (not watched 24/7: TV, PC, phone) that still answers on the network while
 * every service it offers is closed is asleep, not broken. Mirrors the backend's "standby"
 * health status, so notices do not report its closed ports as an outage.
 */
export function isClientStandby(device: Pick<Device, 'alert_offline' | 'services'>): boolean {
  return device.alert_offline === false && device.services.length > 0 && device.services.every((s) => !s.is_up);
}
