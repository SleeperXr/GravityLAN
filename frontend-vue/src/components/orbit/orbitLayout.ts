/**
 * Orbit geometry: where bodies sit, where their labels go and how beams bend.
 *
 * Layout ("solar system"):
 * - The router (star) sits at the centre of its system.
 * - Planets (switches, APs, hosts) circle the star on concentric tier rings: tier 1 are the
 *   planets hanging off the star, tier 2 the planets hanging off tier 1, and so on. Each ring is
 *   just big enough that the planets' own moon systems never overlap.
 * - Moons (endpoints, VMs, WLAN clients) circle their planet on a small ring, fanned away from
 *   the star so the beam towards the centre stays clear.
 */
import type { OrbitBody, Point } from './orbitModel';

export const BODY_RADIUS = { star: 22, planet: 16, dwarf: 12.5, moon: 10.5 } as const;

/** Drawn radius of a body; dwarf planets are smaller planets. */
export const radiusOf = (body: Pick<OrbitBody, 'kind' | 'dwarf'>) => (body.kind === 'planet' && body.dwarf ? BODY_RADIUS.dwarf : BODY_RADIUS[body.kind]);

const SLOT = 104; // arc (world px) one body plus its label needs on a ring
const MOON_RING_MIN = 82;
const STAR_MOON_RING_MIN = 120;
const LABEL_PAD = 38; // room for the two label lines below a body
const TIER_GAP = 40;
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

function childrenOf(bodies: Map<number, OrbitBody>) {
  const moons = new Map<number, OrbitBody[]>();
  const planets = new Map<number, OrbitBody[]>();
  for (const b of bodies.values()) {
    if (b.parentId == null || !bodies.has(b.parentId)) continue;
    const target = b.kind === 'moon' ? moons : planets;
    if (!target.has(b.parentId)) target.set(b.parentId, []);
    target.get(b.parentId)!.push(b);
  }
  const byId = (a: OrbitBody, b: OrbitBody) => a.id - b.id;
  for (const list of [...moons.values(), ...planets.values()]) list.sort(byId);
  return { moons, planets };
}

/** Radius of a ring that fits `n` bodies on an arc of `span` radians, never below `min`. */
function ringRadius(n: number, span: number, min: number): number {
  return n === 0 ? 0 : Math.max(min, Math.ceil((n * SLOT) / span));
}

/** Angles of `n` items spread evenly over `span`, centred on `centre`. */
function fan(n: number, centre: number, span: number): number[] {
  if (n === 1) return [centre];
  const step = span / n;
  return Array.from({ length: n }, (_, i) => centre - span / 2 + step * (i + 0.5));
}

