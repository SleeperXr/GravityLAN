<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useResizeObserver } from '@vueuse/core';
import { ChevronsUpDown } from 'lucide-vue-next';
import { t } from '@/i18n';
import type { RackCable, RackPort } from '@/types';
import RackFaceplate from './RackFaceplate.vue';
import RackCables, { type CableDraw, type StubLabel } from './RackCables.vue';
import {
  REST_SAG,
  assignLanes,
  channelEdge,
  channelPath,
  faceHeight,
  faceLayout,
  faceTop,
  frameHeight,
  frameWidth,
  freeRuns,
  isShortCable,
  jackCentre,
  laneCount,
  laneX,
  loopPath,
  rackFrame,
  snapUnit,
  stubPath,
  unitTop,
  type FaceLayout,
  type JackSpot,
  type Point,
} from './rackGeometry';
import { SWING, prefersReducedMotion, stepSpring, useFrameLoop, type Spring } from './rackMotion';
import { blockerAt, cableDefaults, ownerKeyOf, sideOf, type PortSide, type RackEntry } from './rackModel';
import type { DragState, DragTarget } from './useRackDrag';

/**
 * The rack itself. Faceplates sit on their units and move on springs: a dragged faceplate follows the pointer,
 * the place it would land on lights up (or says what is in the way), and on release it settles with a little
 * overshoot while its cables swing along. Cables hang in loops between nearby jacks and run through the
 * channel on the right otherwise; one whose other end is on the other side or in another rack ends at a label
 * that takes you there. Pressing a free jack and pulling draws a new cable, which snaps to the nearest free jack.
 * Turning to the other side spins the rack. The parent decides what a move, a cable or a resize means.
 */
const props = defineProps<{
  rackName: string;
  units: number;
  inches: number;
  /** Entries drawn on their units; anything without a valid place is listed in the store instead */
  entries: RackEntry[];
  ports: RackPort[];
  cables: RackCable[];
  side: PortSide;
  selectedKey: string | null;
  colourOfPort: Record<number, string>;
  downPorts: ReadonlySet<number>;
  accentOf: Record<string, string | null>;
  ownerLabel: Record<string, string>;
  /** Where an owner that is not drawn here is: another rack (its name) or nowhere */
  elsewhere: (ownerKey: string) => { label: string; rackId: number | null };
  ambient: boolean;
  pendingPortId: number | null;
  /** A cable to light up from outside, e.g. the row under the pointer in the inspector */
  highlightCableId: number | null;
  drag: DragState | null;
  /** Every unit at full height (the rack scrolls) instead of the whole rack in view */
  detail: boolean;
  /** Where the cable of each cabled port goes, for the jack tooltips */
  peerOfPort: Record<number, string>;
}>();
const emit = defineEmits<{
  grab: [entry: RackEntry, event: PointerEvent, grab: { x: number; y: number }];
  select: [key: string | null];
  open: [key: string];
  nudge: [key: string, delta: number];
  remove: [key: string];
  connect: [from: number, to: number];
  pick: [portId: number];
  pickCable: [cableId: number];
  stub: [target: { ownerKey: string; side: PortSide | null; rackId: number | null }];
  resize: [units: number];
}>();

const reduceMotion = prefersReducedMotion();
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

// ── Size ─────────────────────────────────────────────────────────────────────
const scrollRef = ref<HTMLElement | null>(null);
const bodyRef = ref<HTMLElement | null>(null);
const box = ref({ width: 0, height: 0 });
useResizeObserver(scrollRef, (observed) => {
  const rect = observed[0].contentRect;
  box.value = { width: rect.width, height: rect.height };
});
// The observer reports on the next frame; measure at once as well, so the rack is there before anything draws
onMounted(() => {
  const el = scrollRef.value;
  if (el && !box.value.height) box.value = { width: el.clientWidth, height: el.clientHeight };
});
const frame = computed(() => rackFrame(props.units, props.inches, { width: box.value.width - 32, height: box.value.height - 52 }, props.detail));

// ── Turning around ───────────────────────────────────────────────────────────
/** The side drawn right now; it changes halfway through the turn */
const shownSide = ref<PortSide>(props.side);
const turn = ref<'none' | 'out' | 'in-start' | 'in'>('none');
let turnToken = 0;
watch(
  () => props.side,
  async (side) => {
    const token = ++turnToken;
    if (reduceMotion) {
      shownSide.value = side;
      return;
    }
    turn.value = 'out';
    await wait(170);
    if (token !== turnToken) return;
    shownSide.value = side;
    turn.value = 'in-start';
    await nextTick();
    void bodyRef.value?.offsetWidth;
    turn.value = 'in';
    await wait(340);
    if (token === turnToken) turn.value = 'none';
  },
);
const turnStyle = computed(() => {
  switch (turn.value) {
    case 'out':
      return { transform: 'perspective(1600px) rotateY(86deg)', transition: 'transform 170ms ease-in' };
    case 'in-start':
      return { transform: 'perspective(1600px) rotateY(-86deg)', transition: 'none' };
    case 'in':
      return { transform: 'perspective(1600px) rotateY(0deg)', transition: 'transform 340ms var(--ease-out-expo)' };
    default:
      return {};
  }
});

