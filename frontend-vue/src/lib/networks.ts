import type { Device, Subnet } from '@/types';

import { useAppearance } from '@/stores/appearance';
import { useNetworkStore } from '@/stores/network';

/**
 * The line colour of a subnet, the same on the network map, line bullets, device chips and the
 * gateway list: the user's choice (Settings), else the palette slot by subnet id (--line-1..10,
 * which follows light/dark), else a slot hashed from the /24 around the address.
 */
const LINE_SLOTS = 10;

export function networkColor(subnetId: number | null | undefined, ip?: string | null): string {
  if (subnetId != null) {
    const custom = useAppearance().lineColors[String(subnetId)];
    if (custom) return custom;
    return `var(--line-${((Math.abs(subnetId) - 1 + LINE_SLOTS) % LINE_SLOTS) + 1})`;
  }
  const prefix = (ip || '').split('.').slice(0, 3).join('.');
  if (!prefix) return 'var(--gl-fg-subtle)';
  let hash = 0;
  for (let i = 0; i < prefix.length; i++) hash = (hash * 31 + prefix.charCodeAt(i)) >>> 0;
  return `var(--line-${(hash % LINE_SLOTS) + 1})`;
}

/** A line's sign text: the VLAN id, else the first letter of the subnet name. */
export function lineLabel(subnet: Pick<Subnet, 'vlan_id' | 'name'>): string {
  return subnet.vlan_id != null ? String(subnet.vlan_id) : (subnet.name.trim()[0] ?? '·').toUpperCase();
}

/** The sign of the line a device rides on; '·' when its subnet is unknown. */
export function lineLabelFor(subnetId: number | null | undefined): string {
  const subnet = subnetId == null ? undefined : useNetworkStore().subnets.find((s) => s.id === subnetId);
  return subnet ? lineLabel(subnet) : '·';
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