/** Positions for every body, one solar system per star, systems side by side. */
export function layoutOrbit(bodies: Map<number, OrbitBody>): Map<number, Point> {
  const { moons, planets } = childrenOf(bodies);
  const roots = [...bodies.values()].filter((b) => b.parentId == null || !bodies.has(b.parentId)).sort((a, b) => (a.kind === 'star' ? 0 : 1) - (b.kind === 'star' ? 0 : 1) || a.id - b.id);

  /** Radius a planet's own system needs: its moon ring plus their labels. */
  const extentCache = new Map<number, number>();
  function extent(p: OrbitBody): number {
    if (extentCache.has(p.id)) return extentCache.get(p.id)!;
    const n = moons.get(p.id)?.length ?? 0;
    const value = n ? ringRadius(n, MOON_FAN, MOON_RING_MIN) + BODY_RADIUS.moon + LABEL_PAD : BODY_RADIUS.planet + LABEL_PAD;
    extentCache.set(p.id, value);
    return value;
  }

  /** Sector weight of a planet: the number of leaf planets below it (itself when it has none). */
  const weightCache = new Map<number, number>();
  function weight(p: OrbitBody): number {
    if (weightCache.has(p.id)) return weightCache.get(p.id)!;
    const kids = planets.get(p.id) ?? [];
    const value = kids.length ? kids.reduce((s, k) => s + weight(k), 0) : 1;
    weightCache.set(p.id, value);
    return value;
  }

  const out = new Map<number, Point>();
  let cursorX = 0;
  let previousRadius = 0;

  roots.forEach((root, index) => {
    const local = new Map<number, Point>();
    const centre = { x: 0, y: 0 };
    local.set(root.id, centre);

    // Moons of the star on their own ring around it
    const starMoons = moons.get(root.id) ?? [];
    const rStar = ringRadius(starMoons.length, TAU, STAR_MOON_RING_MIN);
    fan(starMoons.length, -Math.PI / 2 + Math.PI / Math.max(1, starMoons.length), TAU).forEach((a, i) => local.set(starMoons[i].id, polar(centre, rStar, a)));
    let reach = starMoons.length ? rStar + BODY_RADIUS.moon + LABEL_PAD : BODY_RADIUS.star + LABEL_PAD;

    // Planets tier by tier, as a radial tree: every planet owns a sector of the circle, sized
    // by how much hangs below it, and its child planets share that sector. So a single core
    // switch still spreads its servers and APs all around the router.
    const sector = new Map<number, { start: number; span: number }>();
    const tier1 = planets.get(root.id) ?? [];
    const w1 = tier1.map(weight);
    const w1Total = w1.reduce((s, w) => s + w, 0) || 1;
    let start = -Math.PI / 2 - ((w1[0] ?? 1) / w1Total) * Math.PI;
    tier1.forEach((p, i) => {
      const span = (w1[i] / w1Total) * TAU;
      sector.set(p.id, { start, span });
      start += span;
    });

    let tier = tier1;
    while (tier.length) {
      const maxExtent = Math.max(...tier.map(extent));
      // Ring big enough to clear the inner rings and to give every planet the arc it needs
      let radius = Math.round(reach + maxExtent + TIER_GAP);
      for (const p of tier) radius = Math.max(radius, Math.ceil((2 * extent(p) + TIER_GAP) / Math.max(sector.get(p.id)!.span, 0.05)));

      for (const p of tier) {
        const s = sector.get(p.id)!;
        const angle = s.start + s.span / 2;
        const pos = polar(centre, radius, angle);
        local.set(p.id, pos);
        // The planet's moons, fanned away from the star
        const own = moons.get(p.id) ?? [];
        const rMoon = ringRadius(own.length, MOON_FAN, MOON_RING_MIN);
        fan(own.length, angle, Math.min(MOON_FAN, (own.length * SLOT) / Math.max(rMoon, 1))).forEach((a, k) => local.set(own[k].id, polar(pos, rMoon, a)));
        // Split the sector among the child planets
        const kids = planets.get(p.id) ?? [];
        const wk = kids.map(weight);
        const wTotal = wk.reduce((sum, w) => sum + w, 0) || 1;
        let a = s.start;
        kids.forEach((k, i) => {
          const span = (wk[i] / wTotal) * s.span;
          sector.set(k.id, { start: a, span });
          a += span;
        });
      }

      reach = radius + maxExtent;
      tier = tier.flatMap((p) => planets.get(p.id) ?? []);
    }

    // Systems side by side along x
    const systemRadius = reach;
    if (index > 0) cursorX += previousRadius + SYSTEM_GAP + systemRadius;
    previousRadius = systemRadius;
    for (const [id, p] of local) out.set(id, { x: p.x + cursorX, y: p.y });
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

/**
 * Put every label where it collides with nothing: below the body if free, else above, right or
 * left (stars first, then planets, then moons). When every side is taken it tries the same sides
 * a label height further out, up to three times, and only then falls back to below.
 */
export function placeLabels(
  items: { id: number; pos: Point; radius: number; size: { w: number; h: number }; rank: number }[],
  /** Labels drawn larger than 1:1 (counter-scaled against the zoom) need larger boxes */
  scale = 1,
  /** Bodies whose circles labels must avoid, labelled or not (defaults to `items`) */
  obstacles: { id: number; pos: Point; radius: number }[] = items,
): Map<number, LabelPlacement> {
  const placed: Box[] = [];
  const out = new Map<number, LabelPlacement>();
  const order = [...items].sort((a, b) => a.rank - b.rank || a.id - b.id);
  for (const item of order) {
    const size = { w: item.size.w * scale, h: item.size.h * scale };
    let chosen: { box: Box; place: LabelPlacement } | null = null;
    for (let ring = 0; ring < 4 && !chosen; ring++) {
      for (const side of ['below', 'above', 'right', 'left'] as LabelSide[]) {
        const candidate = boxFor(item.pos, item.radius + ring * size.h, size, side, scale);
        const blocked = placed.some((b) => overlaps(b, candidate.box)) || obstacles.some((o) => o.id !== item.id && hitsCircle(candidate.box, o.pos, o.radius));
        if (!blocked) {
          chosen = candidate;
          break;
        }
      }
    }
    chosen ??= boxFor(item.pos, item.radius, size, 'below', scale);
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
