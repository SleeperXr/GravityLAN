/**
 * Pure helpers for Orbit map interaction (focus mode, search, viewport fitting).
 * Kept free of Vue/DOM so they stay unit-testable.
 */
import type { LightBeam, OrbitBody, Point } from './orbitModel';

export interface FocusSet {
  /** Body ids that stay fully visible. */
  bodyIds: Set<number>;
  /** Beam ids that stay fully visible. */
  beamIds: Set<number>;
}

export interface ViewTransform {
  x: number;
  y: number;
  zoom: number;
}

/** Low enough that a phone-sized map can show a whole system */
export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 2.5;

/**
 * Everything "close" to a body: itself, its parent, its direct moons
 * and every device connected to it by a light beam.
 */
export function computeFocusSet(
  focusId: number,
  bodies: Map<number, OrbitBody>,
  beams: LightBeam[],
): FocusSet {
  const bodyIds = new Set<number>();
  const beamIds = new Set<number>();
  const focus = bodies.get(focusId);
  if (!focus) return { bodyIds, beamIds };

  bodyIds.add(focusId);
  if (focus.parentId != null) bodyIds.add(focus.parentId);
  for (const b of bodies.values()) {
    if (b.parentId === focusId) bodyIds.add(b.id);
  }
  for (const beam of beams) {
    if (beam.sourceId === focusId || beam.targetId === focusId) {
      bodyIds.add(beam.sourceId);
      bodyIds.add(beam.targetId);
    }
  }
  for (const beam of beams) {
    if (bodyIds.has(beam.sourceId) && bodyIds.has(beam.targetId)) beamIds.add(beam.id);
  }
  return { bodyIds, beamIds };
}

/** Set built from a plain list of body ids (e.g. search hits). */
export function focusSetFromIds(ids: number[], beams: LightBeam[]): FocusSet {
  const bodyIds = new Set(ids);
  const beamIds = new Set<number>();
  for (const beam of beams) {
    if (bodyIds.has(beam.sourceId) && bodyIds.has(beam.targetId)) beamIds.add(beam.id);
  }
  return { bodyIds, beamIds };
}

/** Case-insensitive match over label, IP, hostname-ish text and role badge. */
export function matchBodies(
  query: string,
  bodies: Iterable<OrbitBody>,
  labelOf: (body: OrbitBody) => string,
): OrbitBody[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: OrbitBody[] = [];
  for (const body of bodies) {
    const haystack = `${labelOf(body)} ${body.device.ip ?? ''}`.toLowerCase();
    if (haystack.includes(q)) hits.push(body);
  }
  return hits;
}

/** Viewport transform that frames `points` (plus margin) inside a width x height box. */
export function fitTransform(
  points: Point[],
  width: number,
  height: number,
  options: { margin?: number; padding?: number; maxZoom?: number } = {},
): ViewTransform | null {
  if (points.length === 0 || width <= 0 || height <= 0) return null;
  const { margin = 90, padding = 0.78, maxZoom = 1.6 } = options;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const p of points) {
    minX = Math.min(minX, p.x - margin);
    maxX = Math.max(maxX, p.x + margin);
    minY = Math.min(minY, p.y - margin);
    maxY = Math.max(maxY, p.y + margin);
  }
  const contentW = Math.max(240, maxX - minX);
  const contentH = Math.max(240, maxY - minY);
  const zoom = Math.min(
    maxZoom,
    Math.max(MIN_ZOOM, Math.min((width * padding) / contentW, (height * padding) / contentH)),
  );
  return {
    zoom,
    x: Math.round(width / 2 - ((minX + maxX) / 2) * zoom),
    y: Math.round(height / 2 - ((minY + maxY) / 2) * zoom),
  };
}

/** Zoom around a screen-space anchor so the point under the anchor stays fixed. */
export function zoomAround(
  view: ViewTransform,
  anchor: Point,
  factor: number,
): ViewTransform {
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom * factor));
  const ratio = zoom / view.zoom;
  return {
    zoom,
    x: anchor.x - (anchor.x - view.x) * ratio,
    y: anchor.y - (anchor.y - view.y) * ratio,
  };
}

export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

export function lerpView(a: ViewTransform, b: ViewTransform, t: number): ViewTransform {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    zoom: a.zoom + (b.zoom - a.zoom) * t,
  };
}

export interface TracedPath {
  /** Body ids from start to end (inclusive). */
  bodyIds: number[];
  /** Beam ids in travel order (length = bodyIds.length - 1). */
  beamIds: number[];
  /** True if at least one hop crosses an interrupted beam. */
  broken: boolean;
}

function bfsPath(fromId: number, toId: number, beams: LightBeam[]): TracedPath | null {
  if (fromId === toId) return { bodyIds: [fromId], beamIds: [], broken: false };
  const adjacency = new Map<number, { to: number; beam: LightBeam }[]>();
  for (const beam of beams) {
    for (const [a, b] of [
      [beam.sourceId, beam.targetId],
      [beam.targetId, beam.sourceId],
    ] as const) {
      const list = adjacency.get(a) ?? [];
      list.push({ to: b, beam });
      adjacency.set(a, list);
    }
  }

  const previous = new Map<number, { from: number; beam: LightBeam }>();
  const visited = new Set<number>([fromId]);
  const queue: number[] = [fromId];
  for (let head = 0; head < queue.length; head++) {
    const current = queue[head];
    for (const edge of adjacency.get(current) ?? []) {
      if (visited.has(edge.to)) continue;
      visited.add(edge.to);
      previous.set(edge.to, { from: current, beam: edge.beam });
      if (edge.to === toId) {
        const bodyIds = [toId];
        const path: LightBeam[] = [];
        let step = toId;
        while (step !== fromId) {
          const prev = previous.get(step)!;
          path.push(prev.beam);
          bodyIds.push(prev.from);
          step = prev.from;
        }
        bodyIds.reverse();
        path.reverse();
        return {
          bodyIds,
          beamIds: path.map((b) => b.id),
          broken: path.some((b) => b.interrupted),
        };
      }
      queue.push(edge.to);
    }
  }
  return null;
}

/**
 * Shortest hop path between two bodies along light beams.
 * Prefers a route over healthy beams; falls back to one crossing interrupted
 * beams (flagged `broken`). Returns null if the bodies are not connected at all.
 */
export function findPath(
  fromId: number,
  toId: number,
  beams: LightBeam[],
): TracedPath | null {
  return (
    bfsPath(
      fromId,
      toId,
      beams.filter((b) => !b.interrupted),
    ) ?? bfsPath(fromId, toId, beams)
  );
}