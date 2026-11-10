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

export type LinkRole = 'primary' | 'backup';

export type OrbitLink = TopologyLink & {
  color?: string | null;
  speed?: number | null;
  notes?: string | null;
  /** 'backup': a standby/fallback path; it is drawn but never decides who orbits whom */
  role?: LinkRole | null;
};

export const isBackupLink = (link: Pick<OrbitLink, 'role'>): boolean => link.role === 'backup';

/**
 * A colour as a thin line on the orbit map. The theme says how much of it stays (`--gl-orbit-ink`):
 * all of it on the night ground, less on a light ground, where the rest is text colour so that a
 * pale network or link colour still reads as a line.
 */
export const orbitInk = (colour: string): string => `color-mix(in oklab, ${colour} var(--gl-orbit-ink), var(--gl-fg))`;

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

type WirelessHint = Partial<Pick<Device, 'is_ap' | 'is_wlan'>> | undefined;

/** Default type for a new link: WLAN when either end is an access point or wireless client, else 1GbE. */
export function inferLinkType(a: WirelessHint, b: WirelessHint): 'WLAN' | '1GbE' {
  return a?.is_ap || b?.is_ap || a?.is_wlan || b?.is_wlan ? 'WLAN' : '1GbE';
}

export type BodyKind = 'star' | 'planet' | 'moon';
/** What the user can pick: a dwarf planet is a small planet (a switch or AP with few devices). */
export type OrbitRole = 'star' | 'planet' | 'dwarf' | 'moon';
/** Chosen roles per device id (setting `ui.orbit_roles`); a missing id means automatic. */
export type OrbitRoles = Record<string, OrbitRole>;
/** Orbit map visibility the user chose per device (`ui.orbit_visibility`, JSON {deviceId: shown}) */
export type OrbitVisibility = Record<string, boolean>;

/** Whether a device is on the orbit map: the user's choice, else whether the dashboard shows it. */
export function isOnOrbit(device: Pick<Device, 'id' | 'is_hidden'>, visibility: OrbitVisibility): boolean {
  return visibility[String(device.id)] ?? !device.is_hidden;
}

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
  /** A standby/fallback path: drawn thin and dashed, without photons */
  isBackup: boolean;
  /** A backup path carrying traffic now because the primary one failed (see orbitResilience) */
  failover: boolean;
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

/** Network gear, hosts and devices with VMs or at least two links orbit as planets. */
export function isPlanetCandidate(device: Device, degree: number, hasVmChildren: boolean): boolean {
  return device.is_host || hasVmChildren || isNetworkGear(device) || degree >= 2;
}

type Adjacency = Map<number, { neighborId: number; link: OrbitLink }[]>;

/** Where a body orbits before roles are decided. */
interface RawParent {
  parentId: number | null;
  wireless: boolean;
  linkId: number | null;
  linkColor?: string | null;
}

/** Both ends are different devices on the map: neither a self-link nor dangling. */
function joinsTwoDevices(l: OrbitLink, byId: Map<number, Device>): boolean {
  return l.source_id !== l.target_id && byId.has(l.source_id) && byId.has(l.target_id);
}

/**
 * Undirected adjacency of the primary links whose both ends exist (self-links dropped). Backup links stay
 * out, so adding a fallback path never changes roles, hubs or the layout.
 */
function buildAdjacency(devices: Device[], links: OrbitLink[], byId: Map<number, Device>): Adjacency {
  const adj: Adjacency = new Map(devices.map((d) => [d.id, []]));
  for (const l of links) {
    if (isBackupLink(l) || !joinsTwoDevices(l, byId)) continue;
    adj.get(l.source_id)!.push({ neighborId: l.target_id, link: l });
    adj.get(l.target_id)!.push({ neighborId: l.source_id, link: l });
  }
  return adj;
}

/** A star by choice, or, without a chosen role, a gateway or router. */
function isStarCandidate(d: Device, role: OrbitRole | undefined, gatewayIds: Set<number>): boolean {
  if (role) return role === 'star';
  return gatewayIds.has(d.id) || (d.device_type || '').toLowerCase() === 'router';
}

/** The device with the most links (the lowest id on a tie). */
function mostLinked(devices: Device[], adj: Adjacency): Device {
  const degree = (d: Device) => adj.get(d.id)?.length ?? 0;
  return [...devices].sort((a, b) => degree(b) - degree(a) || a.id - b.id)[0];
}

