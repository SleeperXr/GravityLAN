/**
 * The orbit model gives the same answers as before its refactor.
 *
 * A frozen copy of resolveOrbitSystem (with its helpers), computeLightBeams, computeOrbitRings and
 * snapToOrbitRing as of 0.7.0-rc.7 runs next to the live functions over seeded random networks:
 * device kinds, roles, gateways, VM parents (missing, self, cycles), WLAN, standby clients,
 * interfaces, links (self, dangling, backup, WLAN, coloured), positions and drag targets.
 */
import { describe, expect, it, vi } from 'vitest';
import type { Device } from '@/types';
import { networkColor } from '@/lib/networks';
import { isClientStandby } from '@/lib/standby';
import { orbitCenterId } from './orbitLayout';
import {
  computeLightBeams,
  computeOrbitRings,
  resolveOrbitSystem,
  snapToOrbitRing,
  type BodyKind,
  type BodyState,
  type LightBeam,
  type OrbitBody,
  type OrbitLink,
  type OrbitRing,
  type OrbitRole,
  type OrbitRoles,
  type OrbitStyle,
  type Point,
} from './orbitModel';

vi.mock('@/lib/networks', () => ({
  networkColor: (subnetId: number | null | undefined, ip?: string) => `c-${subnetId ?? 'x'}-${(ip ?? '').split('.')[3] ?? ''}`,
}));

// --- frozen copy (0.7.0-rc.7) -------------------------------------------------------------