// ── Ports and faceplates ─────────────────────────────────────────────────────
const portById = computed(() => new Map(props.ports.map((p) => [p.id, p])));
const entryByKey = computed(() => new Map(props.entries.map((e) => [e.key, e])));
const placed = computed(() => props.entries.filter((e) => e.unit !== null));
const cableOfPort = computed(() => {
  const map = new Map<number, RackCable>();
  for (const c of props.cables) {
    map.set(c.a_port_id, c);
    map.set(c.b_port_id, c);
  }
  return map;
});
const portsByOwner = computed(() => {
  const map = new Map<string, RackPort[]>();
  for (const p of props.ports) {
    const key = ownerKeyOf(p);
    const list = map.get(key);
    if (list) list.push(p);
    else map.set(key, [p]);
  }
  return map;
});
const layouts = computed(() => {
  const f = frame.value;
  const map = new Map<string, FaceLayout>();
  for (const e of placed.value) {
    const own = (portsByOwner.value.get(e.key) ?? []).filter((p) => sideOf(p) === shownSide.value);
    map.set(e.key, faceLayout(own, f.facePx, faceHeight(f, e.height)));
  }
  return map;
});
const otherSidePorts = computed(() => {
  const counts: Record<string, number> = {};
  for (const [key, list] of portsByOwner.value) counts[key] = list.filter((p) => sideOf(p) !== shownSide.value).length;
  return counts;
});
const jackOfPort = computed(() => {
  const map = new Map<number, { key: string; jack: JackSpot }>();
  for (const [key, layout] of layouts.value) for (const jack of layout.jacks) map.set(jack.portId, { key, jack });
  return map;
});

// ── Motion ───────────────────────────────────────────────────────────────────
interface Motion {
  y: Spring;
  x: Spring;
  /** Seconds before it starts falling into place when the rack first fills */
  wait: number;
}
const motion = new Map<string, Motion>();
const sags = new Map<number, Spring>();
const frameNo = ref(0);
const arrived = ref(new Set<string>());
let filled = false;
/** Where the last dragged-in entry was let go, so it settles from there instead of appearing on its unit */
let lastDrop: { key: string; y: number } | null = null;

function syncMotion() {
  if (!box.value.height) return;
  const f = frame.value;
  const firstFill = !filled && placed.value.length > 0;
  const topFirst = [...placed.value].sort((a, b) => (b.unit ?? 0) - (a.unit ?? 0));
  topFirst.forEach((e, order) => {
    if (motion.has(e.key) || e.unit === null) return;
    const y = faceTop(f, e.unit);
    if (firstFill && !reduceMotion) {
      motion.set(e.key, { y: { value: y - 26, velocity: 0 }, x: { value: 0, velocity: 0 }, wait: order * 0.028 });
      return;
    }
    const from = lastDrop?.key === e.key ? lastDrop.y : y;
    motion.set(e.key, { y: { value: from, velocity: 0 }, x: { value: 0, velocity: 0 }, wait: 0 });
    if (filled && from === y && !reduceMotion) {
      arrived.value = new Set(arrived.value).add(e.key);
      window.setTimeout(() => {
        const next = new Set(arrived.value);
        next.delete(e.key);
        arrived.value = next;
      }, 450);
    }
  });
  for (const key of [...motion.keys()]) if (!entryByKey.value.get(key)?.unit) motion.delete(key);
  if (placed.value.length) filled = true;
}

const loop = useFrameLoop(tick);
watch([placed, frame, () => box.value.height], () => {
  syncMotion();
  loop.kick();
});
watch(
  () => (props.drag ? `${props.drag.x},${props.drag.y},${props.drag.lifted},${props.drag.zone}` : ''),
  () => loop.kick(),
);
watch(
  () => props.drag,
  (now, before) => {
    // Remember where a dragged-in entry was let go over the rack
    if (!now && before?.lifted && before.zone === 'stage' && before.from !== 'rack') lastDrop = { key: before.key, y: localOf(before)?.y ?? 0 };
  },
);

/** The pointer of a drag in rack coordinates, or null when it is not over the rack. */
function localOf(d: { x: number; y: number }): Point | null {
  const body = bodyRef.value;
  if (!body) return null;
  const rect = body.getBoundingClientRect();
  return { x: d.x - rect.left, y: d.y - rect.top };
}

function velocityOfPort(portId: number): number {
  const port = portById.value.get(portId);
  const v = port ? (motion.get(ownerKeyOf(port))?.y.velocity ?? 0) : 0;
  return clamp(v, -1500, 1500);
}