/** Chosen stars, else gateways and routers; without any, the device with the most links. */
function findStars(devices: Device[], adj: Adjacency, gatewayIds: Set<number>, roles: OrbitRoles): Set<number> {
  const starIds = new Set(devices.filter((d) => isStarCandidate(d, roles[String(d.id)], gatewayIds)).map((d) => d.id));
  if (starIds.size === 0 && devices.length > 0) starIds.add(mostLinked(devices, adj).id);
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

/** True when following the parents from ``id`` comes back to a device already passed. */
function parentChainLoops(id: number, rawParents: Map<number, RawParent>): boolean {
  const seen = new Set<number>([id]);
  for (let curr = rawParents.get(id)?.parentId ?? null; curr != null; curr = rawParents.get(curr)?.parentId ?? null) {
    if (seen.has(curr)) return true;
    seen.add(curr);
  }
  return false;
}

/** Re-parent every device whose parent chain loops (e.g. a host whose parent_id points to its VM) to the primary star. */
function breakCycles(devices: Device[], rawParents: Map<number, RawParent>, primaryStarId: number | null): void {
  for (const d of devices) {
    if (parentChainLoops(d.id, rawParents)) {
      rawParents.set(d.id, { parentId: primaryStarId !== d.id ? primaryStarId : null, wireless: false, linkId: null });
    }
  }
}

/** What deciding a device's body kind needs to know about it. */
interface BodyFacts {
  isStar: boolean;
  role: OrbitRole | undefined;
  degree: number;
  children: number;
  hasVmChildren: boolean;
}

/** A body others orbit cannot be a moon; otherwise a chosen role wins over what the device is. */
function isPlanetBody(d: Device, { role, degree, children, hasVmChildren }: BodyFacts): boolean {
  if (role === 'planet' || role === 'dwarf' || children > 0) return true;
  return role !== 'moon' && isPlanetCandidate(d, degree, hasVmChildren);
}

/** Chosen as a dwarf, a chosen moon that others orbit, or, without a choice, network gear carrying few devices. */
function isDwarfPlanet(d: Device, { role, children }: BodyFacts): boolean {
  if (role) return role === 'dwarf' || (role === 'moon' && children > 0);
  return isNetworkGear(d) && children < DWARF_MAX_CHILDREN;
}

/** Star, planet or moon, and whether a planet is drawn as a dwarf. */
function classify(d: Device, facts: BodyFacts): { kind: BodyKind; dwarf: boolean } {
  if (facts.isStar) return { kind: 'star', dwarf: false };
  if (!isPlanetBody(d, facts)) return { kind: 'moon', dwarf: false };
  return { kind: 'planet', dwarf: isDwarfPlanet(d, facts) };
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

  const ctx: ParentContext = { byId, adj, starIds, bfsParent, aps, primaryStarId };
  const rawParents = new Map(devices.map((d) => [d.id, rawParentOf(d, ctx)]));
  breakCycles(devices, rawParents, primaryStarId);
  const childCount = countChildren(rawParents);

  const result = new Map<number, OrbitBody>();
  for (const d of devices) {
    const { kind, dwarf } = classify(d, {
      isStar: starIds.has(d.id),
      role: roles[String(d.id)],
      degree: adj.get(d.id)?.length ?? 0,
      children: childCount.get(d.id) ?? 0,
      hasVmChildren: vmParentIds.has(d.id),
    });
    result.set(d.id, toBody(d, rawParents.get(d.id)!, kind, dwarf));
  }
  return result;
}

/** What deciding a device's orbit parent needs to know about the whole map. */
interface ParentContext {
  byId: Map<number, Device>;
  adj: Adjacency;
  starIds: Set<number>;
  bfsParent: Map<number, { parentId: number; link: OrbitLink }>;
  aps: Device[];
  primaryStarId: number | null;
}

/** 1. A VM or container orbits its host, over their link if there is one. */
function hostParent(d: Device, ctx: ParentContext): RawParent | null {
  if (d.parent_id == null || !ctx.byId.has(d.parent_id) || d.parent_id === d.id) return null;
  const explicitLink = (ctx.adj.get(d.id) ?? []).find((n) => n.neighborId === d.parent_id)?.link ?? null;
  return {
    parentId: d.parent_id,
    wireless: explicitLink?.link_type === 'WLAN',
    linkId: explicitLink?.id ?? null,
    linkColor: explicitLink?.color,
  };
}

/** 2. A linked device orbits its neighbour one hop closer to a star. */
function linkedParent(d: Device, ctx: ParentContext): RawParent | null {
  const bfs = ctx.bfsParent.get(d.id);
  if (!bfs) return null;
  return {
    parentId: bfs.parentId,
    wireless: bfs.link.link_type === 'WLAN' || Boolean(d.is_wlan),
    linkId: bfs.link.id,
    linkColor: bfs.link.color,
  };
}

/** 3. An unlinked WLAN client orbits an access point of its subnet, else any access point. */
function accessPointParent(d: Device, ctx: ParentContext): RawParent | null {
  if (!d.is_wlan || d.is_ap) return null;
  const others = ctx.aps.filter((a) => a.id !== d.id);
  const ap = others.find((a) => a.subnet_id === d.subnet_id) ?? others[0];
  return ap ? { parentId: ap.id, wireless: true, linkId: null } : null;
}

/** 4. Anything else orbits the star of its subnet, else the first other star, else the primary star. */
function starParent(d: Device, ctx: ParentContext): RawParent {
  const otherStars = [...ctx.starIds].filter((sid) => sid !== d.id);
  const subnetStar = otherStars.find((sid) => d.subnet_id != null && ctx.byId.get(sid)?.subnet_id === d.subnet_id);
  const fallbackStar = subnetStar ?? otherStars[0] ?? ctx.primaryStarId;
  return {
    parentId: fallbackStar && fallbackStar !== d.id ? fallbackStar : null,
    wireless: Boolean(d.is_wlan),
    linkId: null,
  };
}

function rawParentOf(d: Device, ctx: ParentContext): RawParent {
  if (ctx.starIds.has(d.id)) return { parentId: null, wireless: false, linkId: null };
  return hostParent(d, ctx) ?? linkedParent(d, ctx) ?? accessPointParent(d, ctx) ?? starParent(d, ctx);
}

function countChildren(rawParents: Map<number, RawParent>): Map<number, number> {
  const childCount = new Map<number, number>();
  for (const { parentId } of rawParents.values()) {
    if (parentId != null) childCount.set(parentId, (childCount.get(parentId) ?? 0) + 1);
  }
  return childCount;
}

function toBody(d: Device, info: RawParent, kind: BodyKind, dwarf: boolean): OrbitBody {
  const state = bodyState(d);
  const ownColor = networkColor(d.subnet_id, d.ip);
  const primaryColor = info.linkColor || ownColor;
  return {
    id: d.id,
    device: d,
    kind,
    dwarf,
    state,
    parentId: info.parentId,
    orbitStyle: state === 'offline' ? 'broken' : info.wireless ? 'dashed' : 'solid',
    color: primaryColor,
    rings: [...new Set([primaryColor, ownColor, ...(d.interfaces ?? []).map((i) => networkColor(i.subnet_id, i.ip))])],
    parentLinkId: info.linkId,
  };
}

/**
 * Compute Light Beams from saved TopologyLinks.
 * Links between Stars and Planets (Switches, APs, Hosts) are flagged as primary bridges.
 */
export function computeLightBeams(
  links: OrbitLink[],
  bodies: Map<number, OrbitBody>,
  typeColors: Record<string, string> = {},
  activeBackupIds: ReadonlySet<number> = new Set(),
): LightBeam[] {
  const beams: LightBeam[] = [];
  for (const l of links) {
    const a = bodies.get(l.source_id);
    const b = bodies.get(l.target_id);
    if (a && b) beams.push(toBeam(l, a, b, typeColors, activeBackupIds));
  }
  return beams;
}

/** A link between two non-moons, or one touching a star, carries the backbone. */
function isBridge(a: OrbitBody, b: OrbitBody): boolean {
  return (a.kind !== 'moon' && b.kind !== 'moon') || a.kind === 'star' || b.kind === 'star';
}

function toBeam(
  l: OrbitLink,
  a: OrbitBody,
  b: OrbitBody,
  typeColors: Record<string, string>,
  activeBackupIds: ReadonlySet<number>,
): LightBeam {
  const linkType = l.link_type || '1GbE';
  const backup = isBackupLink(l);
  return {
    id: l.id,
    sourceId: l.source_id,
    targetId: l.target_id,
    linkType,
    // The link's own colour, else the colour chosen for its type (10GbE, WLAN, ...), else its network
    color: l.color || typeColors[linkType] || (b.kind !== 'star' ? b.color : a.color),
    interrupted: !a.device.is_online || !b.device.is_online,
    isWireless: l.link_type === 'WLAN',
    isPrimaryBridge: isBridge(a, b) && !backup,
    isBackup: backup,
    failover: backup && activeBackupIds.has(l.id),
  };
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
  const rings: OrbitRing[] = [];
  for (const [centerId, children] of distancesByCenter(bodies, positions)) {
    clusterByRadius(centerId, children, positions, tolerance).forEach((cluster, idx) => {
      rings.push({
        id: `ring-${centerId}-${idx}-${cluster.radius}`,
        centerId,
        radius: cluster.radius,
        color: ringColor(cluster.members),
        style: ringStyle(cluster.members),
        memberIds: cluster.members.map((m) => m.id),
      });
    });
  }
  return rings;
}

const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

/** Each body's distance to its orbit centre: moons ring around their planet, planets around the star of their system. */
function distancesByCenter(bodies: Map<number, OrbitBody>, positions: Map<number, Point>) {
  const byCenter = new Map<number, { body: OrbitBody; dist: number }[]>();
  for (const body of bodies.values()) {
    const centerId = orbitCenterId(body, bodies);
    const center = centerId == null ? undefined : positions.get(centerId);
    const pos = positions.get(body.id);
    if (centerId == null || !center || !pos) continue;
    const dist = distance(pos, center);
    if (dist < 12) continue;
    if (!byCenter.has(centerId)) byCenter.set(centerId, []);
    byCenter.get(centerId)!.push({ body, dist });
  }
  return byCenter;
}

/** Group siblings, nearest first, into rings whose radius is the mean distance of their members. */
function clusterByRadius(
  centerId: number,
  children: { body: OrbitBody; dist: number }[],
  positions: Map<number, Point>,
  tolerance: number,
): { radius: number; members: OrbitBody[] }[] {
  const center = positions.get(centerId)!;
  const clusters: { radius: number; members: OrbitBody[] }[] = [];
  for (const item of [...children].sort((a, b) => a.dist - b.dist)) {
    const last = clusters[clusters.length - 1];
    if (last && Math.abs(item.dist - last.radius) <= tolerance) {
      last.members.push(item.body);
      const total = last.members.reduce((sum, m) => sum + distance(positions.get(m.id)!, center), 0);
      last.radius = Math.round(total / last.members.length);
    } else {
      clusters.push({ radius: Math.round(item.dist), members: [item.body] });
    }
  }
  return clusters;
}

function ringStyle(members: OrbitBody[]): OrbitStyle {
  if (members.every((m) => m.state === 'offline')) return 'broken';
  return members.some((m) => m.orbitStyle === 'dashed') ? 'dashed' : 'solid';
}

/** Planet tiers around the star are neutral tracks; moon rings take the members' network colour. */
function ringColor(members: OrbitBody[]): string {
  if (members.some((m) => m.kind !== 'moon')) return 'var(--gl-fg-subtle)';
  return members[0]?.color ?? 'var(--gl-accent)';
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
  const rounded = { x: Math.round(candidatePos.x), y: Math.round(candidatePos.y) };
  const body = bodies.get(bodyId);
  const centerId = body ? orbitCenterId(body, bodies) : null;
  const center = centerId == null ? undefined : positions.get(centerId);
  if (!body || centerId == null || !center) return rounded;

  const dx = candidatePos.x - center.x;
  const dy = candidatePos.y - center.y;
  const rawDist = Math.hypot(dx, dy);
  if (rawDist < 24) return rounded;

  const radius = nearestSiblingRadius(body, centerId, center, rawDist, bodies, positions, tolerance) ?? rawDist;
  const angle = Math.atan2(dy, dx);
  return {
    x: Math.round(center.x + radius * Math.cos(angle)),
    y: Math.round(center.y + radius * Math.sin(angle)),
  };
}

/** The orbit radius of the closest sibling of the same kind (moon or not) within ``tolerance``, if any. */
function nearestSiblingRadius(
  body: OrbitBody,
  centerId: number,
  center: Point,
  rawDist: number,
  bodies: Map<number, OrbitBody>,
  positions: Map<number, Point>,
  tolerance: number,
): number | null {
  let best: number | null = null;
  let bestDiff = tolerance + 1;
  for (const other of bodies.values()) {
    const pos = positions.get(other.id);
    const sibling = other.id !== body.id && (other.kind === 'moon') === (body.kind === 'moon');
    if (!sibling || !pos || orbitCenterId(other, bodies) !== centerId) continue;
    const otherDist = distance(pos, center);
    const diff = Math.abs(rawDist - otherDist);
    if (diff <= tolerance && diff < bestDiff) {
      bestDiff = diff;
      best = otherDist;
    }
  }
  return best;
}

/** Smallest angle between two directions, in radians (0 … π). */
const angleBetween = (a: number, b: number) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));

/**
 * Where a body newly assigned to `center` goes: on the ring of the moons already there (or `emptyRadius` for an
 * empty orbit), at the one of 24 directions furthest from them; straight up when nothing is there.
 */
export function freeOrbitSlot(center: Point, siblings: Point[], emptyRadius: number): Point {
  const radius = siblings.length ? Math.round(Math.hypot(siblings[0].x - center.x, siblings[0].y - center.y)) : emptyRadius;
  const taken = siblings.map((s) => Math.atan2(s.y - center.y, s.x - center.x));
  let best = -Math.PI / 2;
  let bestGap = -1;
  for (let k = 0; k < 24; k++) {
    const a = -Math.PI + (k * Math.PI) / 12;
    const gap = taken.length ? Math.min(...taken.map((x) => angleBetween(a, x))) : Math.PI;
    if (gap > bestGap) {
      bestGap = gap;
      best = a;
    }
  }
  return { x: Math.round(center.x + radius * Math.cos(best)), y: Math.round(center.y + radius * Math.sin(best)) };
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
