/**
 * Rack layout, ported from the React UI (Topology/RackVisualizer.tsx). A device sits at
 * `rack_unit` (its top unit) and covers `rack_height` units downwards.
 */
import type { Device } from '@/types';

export interface RackSlot {
  unit: number;
  device?: Device;
}

export const heightOf = (d: Pick<Device, 'rack_height'>) => d.rack_height || 1;

/** Units a device covers, top first; empty when it has no position. */
export function unitsOf(d: Pick<Device, 'rack_unit' | 'rack_height'>): number[] {
  if (!d.rack_unit) return [];
  return Array.from({ length: heightOf(d) }, (_, i) => d.rack_unit! - i);
}

/** One slot per height unit, top unit first; units covered by a taller device above are left out. */
export function rackSlots(units: number, rackDevices: Device[]): RackSlot[] {
  const slots: RackSlot[] = [];
  for (let unit = units; unit >= 1; unit--) {
    const device = rackDevices.find((d) => d.rack_unit === unit);
    const isCovered = rackDevices.some((d) => d.rack_unit !== null && d.rack_unit > unit && d.rack_unit - heightOf(d) < unit);
    if (device || !isCovered) slots.push({ unit, device });
  }
  return slots;
}

export function occupiedUnits(rackDevices: Device[]): number {
  return rackDevices.reduce((sum, d) => sum + heightOf(d), 0);
}

/**
 * Devices that cannot be drawn where they are placed: no position, outside the rack, or sharing
 * a unit with another device. The editor is where they get fixed.
 */
export function placementIssues(units: number, rackDevices: Device[]): { device: Device; reason: 'no_position' | 'outside' | 'overlap' }[] {
  const issues: { device: Device; reason: 'no_position' | 'outside' | 'overlap' }[] = [];
  const owner = new Map<number, number>();
  const ordered = [...rackDevices].sort((a, b) => (b.rack_unit ?? 0) - (a.rack_unit ?? 0) || a.id - b.id);
  for (const device of ordered) {
    const covered = unitsOf(device);
    if (covered.length === 0) {
      issues.push({ device, reason: 'no_position' });
      continue;
    }
    if (covered.some((u) => u < 1 || u > units)) {
      issues.push({ device, reason: 'outside' });
      continue;
    }
    if (covered.some((u) => owner.has(u))) {
      issues.push({ device, reason: 'overlap' });
      continue;
    }
    covered.forEach((u) => owner.set(u, device.id));
  }
  return issues;
}
