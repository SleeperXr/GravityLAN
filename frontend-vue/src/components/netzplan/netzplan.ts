/**
 * The network map ("Liniennetzplan"): devices are stations, saved topology links are line
 * segments. Positions and links are the same records the React topology editor uses
 * (device.topology_x/y, /api/topology/links), so both UIs show one plan.
 */
import type { Device, TopologyLink } from '@/types';
import { networkColor } from '@/lib/networks';

/** The link record as the backend stores it; the shared React type leaves out colour and notes. */
export type PlanLink = TopologyLink & { color?: string | null; speed?: number | null; notes?: string | null };

export const LINK_TYPES = ['10GbE', '2.5GbE', '1GbE', 'WLAN', 'Fiber'] as const;

export type StationState = 'online' | 'degraded' | 'offline';

export interface StationData {
  device: Device;
  state: StationState;
  /** gateway of a subnet, or a device answering in several networks */
  interchange: boolean;
  /** line colours meeting at this station, for the interchange capsule */
  lines: string[];
  editable: boolean;
}

export function stationState(device: Device): StationState {
  if (!device.is_online) return 'offline';
  return device.services.some((s) => !s.is_up) ? 'degraded' : 'online';
}

/** Colour of a link: the user's colour, else its line's palette slot, else its network's colour. */
export function linkColor(link: PlanLink, source?: Device, target?: Device, slot?: number): string {
  if (link.color) return link.color;
  if (slot !== undefined) return `var(--line-${(slot % 10) + 1})`;
  const subnet = target?.subnet_id ?? source?.subnet_id ?? null;
  return networkColor(subnet, target?.ip ?? source?.ip);
}

/**
 * Lines of the map: every link leaving the core (a gateway, else the best-connected station)
 * starts its own line, and the links further out inherit it. Returns link id -> palette slot,
 * so a plain cabling tree reads as several coloured lines instead of one.
 */
export function lineSlots(links: PlanLink[], coreIds: Set<number>): Map<number, number> {
  const adjacency = new Map<number, PlanLink[]>();
  for (const l of links) {
    for (const end of [l.source_id, l.target_id]) {
      if (!adjacency.has(end)) adjacency.set(end, []);
      adjacency.get(end)!.push(l);
    }
  }
  const byDegree = [...adjacency.keys()].sort((a, b) => adjacency.get(b)!.length - adjacency.get(a)!.length);
  const roots = [...coreIds].filter((id) => adjacency.has(id));
  if (roots.length === 0 && byDegree[0] !== undefined) roots.push(byDegree[0]);

  const slots = new Map<number, number>();
  const visited = new Set<number>(roots);
  let next = 0;
  const queue: { node: number; slot: number | null }[] = roots.map((node) => ({ node, slot: null }));
  while (queue.length) {
    const { node, slot } = queue.shift()!;
    // Hubs (switches: three or more links) fan out into separate lines, like a transit interchange
    const isHub = (adjacency.get(node)?.length ?? 0) >= 3;
    for (const l of adjacency.get(node) ?? []) {
      if (slots.has(l.id)) continue;
      const other = l.source_id === node ? l.target_id : l.source_id;
      // A branch off a core station or a hub opens a new line; further out the line continues
      const own = slot === null || isHub ? next++ : slot;
      slots.set(l.id, own);
      if (!visited.has(other)) {
        visited.add(other);
        queue.push({ node: other, slot: own });
      }
    }
  }
  // Islands without a path to the core still get a line each
  for (const l of links) if (!slots.has(l.id)) slots.set(l.id, next++);
  return slots;
}

/**
 * Octilinear route like a transit map: straight along the longer axis, one 45° diagonal to
 * cover the shorter one, then straight again, with rounded joins from the stroke.
 */
