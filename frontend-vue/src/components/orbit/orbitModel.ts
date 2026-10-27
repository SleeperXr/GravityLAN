/**
 * Gravitational network map ("Orbit"):
 * - Stars: Gateways / routers at the center of gravity
 * - Planets: Switches, Access Points, and Hypervisor Hosts orbiting the Star and linked via Light Beams
 * - Moons: Wired endpoints (solid orbit), WLAN devices (dashed orbit), and VMs/Containers around their Host
 *
 * Positions remain stored in device.topology_x / device.topology_y and links in /api/topology/links,
 * preserving full compatibility with the React topology view.
 */
import type { Device, TopologyLink } from '@/types';
import { networkColor } from '@/lib/networks';
import { isClientStandby } from '@/lib/standby';
import { layoutOrbit, orbitCenterId } from './orbitLayout';

export type OrbitLink = TopologyLink & {
  color?: string | null;
  speed?: number | null;
  notes?: string | null;
};

export const LINK_TYPES = ['10GbE', '2.5GbE', '1GbE', '100Mb', 'WLAN', 'Fiber'] as const;

/** Types offered for a link: the known ones, plus its own type if that is none of them (older or imported data). */
export function linkTypeOptions(current: string | null | undefined): string[] {
  return current && !(LINK_TYPES as readonly string[]).includes(current) ? [...LINK_TYPES, current] : [...LINK_TYPES];
}

/** Links ending at a device: what its ports carry on the map. */
export function linkCount(deviceId: number, links: Pick<OrbitLink, 'source_id' | 'target_id'>[]): number {
  return links.filter((l) => l.source_id === deviceId || l.target_id === deviceId).length;
}

/** True when one more link would exceed the device's `max_ports`; 0 or empty means no limit. */
export function portLimitReached(device: Pick<Device, 'id' | 'max_ports'>, links: Pick<OrbitLink, 'source_id' | 'target_id'>[]): boolean {
  const max = device.max_ports ?? 0;
  return max > 0 && linkCount(device.id, links) >= max;
}

export type BodyKind = 'star' | 'planet' | 'moon';
/** What the user can pick: a dwarf planet is a small planet (a switch or AP with few devices). */
export type OrbitRole = 'star' | 'planet' | 'dwarf' | 'moon';
/** Chosen roles per device id (setting `ui.orbit_roles`); a missing id means automatic. */
export type OrbitRoles = Record<string, OrbitRole>;

/** Switches and APs carrying fewer devices than this are dwarf planets unless chosen otherwise. */
export const DWARF_MAX_CHILDREN = 4;
export type BodyState = 'online' | 'degraded' | 'offline';
export type OrbitStyle = 'solid' | 'dashed' | 'broken';

export interface Point {
  x: number;
  y: number;
}

export interface OrbitBody {
  id: number;
  device: Device;
  kind: BodyKind;
  /** A planet drawn small (dwarf planet) */
  dwarf: boolean;
  state: BodyState;
  parentId: number | null;
  orbitStyle: OrbitStyle;
  /** Primary network color for this body and its orbit track */
  color: string;
  /** Additional network colors if multi-homed */
  rings: string[];
  /** Explicit link connecting this body to its orbit parent, if any */
  parentLinkId: number | null;
}

export interface OrbitRing {
  id: string;
  centerId: number;
  radius: number;
  color: string;
  style: OrbitStyle;
  memberIds: number[];
}

export interface LightBeam {
  id: number;
  sourceId: number;
  targetId: number;
  linkType: string;
  color: string;
  interrupted: boolean;
  isWireless: boolean;
  isPrimaryBridge: boolean;
}

/** Radius tolerance (px) for snapping sibling moons onto a shared concentric orbit ring. */
export const ORBIT_SNAP_TOLERANCE = 18;

/** Distance (px) within which dropping a dragged body onto a Planet/Star reassigns its orbit parent. */
export const DROP_TARGET_RADIUS = 46;

export function bodyState(device: Device): BodyState {
  if (!device.is_online) return 'offline';
  // A client in standby answers but has every port closed: asleep, not degraded
  return device.services.some((s) => !s.is_up) && !isClientStandby(device) ? 'degraded' : 'online';
}

/** Switches and access points: network gear that is a dwarf planet while it carries few devices. */
export function isNetworkGear(device: Device): boolean {
  const dt = (device.device_type || '').toLowerCase();
  const sub = (device.device_subtype || '').toLowerCase();
  return device.is_ap || dt === 'switch' || dt === 'ap' || sub === 'switch' || sub === 'ap';
}

