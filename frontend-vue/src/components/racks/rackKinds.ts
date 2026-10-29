/** Kinds of rack equipment outside the network inventory, with their icon and sensible defaults. */
import { BatteryCharging, Box, Cable, Minus, Network, Phone, Rows3, Waves, type LucideIcon } from 'lucide-vue-next';

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
  { value: 'phone_system', icon: Phone, height: 1, ports: 8, portKind: 'RJ45' },
  { value: 'blank', icon: Minus, height: 1, ports: 0, portKind: 'RJ45' },
  { value: 'cable_management', icon: Rows3, height: 1, ports: 0, portKind: 'RJ45' },
  { value: 'other', icon: Box, height: 1, ports: 0, portKind: 'RJ45' },
];

export const kindOf = (value: string): RackKind => RACK_KINDS.find((k) => k.value === value) ?? RACK_KINDS[RACK_KINDS.length - 1];
