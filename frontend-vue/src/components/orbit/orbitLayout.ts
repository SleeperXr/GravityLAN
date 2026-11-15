/**
 * Orbit geometry: where bodies sit, where their labels go and how beams bend.
 *
 * Layout (radial tree, "solar system"):
 * - The router (star) sits at the centre of its system.
 * - Every subtree owns an angular wedge around its parent, sized by how much hangs below it, so
 *   subtrees never cross: switches, hosts and chains of bridges hang on short edges, each one
 *   pointing away from where it came from.
 * - Children without children of their own (VMs, containers, clients) circle their parent on a
 *   small local ring, fanned away from the parent's uplink.
 */
import type { OrbitBody, Point } from './orbitModel';

export const BODY_RADIUS = { star: 22, planet: 16, dwarf: 12.5, moon: 10.5 } as const;

/** Drawn radius of a body; dwarf planets are smaller planets. */
export const radiusOf = (body: Pick<OrbitBody, 'kind' | 'dwarf'>) => (body.kind === 'planet' && body.dwarf ? BODY_RADIUS.dwarf : BODY_RADIUS[body.kind]);

const SLOT = 104; // arc (world px) one body plus its label needs on a ring
const MOON_RING_MIN = 82;
const STAR_MOON_RING_MIN = 120;
const LABEL_PAD = 38; // room for the two label lines below a body
const SYSTEM_GAP = 140;
const MOON_FAN = Math.PI * 2 * 0.78; // moons leave the quarter towards the star free

const TAU = Math.PI * 2;
const polar = (c: Point, r: number, a: number): Point => ({ x: Math.round(c.x + r * Math.cos(a)), y: Math.round(c.y + r * Math.sin(a)) });

/** What a body circles around: moons their parent, planets the star at the root of their system. */
export function orbitCenterId(body: OrbitBody, bodies: Map<number, OrbitBody>): number | null {
  if (body.parentId == null || !bodies.has(body.parentId)) return null;
  if (body.kind === 'moon') return body.parentId;
  let cur = body;
  const seen = new Set<number>([body.id]);
  while (cur.parentId != null && bodies.has(cur.parentId) && !seen.has(cur.parentId)) {
    seen.add(cur.parentId);
    cur = bodies.get(cur.parentId)!;
  }
  return cur.id === body.id ? null : cur.id;
}

/** Distance between two moon rings: a moon, its two label lines and some air. */
export const RING_STEP = 2 * BODY_RADIUS.moon + LABEL_PAD + 12;

/**
 * Concentric rings for `n` moons on an arc of `span`: the innermost at `min`, each holding as many as fit with
 * their labels, the next one `RING_STEP` further out. Many moons no longer stretch a single giant circle.
 */
export function packRings(n: number, span: number, min: number): { radius: number; count: number }[] {
  const rings: { radius: number; count: number }[] = [];
  let radius = min;
  let left = n;
  while (left > 0) {
    const count = Math.min(left, Math.max(1, Math.floor((span * radius) / SLOT)));
    rings.push({ radius, count });
    left -= count;
    radius += RING_STEP;
  }
  return rings;
}

/** Outer radius of the moon rings around a body (0 without moons). */
const outerRing = (rings: { radius: number }[]) => (rings.length ? rings[rings.length - 1].radius : 0);

/**
 * Put `moons` (in order) on their rings around `centre`, fanned around `towards` over at most `span`.
 * Every other ring is turned half a slot so the labels of neighbouring rings do not line up.
 */
function placeOnRings(
  out: Map<number, Point>,
  moons: OrbitBody[],
  centre: Point,
  rings: { radius: number; count: number }[],
  towards: number,
  span: number,
  full: boolean,
): void {
  let next = 0;
  rings.forEach((ring, index) => {
    const arc = full ? span : Math.min(span, (ring.count * SLOT) / Math.max(ring.radius, 1));
    const shift = index % 2 ? arc / ring.count / 2 : 0;
    fan(ring.count, towards + shift, arc).forEach((a) => out.set(moons[next++].id, polar(centre, ring.radius, a)));
  });
}