export function octilinearPath(sx: number, sy: number, tx: number, ty: number): string {
  const dx = tx - sx;
  const dy = ty - sy;
  const ax = Math.abs(dx);
  const ay = Math.abs(dy);
  if (ax < 1 || ay < 1) return `M${sx},${sy} L${tx},${ty}`;
  const diag = Math.min(ax, ay);
  const sxn = Math.sign(dx);
  const syn = Math.sign(dy);
  if (ax >= ay) {
    const run = (ax - diag) / 2;
    const x1 = sx + sxn * run;
    const x2 = x1 + sxn * diag;
    return `M${sx},${sy} L${x1},${sy} L${x2},${ty} L${tx},${ty}`;
  }
  const run = (ay - diag) / 2;
  const y1 = sy + syn * run;
  const y2 = y1 + syn * diag;
  return `M${sx},${sy} L${sx},${y1} L${tx},${y2} L${tx},${ty}`;
}

type Point = { x: number; y: number };

/** How far apart two linked stations may sit and still be drawn on one straight axis. */
export const ALIGN_TOLERANCE = 24;

/**
 * Straight lines stay straight: two linked stations whose x (or y) differ by at most the
 * tolerance are put on one axis. The station with fewer links moves, so hubs stay put.
 * Display only; the saved positions are untouched.
 */
export function alignStations(positions: Map<number, Point>, links: Pick<TopologyLink, 'source_id' | 'target_id'>[], tolerance = ALIGN_TOLERANCE): Map<number, Point> {
  const out = new Map([...positions].map(([id, p]) => [id, { ...p }]));
  const degree = new Map<number, number>();
  for (const l of links) {
    degree.set(l.source_id, (degree.get(l.source_id) ?? 0) + 1);
    degree.set(l.target_id, (degree.get(l.target_id) ?? 0) + 1);
  }
  // Two passes, so a chain A–B–C settles on one axis even when B moved in the first
  for (let pass = 0; pass < 2; pass++) {
    for (const l of links) {
      const a = out.get(l.source_id);
      const b = out.get(l.target_id);
      if (!a || !b) continue;
      const bMoves = (degree.get(l.target_id) ?? 0) <= (degree.get(l.source_id) ?? 0);
      const [anchor, mover] = bMoves ? [a, b] : [b, a];
      if (mover.x !== anchor.x && Math.abs(mover.x - anchor.x) <= tolerance) mover.x = anchor.x;
      if (mover.y !== anchor.y && Math.abs(mover.y - anchor.y) <= tolerance) mover.y = anchor.y;
    }
  }
  return out;
}

/** Where a dropped station lands: on the x/y axis of its nearest linked neighbour, if close enough. */
export function snapToNeighbours(pos: Point, neighbours: Point[], tolerance = ALIGN_TOLERANCE): Point {
  const nearest = (axis: 'x' | 'y') =>
    neighbours.map((n) => n[axis]).filter((v) => Math.abs(v - pos[axis]) <= tolerance).sort((p, q) => Math.abs(p - pos[axis]) - Math.abs(q - pos[axis]))[0];
  return { x: nearest('x') ?? pos.x, y: nearest('y') ?? pos.y };
}

/**
 * Positions for devices that were never placed: one row per network, the gateway of that
 * network at the row's start, members spaced along it in address order.
 */
export function autoLayout(devices: Device[], gatewayIds: Set<number>): Map<number, { x: number; y: number }> {
  const bySubnet = new Map<string, Device[]>();
  for (const d of devices) {
    const key = String(d.subnet_id ?? 'none');
    if (!bySubnet.has(key)) bySubnet.set(key, []);
    bySubnet.get(key)!.push(d);
  }
  const positions = new Map<number, { x: number; y: number }>();
  let row = 0;
  for (const members of bySubnet.values()) {
    const sorted = [...members].sort((a, b) => {
      const ga = gatewayIds.has(a.id) ? 0 : 1;
      const gb = gatewayIds.has(b.id) ? 0 : 1;
      return ga - gb || ipNumber(a.ip) - ipNumber(b.ip);
    });
    sorted.forEach((d, i) => positions.set(d.id, { x: 80 + i * 170, y: 80 + row * 190 + (i % 2) * 40 }));
    row++;
  }
  return positions;
}

function ipNumber(ip: string): number {
  return ip.split('.').reduce((acc, part) => acc * 256 + (parseInt(part, 10) || 0), 0);
}
