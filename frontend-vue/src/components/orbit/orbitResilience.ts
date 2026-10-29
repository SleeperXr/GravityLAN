/**
 * Redundancy on the orbit map, from the same records as the map itself (devices and topology links):
 *
 * - Failover (live): which backup links carry traffic right now, because a device lost its primary path
 *   to a star but is still reached over a backup link.
 * - Single points of failure (planning): which devices, if they failed, would cut others off from the
 *   stars, counting primary and backup links alike.
 *
 * Only the cabled network counts. VMs and containers (devices with a host) are not nodes of their own;
 * they depend on their host and everything their host depends on.
 */
import type { Device } from '@/types';
import { isBackupLink, type OrbitLink } from './orbitModel';

type Graph = Map<number, number[]>;

const isGuest = (d: Pick<Device, 'virtual_type' | 'parent_id'>): boolean => Boolean(d.virtual_type) || d.parent_id != null;

function buildGraph(devices: Device[], links: OrbitLink[], use: (l: OrbitLink) => boolean): Graph {
  const nodes = new Set(devices.filter((d) => !isGuest(d)).map((d) => d.id));
  const graph: Graph = new Map([...nodes].map((id) => [id, []]));
  for (const l of links) {
    if (!use(l) || l.source_id === l.target_id || !nodes.has(l.source_id) || !nodes.has(l.target_id)) continue;
    graph.get(l.source_id)!.push(l.target_id);
    graph.get(l.target_id)!.push(l.source_id);
  }
  return graph;
}

/** Devices reached from the stars, never entering `blocked` ones. */
function reach(graph: Graph, starIds: Iterable<number>, blocked: (id: number) => boolean = () => false): Set<number> {
  const seen = new Set<number>();
  const queue: number[] = [];
  for (const id of starIds) {
    if (graph.has(id) && !blocked(id)) {
      seen.add(id);
      queue.push(id);
    }
  }
  while (queue.length) {
    const cur = queue.shift()!;
    for (const next of graph.get(cur) ?? []) {
      if (!seen.has(next) && !blocked(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return seen;
}

export interface FailoverState {
  /** Backup links carrying traffic now: a device behind them lost its primary path but is still reached */
  activeBackupIds: Set<number>;
  /** Online devices no path reaches any more (primary or backup) */
  cutOffIds: Set<number>;
}

/** The live picture: offline devices are gone, primary paths first, backups only where they are needed. */
export function failoverState(devices: Device[], links: OrbitLink[], starIds: Iterable<number>): FailoverState {
  const online = new Set(devices.filter((d) => d.is_online).map((d) => d.id));
  const down = (id: number) => !online.has(id);
  const stars = [...starIds];
  const viaPrimary = reach(buildGraph(devices, links, (l) => !isBackupLink(l)), stars, down);
  const viaAll = reach(buildGraph(devices, links, () => true), stars, down);
  const rescued = (id: number) => viaAll.has(id) && !viaPrimary.has(id);

  const activeBackupIds = new Set<number>();
  for (const l of links) {
    if (isBackupLink(l) && online.has(l.source_id) && online.has(l.target_id) && (rescued(l.source_id) || rescued(l.target_id))) {
      activeBackupIds.add(l.id);
    }
  }
  const cutOffIds = new Set(devices.filter((d) => !isGuest(d) && d.is_online && !viaAll.has(d.id)).map((d) => d.id));
  return { activeBackupIds, cutOffIds };
}

export interface SinglePoint {
  id: number;
  /** Devices (guests of cut-off hosts included) that lose every path to the stars if this one fails */
  cutOff: number[];
}

export interface Resilience {
  /** Devices whose failure cuts others off, the biggest impact first */
  singlePoints: SinglePoint[];
  /** Per device: the devices it hangs on alone (any one of them failing cuts it off), nearest first */
  dependsOn: Map<number, number[]>;
  /** Devices no link connects to a star at all */
  unconnectedIds: Set<number>;
}

/**
 * The planning picture, independent of who is online right now: remove one device at a time and see who
 * can no longer reach a star. Stars themselves are not counted; losing the core router is a given.
 */
export function analyseResilience(devices: Device[], links: OrbitLink[], starIds: Iterable<number>): Resilience {
  const stars = new Set(starIds);
  const graph = buildGraph(devices, links, () => true);
  const base = reach(graph, stars);
  const guestsOf = new Map<number, number[]>();
  const hostOf = (d: Device): number | null => (d.parent_id != null ? d.parent_id : null);
  for (const d of devices) {
    const host = hostOf(d);
    if (isGuest(d) && host != null) guestsOf.set(host, [...(guestsOf.get(host) ?? []), d.id]);
  }
  // A host's guests go down with it, and with their own guests (a container in a VM)
  const withGuests = (ids: number[]): number[] => {
    const out = [...ids];
    for (let i = 0; i < out.length; i++) out.push(...(guestsOf.get(out[i]) ?? []));
    return out;
  };

  const singlePoints: SinglePoint[] = [];
  const dependsOn = new Map<number, number[]>();
  for (const id of base) {
    if (stars.has(id) || (graph.get(id)?.length ?? 0) < 2) continue;
    const without = reach(graph, stars, (n) => n === id);
    const lost = [...base].filter((n) => n !== id && !without.has(n));
    if (!lost.length) continue;
    singlePoints.push({ id, cutOff: withGuests(lost) });
    for (const n of lost) dependsOn.set(n, [...(dependsOn.get(n) ?? []), id]);
  }
  singlePoints.sort((a, b) => b.cutOff.length - a.cutOff.length || a.id - b.id);

  // Nearest dependency first: the one cutting off the fewest devices sits closest to the device
  const impact = new Map(singlePoints.map((s) => [s.id, s.cutOff.length]));
  for (const [id, deps] of dependsOn) dependsOn.set(id, deps.sort((a, b) => (impact.get(a) ?? 0) - (impact.get(b) ?? 0)));
  // Guests hang on their host and on everything the host hangs on
  const byId = new Map(devices.map((d) => [d.id, d]));
  const guestDeps = (d: Device, seen = new Set<number>()): number[] => {
    const host = hostOf(d);
    if (host == null || seen.has(host) || !byId.has(host)) return [];
    seen.add(host);
    const hostDevice = byId.get(host)!;
    return [host, ...(isGuest(hostDevice) ? guestDeps(hostDevice, seen) : (dependsOn.get(host) ?? []))];
  };
  for (const d of devices) if (isGuest(d)) dependsOn.set(d.id, guestDeps(d));

  const unconnectedIds = new Set(devices.filter((d) => !isGuest(d) && !stars.has(d.id) && !base.has(d.id)).map((d) => d.id));
  return { singlePoints, dependsOn, unconnectedIds };
}