/** Moons of one body in drawing order: grouped by device group, then subnet, so related devices sit together. */
function moonOrder(list: OrbitBody[]): OrbitBody[] {
  const key = (v: number | null | undefined) => (v == null ? Number.MAX_SAFE_INTEGER : v);
  return [...list].sort(
    (a, b) => key(a.device.group_id) - key(b.device.group_id) || key(a.device.subnet_id) - key(b.device.subnet_id) || a.id - b.id,
  );
}

/** Angles of `n` items spread evenly over `span`, centred on `centre`. */
function fan(n: number, centre: number, span: number): number[] {
  if (n === 1) return [centre];
  const step = span / n;
  return Array.from({ length: n }, (_, i) => centre - span / 2 + step * (i + 0.5));
}

// ── Radial tree ("balloon") layout ──────────────────────────────────────────
//
// Every body owns a disc that holds its whole subtree. A parent puts the children that have children of their own
// (branches) at a short hop, each in an angular wedge just wide enough for its disc, and the children without any
// (leaves: VMs, containers, clients, a lone switch) on a small local ring in the wedge that is left. Wedges never
// overlap, so subtrees never cross and every edge stays inside its parent's wedge.

/** Shortest edge from a parent to a child that carries a subtree of its own. */
const HOP_MIN = 150;
/** Air between two neighbouring subtree discs. */
const SUB_GAP = 28;
/** What a child's disc must keep clear of its parent: the parent body and its label. */
const PARENT_CLEAR = BODY_RADIUS.planet + LABEL_PAD;
/** Leaves fit on at most this many local rings before the branches move further out. */
const MAX_LEAF_RINGS = 3;

interface Fan {
  /** Children with children, in drawing order: distance from the parent and wedge angle */
  branches: { body: OrbitBody; dist: number; arc: number }[];
  leaves: OrbitBody[];
  rings: { radius: number; count: number }[];
  /** Arc the leaf rings use */
  leafArc: number;
  /** Radius of the disc around the body that holds its whole subtree */
  reach: number;
}

function childrenByParent(bodies: Map<number, OrbitBody>): Map<number, OrbitBody[]> {
  const kids = new Map<number, OrbitBody[]>();
  for (const b of bodies.values()) {
    if (b.parentId == null || b.parentId === b.id || !bodies.has(b.parentId)) continue;
    if (!kids.has(b.parentId)) kids.set(b.parentId, []);
    kids.get(b.parentId)!.push(b);
  }
  for (const list of kids.values()) list.sort((a, b) => a.id - b.id);
  return kids;
}

/** Arc of the leaf rings: the root fills what is left, others only what their leaves need. */
function leafArcOf(rings: { radius: number; count: number }[], rest: number, full: boolean): number {
  if (!rings.length) return 0;
  if (full) return rest;
  return Math.min(rest, Math.max(...rings.map((r) => (r.count * SLOT) / r.radius)));
}

/** Branches of a body at `scale` times their shortest hop, each with the wedge its disc needs. */
function branchFan(branchBodies: OrbitBody[], reachOf: Map<number, number>, scale: number): Fan['branches'] {
  return branchBodies.map((c) => {
    const r = reachOf.get(c.id)!;
    const dist = Math.round(Math.max(HOP_MIN, r + PARENT_CLEAR) * scale);
    return { body: c, dist, arc: 2 * Math.asin(Math.min(1, (r + SUB_GAP / 2) / dist)) };
  });
}