function tick(dt: number, stalled = false): boolean {
  const f = frame.value;
  const d = props.drag;
  const draggedKey = d?.lifted && d.from === 'rack' ? d.key : null;
  const local = draggedKey && d ? localOf(d) : null;
  // Frames far apart (a hidden or busy page): everything goes straight to where it belongs
  const snap = reduceMotion || stalled;
  let moving = false;
  for (const e of placed.value) {
    const m = motion.get(e.key);
    if (!m || e.unit === null) continue;
    if (snap) m.wait = 0;
    if (m.wait > 0) {
      m.wait -= dt;
      moving = true;
      continue;
    }
    if (e.key === draggedKey && local && d) {
      // A grabbed faceplate follows the pointer; pulled out of the rack it slides aside
      const y = clamp(local.y - d.grabY, f.padPx - f.unitPx, frameHeight(f) - f.padPx);
      m.y.velocity = dt > 0 ? (y - m.y.value) / dt : 0;
      m.y.value = y;
      stepSpring(m.x, d.zone === 'stage' ? 0 : -22, dt);
      moving = true;
      continue;
    }
    const target = faceTop(f, e.unit);
    if (snap) {
      m.y = { value: target, velocity: 0 };
      m.x = { value: 0, velocity: 0 };
      continue;
    }
    if (stepSpring(m.y, target, dt)) moving = true;
    if (stepSpring(m.x, 0, dt)) moving = true;
  }
  if (snap) for (const s of sags.values()) Object.assign(s, { value: REST_SAG, velocity: 0 });
  else {
    for (const c of props.cables) {
      let s = sags.get(c.id);
      if (!s) sags.set(c.id, (s = { value: REST_SAG, velocity: 0 }));
      // A cable lags behind its moving ends: it hangs deeper while they rise and bunches while they fall
      const pull = (velocityOfPort(c.a_port_id) + velocityOfPort(c.b_port_id)) / 2;
      s.velocity += ((REST_SAG - s.value) * SWING.stiffness - s.velocity * SWING.damping - pull * 5) * dt;
      s.value = clamp(s.value + s.velocity * dt, 3, 64);
      if (Math.abs(s.velocity) > 0.5 || Math.abs(s.value - REST_SAG) > 0.3) moving = true;
      else s.value = REST_SAG;
    }
  }
  frameNo.value++;
  return moving || Boolean(d?.lifted) || patch.value !== null;
}

const positions = computed(() => {
  void frameNo.value;
  const f = frame.value;
  const map = new Map<string, { x: number; y: number; waiting: boolean }>();
  for (const e of placed.value) {
    const m = motion.get(e.key);
    map.set(e.key, { x: m?.x.value ?? 0, y: m?.y.value ?? faceTop(f, e.unit!), waiting: (m?.wait ?? 0) > 0 });
  }
  return map;
});

// ── Cables ───────────────────────────────────────────────────────────────────
/** Centre of a port's jack as drawn now, or null when the port is not drawn on this side of this rack */
function jackPoint(portId: number): Point | null {
  const spot = jackOfPort.value.get(portId);
  const pos = spot && positions.value.get(spot.key);
  if (!spot || !pos || pos.waiting) return null;
  return jackCentre(spot.jack, { x: frame.value.railPx + pos.x, y: pos.y });
}

/** Where a jack sits once everything has settled; lanes follow these, so cables keep their lane while things move */
function restPoint(portId: number): Point | null {
  const spot = jackOfPort.value.get(portId);
  const entry = spot && entryByKey.value.get(spot.key);
  if (!spot || !entry || entry.unit === null) return null;
  return jackCentre(spot.jack, { x: frame.value.railPx, y: faceTop(frame.value, entry.unit) });
}

const lanes = computed(() => {
  const f = frame.value;
  const spans: { id: number; top: number; bottom: number }[] = [];
  for (const c of props.cables) {
    const a = restPoint(c.a_port_id);
    const b = restPoint(c.b_port_id);
    if (a && b && !isShortCable(f, a, b)) spans.push({ id: c.id, top: Math.min(a.y, b.y), bottom: Math.max(a.y, b.y) });
  }
  return assignLanes(spans, laneCount(f));
});

type StubTarget = { ownerKey: string; side: PortSide | null; rackId: number | null };
interface Place {
  id: string;
  text: string;
  target: StubTarget;
}

/** Where the other end of a stub is: the other side of this rack, another rack, or nowhere yet. */
function placeOf(port: RackPort): Place {
  const key = ownerKeyOf(port);
  if (entryByKey.value.get(key)?.unit) {
    const side = sideOf(port);
    return { id: `side-${side}`, text: t(side === 'rear' ? 'gv.rack.stub_rear' : 'gv.rack.stub_front'), target: { ownerKey: key, side, rackId: null } };
  }
  const away = props.elsewhere(key);
  if (away.rackId === null) return { id: 'loose', text: t('gv.rack.stub_loose'), target: { ownerKey: key, side: null, rackId: null } };
  const name = away.label.length > 12 ? `${away.label.slice(0, 11)}…` : away.label;
  return { id: `rack-${away.rackId}`, text: `→ ${name}`, target: { ownerKey: key, side: sideOf(port), rackId: away.rackId } };
}

const hoverCable = ref<{ id: number; x: number; y: number } | null>(null);
const hoverPortId = ref<number | null>(null);
let stubTargets = new Map<string, StubTarget>();