const old = (() => {
  const isBackupLink = (link: Pick<OrbitLink, 'role'>): boolean => link.role === 'backup';
  const DWARF_MAX_CHILDREN = 4;
  const ORBIT_SNAP_TOLERANCE = 18;

  function bodyState(device: Device): BodyState {
    if (!device.is_online) return 'offline';
    return device.services.some((s) => !s.is_up) && !isClientStandby(device) ? 'degraded' : 'online';
  }
  function isNetworkGear(device: Device): boolean {
    const dt = (device.device_type || '').toLowerCase();
    const sub = (device.device_subtype || '').toLowerCase();
    return device.is_ap || dt === 'switch' || dt === 'ap' || sub === 'switch' || sub === 'ap';
  }
  function isPlanetCandidate(device: Device, degree: number, hasVmChildren: boolean): boolean {
    const dt = (device.device_type || '').toLowerCase();
    const sub = (device.device_subtype || '').toLowerCase();
    if (device.is_ap || device.is_host || hasVmChildren) return true;
    if (dt === 'switch' || dt === 'ap' || sub === 'switch' || sub === 'ap') return true;
    return degree >= 2;
  }
  type Adjacency = Map<number, { neighborId: number; link: OrbitLink }[]>;
  interface RawParent {
    parentId: number | null;
    wireless: boolean;
    linkId: number | null;
    linkColor?: string | null;
  }
  function buildAdjacency(devices: Device[], links: OrbitLink[], byId: Map<number, Device>): Adjacency {
    const adj: Adjacency = new Map(devices.map((d) => [d.id, []]));
    for (const l of links) {
      if (isBackupLink(l) || !byId.has(l.source_id) || !byId.has(l.target_id) || l.source_id === l.target_id) continue;
      adj.get(l.source_id)!.push({ neighborId: l.target_id, link: l });
      adj.get(l.target_id)!.push({ neighborId: l.source_id, link: l });
    }
    return adj;
  }
  function findStars(devices: Device[], adj: Adjacency, gatewayIds: Set<number>, roles: OrbitRoles): Set<number> {
    const starIds = new Set<number>();
    for (const d of devices) {
      const role = roles[String(d.id)];
      if (role === 'star' || (!role && (gatewayIds.has(d.id) || (d.device_type || '').toLowerCase() === 'router'))) {
        starIds.add(d.id);
      }
    }
    if (starIds.size === 0 && devices.length > 0) {
      const sorted = [...devices].sort((a, b) => (adj.get(b.id)?.length ?? 0) - (adj.get(a.id)?.length ?? 0) || a.id - b.id);
      starIds.add(sorted[0].id);
    }
    return starIds;
  }
  function linkParents(devices: Device[], adj: Adjacency, starIds: Set<number>) {
    const visited = new Set<number>();
    const parents = new Map<number, { parentId: number; link: OrbitLink }>();
    const spread = (seeds: number[]) => {
      for (const id of seeds) visited.add(id);
      const queue = [...seeds];
      while (queue.length > 0) {
        const curr = queue.shift()!;
        for (const { neighborId, link } of adj.get(curr) ?? []) {
          if (visited.has(neighborId)) continue;
          visited.add(neighborId);
          parents.set(neighborId, { parentId: curr, link });
          queue.push(neighborId);
        }
      }
    };
    spread([...starIds]);
    for (const d of devices) {
      if (!visited.has(d.id) && (adj.get(d.id)?.length ?? 0) > 0) spread([d.id]);
    }
    return parents;
  }
  function breakCycles(devices: Device[], rawParents: Map<number, RawParent>, primaryStarId: number | null): void {
    for (const d of devices) {
      const seen = new Set<number>([d.id]);
      let curr = rawParents.get(d.id)?.parentId ?? null;
      while (curr != null) {
        if (seen.has(curr)) {
          rawParents.set(d.id, { parentId: primaryStarId !== d.id ? primaryStarId : null, wireless: false, linkId: null });
          break;
        }
        seen.add(curr);
        curr = rawParents.get(curr)?.parentId ?? null;
      }
    }
  }
  function classify(d: Device, isStar: boolean, role: OrbitRole | undefined, degree: number, children: number, hasVmChildren: boolean): { kind: BodyKind; dwarf: boolean } {
    if (isStar) return { kind: 'star', dwarf: false };
    const planet = role === 'planet' || role === 'dwarf' || children > 0 || (role !== 'moon' && isPlanetCandidate(d, degree, hasVmChildren));
    if (!planet) return { kind: 'moon', dwarf: false };
    const dwarf = role === 'dwarf' || (role === 'moon' && children > 0) || (!role && isNetworkGear(d) && children < DWARF_MAX_CHILDREN);
    return { kind: 'planet', dwarf };
  }

  function resolveOrbitSystem(devices: Device[], links: OrbitLink[], gatewayIds: Set<number>, roles: OrbitRoles = {}): Map<number, OrbitBody> {
    const byId = new Map(devices.map((d) => [d.id, d]));
    const adj = buildAdjacency(devices, links, byId);
    const vmParentIds = new Set(devices.filter((d) => d.parent_id != null && byId.has(d.parent_id)).map((d) => d.parent_id as number));
    const starIds = findStars(devices, adj, gatewayIds, roles);
    const bfsParent = linkParents(devices, adj, starIds);
    const aps = devices.filter((d) => d.is_ap || (d.device_type || '').toLowerCase() === 'ap');
    const primaryStarId = [...starIds][0] ?? null;
    const starForSubnet = (subnetId: number | null | undefined, selfId: number): number | null => {
      const others = [...starIds].filter((sid) => sid !== selfId);
      return others.find((sid) => subnetId != null && byId.get(sid)?.subnet_id === subnetId) ?? others[0] ?? null;
    };
    const parentOf = (d: Device): RawParent => {
      if (starIds.has(d.id)) return { parentId: null, wireless: false, linkId: null };
      if (d.parent_id != null && byId.has(d.parent_id) && d.parent_id !== d.id) {
        const explicitLink = (adj.get(d.id) ?? []).find((n) => n.neighborId === d.parent_id)?.link ?? null;
        return { parentId: d.parent_id, wireless: explicitLink?.link_type === 'WLAN', linkId: explicitLink?.id ?? null, linkColor: explicitLink?.color };
      }
      const bfs = bfsParent.get(d.id);
      if (bfs) {
        return { parentId: bfs.parentId, wireless: bfs.link.link_type === 'WLAN' || Boolean(d.is_wlan), linkId: bfs.link.id, linkColor: bfs.link.color };
      }
      if (d.is_wlan && !d.is_ap) {
        const ap = aps.find((a) => a.id !== d.id && a.subnet_id === d.subnet_id) ?? aps.find((a) => a.id !== d.id);
        if (ap) return { parentId: ap.id, wireless: true, linkId: null };
      }
      const fallbackStar = starForSubnet(d.subnet_id, d.id) ?? primaryStarId;
      return { parentId: fallbackStar && fallbackStar !== d.id ? fallbackStar : null, wireless: Boolean(d.is_wlan), linkId: null };
    };
    const rawParents = new Map(devices.map((d) => [d.id, parentOf(d)]));
    breakCycles(devices, rawParents, primaryStarId);
    const childCount = new Map<number, number>();
    for (const { parentId } of rawParents.values()) {
      if (parentId != null) childCount.set(parentId, (childCount.get(parentId) ?? 0) + 1);
    }
    const result = new Map<number, OrbitBody>();
    for (const d of devices) {
      const info = rawParents.get(d.id)!;
      const { kind, dwarf } = classify(d, starIds.has(d.id), roles[String(d.id)], adj.get(d.id)?.length ?? 0, childCount.get(d.id) ?? 0, vmParentIds.has(d.id));
      const state = bodyState(d);
      const ownColor = networkColor(d.subnet_id, d.ip);
      const primaryColor = info.linkColor || ownColor;
      result.set(d.id, {
        id: d.id, device: d, kind, dwarf, state, parentId: info.parentId,
        orbitStyle: state === 'offline' ? 'broken' : info.wireless ? 'dashed' : 'solid',
        color: primaryColor,
        rings: [...new Set([primaryColor, ownColor, ...(d.interfaces ?? []).map((i) => networkColor(i.subnet_id, i.ip))])],
        parentLinkId: info.linkId,
      });
    }
    return result;
  }

  function computeLightBeams(links: OrbitLink[], bodies: Map<number, OrbitBody>, typeColors: Record<string, string> = {}, activeBackupIds: ReadonlySet<number> = new Set()): LightBeam[] {
    const beams: LightBeam[] = [];
    for (const l of links) {
      const a = bodies.get(l.source_id);
      const b = bodies.get(l.target_id);
      if (!a || !b) continue;
      const isPrimaryBridge = (a.kind !== 'moon' && b.kind !== 'moon') || a.kind === 'star' || b.kind === 'star';
      const color = l.color || typeColors[l.link_type || '1GbE'] || (b.kind !== 'star' ? b.color : a.color);
      beams.push({
        id: l.id, sourceId: l.source_id, targetId: l.target_id, linkType: l.link_type || '1GbE', color,
        interrupted: !a.device.is_online || !b.device.is_online,
        isWireless: l.link_type === 'WLAN',
        isPrimaryBridge: isPrimaryBridge && !isBackupLink(l),
        isBackup: isBackupLink(l),
        failover: isBackupLink(l) && activeBackupIds.has(l.id),
      });
    }
    return beams;
  }

  function computeOrbitRings(bodies: Map<number, OrbitBody>, positions: Map<number, Point>, tolerance = ORBIT_SNAP_TOLERANCE): OrbitRing[] {
    const byParent = new Map<number, { body: OrbitBody; dist: number }[]>();
    for (const body of bodies.values()) {
      const centerId = orbitCenterId(body, bodies);
      if (centerId == null) continue;
      const pPos = positions.get(centerId);
      const cPos = positions.get(body.id);
      if (!pPos || !cPos) continue;
      const dist = Math.hypot(cPos.x - pPos.x, cPos.y - pPos.y);
      if (dist < 12) continue;
      if (!byParent.has(centerId)) byParent.set(centerId, []);
      byParent.get(centerId)!.push({ body, dist });
    }
    const rings: OrbitRing[] = [];
    for (const [centerId, children] of byParent.entries()) {
      const sorted = [...children].sort((a, b) => a.dist - b.dist);
      const clusters: { radius: number; members: OrbitBody[] }[] = [];
      for (const item of sorted) {
        const last = clusters[clusters.length - 1];
        if (last && Math.abs(item.dist - last.radius) <= tolerance) {
          last.members.push(item.body);
          last.radius = Math.round(
            last.members.reduce((sum, m) => {
              const p = positions.get(centerId)!;
              const c = positions.get(m.id)!;
              return sum + Math.hypot(c.x - p.x, c.y - p.y);
            }, 0) / last.members.length,
          );
        } else {
          clusters.push({ radius: Math.round(item.dist), members: [item.body] });
        }
      }
      clusters.forEach((cluster, idx) => {
        const hasOffline = cluster.members.every((m) => m.state === 'offline');
        const hasDashed = cluster.members.some((m) => m.orbitStyle === 'dashed');
        const style: OrbitStyle = hasOffline ? 'broken' : hasDashed ? 'dashed' : 'solid';
        const isTier = cluster.members.some((m) => m.kind !== 'moon');
        const dominantColor = isTier ? 'var(--gl-fg-subtle)' : (cluster.members[0]?.color ?? 'var(--gl-accent)');
        rings.push({ id: `ring-${centerId}-${idx}-${cluster.radius}`, centerId, radius: cluster.radius, color: dominantColor, style, memberIds: cluster.members.map((m) => m.id) });
      });
    }
    return rings;
  }

  function snapToOrbitRing(bodyId: number, candidatePos: Point, bodies: Map<number, OrbitBody>, positions: Map<number, Point>, tolerance = ORBIT_SNAP_TOLERANCE): Point {
    const body = bodies.get(bodyId);
    const centerId = body ? orbitCenterId(body, bodies) : null;
    if (!body || centerId == null) return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
    const center = positions.get(centerId);
    if (!center) return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
    const dx = candidatePos.x - center.x;
    const dy = candidatePos.y - center.y;
    const rawDist = Math.hypot(dx, dy);
    if (rawDist < 24) return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
    const angle = Math.atan2(dy, dx);
    let snappedRadius = rawDist;
    let bestDiff = tolerance + 1;
    for (const other of bodies.values()) {
      if (other.id === bodyId || orbitCenterId(other, bodies) !== centerId || (other.kind === 'moon') !== (body.kind === 'moon')) continue;
      const oPos = positions.get(other.id);
      if (!oPos) continue;
      const oDist = Math.hypot(oPos.x - center.x, oPos.y - center.y);
      const diff = Math.abs(rawDist - oDist);
      if (diff <= tolerance && diff < bestDiff) {
        bestDiff = diff;
        snappedRadius = oDist;
      }
    }
    return { x: Math.round(center.x + snappedRadius * Math.cos(angle)), y: Math.round(center.y + snappedRadius * Math.sin(angle)) };
  }

  return { resolveOrbitSystem, computeLightBeams, computeOrbitRings, snapToOrbitRing };
})();