/** Measure every subtree bottom-up: how far its children sit and how big a disc it needs. */
function measureFans(roots: OrbitBody[], kids: Map<number, OrbitBody[]>): Map<number, Fan> {
  const fans = new Map<number, Fan>();
  const visiting = new Set<number>();

  function measure(body: OrbitBody, isRoot: boolean): number {
    const known = fans.get(body.id);
    if (known) return known.reach;
    visiting.add(body.id);
    const children = (kids.get(body.id) ?? []).filter((c) => !visiting.has(c.id));
    const branchBodies = children.filter((c) => (kids.get(c.id) ?? []).length > 0);
    const leaves = moonOrder(children.filter((c) => !branchBodies.includes(c)));
    const reachOf = new Map(branchBodies.map((c) => [c.id, measure(c, false)]));
    const span = isRoot ? TAU : MOON_FAN;
    const ringMin = isRoot ? STAR_MOON_RING_MIN : MOON_RING_MIN;

    // Push the branches out step by step until they and the leaves share the span
    let branches: Fan['branches'] = [];
    let rings: Fan['rings'] = [];
    let rest = span;
    for (let step = 0, scale = 1; step < 40; step++, scale *= 1.12) {
      branches = branchFan(branchBodies, reachOf, scale);
      rest = span - branches.reduce((s, b) => s + b.arc, 0);
      if (rest < 0) continue;
      if (!leaves.length) break;
      rings = packRings(leaves.length, Math.max(rest, 0.01), ringMin);
      if (rings.length <= MAX_LEAF_RINGS && rest > 0.2) break;
    }
    rest = Math.max(rest, 0);
    if (leaves.length && !rings.length) rings = packRings(leaves.length, Math.max(rest, 0.01), ringMin);

    // The root shares a full circle: spread the branches when nothing else needs the room
    if (isRoot && !leaves.length && rest > 0 && branches.length) {
      const used = TAU - rest;
      branches = branches.map((b) => ({ ...b, arc: (b.arc / used) * TAU }));
      rest = 0;
    }
    const leafArc = leafArcOf(rings, rest, isRoot);
    const leafReach = rings.length ? outerRing(rings) + BODY_RADIUS.moon + LABEL_PAD : 0;
    const branchReach = Math.max(0, ...branches.map((b) => b.dist + reachOf.get(b.body.id)!));
    const reach = Math.max(BODY_RADIUS.star + LABEL_PAD, leafReach, branchReach);
    fans.set(body.id, { branches, leaves, rings, leafArc, reach });
    visiting.delete(body.id);
    return reach;
  }

  for (const root of roots) measure(root, true);
  return fans;
}

/**
 * Place a body's children around it, top-down. The leaves are centred on `towards` (away from the parent), the
 * branches flank them, half on each side, so a chain runs straight on and a host's VMs fan out behind it.
 */
function placeFan(out: Map<number, Point>, fans: Map<number, Fan>, body: OrbitBody, pos: Point, towards: number): void {
  const fan = fans.get(body.id);
  if (!fan) return;
  const half = Math.ceil(fan.branches.length / 2);
  const before = fan.branches.slice(0, half);
  const after = fan.branches.slice(half);
  const beforeArc = before.reduce((s, b) => s + b.arc, 0);
  const total = beforeArc + fan.leafArc + after.reduce((s, b) => s + b.arc, 0);
  let cursor = fan.leaves.length ? towards - fan.leafArc / 2 - beforeArc : towards - total / 2;

  const placeBranch = (b: Fan['branches'][number]) => {
    const angle = cursor + b.arc / 2;
    const at = polar(pos, b.dist, angle);
    out.set(b.body.id, at);
    placeFan(out, fans, b.body, at, angle);
    cursor += b.arc;
  };
  before.forEach(placeBranch);
  if (fan.leaves.length) {
    placeOnRings(out, fan.leaves, pos, fan.rings, cursor + fan.leafArc / 2, fan.leafArc, true);
    cursor += fan.leafArc;
  }
  after.forEach(placeBranch);
}

/** Positions for every body: one radial tree per star (its root at the centre), trees side by side. */
export function layoutOrbit(bodies: Map<number, OrbitBody>): Map<number, Point> {
  const kids = childrenByParent(bodies);
  const roots = [...bodies.values()]
    .filter((b) => b.parentId == null || b.parentId === b.id || !bodies.has(b.parentId))
    .sort((a, b) => (a.kind === 'star' ? 0 : 1) - (b.kind === 'star' ? 0 : 1) || a.id - b.id);
  const fans = measureFans(roots, kids);

  const out = new Map<number, Point>();
  let cursorX = 0;
  let previousReach = 0;
  roots.forEach((root, index) => {
    const reach = fans.get(root.id)?.reach ?? BODY_RADIUS.star + LABEL_PAD;
    if (index > 0) cursorX += previousReach + SYSTEM_GAP + reach;
    previousReach = reach;
    const centre = { x: cursorX, y: 0 };
    out.set(root.id, centre);
    // The root's own leaves sit on top, its branches around them
    placeFan(out, fans, root, centre, -Math.PI / 2);
  });
  return out;
}

