/**
 * Where the rack stage draws things, in px. Everything here is computed from the model rather than measured on
 * the page, so a faceplate that is being dragged or is settling, and the cables plugged into it, can be drawn for
 * every frame of the motion. Units count from the bottom as on the rails: unit 1 is the lowest.
 */
import type { RackPort } from '@/types';
import type { RackEntry } from './rackModel';

export interface Point {
  x: number;
  y: number;
}

/** The rack as drawn: the unit rail on the left, the faceplates, the cable channel on the right. */
export interface RackFrame {
  units: number;
  unitPx: number;
  railPx: number;
  facePx: number;
  channelPx: number;
  padPx: number;
}

export const MIN_UNIT_PX = 18;
export const MAX_UNIT_PX = 30;
const RAIL_PX = 30;
const CHANNEL_PX = 84;
/** On a phone the channel gets narrower, so a 19-inch rack still fits the width */
const NARROW_CHANNEL_PX = 60;
const PAD_PX = 10;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const round = (value: number) => Math.round(value * 10) / 10;

/**
 * A frame that fits the box: units as tall as the height allows (within limits, so a 60-unit rack scrolls rather
 * than turning into hairlines), faceplates as wide as the width allows. A 10″ rack is a little over half as wide.
 */
export function rackFrame(units: number, inches: number, box: { width: number; height: number }, detail = false): RackFrame {
  // Detail: every unit at full height, the rack scrolls; otherwise it fits the height as far as it can
  const unitPx = detail ? MAX_UNIT_PX : clamp(Math.floor((box.height - 2 * PAD_PX) / Math.max(1, units)), MIN_UNIT_PX, MAX_UNIT_PX);
  const channelPx = box.width < 480 ? NARROW_CHANNEL_PX : CHANNEL_PX;
  const full = clamp(Math.floor(box.width - RAIL_PX - channelPx), 220, 560);
  const facePx = inches === 10 ? Math.max(200, Math.round(full * 0.56)) : full;
  return { units, unitPx, railPx: RAIL_PX, facePx, channelPx, padPx: PAD_PX };
}

export const frameWidth = (f: RackFrame): number => f.railPx + f.facePx + f.channelPx;
export const frameHeight = (f: RackFrame): number => f.units * f.unitPx + 2 * f.padPx;
/** Top edge of a unit. */
export const unitTop = (f: RackFrame, unit: number): number => f.padPx + (f.units - unit) * f.unitPx;
/** Top edge of a faceplate whose top unit is `unit`; one px of air above and below each faceplate. */
export const faceTop = (f: RackFrame, unit: number): number => unitTop(f, unit) + 1;
export const faceHeight = (f: RackFrame, height: number): number => height * f.unitPx - 2;
/** The top unit a faceplate snaps to when its top edge is at `top`. */
export const snapUnit = (f: RackFrame, top: number): number => f.units - Math.round((top - 1 - f.padPx) / f.unitPx);

// ── Faceplates ───────────────────────────────────────────────────────────────