// --- seeded random networks ---------------------------------------------------------------

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function scenario(seed: number) {
  const rnd = mulberry32(seed);
  const pick = <T,>(items: readonly T[]): T => items[Math.floor(rnd() * items.length)];
  const chance = (p: number) => rnd() < p;
  const count = 1 + Math.floor(rnd() * 14);
  const ids = Array.from({ length: count }, (_, i) => i + 1);

  const devices: Device[] = ids.map((id) => ({
    id,
    ip: `192.168.${pick([1, 2, 3])}.${id}`,
    device_type: pick(['server', 'router', 'Router', 'switch', 'ap', 'AP', 'nas', '', null] as const) as string,
    device_subtype: pick(['', 'switch', 'Switch', 'ap', 'x', null] as const) as string,
    is_ap: chance(0.15),
    is_host: chance(0.15),
    is_wlan: chance(0.3),
    is_online: chance(0.8),
    alert_offline: pick([true, false, undefined] as const),
    services: chance(0.5) ? [] : Array.from({ length: 1 + Math.floor(rnd() * 3) }, () => ({ is_up: chance(0.6) })),
    parent_id: chance(0.25) ? pick([...ids, 99, id]) : null,
    subnet_id: pick([1, 2, 3, null] as const),
    interfaces: chance(0.2) ? [{ subnet_id: pick([1, 2, 4]), ip: `10.0.${id}.1` }] : undefined,
  })) as unknown as Device[];

  const links: OrbitLink[] = Array.from({ length: Math.floor(rnd() * count * 1.6) }, (_, i) => ({
    id: 100 + i,
    source_id: pick([...ids, 77]),
    target_id: pick([...ids, 78]),
    link_type: pick(['1GbE', '10GbE', 'WLAN', 'Fiber', undefined, ''] as const),
    color: chance(0.25) ? pick(['#f00', '#0f0', '']) : null,
    role: pick([null, undefined, 'primary', 'backup', 'backup'] as const),
  })) as OrbitLink[];

  const gatewayIds = new Set(ids.filter(() => chance(0.15)));
  const roles: OrbitRoles = {};
  for (const id of ids) if (chance(0.2)) roles[String(id)] = pick(['star', 'planet', 'dwarf', 'moon'] as const);

  const positions = new Map<number, Point>(
    ids.filter(() => chance(0.9)).map((id) => [id, { x: Math.round((rnd() - 0.5) * 900), y: Math.round((rnd() - 0.5) * 900) }]),
  );
  const typeColors: Record<string, string> = chance(0.5) ? { '1GbE': '#111', WLAN: '#222' } : {};
  const activeBackupIds = new Set(links.filter(() => chance(0.3)).map((l) => l.id));
  const drags = Array.from({ length: 4 }, () => ({
    id: pick([...ids, 55]),
    pos: { x: (rnd() - 0.5) * 900, y: (rnd() - 0.5) * 900 },
    tolerance: pick([18, 40, 0]),
  }));
  return { devices, links, gatewayIds, roles, positions, typeColors, activeBackupIds, drags };
}