// ── Labels ───────────────────────────────────────────────────────────────────

export type LabelSide = 'below' | 'above' | 'right' | 'left';
export interface LabelPlacement {
  side: LabelSide;
  /** Offset of the text anchor (first line baseline) from the body centre */
  x: number;
  y: number;
  anchor: 'middle' | 'start' | 'end';
}
interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

const BASE_LINE = 13;
export function labelSize(name: string, ip: string, extraLine: boolean): { w: number; h: number } {
  return { w: Math.max(name.length * 7.1, ip.length * 6.2) + 8, h: BASE_LINE * (extraLine ? 3 : 2) + 2 };
}

/**
 * Order in which labels claim their space: stars, then planets, then moons that need attention,
 * then healthy moons. A moon that is offline or degraded keeps its label at overview zoom.
 */
export function labelRank(body: Pick<OrbitBody, 'kind' | 'state'>): number {
  if (body.kind === 'star') return 0;
  if (body.kind === 'planet') return 1;
  return body.state === 'online' ? 3 : 2;
}

/** Bodies that need attention, offline before degraded (map order otherwise). */
export function problemBodyIds(bodies: Pick<OrbitBody, 'id' | 'state'>[]): number[] {
  return [...bodies.filter((b) => b.state === 'offline'), ...bodies.filter((b) => b.state === 'degraded')].map((b) => b.id);
}

function boxFor(p: Point, r: number, size: { w: number; h: number }, side: LabelSide, scale = 1): { box: Box; place: LabelPlacement } {
  const gap = 6;
  const LINE = BASE_LINE * scale;
  switch (side) {
    case 'above':
      return { box: { x1: p.x - size.w / 2, y1: p.y - r - gap - size.h, x2: p.x + size.w / 2, y2: p.y - r - gap }, place: { side, x: 0, y: -r - gap - size.h + LINE - 2, anchor: 'middle' } };
    case 'right':
      return { box: { x1: p.x + r + gap, y1: p.y - size.h / 2, x2: p.x + r + gap + size.w, y2: p.y + size.h / 2 }, place: { side, x: r + gap, y: -size.h / 2 + LINE - 2, anchor: 'start' } };
    case 'left':
      return { box: { x1: p.x - r - gap - size.w, y1: p.y - size.h / 2, x2: p.x - r - gap, y2: p.y + size.h / 2 }, place: { side, x: -r - gap, y: -size.h / 2 + LINE - 2, anchor: 'end' } };
    default:
      return { box: { x1: p.x - size.w / 2, y1: p.y + r + gap, x2: p.x + size.w / 2, y2: p.y + r + gap + size.h }, place: { side: 'below', x: 0, y: r + gap + LINE - 2, anchor: 'middle' } };
  }
}

const overlaps = (a: Box, b: Box) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
const hitsCircle = (b: Box, c: Point, r: number) => {
  const nx = Math.max(b.x1, Math.min(c.x, b.x2));
  const ny = Math.max(b.y1, Math.min(c.y, b.y2));
  return Math.hypot(nx - c.x, ny - c.y) < r + 2;
};

type LabelItem = { id: number; pos: Point; radius: number; size: { w: number; h: number }; rank: number };
type LabelObstacle = { id: number; pos: Point; radius: number };
type LabelClaim = { box: Box; place: LabelPlacement };

const LABEL_SIDES: LabelSide[] = ['below', 'above', 'right', 'left'];

function isFree(box: Box, ownId: number, placed: Box[], obstacles: LabelObstacle[]): boolean {
  return !placed.some((b) => overlaps(b, box)) && !obstacles.some((o) => o.id !== ownId && hitsCircle(box, o.pos, o.radius));
}