/** The role shown and offered to the user for a resolved body. */
export function roleOf(body: OrbitBody): OrbitRole {
  return body.kind === 'planet' && body.dwarf ? 'dwarf' : body.kind;
}

export function isPlanetCandidate(device: Device, degree: number, hasVmChildren: boolean): boolean {
  const dt = (device.device_type || '').toLowerCase();
  const sub = (device.device_subtype || '').toLowerCase();
  if (device.is_ap || device.is_host || hasVmChildren) return true;
  if (dt === 'switch' || dt === 'ap' || sub === 'switch' || sub === 'ap') return true;
  return degree >= 2;
}

type Adjacency = Map<number, { neighborId: number; link: OrbitLink }[]>;

/** Where a body orbits before roles are decided. */
interface RawParent {
  parentId: number | null;
  wireless: boolean;
  linkId: number | null;
  linkColor?: string | null;
}

/** Undirected adjacency of the links whose both ends exist (self-links dropped). */
function buildAdjacency(devices: Device[], links: OrbitLink[], byId: Map<number, Device>): Adjacency {
  const adj: Adjacency = new Map(devices.map((d) => [d.id, []]));
  for (const l of links) {
    if (!byId.has(l.source_id) || !byId.has(l.target_id) || l.source_id === l.target_id) continue;
    adj.get(l.source_id)!.push({ neighborId: l.target_id, link: l });
    adj.get(l.target_id)!.push({ neighborId: l.source_id, link: l });
  }
  return adj;
}

/** Chosen stars, else gateways and routers; without any, the device with the most links. */
function findStars(devices: Device[], adj: Adjacency, gatewayIds: Set<number>, roles: OrbitRoles): Set<number> {
  const starIds = new Set<number>();
  for (const d of devices) {
    const role = roles[String(d.id)];
    if (role === 'star' || (!role && (gatewayIds.has(d.id) || (d.device_type || '').toLowerCase() === 'router'))) {
      starIds.add(d.id);
    }
  }
  if (starIds.size === 0 && devices.length > 0) {
    const sorted = [...devices].sort(
      (a, b) => (adj.get(b.id)?.length ?? 0) - (adj.get(a.id)?.length ?? 0) || a.id - b.id,
    );
    starIds.add(sorted[0].id);
  }
  return starIds;
}

/**
 * Breadth-first over the links, first from the stars, then from each link island the stars do not reach,
 * so linked pairs still orbit one another. Returns each reached device's neighbour one hop closer to the start.
 */