const cableLayer = computed(() => {
  void frameNo.value;
  const f = frame.value;
  const draws: CableDraw[] = [];
  const groups = new Map<string, { y: number; count: number; place: Place }>();
  const focus = hoverCable.value?.id ?? props.highlightCableId;
  const anyFocus = props.selectedKey !== null || focus !== null;
  for (const c of props.cables) {
    const pa = portById.value.get(c.a_port_id);
    const pb = portById.value.get(c.b_port_id);
    if (!pa || !pb) continue;
    const a = jackPoint(pa.id);
    const b = jackPoint(pb.id);
    if (!a && !b) continue;
    const mine = props.selectedKey !== null && (ownerKeyOf(pa) === props.selectedKey || ownerKeyOf(pb) === props.selectedKey);
    const state: CableDraw['state'] = focus === c.id || mine ? 'active' : anyFocus ? 'dim' : 'normal';
    const colour = c.color ?? cableDefaults(pa.kind).colour;
    const sag = sags.get(c.id)?.value ?? REST_SAG;
    if (a && b) {
      const d = isShortCable(f, a, b) ? loopPath(a, b, sag) : channelPath(a, b, laneX(f, lanes.value.get(c.id) ?? 0), (sag - REST_SAG) * 0.8);
      draws.push({ id: c.id, d, colour, dashed: false, state });
      continue;
    }
    const own = (a ?? b)!;
    const ownPort = a ? pa : pb;
    const place = placeOf(a ? pb : pa);
    const groupKey = `${ownerKeyOf(ownPort)}|${place.id}`;
    const group = groups.get(groupKey) ?? { y: own.y, count: 0, place };
    const end = { x: channelEdge(f), y: Math.round(group.y + 6 + Math.min(group.count, 5) * 3) };
    group.count++;
    groups.set(groupKey, group);
    draws.push({ id: c.id, d: stubPath(own, end, sag), colour, dashed: true, state });
  }
  stubTargets = new Map([...groups].map(([key, g]) => [key, g.place.target]));
  const labels: StubLabel[] = [...groups].map(([key, g]) => ({
    key,
    x: channelEdge(f),
    y: Math.round(g.y - 5),
    text: g.count > 1 ? `${g.place.text} · ${g.count}` : g.place.text,
  }));
  return { draws, labels };
});

function onStub(key: string) {
  const target = stubTargets.get(key);
  if (target) emit('stub', target);
}

/** The jack element under the pointer, looking through the cable layer */
function jackUnder(event: { clientX: number; clientY: number }): number | null {
  const el = document.elementsFromPoint(event.clientX, event.clientY).find((node) => node instanceof HTMLElement && node.dataset.port);
  return el instanceof HTMLElement ? Number(el.dataset.port) : null;
}

function onCableHover(id: number | null, event: PointerEvent) {
  const jack = id === null ? null : jackUnder(event);
  hoverPortId.value = jack;
  if (id === null || jack !== null) {
    hoverCable.value = null;
    return;
  }
  const local = localOf({ x: event.clientX, y: event.clientY });
  if (local) hoverCable.value = { id, ...local };
}

/** Set when a press on a cable went to what lies underneath, so its click does not pick the cable as well */
let forwarded = false;

/** A press on a cable that lies over a jack or a faceplate goes to what is underneath */
function onCableDown(event: PointerEvent) {
  forwarded = false;
  if (!(event.target instanceof SVGPathElement)) return;
  const jack = jackUnder(event);
  if (jack !== null) {
    forwarded = true;
    onJackDown(jack, event);
    return;
  }
  const el = document.elementsFromPoint(event.clientX, event.clientY).find((node) => node instanceof HTMLElement && node.dataset.entry);
  const entry = el instanceof HTMLElement ? entryByKey.value.get(el.dataset.entry ?? '') : undefined;
  if (entry && el instanceof HTMLElement) {
    forwarded = true;
    onEntryDown(entry, event, el);
  }
}

function onCablePick(id: number) {
  if (forwarded) forwarded = false;
  else emit('pickCable', id);
}

const hoverInfo = computed(() => {
  const hover = hoverCable.value;
  const cable = hover && props.cables.find((c) => c.id === hover.id);
  const pa = cable && portById.value.get(cable.a_port_id);
  const pb = cable && portById.value.get(cable.b_port_id);
  if (!hover || !cable || !pa || !pb) return null;
  return {
    x: hover.x,
    y: hover.y,
    colour: cable.color ?? cableDefaults(pa.kind).colour,
    type: cable.cable,
    ends: `${props.ownerLabel[ownerKeyOf(pa)] ?? '?'} ${pa.number} ↔ ${props.ownerLabel[ownerKeyOf(pb)] ?? '?'} ${pb.number}`,
  };
});

// ── Plugging in a cable ──────────────────────────────────────────────────────
const patch = ref<{ from: number; pointer: Point | null; target: number | null; moved: boolean; startX: number; startY: number } | null>(null);
/** The pointer over the rack while a start port waits for its other end (picked in the inspector or by a tap) */
const hoverPoint = ref<Point | null>(null);

/** The nearest free jack of another entry within reach, so a cable finds even a tiny jack */
function nearestJack(point: Point, fromPortId: number): number | null {
  const from = portById.value.get(fromPortId);
  const fromOwner = from ? ownerKeyOf(from) : null;
  let best: number | null = null;
  let bestDist = Infinity;
  for (const [portId, spot] of jackOfPort.value) {
    if (spot.key === fromOwner || cableOfPort.value.has(portId)) continue;
    const centre = jackPoint(portId);
    if (!centre) continue;
    const dist = Math.hypot(centre.x - point.x, centre.y - point.y);
    if (dist < Math.max(14, spot.jack.w * 1.6) && dist < bestDist) {
      best = portId;
      bestDist = dist;
    }
  }
  return best;
}

function onJackDown(portId: number, event: PointerEvent) {
  if (event.button !== 0) return;
  const cable = cableOfPort.value.get(portId);
  if (cable) {
    emit('pickCable', cable.id);
    return;
  }
  if (props.pendingPortId !== null && props.pendingPortId !== portId) {
    emit('pick', portId);
    return;
  }
  patch.value = { from: portId, pointer: null, target: null, moved: false, startX: event.clientX, startY: event.clientY };
  window.addEventListener('pointermove', onPatchMove);
  window.addEventListener('pointerup', onPatchUp);
  window.addEventListener('pointercancel', endPatch);
  loop.kick();
}

