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

export type OrbitLink = TopologyLink & {
  color?: string | null;
  speed?: number | null;
  notes?: string | null;
};

export const LINK_TYPES = ['10GbE', '2.5GbE', '1GbE', 'WLAN', 'Fiber'] as const;

export type BodyKind = 'star' | 'planet' | 'moon';
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
  return device.services.some((s) => !s.is_up) ? 'degraded' : 'online';
}

export function isPlanetCandidate(device: Device, degree: number, hasVmChildren: boolean): boolean {
  const dt = (device.device_type || '').toLowerCase();
  const sub = (device.device_subtype || '').toLowerCase();
  if (device.is_ap || device.is_host || hasVmChildren) return true;
  if (dt === 'switch' || dt === 'ap' || sub === 'switch' || sub === 'ap') return true;
  return degree >= 2;
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
): Map<number, OrbitBody> {
  const byId = new Map(devices.map((d) => [d.id, d]));

  // Build undirected adjacency list of valid topology links
  const adj = new Map<number, { neighborId: number; link: OrbitLink }[]>();
  for (const d of devices) adj.set(d.id, []);
  for (const l of links) {
    if (!byId.has(l.source_id) || !byId.has(l.target_id) || l.source_id === l.target_id) continue;
    adj.get(l.source_id)!.push({ neighborId: l.target_id, link: l });
    adj.get(l.target_id)!.push({ neighborId: l.source_id, link: l });
  }

  const vmParentIds = new Set<number>();
  for (const d of devices) {
    if (d.parent_id != null && byId.has(d.parent_id)) vmParentIds.add(d.parent_id);
  }

  // Identify Stars (gateways or routers; fallback to highest-degree node if none)
  const starIds = new Set<number>();
  for (const d of devices) {
    if (gatewayIds.has(d.id) || (d.device_type || '').toLowerCase() === 'router') {
      starIds.add(d.id);
    }
  }
  if (starIds.size === 0 && devices.length > 0) {
    const sorted = [...devices].sort(
      (a, b) => (adj.get(b.id)?.length ?? 0) - (adj.get(a.id)?.length ?? 0) || a.id - b.id,
    );
    starIds.add(sorted[0].id);
  }

  // BFS from Stars over topology links to establish hop distance & parent link toward a Star
  const distFromStar = new Map<number, number>();
  const bfsParent = new Map<number, { parentId: number; link: OrbitLink }>();
  const queue: number[] = [];

  for (const sid of starIds) {
    distFromStar.set(sid, 0);
    queue.push(sid);
  }

  while (queue.length > 0) {
    const curr = queue.shift()!;
    const currDist = distFromStar.get(curr)!;
    for (const { neighborId, link } of adj.get(curr) ?? []) {
      if (!distFromStar.has(neighborId)) {
        distFromStar.set(neighborId, currDist + 1);
        bfsParent.set(neighborId, { parentId: curr, link });
        queue.push(neighborId);
      }
    }
  }

  // Also handle disconnected link islands so linked pairs still orbit one another
  for (const d of devices) {
    if (distFromStar.has(d.id)) continue;
    const neighbors = adj.get(d.id) ?? [];
    if (neighbors.length === 0) continue;
    distFromStar.set(d.id, 1);
    const q = [d.id];
    while (q.length > 0) {
      const curr = q.shift()!;
      const cd = distFromStar.get(curr)!;
      for (const { neighborId, link } of adj.get(curr) ?? []) {
        if (!distFromStar.has(neighborId)) {
          distFromStar.set(neighborId, cd + 1);
          bfsParent.set(neighborId, { parentId: curr, link });
          q.push(neighborId);
        }
      }
    }
  }

  // Access points by subnet for unlinked WLAN devices
  const aps = devices.filter((d) => d.is_ap || (d.device_type || '').toLowerCase() === 'ap');
  const primaryStarId = [...starIds][0] ?? null;

  function starForSubnet(subnetId: number | null | undefined, selfId: number): number | null {
    for (const sid of starIds) {
      if (sid === selfId) continue;
      const sd = byId.get(sid);
      if (sd && subnetId != null && sd.subnet_id === subnetId) return sid;
    }
    for (const sid of starIds) {
      if (sid !== selfId) return sid;
    }
    return null;
  }

  // First pass: assign preliminary parentId and link
  const rawParents = new Map<number, { parentId: number | null; wireless: boolean; linkId: number | null; linkColor?: string | null }>();

  for (const d of devices) {
    if (starIds.has(d.id)) {
      rawParents.set(d.id, { parentId: null, wireless: false, linkId: null });
      continue;
    }

    // 1. VM / Container -> Host
    if (d.parent_id != null && byId.has(d.parent_id) && d.parent_id !== d.id) {
      const explicitLink = (adj.get(d.id) ?? []).find((n) => n.neighborId === d.parent_id)?.link ?? null;
      rawParents.set(d.id, {
        parentId: d.parent_id,
        wireless: explicitLink?.link_type === 'WLAN',
        linkId: explicitLink?.id ?? null,
        linkColor: explicitLink?.color,
      });
      continue;
    }

    // 2. Explicit TopologyLink (BFS neighbor closer to Star)
    const bfs = bfsParent.get(d.id);
    if (bfs) {
      rawParents.set(d.id, {
        parentId: bfs.parentId,
        wireless: bfs.link.link_type === 'WLAN' || Boolean(d.is_wlan),
        linkId: bfs.link.id,
        linkColor: bfs.link.color,
      });
      continue;
    }

    // 3. Unlinked WLAN device -> Access Point in same subnet (or first AP)
    if (d.is_wlan && !d.is_ap) {
      const ap = aps.find((a) => a.id !== d.id && a.subnet_id === d.subnet_id) ?? aps.find((a) => a.id !== d.id);
      if (ap) {
        rawParents.set(d.id, { parentId: ap.id, wireless: true, linkId: null });
        continue;
      }
    }

    // 4. Default -> Star of its subnet (or primary Star)
    const fallbackStar = starForSubnet(d.subnet_id, d.id) ?? primaryStarId;
    rawParents.set(d.id, {
      parentId: fallbackStar && fallbackStar !== d.id ? fallbackStar : null,
      wireless: Boolean(d.is_wlan),
      linkId: null,
    });
  }

  // Break any accidental cycles (e.g. if a host has parent_id pointing to a child)
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

  // Count children in the resolved orbit tree
  const childCount = new Map<number, number>();
  for (const { parentId } of rawParents.values()) {
    if (parentId != null) childCount.set(parentId, (childCount.get(parentId) ?? 0) + 1);
  }

  // Build final OrbitBody records
  const result = new Map<number, OrbitBody>();
  for (const d of devices) {
    const info = rawParents.get(d.id)!;
    const degree = adj.get(d.id)?.length ?? 0;
    const hasChildren = (childCount.get(d.id) ?? 0) > 0;
    const kind: BodyKind = starIds.has(d.id)
      ? 'star'
      : isPlanetCandidate(d, degree, vmParentIds.has(d.id) || hasChildren)
        ? 'planet'
        : 'moon';

    const state = bodyState(d);
    const orbitStyle: OrbitStyle = state === 'offline' ? 'broken' : info.wireless ? 'dashed' : 'solid';
    const primaryColor = info.linkColor || networkColor(d.subnet_id, d.ip);
    const rings = [
      ...new Set([
        primaryColor,
        networkColor(d.subnet_id, d.ip),
        ...(d.interfaces ?? []).map((i) => networkColor(i.subnet_id, i.ip)),
      ]),
    ];

    result.set(d.id, {
      id: d.id,
      device: d,
      kind,
      state,
      parentId: info.parentId,
      orbitStyle,
      color: primaryColor,
      rings,
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
): LightBeam[] {
  const beams: LightBeam[] = [];
  for (const l of links) {
    const a = bodies.get(l.source_id);
    const b = bodies.get(l.target_id);
    if (!a || !b) continue;
    const isPrimaryBridge = (a.kind !== 'moon' && b.kind !== 'moon') || a.kind === 'star' || b.kind === 'star';
    const color = l.color || (b.kind !== 'star' ? b.color : a.color);
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
  const byParent = new Map<number, { body: OrbitBody; dist: number }[]>();
  for (const body of bodies.values()) {
    if (body.parentId == null) continue;
    const pPos = positions.get(body.parentId);
    const cPos = positions.get(body.id);
    if (!pPos || !cPos) continue;
    const dist = Math.hypot(cPos.x - pPos.x, cPos.y - pPos.y);
    if (dist < 12) continue;
    if (!byParent.has(body.parentId)) byParent.set(body.parentId, []);
    byParent.get(body.parentId)!.push({ body, dist });
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
      const dominantColor = cluster.members[0]?.color ?? 'var(--gl-accent)';
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
): Map<number, Point> {
  const bodies = resolveOrbitSystem(devices, links, gatewayIds);
  const positions = new Map<number, Point>();

  const childrenOf = new Map<number, OrbitBody[]>();
  const roots: OrbitBody[] = [];

  for (const b of bodies.values()) {
    if (b.parentId == null || !bodies.has(b.parentId)) {
      roots.push(b);
    } else {
      if (!childrenOf.has(b.parentId)) childrenOf.set(b.parentId, []);
      childrenOf.get(b.parentId)!.push(b);
    }
  }

  roots.sort((a, b) => a.id - b.id);
  const starSpacing = 680;
  const startX = -((roots.length - 1) * starSpacing) / 2;

  roots.forEach((star, idx) => {
    positions.set(star.id, { x: Math.round(startX + idx * starSpacing), y: 0 });
  });

  // BFS placement from Stars -> Planets -> Moons
  const queue = [...roots];
  while (queue.length > 0) {
    const parent = queue.shift()!;
    const pPos = positions.get(parent.id) ?? { x: 0, y: 0 };
    const kids = childrenOf.get(parent.id) ?? [];
    if (kids.length === 0) continue;

    const planets = kids.filter((k) => k.kind !== 'moon');
    const moons = kids.filter((k) => k.kind === 'moon');

    if (parent.kind === 'star') {
      // Direct moons of the Star sit on an inner belt (r = 135)
      placeOnBelt(moons, pPos, 135, 6, 55, positions, -Math.PI / 4);
      // Planets (Switches, APs, Hosts) sit on a wider belt so their own moons don't collide
      const planetRadius = moons.length > 0 ? 310 : 255;
      placeOnBelt(planets, pPos, planetRadius, 6, 110, positions, -Math.PI / 2);
    } else {
      // Children of a Planet (Switch / AP / Host)
      // Orient the fan away from the Star so moons don't crowd the inner beam
      const gParentPos = parent.parentId != null ? positions.get(parent.parentId) : null;
      const outwardAngle = gParentPos
        ? Math.atan2(pPos.y - gParentPos.y, pPos.x - gParentPos.x)
        : -Math.PI / 2;
      placeOnBelt(moons, pPos, 96, 6, 48, positions, outwardAngle);
      placeOnBelt(planets, pPos, 175, 5, 70, positions, outwardAngle);
    }

    queue.push(...planets, ...moons);
  }

  return positions;
}

function placeOnBelt(
  items: OrbitBody[],
  center: Point,
  baseRadius: number,
  maxPerRing: number,
  ringStep: number,
  out: Map<number, Point>,
  startAngle = -Math.PI / 2,
) {
  if (items.length === 0) return;
  const sorted = [...items].sort((a, b) => a.id - b.id);
  sorted.forEach((item, index) => {
    const ringIndex = Math.floor(index / maxPerRing);
    const countInRing = Math.min(maxPerRing, sorted.length - ringIndex * maxPerRing);
    const posInRing = index % maxPerRing;
    const radius = baseRadius + ringIndex * ringStep;
    const angleOffset = ringIndex % 2 === 1 ? Math.PI / countInRing : 0;
    const angle = startAngle + angleOffset + (posInRing * 2 * Math.PI) / Math.max(1, countInRing);
    out.set(item.id, {
      x: Math.round(center.x + radius * Math.cos(angle)),
      y: Math.round(center.y + radius * Math.sin(angle)),
    });
  });
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
  if (!body || body.parentId == null) {
    return { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
  }
  const center = positions.get(body.parentId);
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
    if (other.id === bodyId || other.parentId !== body.parentId) continue;
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