const plain = (bodies: Map<number, OrbitBody>) =>
  [...bodies.entries()].map(([id, b]) => [id, { ...b, device: b.device.id }]);

describe('orbit model refactor keeps every result', () => {
  it('matches the frozen model over 3000 random networks', () => {
    let bodiesChecked = 0;
    for (let seed = 1; seed <= 3000; seed++) {
      const s = scenario(seed);
      const before = old.resolveOrbitSystem(s.devices, s.links, s.gatewayIds, s.roles);
      const now = resolveOrbitSystem(s.devices, s.links, s.gatewayIds, s.roles);
      expect(plain(now), `seed ${seed}: bodies`).toEqual(plain(before));
      bodiesChecked += now.size;

      expect(computeLightBeams(s.links, now, s.typeColors, s.activeBackupIds), `seed ${seed}: beams`).toEqual(
        old.computeLightBeams(s.links, before, s.typeColors, s.activeBackupIds),
      );
      expect(computeOrbitRings(now, s.positions), `seed ${seed}: rings`).toEqual(old.computeOrbitRings(before, s.positions));
      expect(computeOrbitRings(now, s.positions, 60), `seed ${seed}: wide rings`).toEqual(old.computeOrbitRings(before, s.positions, 60));
      for (const d of s.drags) {
        expect(snapToOrbitRing(d.id, d.pos, now, s.positions, d.tolerance), `seed ${seed}: snap ${d.id}`).toEqual(
          old.snapToOrbitRing(d.id, d.pos, before, s.positions, d.tolerance),
        );
      }
    }
    expect(bodiesChecked).toBeGreaterThan(15000);
  });
});