function onPatchMove(event: PointerEvent) {
  const p = patch.value;
  if (!p) return;
  if (!p.moved && Math.hypot(event.clientX - p.startX, event.clientY - p.startY) < 4) return;
  p.moved = true;
  p.pointer = localOf({ x: event.clientX, y: event.clientY });
  p.target = p.pointer ? nearestJack(p.pointer, p.from) : null;
}

function onPatchUp() {
  const p = patch.value;
  endPatch();
  if (!p) return;
  if (!p.moved) emit('pick', p.from);
  else if (p.target !== null) emit('connect', p.from, p.target);
}

function endPatch() {
  window.removeEventListener('pointermove', onPatchMove);
  window.removeEventListener('pointerup', onPatchUp);
  window.removeEventListener('pointercancel', endPatch);
  patch.value = null;
}

const pendingTarget = computed(() => (props.pendingPortId !== null && hoverPoint.value ? nearestJack(hoverPoint.value, props.pendingPortId) : null));

const live = computed(() => {
  void frameNo.value;
  const from = patch.value?.from ?? props.pendingPortId;
  if (from === null || from === undefined) return null;
  const a = jackPoint(from);
  const pointer = patch.value ? patch.value.pointer : hoverPoint.value;
  if (!a || !pointer) return null;
  const target = patch.value ? patch.value.target : pendingTarget.value;
  const b = (target !== null && jackPoint(target)) || pointer;
  const dist = Math.hypot(b.x - a.x, b.y - a.y);
  return { d: loopPath(a, b, 16 + dist * 0.12), colour: cableDefaults(portById.value.get(from)?.kind ?? 'RJ45').colour, snapped: target !== null, target };
});

const liveInfo = computed(() => {
  const target = live.value?.target;
  const port = target !== null && target !== undefined ? portById.value.get(target) : undefined;
  const at = target !== null && target !== undefined ? jackPoint(target) : null;
  if (!port || !at) return null;
  return { x: at.x, y: at.y, text: t('gv.rack.patch_target', { label: props.ownerLabel[ownerKeyOf(port)] ?? '?', port: port.number }) };
});

function onStageMove(event: PointerEvent) {
  hoverPoint.value = props.pendingPortId !== null ? localOf({ x: event.clientX, y: event.clientY }) : null;
}

const hotPorts = computed(() => {
  const set = new Set<number>();
  const focus = hoverCable.value?.id ?? props.highlightCableId;
  const cable = focus !== null ? props.cables.find((c) => c.id === focus) : undefined;
  if (cable) set.add(cable.a_port_id).add(cable.b_port_id);
  if (hoverPortId.value !== null) set.add(hoverPortId.value);
  const target = live.value?.target;
  if (target !== null && target !== undefined) set.add(target);
  return set;
});

// ── Dragging ─────────────────────────────────────────────────────────────────
function onEntryDown(entry: RackEntry, event: PointerEvent, el: HTMLElement) {
  if (event.button !== 0) return;
  if (event.pointerType === 'mouse') event.preventDefault();
  el.focus({ preventScroll: true });
  const rect = el.getBoundingClientRect();
  emit('grab', entry, event, { x: event.clientX - rect.left, y: event.clientY - rect.top });
}

const liftedKey = computed(() => (props.drag?.lifted && props.drag.from === 'rack' ? props.drag.key : null));
const runs = computed(() => freeRuns(props.units, placed.value, liftedKey.value));

/** The unit under a drag and whether it fits there; the parent asks while the pointer is over the rack. */
function locate(d: DragState): DragTarget | null {
  const local = localOf(d);
  if (!local) return null;
  const f = frame.value;
  const top = d.from === 'rack' ? local.y - d.grabY : local.y - faceHeight(f, d.height) / 2;
  const unit = clamp(snapUnit(f, top), Math.min(d.height, f.units), f.units);
  const blocker = blockerAt(f.units, props.entries, unit, d.height, d.entry?.key ?? d.key);
  if (blocker === null) return { unit, blocker: null };
  return { unit, blocker: blocker === 'outside' ? t('gv.rack.drop_outside') : t('gv.rack.drop_blocked_by', { name: blocker.label }) };
}

const ghost = computed(() => {
  const d = props.drag;
  if (!d?.lifted || d.zone !== 'stage' || !d.target) return null;
  const f = frame.value;
  const unit = clamp(d.target.unit, Math.min(d.height, f.units), f.units);
  return { top: faceTop(f, unit), height: faceHeight(f, d.height), blocked: d.target.blocker !== null, text: d.target.blocker ?? t('gv.rack.drop_at', { unit }) };
});

/** Something from the palette or the store, drawn where the pointer holds it over the rack */
const phantom = computed(() => {
  void frameNo.value;
  const d = props.drag;
  if (!d?.lifted || d.from === 'rack' || d.zone !== 'stage') return null;
  const local = localOf(d);
  if (!local) return null;
  const f = frame.value;
  const height = faceHeight(f, d.height);
  const entry: RackEntry = d.entry ?? {
    key: d.key,
    kind: 'item',
    id: -1,
    label: d.label,
    detail: '',
    online: true,
    itemKind: d.itemKind,
    unit: null,
    height: d.height,
    face: d.face,
    subnetId: null,
  };
  return { entry, y: clamp(local.y - height / 2, 0, frameHeight(f) - height), height, layout: faceLayout([], f.facePx, height) };
});

