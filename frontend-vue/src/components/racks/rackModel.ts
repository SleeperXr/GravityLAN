/**
 * Rack layout. A thing in a rack sits at `unit` (its top unit) and covers `height` units downwards.
 * Network devices and rack equipment (switches, UPS, patch panels, blanks, cable management) share one
 * layout, so one overlap rule, one set of placement issues and one drop check apply to both.
 */
import type { Device, RackItem, RackPort } from '@/types';

export type EntryKind = 'device' | 'item';

/** Anything that takes rack units, as the elevation draws it. `unit` is null while it sits in the tray. */
export interface RackEntry {
  key: string;
  kind: EntryKind;
  id: number;
  label: string;
  /** Second line in the elevation: the address of a device */
  detail: string;
  online: boolean;
  /** The kind of a rack item (switch_unmanaged, ups, blank, ...); null for devices */
  itemKind: string | null;
  unit: number | null;
  height: number;
}

export interface RackSlot {
  unit: number;
  entry?: RackEntry;
}

export type PlacementIssue = 'no_position' | 'outside' | 'overlap';

export const entryKey = (kind: EntryKind, id: number): string => `${kind}-${id}`;

export function deviceEntry(device: Device, label: string): RackEntry {
  return {
    key: entryKey('device', device.id),
    kind: 'device',
    id: device.id,
    label,
    detail: device.ip,
    online: device.is_online,
    itemKind: null,
    unit: device.rack_unit,
    height: device.rack_height || 1,
  };
}

export function itemEntry(item: RackItem): RackEntry {
  return {
    key: entryKey('item', item.id),
    kind: 'item',
    id: item.id,
    label: item.name,
    detail: '',
    online: true,
    itemKind: item.kind,
    unit: item.rack_unit,
    height: item.rack_height || 1,
  };
}

/** The units a thing at `unit` covering `height` units downwards takes, top first. */
export const spanOf = (unit: number, height: number): number[] => Array.from({ length: height }, (_, i) => unit - i);

/** One slot per unit, top first; units covered by a taller entry above are left out. */
export function rackSlots(units: number, entries: RackEntry[]): RackSlot[] {
  const slots: RackSlot[] = [];
  for (let unit = units; unit >= 1; unit--) {
    const entry = entries.find((e) => e.unit === unit);
    const covered = entries.some((e) => e.unit !== null && e.unit > unit && e.unit - e.height < unit);
    if (entry || !covered) slots.push({ unit, entry });
  }
  return slots;
}

/** Units taken by entries that sit in the rack (tray entries take none). */
export function occupiedUnits(entries: RackEntry[]): number {
  return entries.reduce((sum, e) => sum + (e.unit === null ? 0 : e.height), 0);
}

/** Whether an entry of `height` may have its top unit at `unit`: inside the rack, on units nothing else uses. */
export function fitsAt(units: number, entries: RackEntry[], unit: number, height: number, movingKey?: string): boolean {
  const span = spanOf(unit, height);
  if (Math.min(...span) < 1 || Math.max(...span) > units) return false;
  return entries.every((e) => e.key === movingKey || e.unit === null || !spanOf(e.unit, e.height).some((u) => span.includes(u)));
}

/**
 * Entries that cannot be drawn where they are placed: no position, outside the rack, or sharing a unit with
 * another entry. The first entry on a unit keeps it; the editor is where the others get fixed.
 */
export function placementIssues(units: number, entries: RackEntry[]): { entry: RackEntry; reason: PlacementIssue }[] {
  const issues: { entry: RackEntry; reason: PlacementIssue }[] = [];
  const taken = new Set<number>();
  const ordered = [...entries].sort((a, b) => (b.unit ?? 0) - (a.unit ?? 0) || a.key.localeCompare(b.key));
  for (const entry of ordered) {
    if (entry.unit === null) {
      issues.push({ entry, reason: 'no_position' });
      continue;
    }
    const span = spanOf(entry.unit, entry.height);
    if (Math.min(...span) < 1 || Math.max(...span) > units) {
      issues.push({ entry, reason: 'outside' });
      continue;
    }
    if (span.some((u) => taken.has(u))) {
      issues.push({ entry, reason: 'overlap' });
      continue;
    }
    span.forEach((u) => taken.add(u));
  }
  return issues;
}

/** Ports of one entry, in port order. */
export function portsOf(entry: RackEntry, ports: RackPort[]): RackPort[] {
  return ports
    .filter((p) => (entry.kind === 'device' ? p.device_id === entry.id : p.rack_item_id === entry.id))
    .sort((a, b) => a.number - b.number);
}

/** The entry a port belongs to, as its key. */
export function ownerKeyOf(port: RackPort): string {
  return port.device_id !== null ? entryKey('device', port.device_id) : entryKey('item', port.rack_item_id!);
}

/** Cable type and colour a new cable gets from the kind of its ports. */
const CABLE_DEFAULTS: Record<string, { cable: string; colour: string }> = {
  RJ45: { cable: 'Cat6', colour: '#2ec4a6' },
  SFP: { cable: 'DAC / Modul', colour: '#5aa9ff' },
  'SFP+': { cable: 'DAC / Modul', colour: '#5aa9ff' },
  LC: { cable: 'OM4 LC-LC', colour: '#ffb547' },
  Power: { cable: 'Stromkabel C13', colour: '#ff7eb6' },
  Console: { cable: 'Konsolenkabel', colour: '#c3cad4' },
};
const FALLBACK_CABLE = { cable: 'Kabel', colour: '#c3cad4' };

export const PORT_KINDS = ['RJ45', 'SFP', 'SFP+', 'LC', 'Power', 'Console'] as const;

export const cableDefaults = (portKind: string): { cable: string; colour: string } => CABLE_DEFAULTS[portKind] ?? FALLBACK_CABLE;
