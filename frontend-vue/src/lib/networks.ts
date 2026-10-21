import type { Device } from '@/types';

/**
 * One hue per subnet, the same on device chips, the gateway list and the interface tab.
 * Same assignment as the React UI (by subnet id, else by /24), but a palette without
 * violet, and green/red stay reserved for online/offline.
 */
const NETWORK_HUES = ['#2DD4BF', '#FB923C', '#F472B6', '#60A5FA', '#FACC15', '#22D3EE', '#F9A8D4', '#94A3B8'];

export function networkColor(subnetId: number | null | undefined, ip?: string | null): string {
  if (subnetId != null) return NETWORK_HUES[(Math.abs(subnetId) - 1 + NETWORK_HUES.length) % NETWORK_HUES.length];
  const prefix = (ip || '').split('.').slice(0, 3).join('.');
  if (!prefix) return 'var(--gl-fg-subtle)';
  let hash = 0;
  for (let i = 0; i < prefix.length; i++) hash = (hash * 31 + prefix.charCodeAt(i)) >>> 0;
  return NETWORK_HUES[hash % NETWORK_HUES.length];
}

export interface NetworkChip {
  ip: string;
  name: string | null;
  vlanId: number | null;
  label: string | null;
  isOnline: boolean;
  isPrimary: boolean;
  color: string;
  interfaceId: number | null;
}

/** The device's primary address followed by its further interfaces, one entry per network. */
export function deviceNetworks(device: Device): NetworkChip[] {
  const primary: NetworkChip = {
    ip: device.ip,
    name: device.subnet_name ?? null,
    vlanId: device.subnet_vlan_id ?? null,
    label: null,
    isOnline: device.is_online,
    isPrimary: true,
    color: networkColor(device.subnet_id, device.ip),
    interfaceId: null,
  };
  const others = (device.interfaces ?? []).map(
    (iface): NetworkChip => ({
      ip: iface.ip,
      name: iface.subnet_name,
      vlanId: iface.vlan_id,
      label: iface.label,
      isOnline: iface.is_online,
      isPrimary: false,
      color: networkColor(iface.subnet_id, iface.ip),
      interfaceId: iface.id,
    }),
  );
  return [primary, ...others];
}

/** "IoT", or the address when the network is not configured. */
export function chipName(chip: Pick<NetworkChip, 'name' | 'ip'>): string {
  return chip.name || chip.ip;
}

/** Name shown for a device everywhere: display name, then hostname, then address. */
export function deviceLabel(device: Pick<Device, 'display_name' | 'hostname' | 'ip'>): string {
  return device.display_name || device.hostname || device.ip;
}

/** Sort key for IPv4 addresses (10.0.0.9 before 10.0.0.10). */
export function ipSortKey(ip: string): number {
  const parts = ip.split('.').map((p) => parseInt(p, 10));
  if (parts.length !== 4 || parts.some(Number.isNaN)) return Number.MAX_SAFE_INTEGER;
  return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3];
}