/** A press on the empty rack (free units, the cabinet, the channel) clears the selection */
function onBodyDown(event: PointerEvent) {
  if (!(event.target as Element).closest('[data-entry], .rack-resize, .rack-stub, .rack-hit')) emit('select', null);
}

function onEntryKey(entry: RackEntry, event: KeyboardEvent) {
  if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    event.preventDefault();
    emit('nudge', entry.key, event.key === 'ArrowUp' ? 1 : -1);
  } else if (event.key === 'Enter') {
    event.preventDefault();
    emit('open', entry.key);
  } else if (event.key === ' ') {
    event.preventDefault();
    emit('select', entry.key);
  } else if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault();
    emit('remove', entry.key);
  } else if (event.key === 'Escape') {
    emit('select', null);
  }
}

// ── Rack height ──────────────────────────────────────────────────────────────
/** The highest unit in use: the rack cannot get lower than that */
const minUnits = computed(() => Math.max(1, ...placed.value.map((e) => e.unit ?? 1)));
const resizing = ref<{ startY: number; start: number; units: number; held: boolean } | null>(null);

function onResizeDown(event: PointerEvent) {
  if (event.button !== 0) return;
  event.preventDefault();
  resizing.value = { startY: event.clientY, start: props.units, units: props.units, held: false };
  window.addEventListener('pointermove', onResizeMove);
  window.addEventListener('pointerup', onResizeUp, { once: true });
}

function onResizeMove(event: PointerEvent) {
  const r = resizing.value;
  if (!r) return;
  const wanted = r.start - Math.round((event.clientY - r.startY) / frame.value.unitPx);
  r.held = wanted < minUnits.value;
  r.units = clamp(wanted, minUnits.value, 60);
}

function onResizeUp() {
  window.removeEventListener('pointermove', onResizeMove);
  const r = resizing.value;
  resizing.value = null;
  if (r && r.units !== r.start) emit('resize', r.units);
}

function onResizeKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
  event.preventDefault();
  const next = clamp(props.units + (event.key === 'ArrowUp' ? 1 : -1), minUnits.value, 60);
  if (next !== props.units) emit('resize', next);
}

const resizeLabel = computed(() => {
  const r = resizing.value;
  if (!r) return t('gv.rack.units_label', { count: props.units });
  const diff = r.units - r.start;
  return diff ? `${t('gv.rack.units_label', { count: r.units })} (${diff > 0 ? '+' : ''}${diff})` : t('gv.rack.units_label', { count: r.units });
});
const resizeBlocker = computed(() => {
  if (!resizing.value?.held) return null;
  const top = placed.value.find((e) => e.unit === minUnits.value);
  return top ? t('gv.rack.resize_blocked', { name: top.label, unit: minUnits.value }) : null;
});
/** Units that a smaller rack would lose, shown while dragging the handle down */
const cut = computed(() => {
  const r = resizing.value;
  if (!r || r.units >= props.units) return null;
  const f = frame.value;
  return { top: f.padPx, height: (props.units - r.units) * f.unitPx };
});

/** Scroll a faceplate into view, e.g. when the status line jumps to an offline device */
function reveal(key: string) {
  const entry = entryByKey.value.get(key);
  const scroller = scrollRef.value;
  const body = bodyRef.value;
  if (!entry || entry.unit === null || !scroller || !body) return;
  const y = body.offsetTop + faceTop(frame.value, entry.unit);
  scroller.scrollTo({ top: Math.max(0, y - scroller.clientHeight / 2), behavior: reduceMotion ? 'auto' : 'smooth' });
}

defineExpose({ locate, reveal });

const sideName = computed(() => t(shownSide.value === 'front' ? 'gv.rack.side_front' : 'gv.rack.side_rear'));
</script>