/** The first free spot: every side next to the body, then the same sides up to three label heights further out. */
function freeClaim(item: LabelItem, size: { w: number; h: number }, scale: number, placed: Box[], obstacles: LabelObstacle[]): LabelClaim | null {
  for (let ring = 0; ring < 4; ring++) {
    for (const side of LABEL_SIDES) {
      const candidate = boxFor(item.pos, item.radius + ring * size.h, size, side, scale);
      if (isFree(candidate.box, item.id, placed, obstacles)) return candidate;
    }
  }
  return null;
}

/**
 * Put every label where it collides with nothing: below the body if free, else above, right or
 * left (stars first, then planets, then moons). When every side is taken it tries the same sides
 * a label height further out, up to three times, and only then falls back to below.
 */
export function placeLabels(
  items: LabelItem[],
  /** Labels drawn larger than 1:1 (counter-scaled against the zoom) need larger boxes */
  scale = 1,
  /** Bodies whose circles labels must avoid, labelled or not (defaults to `items`) */
  obstacles: LabelObstacle[] = items,
): Map<number, LabelPlacement> {
  const placed: Box[] = [];
  const out = new Map<number, LabelPlacement>();
  const order = [...items].sort((a, b) => a.rank - b.rank || a.id - b.id);
  for (const item of order) {
    const size = { w: item.size.w * scale, h: item.size.h * scale };
    const chosen = freeClaim(item, size, scale, placed, obstacles) ?? boxFor(item.pos, item.radius, size, 'below', scale);
    placed.push(chosen.box);
    out.set(item.id, chosen.place);
  }
  return out;
}

// ── Beams ────────────────────────────────────────────────────────────────────

/**
 * SVG path of a beam. Between two bodies on rings around the same centre the beam bends along
 * the orbit (a transfer arc) instead of cutting across the star; otherwise it is straight.
 * Also returns the point halfway along it, for the link-type badge.
 */
export function beamPath(a: Point, b: Point, centre: Point | null): { d: string; mid: Point } {
  const straight = { d: `M${a.x},${a.y} L${b.x},${b.y}`, mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
  if (!centre) return straight;
  const ra = Math.hypot(a.x - centre.x, a.y - centre.y);
  const rb = Math.hypot(b.x - centre.x, b.y - centre.y);
  if (ra < 30 || rb < 30) return straight;
  const ta = Math.atan2(a.y - centre.y, a.x - centre.x);
  const tb = Math.atan2(b.y - centre.y, b.x - centre.x);
  let delta = tb - ta;
  while (delta > Math.PI) delta -= TAU;
  while (delta < -Math.PI) delta += TAU;
  if (Math.abs(delta) < 0.3) return straight;
  const mid = polar(centre, (ra + rb) / 2, ta + delta / 2);
  // Quadratic control point so the curve passes through `mid`
  const cx = Math.round(2 * mid.x - (a.x + b.x) / 2);
  const cy = Math.round(2 * mid.y - (a.y + b.y) / 2);
  return { d: `M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`, mid };
}

// ── Background ───────────────────────────────────────────────────────────────

export interface CosmicStar {
  id: number;
  x: number;
  y: number;
  r: number;
  opacity: number;
}

/**
 * Twinkling stars fade in this many groups, not one by one: every animated element on the map is
 * a compositor layer of its own, and with one per star each scrolled frame of the dashboard cost
 * about 40 ms instead of 8.
 */
export const TWINKLE_GROUPS = 3;

/** Deterministic background stars: the still ones, and the twinkling ones by group. */
export function cosmicStarfield(count = 96): { still: CosmicStar[]; twinkling: CosmicStar[][] } {
  let seed = 1337;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  const still: CosmicStar[] = [];
  const twinkling: CosmicStar[][] = Array.from({ length: TWINKLE_GROUPS }, () => []);
  for (let id = 0; id < count; id++) {
    const star = {
      id,
      x: Math.round((rand() - 0.48) * 3600),
      y: Math.round((rand() - 0.48) * 2600),
      r: rand() > 0.86 ? 1.4 : rand() > 0.45 ? 1.0 : 0.65,
      opacity: Math.round((0.25 + rand() * 0.55) * 100) / 100,
    };
    const twinkles = rand() > 0.4;
    const group = Math.floor(rand() * TWINKLE_GROUPS);
    (twinkles ? twinkling[group] : still).push(star);
  }
  return { still, twinkling };
}
