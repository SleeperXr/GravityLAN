/** Kinds of rack equipment outside the network inventory, with their icon and sensible defaults. */
import { BatteryCharging, Box, Cable, Minus, Network, PlugZap, Rows3, Waves, type LucideIcon } from 'lucide-vue-next';
import type { Device } from '@/types';

export interface RackKind {
  value: string;
  icon: LucideIcon;
  height: number;
  ports: number;
  portKind: string;
}

export const RACK_KINDS: RackKind[] = [
  { value: 'switch_unmanaged', icon: Network, height: 1, ports: 8, portKind: 'RJ45' },
  { value: 'ups', icon: BatteryCharging, height: 2, ports: 4, portKind: 'Power' },
  { value: 'patch_copper', icon: Cable, height: 1, ports: 24, portKind: 'RJ45' },
  { value: 'patch_fiber', icon: Waves, height: 1, ports: 12, portKind: 'LC' },
  { value: 'power_strip', icon: PlugZap, height: 1, ports: 8, portKind: 'Power' },
  { value: 'blank', icon: Minus, height: 1, ports: 0, portKind: 'RJ45' },
  { value: 'cable_management', icon: Rows3, height: 1, ports: 0, portKind: 'RJ45' },
  { value: 'other', icon: Box, height: 1, ports: 0, portKind: 'RJ45' },
];

export const kindOf = (value: string): RackKind => RACK_KINDS.find((k) => k.value === value) ?? RACK_KINDS[RACK_KINDS.length - 1];

/** The hardware a faceplate is drawn as, at the front and at the rear. */
export type FaceKind = 'switch' | 'router' | 'server' | 'storage' | 'ups' | 'power' | 'patch' | 'fiber' | 'phone' | 'blank' | 'cable' | 'generic';

const ITEM_FACES: Record<string, FaceKind> = {
  switch_unmanaged: 'switch',
  ups: 'ups',
  patch_copper: 'patch',
  patch_fiber: 'fiber',
  power_strip: 'power',
  blank: 'blank',
  cable_management: 'cable',
};

export const faceOfItem = (kind: string): FaceKind => ITEM_FACES[kind] ?? 'generic';

/**
 * A network device looks like what its type says; a hypervisor host is a server whatever its type. A phone
 * system has an IP, so it comes in as a device (the scanner calls it "Phone System") rather than as rack equipment.
 */
export function faceOfDevice(device: Pick<Device, 'device_type' | 'device_subtype' | 'is_host'>): FaceKind {
  const type = `${device.device_type ?? ''} ${device.device_subtype ?? ''}`.toLowerCase();
  if (/phone|pbx|voip|telefon|3cx|starface/.test(type)) return 'phone';
  if (type.includes('switch')) return 'switch';
  if (/firewall|router|gateway/.test(type)) return 'router';
  if (/\bnas\b|storage/.test(type)) return 'storage';
  if (/\bups\b|\busv\b/.test(type)) return 'ups';
  if (device.is_host || /server|hypervisor/.test(type)) return 'server';
  return 'generic';
}