<template>
  <div
    ref="scrollRef"
    class="rack-stage relative h-full min-h-0 overflow-x-hidden overflow-y-auto"
    data-rack-drop="stage"
    @pointermove="onStageMove"
    @pointerleave="hoverPoint = null"
    @pointerdown.self="emit('select', null)"
  >
    <div v-if="box.height" class="flex min-h-full justify-center px-4 pt-9 pb-4" @pointerdown.self="emit('select', null)">
      <div
        ref="bodyRef"
        class="relative shrink-0"
        :style="{ width: `${frameWidth(frame)}px`, height: `${frameHeight(frame)}px`, ...turnStyle }"
        role="group"
        :aria-label="t('gv.rack.stage_label', { name: rackName, side: sideName })"
        @pointerdown="onBodyDown"
      >
        <!-- Cabinet: posts with a hole per unit, the cable channel on the right -->
        <div class="rack-cabinet" :style="{ left: `${frame.railPx - 8}px`, width: `${frame.facePx + 16}px`, '--unit': `${frame.unitPx}px` }" aria-hidden="true" />
        <div class="rack-channel" :style="{ left: `${frame.railPx + frame.facePx + 8}px`, width: `${frame.channelPx - 10}px` }" aria-hidden="true" />
        <span
          v-for="u in units"
          :key="u"
          class="pointer-events-none absolute left-0 text-right font-mono text-micro text-fg-subtle tabular"
          :style="{ top: `${unitTop(frame, u) + (frame.unitPx - 12) / 2}px`, width: `${frame.railPx - 12}px` }"
          aria-hidden="true"
        >
          {{ u }}
        </span>

        <div
          v-for="run in runs"
          :key="`${run.top}-${run.length}`"
          class="rack-free"
          :style="{ left: `${frame.railPx}px`, width: `${frame.facePx}px`, top: `${unitTop(frame, run.top) + 1}px`, height: `${run.length * frame.unitPx - 2}px` }"
          aria-hidden="true"
        >
          <span v-if="run.length > 1 && run.length * frame.unitPx >= 30">{{ t('gv.racks.free', { count: run.length }) }}</span>
        </div>

        <div v-if="cut" class="rack-cut" :style="{ left: `${frame.railPx - 8}px`, width: `${frame.facePx + 16}px`, top: `${cut.top}px`, height: `${cut.height}px` }" aria-hidden="true" />

        <div
          v-if="ghost"
          class="rack-ghost"
          :class="ghost.blocked && 'is-blocked'"
          :style="{ left: `${frame.railPx}px`, width: `${frame.facePx}px`, top: `${ghost.top}px`, height: `${ghost.height}px` }"
          role="status"
        >
          {{ ghost.text }}
        </div>

        <div
          v-for="e in placed"
          :key="e.key"
          class="rack-entry"
          :class="[selectedKey === e.key && 'is-selected', liftedKey === e.key && 'is-lifted', arrived.has(e.key) && 'is-arriving', positions.get(e.key)?.waiting && 'is-waiting']"
          :style="{
            left: `${frame.railPx}px`,
            width: `${frame.facePx}px`,
            height: `${faceHeight(frame, e.height)}px`,
            transform: `translate3d(${positions.get(e.key)?.x ?? 0}px, ${positions.get(e.key)?.y ?? 0}px, 0)${liftedKey === e.key ? ' scale(1.02)' : ''}`,
          }"
          :data-entry="e.key"
          role="button"
          tabindex="0"
          :aria-label="t('gv.rack.entry_label', { label: e.label, unit: e.unit })"
          :aria-pressed="selectedKey === e.key"
          @pointerdown="onEntryDown(e, $event, $event.currentTarget as HTMLElement)"
          @dblclick="emit('open', e.key)"
          @keydown="onEntryKey(e, $event)"
        >
          <RackFaceplate
            :entry="e"
            :side="shownSide"
            :width="frame.facePx"
            :height="faceHeight(frame, e.height)"
            :layout="layouts.get(e.key)!"
            :colour-of-port="colourOfPort"
            :down-ports="downPorts"
            :peer-of-port="peerOfPort"
            :accent="accentOf[e.key] ?? null"
            :other-side-ports="otherSidePorts[e.key] ?? 0"
            :ambient="ambient"
            :hot-ports="hotPorts"
            :pending-port-id="pendingPortId"
            @jack-down="onJackDown"
          />
        </div>

        <div
          v-if="phantom"
          class="rack-entry is-lifted is-phantom"
          :style="{ left: `${frame.railPx}px`, width: `${frame.facePx}px`, height: `${phantom.height}px`, transform: `translate3d(0, ${phantom.y}px, 0) scale(1.02)` }"
          aria-hidden="true"
        >
          <RackFaceplate
            :entry="phantom.entry"
            :side="shownSide"
            :width="frame.facePx"
            :height="phantom.height"
            :layout="phantom.layout"
            :colour-of-port="colourOfPort"
            :down-ports="downPorts"
            :peer-of-port="peerOfPort"
            :accent="null"
            :other-side-ports="0"
            :ambient="false"
            :hot-ports="hotPorts"
            :pending-port-id="null"
          />
        </div>

        <RackCables
          :width="frameWidth(frame)"
          :height="frameHeight(frame)"
          :cables="cableLayer.draws"
          :labels="cableLayer.labels"
          :live="live"
          :ambient="ambient"
          :class="(drag?.lifted || patch || pendingPortId !== null) && 'is-quiet'"
          @hover="onCableHover"
          @pick="onCablePick"
          @stub="onStub"
          @pointerdown.capture="onCableDown"
        />

        <div v-if="hoverInfo" class="rack-chip" :style="{ left: `${hoverInfo.x + 12}px`, top: `${hoverInfo.y + 14}px` }" role="tooltip">
          <span class="size-2 shrink-0 rounded-full" :style="{ backgroundColor: hoverInfo.colour }" />
          <span class="font-semibold text-fg">{{ hoverInfo.type }}</span>
          <span class="font-mono text-fg-muted">{{ hoverInfo.ends }}</span>
        </div>
        <div v-if="liveInfo" class="rack-chip" :style="{ left: `${liveInfo.x + 10}px`, top: `${liveInfo.y - 30}px` }" role="status">
          <span class="font-mono text-fg">{{ liveInfo.text }}</span>
        </div>

        <button
          type="button"
          class="rack-resize"
          :class="resizing && 'is-active'"
          :style="{ left: `${frame.railPx + frame.facePx / 2}px` }"
          :aria-label="t('gv.rack.resize_label', { count: units })"
          :title="t('gv.rack.resize_hint')"
          @pointerdown="onResizeDown"
          @keydown="onResizeKey"
        >
          <ChevronsUpDown class="size-3" aria-hidden="true" />
          <span class="font-mono tabular">{{ resizeLabel }}</span>
        </button>
        <p v-if="resizeBlocker" class="rack-chip -translate-x-1/2" :style="{ left: `${frame.railPx + frame.facePx / 2}px`, top: '0.4rem' }" role="status">
          {{ resizeBlocker }}
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rack-stage {
  touch-action: pan-y;
  background-image: radial-gradient(var(--gl-line) 1px, transparent 1px);
  background-size: 24px 24px;
}
.rack-cabinet {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 8px;
  background:
    repeating-linear-gradient(to bottom, transparent 0 calc(var(--unit) / 2 - 2px), var(--gl-sunken) calc(var(--unit) / 2 - 2px) calc(var(--unit) / 2 + 2px), transparent calc(var(--unit) / 2 + 2px) var(--unit)) left 2px top 10px / 4px calc(100% - 20px) no-repeat,
    repeating-linear-gradient(to bottom, transparent 0 calc(var(--unit) / 2 - 2px), var(--gl-sunken) calc(var(--unit) / 2 - 2px) calc(var(--unit) / 2 + 2px), transparent calc(var(--unit) / 2 + 2px) var(--unit)) right 2px top 10px / 4px calc(100% - 20px) no-repeat,
    var(--gl-sunken);
  box-shadow:
    inset 8px 0 0 color-mix(in oklab, var(--gl-line-strong) 70%, transparent),
    inset -8px 0 0 color-mix(in oklab, var(--gl-line-strong) 70%, transparent),
    inset 0 0 0 1px var(--gl-line-strong);
}
.rack-channel {
  position: absolute;
  top: 6px;
  bottom: 6px;
  border: 1px dashed var(--gl-line);
  border-radius: 8px;
  background: color-mix(in oklab, var(--gl-sunken) 60%, transparent);
}
.rack-free {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--gl-line);
  border-radius: 4px;
  color: var(--gl-fg-subtle);
  font-size: var(--text-xs);
}
.rack-cut {
  position: absolute;
  z-index: 6;
  border-radius: 8px 8px 0 0;
  background: color-mix(in oklab, var(--gl-danger) 18%, transparent);
  box-shadow: inset 0 -2px 0 var(--gl-danger);
}
.rack-ghost {
  position: absolute;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px dashed var(--gl-accent);
  border-radius: 4px;
  background: color-mix(in oklab, var(--gl-accent) 12%, transparent);
  color: var(--gl-accent-text);
  font-size: var(--text-xs);
  font-weight: 600;
  transition:
    top 120ms var(--ease-out-expo),
    height 120ms var(--ease-out-expo);
}
.rack-ghost.is-blocked {
  border-color: var(--gl-danger);
  background: color-mix(in oklab, var(--gl-danger) 12%, transparent);
  color: var(--gl-danger-text);
}
.rack-entry {
  position: absolute;
  top: 0;
  z-index: 2;
  border-radius: 4px;
  cursor: grab;
  outline: none;
  transition:
    opacity 220ms ease-out,
    box-shadow 160ms ease-out;
  will-change: transform;
}
.rack-entry:focus-visible {
  box-shadow: 0 0 0 2px var(--gl-accent);
}
.rack-entry.is-selected {
  z-index: 3;
  box-shadow:
    0 0 0 1.5px var(--gl-accent),
    0 0 18px -4px color-mix(in oklab, var(--gl-accent) 60%, transparent);
}
.rack-entry.is-lifted {
  z-index: 20;
  cursor: grabbing;
  pointer-events: none;
  box-shadow: var(--gl-shadow-pop);
}
.rack-entry.is-phantom {
  opacity: 0.92;
}
.rack-entry.is-waiting {
  opacity: 0;
}
.rack-entry.is-arriving {
  animation: rack-arrive 420ms var(--ease-out-expo);
}
@keyframes rack-arrive {
  from {
    opacity: 0;
    scale: 0.96;
  }
}
:deep(.is-quiet .rack-hit) {
  pointer-events: none;
}
.rack-chip {
  position: absolute;
  z-index: 30;
  display: flex;
  max-width: 22rem;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.55rem;
  border: 1px solid var(--gl-line-strong);
  border-radius: 6px;
  background: var(--gl-surface);
  box-shadow: var(--gl-shadow-pop);
  font-size: var(--text-xs);
  white-space: nowrap;
  pointer-events: none;
}
.rack-resize {
  position: absolute;
  top: -1.55rem;
  z-index: 8;
  display: inline-flex;
  height: 1.35rem;
  transform: translateX(-50%);
  align-items: center;
  gap: 0.3rem;
  padding: 0 0.55rem;
  border: 1px solid var(--gl-line-strong);
  border-radius: 9999px;
  background: var(--gl-surface);
  color: var(--gl-fg-muted);
  font-size: var(--text-micro);
  cursor: ns-resize;
  touch-action: none;
  transition:
    color 120ms,
    border-color 120ms;
}
.rack-resize:hover,
.rack-resize.is-active,
.rack-resize:focus-visible {
  border-color: var(--gl-accent);
  color: var(--gl-fg);
  outline: none;
}
</style>