/** A jack on a faceplate, relative to the faceplate's top left corner. */
export interface JackSpot {
  portId: number;
  number: number;
  kind: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface FaceLayout {
  /** Width of the mounting ear on either side */
  earPx: number;
  jacks: JackSpot[];
  /** Left edge of the jack field; the label and the decoration end before it */
  jackLeft: number;
  /** Whether a second line of text fits */
  twoLines: boolean;
}

export const EAR_PX = 10;
/** Room the label keeps on the left before jacks start: about a third of the faceplate, within limits */
const labelRoom = (facePx: number) => clamp(Math.round(facePx * 0.3), 96, 150);
/** Pitch and shape per port kind: RJ45 nearly square, SFP wide and flat, LC narrow and tall, power inlets large. */
const JACK_SHAPES: Record<string, { pitch: number; aspect: number }> = {
  RJ45: { pitch: 14, aspect: 0.82 },
  SFP: { pitch: 18, aspect: 0.5 },
  'SFP+': { pitch: 18, aspect: 0.5 },
  LC: { pitch: 10, aspect: 1.3 },
  Power: { pitch: 20, aspect: 0.72 },
  Console: { pitch: 14, aspect: 0.82 },
};

/**
 * The jack field of a faceplate, right-aligned as on real hardware. More than 24 ports (or more than 12 on a
 * faceplate of two units or more) take two rows with odd ports on top, and every 12 columns get a small gap.
 * Jacks shrink until they fit, so a 48-port switch still sits on one unit.
 */
export function faceLayout(ports: RackPort[], facePx: number, heightPx: number): FaceLayout {
  const twoLines = heightPx >= 34;
  const sorted = [...ports].sort((a, b) => a.number - b.number);
  const count = sorted.length;
  if (!count) return { earPx: EAR_PX, jacks: [], jackLeft: facePx - EAR_PX, twoLines };
  const shape = JACK_SHAPES[sorted[0].kind] ?? JACK_SHAPES.RJ45;
  const rows = count > 24 || (count > 12 && heightPx >= 40) ? 2 : 1;
  const cols = Math.ceil(count / rows);
  const groups = Math.ceil(cols / 12);
  const field = Math.max(48, facePx - 2 * EAR_PX - labelRoom(facePx) - 16);
  const pitch = Math.min(shape.pitch, field / (cols + (groups - 1) * 0.6));
  const groupGap = pitch * 0.6;
  const rowGap = 2;
  const rowH = Math.min(12, (heightPx - 6 - (rows - 1) * rowGap) / rows);
  const w = Math.max(3, round(pitch * 0.74));
  const h = Math.max(3, round(Math.min(rowH, w * shape.aspect)));
  const total = cols * pitch + (groups - 1) * groupGap;
  const left = facePx - EAR_PX - 8 - total;
  const top = (heightPx - (rows * h + (rows - 1) * rowGap)) / 2;
  const jacks = sorted.map((port, i) => {
    const col = rows === 2 ? Math.floor(i / 2) : i;
    const row = rows === 2 ? i % 2 : 0;
    return {
      portId: port.id,
      number: port.number,
      kind: port.kind,
      x: round(left + col * pitch + Math.floor(col / 12) * groupGap + (pitch - w) / 2),
      y: round(top + row * (h + rowGap)),
      w,
      h,
    };
  });
  return { earPx: EAR_PX, jacks, jackLeft: round(left), twoLines };
}

/** Centre of a jack on the stage, for a faceplate whose top left corner is at `origin`. */
export const jackCentre = (jack: JackSpot, origin: Point): Point => ({ x: round(origin.x + jack.x + jack.w / 2), y: round(origin.y + jack.y + jack.h / 2) });

// ── Cables ───────────────────────────────────────────────────────────────────

/** Two jacks at most this many units apart are joined by a hanging loop; further apart, the cable takes the channel. */
export const SHORT_CABLE_UNITS = 2.5;
export const LANE_PX = 6;
/** How far a patch loop hangs below its jacks at rest */
export const REST_SAG = 14;

export const isShortCable = (f: RackFrame, a: Point, b: Point): boolean => Math.abs(b.y - a.y) <= f.unitPx * SHORT_CABLE_UNITS;
export const laneCount = (f: RackFrame): number => Math.max(1, Math.floor((f.channelPx - 24) / LANE_PX));
export const laneX = (f: RackFrame, lane: number): number => f.railPx + f.facePx + 10 + (lane % laneCount(f)) * LANE_PX;
/** Right edge of the channel, where a cable whose other end is not drawn here leaves. */
export const channelEdge = (f: RackFrame): number => frameWidth(f) - 4;

/** A patch cable between two nearby jacks hangs in a loop below them; `sag` is how far. */
export function loopPath(a: Point, b: Point, sag: number): string {
  return `M ${a.x} ${a.y} C ${round(a.x + 4)} ${round(a.y + sag)} ${round(b.x + 4)} ${round(b.y + sag)} ${b.x} ${b.y}`;
}

/**
 * A longer cable leaves its jack to the side, runs up or down the channel at `lane` and comes back to the other
 * jack. `bow` bends the run sideways while an end is moving, so the cable swings and settles.
 */
export function channelPath(a: Point, b: Point, lane: number, bow = 0): string {
  const dir = b.y >= a.y ? 1 : -1;
  const radius = Math.min(14, Math.abs(b.y - a.y) / 2);
  const midY = round((a.y + b.y) / 2);
  return [
    `M ${a.x} ${a.y}`,
    `C ${round((a.x + lane) / 2)} ${a.y} ${lane} ${a.y} ${lane} ${round(a.y + dir * radius)}`,
    `Q ${round(lane + bow)} ${midY} ${lane} ${round(b.y - dir * radius)}`,
    `C ${lane} ${b.y} ${round((b.x + lane) / 2)} ${b.y} ${b.x} ${b.y}`,
  ].join(' ');
}

/** A cable whose other end is not drawn here (other side, other rack) runs out to `end` at the channel edge. */
export function stubPath(a: Point, end: Point, sag: number): string {
  return `M ${a.x} ${a.y} C ${round(a.x + 16)} ${round(a.y + sag * 0.4)} ${round(end.x - 18)} ${end.y} ${end.x} ${end.y}`;
}

/**
 * A lane in the channel for each long cable. Short cables take the lanes next to the faceplates, and cables whose
 * runs overlap never share a lane while one is free; past the last lane they start over.
 */
export function assignLanes(spans: { id: number; top: number; bottom: number }[], count: number): Map<number, number> {
  const taken: { top: number; bottom: number }[][] = Array.from({ length: count }, () => []);
  const lanes = new Map<number, number>();
  const ordered = [...spans].sort((a, b) => a.bottom - a.top - (b.bottom - b.top) || a.top - b.top);
  ordered.forEach((span, i) => {
    const free = taken.findIndex((runs) => runs.every((run) => span.bottom + 3 < run.top || span.top - 3 > run.bottom));
    const lane = free === -1 ? i % count : free;
    taken[lane].push(span);
    lanes.set(span.id, lane);
  });
  return lanes;
}

// ── Free space ───────────────────────────────────────────────────────────────

/** Runs of free units, top first: where nothing is placed, so the stage can say "6 units free" once instead of six times. */
export function freeRuns(units: number, entries: RackEntry[], skipKey?: string | null): { top: number; length: number }[] {
  const taken = new Set<number>();
  for (const e of entries) {
    if (e.unit === null || e.key === skipKey) continue;
    for (let i = 0; i < e.height; i++) taken.add(e.unit - i);
  }
  const runs: { top: number; length: number }[] = [];
  let unit = units;
  while (unit >= 1) {
    if (taken.has(unit)) {
      unit--;
      continue;
    }
    const top = unit;
    while (unit >= 1 && !taken.has(unit)) unit--;
    runs.push({ top, length: top - unit });
  }
  return runs;
}