function linkParents(
  devices: Device[],
  adj: Adjacency,
  starIds: Set<number>,
): Map<number, { parentId: number; link: OrbitLink }> {
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

/** Re-parent every device whose parent chain loops (e.g. a host whose parent_id points to its VM) to the primary star. */
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

/** Star, planet or moon, and whether a planet is drawn as a dwarf. */
function classify(
  d: Device,
  isStar: boolean,
  role: OrbitRole | undefined,
  degree: number,
  children: number,
  hasVmChildren: boolean,
): { kind: BodyKind; dwarf: boolean } {
  if (isStar) return { kind: 'star', dwarf: false };
  // A body others orbit cannot be a moon, so a chosen moon with children stays a dwarf planet.
  const planet =
    role === 'planet' ||
    role === 'dwarf' ||
    children > 0 ||
    (role !== 'moon' && isPlanetCandidate(d, degree, hasVmChildren));
  if (!planet) return { kind: 'moon', dwarf: false };
  const dwarf =
    role === 'dwarf' || (role === 'moon' && children > 0) || (!role && isNetworkGear(d) && children < DWARF_MAX_CHILDREN);
  return { kind: 'planet', dwarf };
}

/**
 * Determine each device's celestial role (star, planet, moon) and who it orbits around:
 * 1. parent_id (VM / container) -> Host
 * 2. Explicit TopologyLink -> neighbor closer to the Star (BFS from gateway/star)
 * 3. is_wlan without link -> Access Point in the same subnet (or any AP)
 * 4. Otherwise -> Star of the device's subnet (or primary Star)
 */
export function resolveOrbitSystem(
  devices: Device[],
  links: OrbitLink[],
  gatewayIds: Set<number>,
  roles: OrbitRoles = {},
): Map<number, OrbitBody> {
  const byId = new Map(devices.map((d) => [d.id, d]));
  const adj = buildAdjacency(devices, links, byId);
  const vmParentIds = new Set(
    devices.filter((d) => d.parent_id != null && byId.has(d.parent_id)).map((d) => d.parent_id as number),
  );
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

    // 1. VM / Container -> Host
    if (d.parent_id != null && byId.has(d.parent_id) && d.parent_id !== d.id) {
      const explicitLink = (adj.get(d.id) ?? []).find((n) => n.neighborId === d.parent_id)?.link ?? null;
      return {
        parentId: d.parent_id,
        wireless: explicitLink?.link_type === 'WLAN',
        linkId: explicitLink?.id ?? null,
        linkColor: explicitLink?.color,
      };
    }

    // 2. Explicit TopologyLink (BFS neighbor closer to Star)
    const bfs = bfsParent.get(d.id);
    if (bfs) {
      return {
        parentId: bfs.parentId,
        wireless: bfs.link.link_type === 'WLAN' || Boolean(d.is_wlan),
        linkId: bfs.link.id,
        linkColor: bfs.link.color,
      };
    }

    // 3. Unlinked WLAN device -> Access Point in same subnet (or first AP)
    if (d.is_wlan && !d.is_ap) {
      const ap = aps.find((a) => a.id !== d.id && a.subnet_id === d.subnet_id) ?? aps.find((a) => a.id !== d.id);
      if (ap) return { parentId: ap.id, wireless: true, linkId: null };
    }

    // 4. Default -> Star of its subnet (or primary Star)
    const fallbackStar = starForSubnet(d.subnet_id, d.id) ?? primaryStarId;
    return {
      parentId: fallbackStar && fallbackStar !== d.id ? fallbackStar : null,
      wireless: Boolean(d.is_wlan),
      linkId: null,
    };
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
    const { kind, dwarf } = classify(
      d,
      starIds.has(d.id),
      roles[String(d.id)],
      adj.get(d.id)?.length ?? 0,
      childCount.get(d.id) ?? 0,
      vmParentIds.has(d.id),
    );
    const state = bodyState(d);
    const ownColor = networkColor(d.subnet_id, d.ip);
    const primaryColor = info.linkColor || ownColor;

    result.set(d.id, {
      id: d.id,
      device: d,
      kind,
      dwarf,
      state,
      parentId: info.parentId,
      orbitStyle: state === 'offline' ? 'broken' : info.wireless ? 'dashed' : 'solid',
      color: primaryColor,
      rings: [
        ...new Set([primaryColor, ownColor, ...(d.interfaces ?? []).map((i) => networkColor(i.subnet_id, i.ip))]),
      ],
      parentLinkId: info.linkId,
    });
  }

  return result;
}

/**
 * Compute Light Beams from saved TopologyLinks.
 * Links between Stars and Planets (Switches, APs, Hosts) are flagged as primary bridges.
 */
export function computeLightBeams(
  links: OrbitLink[],
  bodies: Map<number, OrbitBody>,
  typeColors: Record<string, string> = {},
): LightBeam[] {
  const beams: LightBeam[] = [];
  for (const l of links) {
    const a = bodies.get(l.source_id);
    const b = bodies.get(l.target_id);
    if (!a || !b) continue;
    const isPrimaryBridge = (a.kind !== 'moon' && b.kind !== 'moon') || a.kind === 'star' || b.kind === 'star';
    // The link's own colour, else the colour chosen for its type (10GbE, WLAN, ...), else its network
    const color = l.color || typeColors[l.link_type || '1GbE'] || (b.kind !== 'star' ? b.color : a.color);
    beams.push({
      id: l.id,
      sourceId: l.source_id,
      targetId: l.target_id,
      linkType: l.link_type || '1GbE',
      color,
      interrupted: !a.device.is_online || !b.device.is_online,
      isWireless: l.link_type === 'WLAN',
      isPrimaryBridge,
    });
  }
  return beams;
}

/**
 * Compute concentric OrbitRings from current positions.
 * Siblings orbiting the same center within ORBIT_SNAP_TOLERANCE share a single ring radius.
 */
export function computeOrbitRings(
  bodies: Map<number, OrbitBody>,
  positions: Map<number, Point>,
  tolerance = ORBIT_SNAP_TOLERANCE,
): OrbitRing[] {
  // Moons ring around their planet, planets around the star of their system
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
      // Planet tiers around the star are neutral tracks; moon rings take the members' network colour
      const isTier = cluster.members.some((m) => m.kind !== 'moon');
      const dominantColor = isTier ? 'var(--gl-fg-subtle)' : (cluster.members[0]?.color ?? 'var(--gl-accent)');
      rings.push({
        id: `ring-${centerId}-${idx}-${cluster.radius}`,
        centerId,
        radius: cluster.radius,
        color: dominantColor,
        style,
        memberIds: cluster.members.map((m) => m.id),
      });
    });
  }

  return rings;
}

