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

/**
 * One row of the elevation: a free unit, or the units one entry covers. Entries that overlap share one row
 * that spans all of their units; each sits on its real units in its own column, so the rail numbers stay true.
 */
export interface RackSlot {
  /** Top unit of the row */
  unit: number;
  /** Units the row covers, downwards from `unit` */
  height: number;
  /** The first entry of the row; undefined for a free unit */
  entry?: RackEntry;
  /** Every entry of the row, top first; more than one when they overlap */
  entries: RackEntry[];
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

/** Device types that are built for a rack, as the scanner or the user names them. */
const RACK_TYPES = new Set(['firewall', 'router', 'switch', 'server', 'nas', 'ups', 'storage', 'patch']);

/**
 * Whether a network device is likely to sit in a rack: not a VM or container, not an access point and not a
 * wireless client (phones, tablets, speakers). Rack gear types and hosts always count.
 */
export function isRackMountable(device: Device): boolean {
  if (device.virtual_type) return false;
  const type = (device.device_type || '').toLowerCase();
  const subtype = (device.device_subtype || '').toLowerCase();
  if (device.is_host || RACK_TYPES.has(type) || RACK_TYPES.has(subtype)) return true;
  return !device.is_ap && !device.is_wlan;
}

/** The devices offered for a rack: those that look rack-mountable, or every one with `showAll`. */
export function rackCandidates(devices: Device[], showAll: boolean): Device[] {
  return showAll ? devices : devices.filter(isRackMountable);
}

/** The units a thing at `unit` covering `height` units downwards takes, top first. */
export const spanOf = (unit: number, height: number): number[] => Array.from({ length: height }, (_, i) => unit - i);

/**
 * The rows of the elevation, top first. A free unit is a row of its own; an entry takes a row as tall as it is.
 * Entries whose units overlap are grouped into one row, so no unit is drawn twice and none is left out.
 * Entries whose top unit is outside the rack are not drawn (they are placement issues).
 */
export function rackSlots(units: number, entries: RackEntry[]): RackSlot[] {
  const placed = entries
    .filter((e): e is RackEntry & { unit: number } => e.unit !== null && e.unit >= 1 && e.unit <= units)
    .sort((a, b) => b.unit - a.unit || a.key.localeCompare(b.key));
  const slots: RackSlot[] = [];
  let unit = units;
  let next = 0;
  while (unit >= 1) {
    if (next >= placed.length || placed[next].unit < unit) {
      slots.push({ unit, height: 1, entries: [] });
      unit -= 1;
      continue;
    }
    // Take every entry that starts within the row, growing the row while they reach further down
    const row: RackEntry[] = [];
    let bottom = unit;
    while (next < placed.length && placed[next].unit >= bottom) {
      const entry = placed[next];
      row.push(entry);
      bottom = Math.max(1, Math.min(bottom, entry.unit - entry.height + 1));
      next += 1;
    }
    slots.push({ unit, height: unit - bottom + 1, entry: row[0], entries: row });
    unit = bottom - 1;
  }
  return slots;
}

/** Keys of the entries that share at least one unit with another entry in the rack. */
export function overlappingKeys(entries: RackEntry[]): Set<string> {
  const keys = new Set<string>();
  const placed = entries.filter((e) => e.unit !== null);
  placed.forEach((a, i) => {
    const span = spanOf(a.unit!, a.height);
    for (const b of placed.slice(i + 1)) {
      if (spanOf(b.unit!, b.height).some((u) => span.includes(u))) {
        keys.add(a.key);
        keys.add(b.key);
      }
    }
  });
  return keys;
}

/**
 * Units taken by entries that sit in the rack (tray entries take none). A unit counts once, however many
 * entries overlap on it; with `units`, only units inside the rack count.
 */
export function occupiedUnits(entries: RackEntry[], units?: number): number {
  const taken = new Set<number>();
  for (const e of entries) {
    if (e.unit === null) continue;
    for (const u of spanOf(e.unit, e.height)) if (units === undefined || (u >= 1 && u <= units)) taken.add(u);
  }
  return taken.size;
}

/**
 * The free place nearest to where the entry is now (or the top of the rack while it has no unit), as its new
 * top unit; null when it fits nowhere. On a tie the higher place wins.
 */
export function nearestFreeUnit(units: number, entries: RackEntry[], entry: RackEntry): number | null {
  const from = entry.unit === null ? units : Math.min(units, Math.max(1, entry.unit));
  for (let distance = 0; distance < units; distance++) {
    for (const unit of [from + distance, from - distance]) {
      if (unit >= 1 && unit <= units && fitsAt(units, entries, unit, entry.height, entry.key)) return unit;
    }
  }
  return null;
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

export type PortSide = 'front' | 'rear';

/** Side of the rack a port sits on; ports without a side are on the front. */
export const sideOf = (port: RackPort): PortSide => (port.side === 'rear' ? 'rear' : 'front');

/** The ports of one entry that sit on the given side of the rack. */
export function portsOnSide(entry: RackEntry, ports: RackPort[], side: PortSide): RackPort[] {
  return portsOf(entry, ports).filter((p) => sideOf(p) === side);
}

/**
 * A cable as a route: it leaves its jack to the right, runs up or down the lane at laneX with rounded corners,
 * and comes back to the other jack. Cables in one lane do not cross the faceplates they are plugged into.
 */
export function cableRoute(a: { x: number; y: number }, b: { x: number; y: number }, laneX: number, radius = 6): string {
  if (a.y === b.y) return `M ${a.x} ${a.y} H ${b.x}`;
  const dir = b.y > a.y ? 1 : -1;
  const r = Math.min(radius, Math.abs(b.y - a.y) / 2);
  return `M ${a.x} ${a.y} H ${laneX - r} Q ${laneX} ${a.y} ${laneX} ${a.y + dir * r} V ${b.y - dir * r} Q ${laneX} ${b.y} ${laneX - r} ${b.y} H ${b.x}`;
}