/**
 * Automatic gravitational layout:
 * - Stars sit at the origin (or spaced along x if multiple gateways exist)
 * - Planets orbit their Star on outer rings (r = 250..360) so their moon systems have room
 * - Direct Moons of a Star orbit on inner rings (r = 125..185)
 * - Moons of a Planet orbit their Planet on compact rings (r = 88..135)
 */
export function autoOrbitLayout(
  devices: Device[],
  links: OrbitLink[],
  gatewayIds: Set<number>,
  roles: OrbitRoles = {},
): Map<number, Point> {
  return layoutOrbit(resolveOrbitSystem(devices, links, gatewayIds, roles));
}

/**
 * Collect all descendant IDs (moons, sub-planets, sub-moons) of a given body so moving a
 * Planet or Star moves its entire orbital subsystem by the same delta.
 */
export function getDescendantIds(rootId: number, bodies: Map<number, OrbitBody>): number[] {
  const descendants: number[] = [];
  const visited = new Set<number>([rootId]);
  const queue = [rootId];

  while (queue.length > 0) {
    const curr = queue.shift()!;
    for (const b of bodies.values()) {
      if (b.parentId === curr && !visited.has(b.id)) {
        visited.add(b.id);
        descendants.push(b.id);
        queue.push(b.id);
      }
    }
  }
  return descendants;
}

/**
 * Translate a body and all of its orbital descendants by (dx, dy).
 */
export function moveWithDescendants(
  rootId: number,
  delta: Point,
  bodies: Map<number, OrbitBody>,
  positions: Map<number, Point>,
): Map<number, Point> {
  const next = new Map(positions);
  const idsToMove = [rootId, ...getDescendantIds(rootId, bodies)];
  for (const id of idsToMove) {
    const prev = positions.get(id);
    if (prev) {
      next.set(id, { x: Math.round(prev.x + delta.x), y: Math.round(prev.y + delta.y) });
    }
  }
  return next;
}

/**
 * Snap a dragged body's radius to a sibling's orbit radius if within ORBIT_SNAP_TOLERANCE,
 * preserving the dragged angle.
 */
export function snapToOrbitRing(
  bodyId: number,
  candidatePos: Point,
  bodies: Map<number, OrbitBody>,
  positions: Map<number, Point>,
  tolerance = ORBIT_SNAP_TOLERANCE,
): Point {
  const body = bodies.get(bodyId);
  const centerId = body ? orbitCenterId(body, bodies) : null;
  if (!body || centerId == null) {
    return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
  }
  const center = positions.get(centerId);
  if (!center) {
    return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
  }

  const dx = candidatePos.x - center.x;
  const dy = candidatePos.y - center.y;
  const rawDist = Math.hypot(dx, dy);
  if (rawDist < 24) {
    return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
  }

  const angle = Math.atan2(dy, dx);

  // Check sibling distances around the same parent
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

  return {
    x: Math.round(center.x + snappedRadius * Math.cos(angle)),
    y: Math.round(center.y + snappedRadius * Math.sin(angle)),
  };
}

/**
 * Find a Planet or Star under the cursor when dragging a body so the user can drop a Moon/Planet
 * onto another Planet/AP/Switch/Star to reassign its orbit and create/move the Light Beam link.
 */
export function findDropTargetBody(
  draggedId: number,
  cursor: Point,
  bodies: Map<number, OrbitBody>,
  positions: Map<number, Point>,
  radius = DROP_TARGET_RADIUS,
): OrbitBody | null {
  const descendants = new Set(getDescendantIds(draggedId, bodies));
  let best: { body: OrbitBody; dist: number } | null = null;

  for (const candidate of bodies.values()) {
    if (candidate.id === draggedId || descendants.has(candidate.id)) continue;
    const pos = positions.get(candidate.id);
    if (!pos) continue;
    const dist = Math.hypot(cursor.x - pos.x, cursor.y - pos.y);
    if (dist <= radius && (!best || dist < best.dist)) {
      best = { body: candidate, dist };
    }
  }

  return best?.body ?? null;
}
