<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useEventListener, useFullscreen, useMediaQuery, useResizeObserver, useStorage } from '@vueuse/core';
import { Check, Expand, Hand, Maximize, Minus, MousePointer2, Orbit, Pencil, Plus, Search, ShieldAlert, Shrink, Sparkles, TriangleAlert, Wand2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device } from '@/types';
import { useNetworkStore } from '@/stores/network';
import { useAppearance } from '@/stores/appearance';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import Button from '@/components/ui/Button.vue';
import {
  autoOrbitLayout,
  computeLightBeams,
  computeOrbitRings,
  findDropTargetBody,
  getDescendantIds,
  linkCount,
  moveWithDescendants,
  portLimitReached,
  resolveOrbitSystem,
  snapToOrbitRing,
  type LightBeam,
  type OrbitBody,
  type OrbitLink,
  type OrbitRole,
  type Point,
} from './orbitModel';
import { labelRank, labelSize, orbitCenterId, placeLabels, problemBodyIds, radiusOf } from './orbitLayout';
import { computeFocusSet, findPath, focusSetFromIds, matchBodies, type FocusSet, type TracedPath } from './orbitFocus';
import { useOrbitViewport } from './useOrbitViewport';
import { analyseResilience, failoverState } from './orbitResilience';
import OrbitBodyNode from './OrbitBodyNode.vue';
import OrbitBeamLayer from './OrbitBeamLayer.vue';
import OrbitFocusCard from './OrbitFocusCard.vue';
import OrbitTracePanel from './OrbitTracePanel.vue';
import OrbitLinkInspector from './OrbitLinkInspector.vue';
import OrbitBodyInspector from './OrbitBodyInspector.vue';
import OrbitResiliencePanel from './OrbitResiliencePanel.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * The network as a gravitational system: the router is the star in the middle, switches, APs
 * and hosts are planets on rings around it, endpoints, VMs and WLAN clients are moons around
 * their planet. Everything can be moved, re-assigned to another planet and linked by beams;
 * positions and links are the same records as the React topology.
 */
const props = withDefaults(defineProps<{ editable?: boolean; startEditing?: boolean; flowId?: string }>(), {
  editable: false,
  startEditing: false,
  flowId: 'orbit',
});
const emit = defineEmits<{ openDevice: [device: Device] }>();

const store = useNetworkStore();
const appearance = useAppearance();
const { showToast } = useToast();
const { confirm } = useConfirm();

const reduceMotionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const prefersReducedMotion = ref(Boolean(reduceMotionQuery?.matches));

/** Ambient motion: 'off' | 'subtle' | 'lively' (off under reduced motion). */
const vitalityMode = useStorage<'off' | 'subtle' | 'lively'>('gravityui.orbit.vitality', prefersReducedMotion.value ? 'off' : 'subtle');
function cycleVitality() {
  const order = ['off', 'subtle', 'lively'] as const;
  vitalityMode.value = order[(order.indexOf(vitalityMode.value) + 1) % order.length];
}

const editing = ref(props.editable && props.startEditing);
/** Resilience view: single points of failure lit up, with their list */
const resilienceMode = ref(false);
const canvasRef = ref<HTMLElement | null>(null);
const { isFullscreen, isSupported: fullscreenSupported, toggle: toggleFullscreen } = useFullscreen(canvasRef);
const links = ref<OrbitLink[]>([]);
const gatewayIds = ref(new Set<number>());
const localPositions = ref(new Map<number, Point>());
const selectedLinkId = ref<number | null>(null);
const selectedDeviceId = ref<number | null>(null);
const hoveredBodyId = ref<number | null>(null);
const loaded = ref(false);

const svgRef = ref<SVGSVGElement | null>(null);

/**
 * The read-only map is the one embedded in a scrolling page (the dashboard), so the page keeps the plain wheel
 * and one-finger swipes there: Ctrl/⌘ + wheel zooms, and on touch the map takes gestures only after a tap on it
 * (or on "Use map") until "Done", a tap outside it or Esc. In fullscreen it behaves like the full map.
 */
const pageScrolls = computed(() => !props.editable && !isFullscreen.value);
const coarsePointer = useMediaQuery('(pointer: coarse)');
const touchActive = ref(false);
const touchLocked = computed(() => pageScrolls.value && !touchActive.value);
const modifierKey = computed(() => (/Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘' : t('gv.orbit.key_ctrl')));
/** A finger that moves less than this between down and up is a tap, not a swipe */
const TAP_SLOP_PX = 10;
let tapStart: Point | null = null;
const wheelHint = ref(false);
let wheelHintTimer = 0;

const view = useOrbitViewport(svgRef, prefersReducedMotion, pageScrolls);

// Dragging a body or drawing a beam
const draggingBodyId = ref<number | null>(null);
const dragStartWorld = ref<Point>({ x: 0, y: 0 });
const dragStartPositions = ref(new Map<number, Point>());
const dragMoved = ref(false);
const dropTarget = ref<OrbitBody | null>(null);
const connectingFromId = ref<number | null>(null);
const connectingCursor = ref<Point>({ x: 0, y: 0 });

// View mode: focus, search, path tracing
const focusedId = ref<number | null>(null);
const searchQuery = ref('');
const traceFromId = ref<number | null>(null);
const traceToId = ref<number | null>(null);

async function load() {
  try {
    const [linkList, gateways] = await Promise.all([api.getTopologyLinks() as Promise<OrbitLink[]>, api.getGateways().catch(() => [])]);
    links.value = linkList;
    gatewayIds.value = new Set(gateways.map((g) => g.device_id).filter((id): id is number => id != null));
  } catch {
    links.value = [];
  } finally {
    loaded.value = true;
  }
}

// ── Bodies and positions ────────────────────────────────────────────────────
const devicesById = computed(() => new Map(store.devices.map((d) => [d.id, d])));
const bodies = computed(() => resolveOrbitSystem(store.devices, links.value, gatewayIds.value, appearance.orbitRoles));
const bodyList = computed(() => [...bodies.value.values()]);
const autoLayout = computed(() => autoOrbitLayout(store.devices, links.value, gatewayIds.value, appearance.orbitRoles));

/**
 * Drag positions of this session first; then, once the user arranged the orbit themselves, the
 * saved positions; otherwise the automatic orbit layout (saved positions may come from the
 * React topology or the earlier transit map and would not form orbits).
 */
const positions = computed(() => {
  const map = new Map<number, Point>();
  for (const d of store.devices) {
    const local = localPositions.value.get(d.id);
    if (local) map.set(d.id, local);
    else if (appearance.orbitCustom && d.topology_x != null && d.topology_y != null) map.set(d.id, { x: d.topology_x, y: d.topology_y });
    else map.set(d.id, autoLayout.value.get(d.id) ?? { x: 0, y: 0 });
  }
  return map;
});
const posOf = (id: number): Point => positions.value.get(id) ?? { x: 0, y: 0 };

const orbitRings = computed(() => computeOrbitRings(bodies.value, positions.value));
const starIds = computed(() => bodyList.value.filter((b) => b.kind === 'star').map((b) => b.id));
/** Live: backup links that took over for a failed primary path, and online devices nothing reaches */
const failover = computed(() => failoverState(store.devices, links.value, starIds.value));
/** Planning: devices whose failure would cut others off, and who hangs on whom alone */
const resilience = computed(() => analyseResilience(store.devices, links.value, starIds.value));
const lightBeams = computed(() => computeLightBeams(links.value, bodies.value, appearance.linkTypeColors, failover.value.activeBackupIds));

/** The star at the root of a body's system. */
function rootOf(id: number): number {
  let cur = bodies.value.get(id);
  const seen = new Set<number>();
  while (cur?.parentId != null && bodies.value.has(cur.parentId) && !seen.has(cur.id)) {
    seen.add(cur.id);
    cur = bodies.value.get(cur.parentId);
  }
  return cur?.id ?? id;
}
/** Beams between two bodies of the same system bend around its star. */
function beamCentre(beam: LightBeam): Point | null {
  const a = rootOf(beam.sourceId);
  return a === rootOf(beam.targetId) ? posOf(a) : null;
}

function roleBadge(device: Device): string | null {
  if (device.is_ap) return 'AP';
  if (device.is_host) return 'HOST';
  const dt = (device.device_type || '').toLowerCase();
  const sub = (device.device_subtype || '').toLowerCase();
  return dt === 'switch' || sub === 'switch' ? 'SW' : null;
}

/**
 * Semantic zoom: labels are counter-scaled so they stay readable (about 11 px) when the whole
 * map is in view; moon labels join once zoomed in, or for the bodies under hover, focus or search.
 * A moon that is offline or degraded always keeps its label: that is what the overview is for.
 */
const MAX_LABEL_SCALE = 2.4;
const labelScale = computed(() => Math.min(MAX_LABEL_SCALE, Math.max(1, 0.95 / view.zoom.value)));
const showMoonLabels = computed(() => view.zoom.value >= 0.7);
function labelShown(b: OrbitBody): boolean {
  if (b.kind !== 'moon' || b.state !== 'online' || showMoonLabels.value || hoveredBodyId.value === b.id || selectedDeviceId.value === b.id) return true;
  const s = spotlight.value;
  return Boolean(s?.strong && s.set.bodyIds.has(b.id));
}
const labels = computed(() => {
  // A body that needs attention is as large as its halo, so labels keep clear of that ring
  const reach = (b: OrbitBody) => (b.state !== 'online' ? Math.max(radiusOf(b), (radiusOf(b) + 5) * labelScale.value) : radiusOf(b) + (b.kind === 'planet' ? 7 : 0));
  const obstacles = bodyList.value.map((b) => ({ id: b.id, pos: posOf(b.id), radius: reach(b) }));
  const items = bodyList.value.filter(labelShown).map((b) => ({
    ...obstacles.find((o) => o.id === b.id)!,
    size: labelSize(deviceLabel(b.device), b.device.ip, b.state !== 'online'),
    rank: labelRank(b),
  }));
  return placeLabels(items, labelScale.value, obstacles);
});

/** Deterministic background stars. */
const cosmicStars = computed(() => {
  let seed = 1337;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  return Array.from({ length: 96 }, (_, i) => ({
    id: i,
    x: Math.round((rand() - 0.48) * 3600),
    y: Math.round((rand() - 0.48) * 2600),
    r: rand() > 0.86 ? 1.4 : rand() > 0.45 ? 1.0 : 0.65,
    opacity: Math.round((0.25 + rand() * 0.55) * 100) / 100,
    twinkle: rand() > 0.4,
    delay: `${Math.round(rand() * 45) / 10}s`,
  }));
});

/** Hub under inspection: its rings light up. */
const activeClusterCenterId = computed(() => {
  if (draggingBodyId.value) {
    const b = bodies.value.get(draggingBodyId.value);
    return b ? orbitCenterId(b, bodies.value) : null;
  }
  const activeId = hoveredBodyId.value ?? selectedDeviceId.value ?? focusedId.value;
  const b = activeId ? bodies.value.get(activeId) : null;
  if (!b) return null;
  return b.kind === 'moon' ? b.parentId : b.id;
});

const activeDragOrbit = computed(() => {
  if (draggingBodyId.value == null || dropTarget.value) return null;
  const body = bodies.value.get(draggingBodyId.value);
  const centerId = body ? orbitCenterId(body, bodies.value) : null;
  if (!body || centerId == null) return null;
  const center = posOf(centerId);
  const curr = posOf(body.id);
  const r = Math.hypot(curr.x - center.x, curr.y - center.y);
  return r >= 16 ? { center, radius: Math.round(r), color: body.color } : null;
});

const selectedLink = computed(() => links.value.find((l) => l.id === selectedLinkId.value) ?? null);
const selectedDevice = computed(() => (selectedDeviceId.value ? (devicesById.value.get(selectedDeviceId.value) ?? null) : null));
const selectedBody = computed(() => (selectedDeviceId.value ? (bodies.value.get(selectedDeviceId.value) ?? null) : null));
const assignableParents = computed(() => {
  const sel = selectedBody.value;
  if (!sel) return [];
  const invalid = new Set([sel.id, ...getDescendantIds(sel.id, bodies.value)]);
  return bodyList.value.filter((b) => !invalid.has(b.id) && (b.kind === 'star' || b.kind === 'planet'));
});
const swatches = computed(() => {
  void appearance.lineColors;
  const style = getComputedStyle(document.documentElement);
  return Array.from({ length: 10 }, (_, i) => style.getPropertyValue(`--line-${i + 1}`).trim()).filter(Boolean);
});
const linkEnds = computed(() => {
  const l = selectedLink.value;
  if (!l) return '';
  const a = devicesById.value.get(l.source_id);
  const b = devicesById.value.get(l.target_id);
  return `${a ? deviceLabel(a) : '?'} – ${b ? deviceLabel(b) : '?'}`;
});

// ── Viewport ─────────────────────────────────────────────────────────────────
/**
 * Everything the whole-map view must show: bodies with room for their labels. Star and planet labels
 * are drawn up to MAX_LABEL_SCALE times larger at that zoom, so they get boxes of that size; otherwise
 * a small (phone) map cuts them off at its edges.
 */
function contentPoints(): Point[] {
  const pts: Point[] = [];
  for (const b of bodyList.value) {
    const p = posOf(b.id);
    const problem = b.state !== 'online';
    const scale = b.kind === 'moon' && !problem ? 1 : MAX_LABEL_SCALE;
    const size = labelSize(deviceLabel(b.device), b.device.ip, problem);
    const halfW = Math.max(70, (size.w * scale) / 2);
    const reach = radiusOf(b) + 6 + size.h * scale;
    pts.push({ x: p.x - halfW, y: p.y - reach }, { x: p.x + halfW, y: p.y + reach });
  }
  return pts;
}
// The search field covers the top 48 px of the map; the whole-map view starts below it
const fitView = (animated = false) => view.fit(contentPoints(), animated, 48);
const flyToBodies = (ids: number[]) => view.flyTo(ids.map(posOf));

function onCanvasPointerDown(e: PointerEvent) {
  if (e.button !== 0) return;
  // The page scrolls under a finger until the map is tapped
  if (touchLocked.value && e.pointerType === 'touch') {
    tapStart = { x: e.clientX, y: e.clientY };
    return;
  }
  if (view.pointerDown(e) === 'pinch') return;
  selectedLinkId.value = null;
  selectedDeviceId.value = null;
  focusedId.value = null;
}

/** A plain wheel that the map left to the page shows briefly how to zoom instead. */
function onCanvasWheel(e: WheelEvent) {
  if (view.onWheel(e)) return;
  wheelHint.value = true;
  window.clearTimeout(wheelHintTimer);
  wheelHintTimer = window.setTimeout(() => (wheelHint.value = false), 1500);
}

// A tap outside the map gives the gestures back to the page
useEventListener(window, 'pointerdown', (e: PointerEvent) => {
  if (touchActive.value && canvasRef.value && !canvasRef.value.contains(e.target as Node)) touchActive.value = false;
});

function onCanvasDoubleClick() {
  focusedId.value = null;
  fitView(true);
}

// ── Editing ──────────────────────────────────────────────────────────────────
/**
 * The first change makes the arrangement the user's own: save every position as shown (so
 * nothing jumps back to an old saved spot) and remember that the orbit is custom from now on.
 */
async function ensureCustom() {
  if (appearance.orbitCustom) return;
  const shown = new Map(positions.value);
  await Promise.all(
    [...shown].map(([id, p]) => {
      store.patchDevice(id, { topology_x: p.x, topology_y: p.y });
      return api.updateDevice(id, { topology_x: p.x, topology_y: p.y }).catch(() => {});
    }),
  );
  await appearance.setOrbitCustom(true).catch(() => {});
}

/**
 * Before a link changes: pin every body where it is shown right now, so a new, removed or changed link
 * (a second fibre, a backup path) never rearranges the map. Saving the positions runs in the background.
 */
function freezeLayout() {
  if (appearance.orbitCustom) return;
  localPositions.value = new Map(positions.value);
  void ensureCustom();
}

function onBodyPointerDown(body: OrbitBody, e: PointerEvent) {
  e.stopPropagation();
  if (!editing.value) return;
  draggingBodyId.value = body.id;
  dragMoved.value = false;
  dragStartWorld.value = view.screenToWorld(e.clientX, e.clientY);
  dragStartPositions.value = new Map(positions.value);
  dropTarget.value = null;
}

function startBeamConnect(body: OrbitBody, e: PointerEvent) {
  e.stopPropagation();
  if (!editing.value) return;
  connectingFromId.value = body.id;
  connectingCursor.value = posOf(body.id);
}

function onWindowPointerMove(e: PointerEvent) {
  if (view.pointerMove(e)) return;
  if (connectingFromId.value != null) {
    connectingCursor.value = view.screenToWorld(e.clientX, e.clientY);
    return;
  }
  if (draggingBodyId.value == null) return;
  const id = draggingBodyId.value;
  const world = view.screenToWorld(e.clientX, e.clientY);
  const dx = world.x - dragStartWorld.value.x;
  const dy = world.y - dragStartWorld.value.y;
  if (Math.hypot(dx, dy) > 3) dragMoved.value = true;
  const startPos = dragStartPositions.value.get(id) ?? { x: 0, y: 0 };
  const candidate = { x: startPos.x + dx, y: startPos.y + dy };
  // Hovering another planet or star offers to orbit it instead
  const target = findDropTargetBody(id, candidate, bodies.value, dragStartPositions.value);
  dropTarget.value = target && target.id !== bodies.value.get(id)?.parentId ? target : null;
  const body = bodies.value.get(id);
  if (!body) return;
  if (body.kind === 'moon') {
    // A moon snaps onto a sibling's ring
    const snapped = dropTarget.value ? candidate : snapToOrbitRing(id, candidate, bodies.value, dragStartPositions.value);
    localPositions.value = new Map(localPositions.value).set(id, snapped);
  } else {
    // A planet or star takes its whole system along; a planet also snaps onto its tier ring
    const snapped = body.kind === 'planet' && !dropTarget.value ? snapToOrbitRing(id, candidate, bodies.value, dragStartPositions.value) : candidate;
    localPositions.value = moveWithDescendants(id, { x: snapped.x - startPos.x, y: snapped.y - startPos.y }, bodies.value, dragStartPositions.value);
  }
}

async function onWindowPointerUp(e: PointerEvent) {
  if (tapStart) {
    const start = tapStart;
    tapStart = null;
    // A cancelled pointer is a swipe the page took over for scrolling
    if (e.type === 'pointerup' && Math.hypot(e.clientX - start.x, e.clientY - start.y) < TAP_SLOP_PX) touchActive.value = true;
    return;
  }
  if (view.pointerUp(e)) return;
  if (connectingFromId.value != null) {
    const fromId = connectingFromId.value;
    connectingFromId.value = null;
    const world = view.screenToWorld(e.clientX, e.clientY);
    const hit = bodyList.value.find((b) => b.id !== fromId && Math.hypot(world.x - posOf(b.id).x, world.y - posOf(b.id).y) <= radiusOf(b) + 18);
    if (hit) await createBeamBetween(fromId, hit.id);
    return;
  }
  if (draggingBodyId.value == null) return;
  const id = draggingBodyId.value;
  const moved = dragMoved.value;
  const target = dropTarget.value;
  draggingBodyId.value = null;
  dropTarget.value = null;
  if (!moved) {
    selectedDeviceId.value = id;
    selectedLinkId.value = null;
    return;
  }
  if (target) {
    await assignOrbitToTarget(id, target);
    return;
  }
  const body = bodies.value.get(id);
  const ids = body && body.kind !== 'moon' ? [id, ...getDescendantIds(id, bodies.value)] : [id];
  const dropped = new Map(ids.map((i) => [i, posOf(i)]));
  try {
    await ensureCustom();
    await Promise.all(
      [...dropped].map(([devId, p]) => {
        store.patchDevice(devId, { topology_x: p.x, topology_y: p.y });
        return api.updateDevice(devId, { topology_x: p.x, topology_y: p.y });
      }),
    );
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

/** Pin the selected body's role (or back to automatic); an auto-laid-out map rearranges itself. */
async function setRole(role: OrbitRole | null) {
  const body = selectedBody.value;
  if (!body) return;
  try {
    await appearance.setOrbitRole(body.id, role);
    showToast('success', t('gv.orbit.role_saved', { name: deviceLabel(body.device), role: t(`gv.orbit.role_${role ?? 'auto'}`) }), '');
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

/** Make `childId` orbit `target`: move it onto a free spot of the target's ring and relink it. */
async function assignOrbitToTarget(childId: number, target: OrbitBody) {
  const child = bodies.value.get(childId);
  if (!child || child.id === target.id) return;
  if (target.id !== child.parentId && warnPortLimit(target.device)) return;
  const tPos = posOf(target.id);
  const siblings = bodyList.value.filter((b) => b.parentId === target.id && b.kind === 'moon');
  const radius = siblings.length ? Math.round(Math.hypot(posOf(siblings[0].id).x - tPos.x, posOf(siblings[0].id).y - tPos.y)) : target.kind === 'star' ? 140 : 90;
  const taken = siblings.map((s) => Math.atan2(posOf(s.id).y - tPos.y, posOf(s.id).x - tPos.x));
  // The free angle furthest from the siblings already there
  let best = -Math.PI / 2;
  let bestGap = -1;
  for (let k = 0; k < 24; k++) {
    const a = -Math.PI + (k * Math.PI) / 12;
    const gap = taken.length ? Math.min(...taken.map((x) => Math.abs(Math.atan2(Math.sin(a - x), Math.cos(a - x))))) : Math.PI;
    if (gap > bestGap) {
      bestGap = gap;
      best = a;
    }
  }
  const newPos = { x: Math.round(tPos.x + radius * Math.cos(best)), y: Math.round(tPos.y + radius * Math.sin(best)) };
  try {
    await ensureCustom();
    localPositions.value = new Map(localPositions.value).set(childId, newPos);
    store.patchDevice(childId, { topology_x: newPos.x, topology_y: newPos.y });
    await api.updateDevice(childId, { topology_x: newPos.x, topology_y: newPos.y });
    if (child.parentLinkId != null) {
      await api.deleteTopologyLink(child.parentLinkId).catch(() => {});
      links.value = links.value.filter((l) => l.id !== child.parentLinkId);
    }
    const type = child.device.is_ap || target.device.is_ap || child.device.is_wlan ? 'WLAN' : '1GbE';
    const created = (await api.createTopologyLink({ source_id: target.id, target_id: childId, link_type: type })) as OrbitLink;
    links.value = [...links.value, created];
    showToast('success', t('gv.plan.assigned_to', { parent: deviceLabel(target.device) }), '');
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
    void load();
  }
}

/** Toasts and returns true when `device` has no free port left for one more link (React parity). */
function warnPortLimit(device: Device | undefined): boolean {
  if (!device || !portLimitReached(device, links.value)) return false;
  showToast('error', t('topology.port_limit_reached', { name: deviceLabel(device), current: linkCount(device.id, links.value), max: device.max_ports }), '');
  return true;
}

async function setMaxPorts(device: Device, value: number) {
  store.patchDevice(device.id, { max_ports: value });
  try {
    await api.updateDevice(device.id, { max_ports: value });
    showToast('success', t('gv.orbit.ports_saved', { name: deviceLabel(device) }), '');
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
    void store.loadData(true);
  }
}

async function createBeamBetween(source: number, target: number) {
  if (source === target) return;
  if (links.value.some((l) => (l.source_id === source && l.target_id === target) || (l.source_id === target && l.target_id === source))) {
    showToast('info', t('gv.plan.link_exists'), '');
    return;
  }
  const a = devicesById.value.get(source);
  const b = devicesById.value.get(target);
  if (warnPortLimit(a) || warnPortLimit(b)) return;
  freezeLayout();
  try {
    const type = a?.is_ap || b?.is_ap || a?.is_wlan || b?.is_wlan ? 'WLAN' : '1GbE';
    const created = (await api.createTopologyLink({ source_id: source, target_id: target, link_type: type })) as OrbitLink;
    links.value = [...links.value, created];
    selectedLinkId.value = created.id;
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

async function patchLink(patch: Partial<OrbitLink>) {
  const link = selectedLink.value;
  if (!link) return;
  freezeLayout();
  links.value = links.value.map((l) => (l.id === link.id ? { ...l, ...patch } : l));
  try {
    await api.updateTopologyLink(link.id, patch as never);
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
    void load();
  }
}

async function deleteLink() {
  const link = selectedLink.value;
  if (!link) return;
  freezeLayout();
  links.value = links.value.filter((l) => l.id !== link.id);
  selectedLinkId.value = null;
  try {
    await api.deleteTopologyLink(link.id);
  } catch (err) {
    showToast('error', t('notifications.delete_failed'), (err as Error).message);
    void load();
  }
}

/** Back to clean automatic orbits, saved as the user's arrangement. */
async function arrange() {
  const ok = await confirm({ title: t('gv.plan.arrange'), message: t('gv.plan.arrange_confirm') });
  if (!ok) return;
  const layout = autoOrbitLayout(store.devices, links.value, gatewayIds.value, appearance.orbitRoles);
  localPositions.value = new Map(layout);
  await Promise.all([...layout].map(([id, p]) => api.updateDevice(id, { topology_x: p.x, topology_y: p.y }).catch(() => {})));
  await appearance.setOrbitCustom(true).catch(() => {});
  await store.loadData(true);
  window.setTimeout(() => fitView(true), 60);
}

function toggleEditing() {
  editing.value = !editing.value;
  focusedId.value = null;
  traceFromId.value = null;
  traceToId.value = null;
  selectedLinkId.value = null;
  selectedDeviceId.value = null;
}

// ── Focus, search, path tracing (view mode) ─────────────────────────────────
function onBodyClick(body: OrbitBody, e: MouseEvent) {
  e.stopPropagation();
  if (editing.value) {
    selectedDeviceId.value = body.id;
    selectedLinkId.value = null;
  } else if (traceFromId.value != null) {
    if (body.id !== traceFromId.value) {
      traceToId.value = body.id;
      flyToBodies(tracedPath.value ? tracedPath.value.bodyIds : [traceFromId.value, body.id]);
    }
  } else {
    focusedId.value = body.id;
    searchQuery.value = '';
    flyToBodies([...computeFocusSet(body.id, bodies.value, lightBeams.value).bodyIds]);
  }
}

function onBodyDoubleClick(body: OrbitBody, e: MouseEvent) {
  e.stopPropagation();
  if (!editing.value) emit('openDevice', body.device);
}

function startTrace(fromId: number) {
  traceFromId.value = fromId;
  traceToId.value = null;
  focusedId.value = null;
  searchQuery.value = '';
  flyToBodies([fromId]);
}
function cancelTrace() {
  traceFromId.value = null;
  traceToId.value = null;
  fitView(true);
}

const tracedPath = computed<TracedPath | null>(() => (traceFromId.value != null && traceToId.value != null ? findPath(traceFromId.value, traceToId.value, lightBeams.value) : null));
const traceHops = computed(() => {
  const path = tracedPath.value;
  if (!path) return [];
  return path.bodyIds.map((id, i) => {
    const beam = i > 0 ? lightBeams.value.find((b) => b.id === path.beamIds[i - 1]) : null;
    const body = bodies.value.get(id);
    return { id, label: body ? deviceLabel(body.device) : '?', linkType: beam?.linkType ?? null, interrupted: beam?.interrupted ?? false };
  });
});
const traceLayer = computed(() => {
  const path = tracedPath.value;
  if (!path) return { segments: [], hops: [] };
  return {
    segments: path.beamIds.map((beamId, i) => ({ key: beamId, from: path.bodyIds[i], to: path.bodyIds[i + 1], interrupted: lightBeams.value.find((b) => b.id === beamId)?.interrupted ?? false })),
    hops: path.bodyIds,
  };
});
const traceStartLabel = computed(() => {
  const b = traceFromId.value != null ? bodies.value.get(traceFromId.value) : null;
  return b ? deviceLabel(b.device) : '?';
});

const problemIds = computed(() => problemBodyIds(bodyList.value));
/** Bodies that need attention are drawn last, so their halo lies on top rather than under a neighbour */
const paintOrder = computed(() => [...bodyList.value.filter((b) => b.state === 'online'), ...bodyList.value.filter((b) => b.state !== 'online')]);
/**
 * Each press focuses the body after the focused one among those that need attention (offline
 * first), with its focus card. A search or a path trace would keep their own spotlight, so they end.
 */
function focusNextProblem() {
  const ids = problemIds.value;
  if (!ids.length) return;
  const id = ids[(ids.indexOf(focusedId.value ?? -1) + 1) % ids.length];
  if (traceFromId.value != null) cancelTrace();
  searchQuery.value = '';
  focusedId.value = id;
  flyToBodies([...computeFocusSet(id, bodies.value, lightBeams.value).bodyIds]);
}
const searchHits = computed(() => matchBodies(searchQuery.value, bodyList.value, (b) => deviceLabel(b.device)));
function submitSearch() {
  const ids = searchHits.value.map((b) => b.id);
  if (ids.length) flyToBodies(ids);
}

function onWindowKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return;
  if (traceFromId.value != null) cancelTrace();
  else if (searchQuery.value) searchQuery.value = '';
  else if (focusedId.value != null) {
    focusedId.value = null;
    fitView(true);
  } else if (touchActive.value) touchActive.value = false;
}

/** What stays lit: focus, search and tracing dim the rest hard, hover only softly. */
const spotlight = computed<{ set: FocusSet; strong: boolean } | null>(() => {
  if (editing.value) return null;
  if (traceFromId.value != null) {
    const path = tracedPath.value;
    return { set: { bodyIds: new Set(path ? path.bodyIds : [traceFromId.value]), beamIds: new Set(path ? path.beamIds : []) }, strong: true };
  }
  if (searchQuery.value.trim()) return { set: focusSetFromIds(searchHits.value.map((b) => b.id), lightBeams.value), strong: true };
  if (focusedId.value != null) return { set: computeFocusSet(focusedId.value, bodies.value, lightBeams.value), strong: true };
  if (resilienceMode.value) return { set: focusSetFromIds(resilience.value.singlePoints.map((p) => p.id), lightBeams.value), strong: true };
  if (hoveredBodyId.value != null) return { set: computeFocusSet(hoveredBodyId.value, bodies.value, lightBeams.value), strong: false };
  return null;
});
function bodyDim(id: number): number {
  const s = spotlight.value;
  if (!s || s.set.bodyIds.has(id)) return 1;
  return s.strong ? 0.16 : 0.55;
}
function beamDim(id: number): number {
  const s = spotlight.value;
  if (!s || s.set.beamIds.has(id)) return 1;
  return s.strong ? 0.1 : 0.5;
}

const focusedInfo = computed(() => {
  const b = focusedId.value != null ? bodies.value.get(focusedId.value) : null;
  if (!b) return null;
  return {
    body: b,
    parent: b.parentId != null ? (bodies.value.get(b.parentId) ?? null) : null,
    moons: bodyList.value.filter((o) => o.parentId === b.id).length,
    beams: lightBeams.value.filter((l) => l.sourceId === b.id || l.targetId === b.id).length,
    badge: roleBadge(b.device),
    resilience:
      b.kind === 'star'
        ? null
        : {
            dependsOn: (resilience.value.dependsOn.get(b.id) ?? []).map((id) => deviceLabel(devicesById.value.get(id) ?? b.device)),
            cutOff: resilience.value.singlePoints.find((p) => p.id === b.id)?.cutOff.length ?? 0,
            unconnected: resilience.value.unconnectedIds.has(b.id),
            cutOffNow: failover.value.cutOffIds.has(b.id),
          },
  };
});

const resiliencePoints = computed(() =>
  resilience.value.singlePoints.map((p) => ({ id: p.id, label: deviceLabel(devicesById.value.get(p.id)!), cutOff: p.cutOff.length })),
);
/** Online devices nothing reaches now; `unlinked` when no link on the map leads to the core at all */
const cutOffDevices = computed(() =>
  [...failover.value.cutOffIds].map((id) => ({
    id,
    label: devicesById.value.get(id) ? deviceLabel(devicesById.value.get(id)!) : String(id),
    unlinked: resilience.value.unconnectedIds.has(id),
  })),
);
/** Resilience list: focus the device with its card, like a problem from the warning button. */
function focusSinglePoint(id: number) {
  focusedId.value = id;
  flyToBodies([...computeFocusSet(id, bodies.value, lightBeams.value).bodyIds]);
}

/** Focus card "to hub": focus the body the focused one orbits. */
function focusParent() {
  const parent = focusedInfo.value?.parent;
  if (!parent) return;
  focusedId.value = parent.id;
  flyToBodies([...computeFocusSet(parent.id, bodies.value, lightBeams.value).bodyIds]);
}

function onBeamSelect(beamId: number, e: MouseEvent) {
  e.stopPropagation();
  if (!editing.value) return;
  selectedLinkId.value = beamId;
  selectedDeviceId.value = null;
}

onMounted(() => {
  void load();
  void appearance.load();
  if (!store.loaded) void store.loadData();
  window.addEventListener('pointermove', onWindowPointerMove);
  window.addEventListener('pointerup', onWindowPointerUp);
  window.addEventListener('pointercancel', onWindowPointerUp);
  window.addEventListener('keydown', onWindowKeyDown);
});
onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onWindowPointerMove);
  window.removeEventListener('pointerup', onWindowPointerUp);
  window.removeEventListener('pointercancel', onWindowPointerUp);
  window.removeEventListener('keydown', onWindowKeyDown);
  window.clearTimeout(wheelHintTimer);
  view.cancel();
});

// Fit once, when the map first has something to show. Saving a drag or a role replaces the device
// list, and refitting then threw the user's zoom away mid-edit.
// On a phone the map may have no size yet at that moment, so the first fit counts only once it
// happened, and the map tries again as soon as it gets one.
let fitted = false;
const ready = computed(() => loaded.value && store.devices.length > 0);
function initialFit() {
  if (!fitted && ready.value) fitted = fitView();
}
watch(ready, (isReady) => isReady && window.setTimeout(initialFit, 60), { immediate: true });
useResizeObserver(svgRef, initialFit);
</script>

<template>
  <div
    :id="flowId"
    ref="canvasRef"
    class="cosmic-canvas relative h-full w-full overflow-hidden select-none"
    :class="[editing && 'is-editing', vitalityMode === 'subtle' && 'vitality-subtle', vitalityMode === 'lively' && 'vitality-lively']"
  >
    <!-- A group, not an image: the bodies inside are buttons that assistive technology must reach -->
    <svg
      ref="svgRef"
      class="h-full w-full"
      :class="touchLocked ? 'touch-pan-y' : 'touch-none'"
      role="group"
      :aria-label="t('gv.plan.title')"
      @wheel="onCanvasWheel"
      @pointerdown="onCanvasPointerDown"
      @dblclick="onCanvasDoubleClick"
    >
      <defs>
        <radialGradient v-for="body in bodyList" :id="`${flowId}-nebula-${body.id}`" :key="`nebula-${body.id}`" cx="50%" cy="50%" r="50%">
          <stop offset="0%" :stop-color="body.color" stop-opacity="0.32" />
          <stop offset="45%" :stop-color="body.color" stop-opacity="0.12" />
          <stop offset="100%" :stop-color="body.color" stop-opacity="0" />
        </radialGradient>
      </defs>

      <g :transform="`translate(${view.viewX.value}, ${view.viewY.value}) scale(${view.zoom.value})`">
        <!-- Background stars -->
        <g class="cosmic-starfield pointer-events-none" aria-hidden="true">
          <circle
            v-for="s in cosmicStars"
            :key="s.id"
            :cx="s.x"
            :cy="s.y"
            :r="s.r"
            fill="var(--gl-fg)"
            :fill-opacity="s.opacity"
            :class="s.twinkle && 'star-twinkle'"
            :style="{ animationDelay: s.delay }"
          />
        </g>

        <!-- Nebula glow around stars and planets -->
        <g class="pointer-events-none" aria-hidden="true">
          <circle
            v-for="body in bodyList.filter((b) => b.kind !== 'moon')"
            :key="`neb-${body.id}`"
            :cx="posOf(body.id).x"
            :cy="posOf(body.id).y"
            :r="body.kind === 'star' ? 120 : 80"
            :fill="`url(#${flowId}-nebula-${body.id})`"
            class="transition-opacity duration-300"
            :class="[activeClusterCenterId === body.id ? 'opacity-90' : 'opacity-40', body.kind === 'star' && 'star-nebula-pulse']"
          />
        </g>

        <!-- Orbits: always faint, the inspected hub's rings brighter -->
        <g class="pointer-events-none" aria-hidden="true">
          <circle
            v-for="ring in orbitRings"
            :key="ring.id"
            :cx="posOf(ring.centerId).x"
            :cy="posOf(ring.centerId).y"
            :r="ring.radius"
            fill="none"
            :stroke="ring.style === 'broken' ? 'var(--gl-danger)' : ring.color"
            :stroke-width="activeClusterCenterId === ring.centerId || editing ? 1.6 : 1.1"
            :stroke-dasharray="ring.style === 'broken' ? '4 10' : ring.style === 'dashed' ? '6 6' : undefined"
            :stroke-opacity="activeClusterCenterId === ring.centerId ? 0.6 : ring.style === 'broken' ? 0.35 : 0.22"
            class="transition-[stroke-opacity] duration-300"
          />
          <circle
            v-if="activeDragOrbit"
            :cx="activeDragOrbit.center.x"
            :cy="activeDragOrbit.center.y"
            :r="activeDragOrbit.radius"
            fill="none"
            :stroke="activeDragOrbit.color"
            stroke-width="1.75"
            stroke-dasharray="4 4"
            stroke-opacity="0.75"
          />
          <g v-if="dropTarget">
            <circle
              :cx="posOf(dropTarget.id).x"
              :cy="posOf(dropTarget.id).y"
              :r="radiusOf(dropTarget) + 24"
              fill="none"
              stroke="var(--gl-accent)"
              stroke-width="2.5"
              stroke-dasharray="6 4"
              class="orbit-drop-ring"
            />
            <circle :cx="posOf(dropTarget.id).x" :cy="posOf(dropTarget.id).y" :r="radiusOf(dropTarget) + 14" fill="var(--gl-accent)" fill-opacity="0.16" />
          </g>
        </g>

        <OrbitBeamLayer
          :beams="lightBeams"
          :pos="posOf"
          :centre-of="beamCentre"
          :dim="beamDim"
          :selected-id="selectedLinkId"
          :animated="vitalityMode !== 'off'"
          :connecting="connectingFromId != null ? { from: posOf(connectingFromId), to: connectingCursor } : null"
          :trace="traceLayer"
          @select="onBeamSelect"
        />

        <g>
          <OrbitBodyNode
            v-for="(body, idx) in paintOrder"
            :key="body.id"
            :body="body"
            :pos="posOf(body.id)"
            :label="labels.get(body.id) ?? null"
            :label-scale="labelScale"
            :index="idx"
            :editing="editing"
            :selected="selectedDeviceId === body.id"
            :dim="bodyDim(body.id)"
            :badge="roleBadge(body.device)"
            @down="onBodyPointerDown(body, $event)"
            @click="onBodyClick(body, $event)"
            @dblclick="onBodyDoubleClick(body, $event)"
            @enter="hoveredBodyId = body.id"
            @leave="hoveredBodyId = null"
            @beam-start="startBeamConnect(body, $event)"
          />
        </g>
      </g>
    </svg>

    <div
      v-if="dropTarget"
      class="pointer-events-none absolute top-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full border border-accent bg-surface/95 px-3.5 py-1.5 text-xs font-semibold text-accent-text shadow-pop"
    >
      <Orbit class="size-3.5" aria-hidden="true" />
      <span>{{ t('gv.orbit.drop_to', { name: deviceLabel(dropTarget.device) }) }}</span>
    </div>

    <!-- Search: highlights matches, Enter flies there -->
    <div
      v-if="!editing"
      class="absolute top-3 left-3 z-10 flex h-9 items-center gap-2 rounded-md border border-line bg-surface/95 px-2.5 shadow-pop backdrop-blur focus-within:border-accent"
      :class="editable ? 'w-[min(16rem,calc(100%-12rem))]' : 'w-[min(16rem,calc(100%-1.5rem))]'"
      @pointerdown.stop
    >
      <Search class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
      <input
        v-model="searchQuery"
        type="search"
        class="min-w-0 flex-1 bg-transparent text-sm text-ellipsis text-fg placeholder:text-fg-subtle focus:outline-none"
        :placeholder="t('gv.orbit.search')"
        :aria-label="t('gv.orbit.search_label')"
        @keydown.enter.prevent="submitSearch"
      />
      <span v-if="searchQuery" class="font-mono text-micro text-fg-subtle" aria-live="polite">{{ searchHits.length }}</span>
    </div>

    <OrbitFocusCard
      v-if="!editing && focusedInfo && traceFromId == null"
      :body="focusedInfo.body"
      :parent="focusedInfo.parent"
      :moons="focusedInfo.moons"
      :beams="focusedInfo.beams"
      :badge="focusedInfo.badge"
      :resilience="focusedInfo.resilience"
      @close="focusedId = null; fitView(true)"
      @open="emit('openDevice', focusedInfo.body.device)"
      @to-hub="focusParent"
      @centre="flyToBodies([focusedInfo.body.id])"
      @trace="startTrace(focusedInfo.body.id)"
    />

    <p
      v-if="!editing && !focusedInfo && !searchQuery && traceFromId == null && !(coarsePointer && pageScrolls)"
      class="pointer-events-none absolute bottom-3 left-3 z-10 hidden max-w-xs rounded-md border border-line bg-surface/90 px-2.5 py-1.5 text-xs text-fg-muted backdrop-blur sm:block"
    >
      {{ pageScrolls ? t('gv.orbit.hint_embedded', { key: modifierKey }) : t('gv.orbit.hint') }}
    </p>

    <!-- Plain wheel over the embedded map: the page scrolls, this says how to zoom -->
    <p
      v-if="pageScrolls"
      class="pointer-events-none absolute top-1/2 left-1/2 z-20 -translate-x-1/2 -translate-y-1/2 rounded-md border border-line bg-surface/95 px-3 py-1.5 text-xs font-medium text-fg shadow-pop backdrop-blur transition-opacity duration-200"
      :class="wheelHint ? 'opacity-100' : 'opacity-0'"
      aria-hidden="true"
    >
      {{ t('gv.orbit.wheel_hint', { key: modifierKey }) }}
    </p>

    <!-- Touch on the embedded map: take the gestures from the page, and give them back -->
    <button
      v-if="coarsePointer && pageScrolls && !resilienceMode"
      type="button"
      class="absolute top-14 right-3 z-20 inline-flex h-11 items-center gap-1.5 rounded-full border px-3.5 text-xs font-semibold shadow-pop backdrop-blur"
      :class="touchActive ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-surface/95 text-fg'"
      @click="touchActive = !touchActive"
    >
      <component :is="touchActive ? Check : Hand" class="size-3.5" aria-hidden="true" />{{ touchActive ? t('gv.orbit.touch_release') : t('gv.orbit.touch_activate') }}
    </button>

    <OrbitResiliencePanel
      v-if="resilienceMode && !editing && traceFromId == null"
      :points="resiliencePoints"
      :active-backups="failover.activeBackupIds.size"
      :cut-off="cutOffDevices"
      @select="focusSinglePoint"
      @close="resilienceMode = false"
    />

    <OrbitTracePanel v-if="!editing && traceFromId != null" :start-label="traceStartLabel" :has-target="traceToId != null" :path="tracedPath" :hops="traceHops" @close="cancelTrace" />

    <!-- Motion and zoom controls; a row on phones, where a column of 44 px buttons covered the map height -->
    <div class="absolute right-3 bottom-3 z-10 flex flex-col overflow-hidden rounded-md border border-line bg-surface shadow-pop max-md:flex-row">
      <button
        v-if="problemIds.length && !editing"
        type="button"
        class="flex h-8 items-center justify-center gap-0.5 border-b border-line bg-danger/10 max-md:h-11 max-md:min-w-11 max-md:border-r max-md:border-b-0 px-1 font-mono text-xs font-semibold text-danger-text hover:bg-danger/20"
        :title="t('gv.orbit.problems_label', { count: problemIds.length })"
        :aria-label="t('gv.orbit.problems_label', { count: problemIds.length })"
        @click="focusNextProblem"
      >
        <TriangleAlert class="size-3.5 shrink-0" aria-hidden="true" />{{ problemIds.length }}
      </button>
      <button
        v-if="!editing"
        type="button"
        class="flex size-8 items-center justify-center border-b border-line text-fg-muted hover:bg-control-hover hover:text-fg max-md:size-11 max-md:border-r max-md:border-b-0"
        :class="resilienceMode && 'bg-warn/10 text-warn-text'"
        :title="t('gv.orbit.resilience')"
        :aria-label="t('gv.orbit.resilience')"
        :aria-pressed="resilienceMode"
        @click="resilienceMode = !resilienceMode"
      >
        <ShieldAlert class="size-3.5" />
      </button>
      <button
        type="button"
        class="flex size-8 items-center justify-center text-fg-muted hover:bg-control-hover hover:text-fg max-md:size-11"
        :class="vitalityMode !== 'off' && 'text-accent-text'"
        :title="t('gv.orbit.motion', { mode: t(`gv.orbit.motion_${vitalityMode}`) })"
        :aria-label="t('gv.orbit.motion', { mode: t(`gv.orbit.motion_${vitalityMode}`) })"
        @click="cycleVitality"
      >
        <Sparkles class="size-3.5" />
      </button>
      <button type="button" class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg max-md:size-11 max-md:border-t-0 max-md:border-l" :aria-label="t('gv.plan.zoom_in')" @click="view.zoomBy(1.2)">
        <Plus class="size-4" />
      </button>
      <button type="button" class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg max-md:size-11 max-md:border-t-0 max-md:border-l" :aria-label="t('gv.plan.zoom_out')" @click="view.zoomBy(0.82)">
        <Minus class="size-4" />
      </button>
      <button type="button" class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg max-md:size-11 max-md:border-t-0 max-md:border-l" :aria-label="t('gv.plan.fit')" @click="fitView(true)">
        <Maximize class="size-3.5" />
      </button>
      <button
        v-if="fullscreenSupported"
        type="button"
        class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg max-md:size-11 max-md:border-t-0 max-md:border-l"
        :aria-label="isFullscreen ? t('gv.orbit.exit_fullscreen') : t('gv.orbit.fullscreen')"
        :title="isFullscreen ? t('gv.orbit.exit_fullscreen') : t('gv.orbit.fullscreen')"
        :aria-pressed="isFullscreen"
        @click="toggleFullscreen()"
      >
        <component :is="isFullscreen ? Shrink : Expand" class="size-3.5" />
      </button>
    </div>

    <div v-if="editable" class="absolute top-3 right-3 z-10 flex gap-2">
      <Button v-if="editing" size="sm" @click="arrange"><Wand2 aria-hidden="true" />{{ t('gv.plan.arrange') }}</Button>
      <Button size="sm" :variant="editing ? 'primary' : 'secondary'" @click="toggleEditing">
        <component :is="editing ? Check : Pencil" aria-hidden="true" />
        {{ editing ? t('dashboard.edit_finish') : t('gv.plan.edit') }}
      </Button>
    </div>

    <p
      v-if="editing && !selectedLink && !selectedDevice"
      class="absolute bottom-3 left-3 z-10 flex max-w-md items-start gap-2 rounded-md border border-line bg-surface/95 px-3 py-2 text-xs text-fg-muted shadow-pop backdrop-blur"
    >
      <MousePointer2 class="mt-0.5 size-3.5 shrink-0 text-accent-text" aria-hidden="true" />
      {{ t('gv.plan.edit_hint') }}
    </p>

    <OrbitLinkInspector v-if="editing && selectedLink" :link="selectedLink" :ends="linkEnds" :swatches="swatches" @patch="patchLink" @remove="deleteLink" @close="selectedLinkId = null" />

    <OrbitBodyInspector
      v-if="editing && selectedDevice && selectedBody"
      :device="selectedDevice"
      :body="selectedBody"
      :parents="assignableParents"
      :chosen-role="appearance.orbitRoles[String(selectedBody.id)] ?? null"
      :has-orbiters="bodyList.some((b) => b.parentId === selectedBody?.id)"
      :links="linkCount(selectedBody.id, links)"
      @max-ports="(value) => selectedDevice && setMaxPorts(selectedDevice, value)"
      @role="setRole"
      @open="emit('openDevice', selectedDevice)"
      @close="selectedDeviceId = null"
      @assign="(targetId) => { const tgt = bodies.get(targetId); if (tgt && selectedBody) assignOrbitToTarget(selectedBody.id, tgt); }"
    />
  </div>
</template>

<style scoped>
.cosmic-canvas {
  background-color: var(--gl-canvas);
  background-image:
    radial-gradient(ellipse 65% 50% at 50% 35%, rgba(46, 196, 166, 0.045) 0%, transparent 70%),
    radial-gradient(circle at 82% 18%, rgba(90, 169, 255, 0.04) 0%, transparent 50%),
    radial-gradient(circle at 18% 75%, rgba(255, 159, 67, 0.03) 0%, transparent 50%);
}

:root[data-theme='light'] .cosmic-canvas {
  background-color: var(--gl-surface);
  background-image:
    radial-gradient(ellipse 65% 50% at 50% 35%, rgba(8, 122, 101, 0.035) 0%, transparent 70%),
    radial-gradient(circle at 82% 18%, rgba(31, 111, 209, 0.03) 0%, transparent 50%),
    radial-gradient(circle at 18% 75%, rgba(240, 138, 36, 0.025) 0%, transparent 50%);
}

.cosmic-canvas.is-editing {
  background-image:
    radial-gradient(var(--gl-line-strong) 1px, transparent 1px),
    radial-gradient(ellipse 65% 50% at 50% 35%, rgba(46, 196, 166, 0.045) 0%, transparent 70%);
  background-size: 28px 28px, 100% 100%;
}

@keyframes star-twinkle {
  0%,
  100% {
    opacity: 0.25;
    transform: scale(0.9);
  }
  50% {
    opacity: 0.9;
    transform: scale(1.15);
  }
}

.star-twinkle {
  animation: star-twinkle 4.5s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

@keyframes orbit-float {
  0%,
  100% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-3.5px);
  }
}

@keyframes corona-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.16;
  }
  50% {
    transform: scale(1.18);
    opacity: 0.3;
  }
}

@keyframes diffraction-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.75;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.95;
  }
}

@keyframes beam-flow {
  from {
    stroke-dashoffset: 128;
  }
  to {
    stroke-dashoffset: 0;
  }
}

@keyframes drop-ring-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.vitality-subtle :deep(.orbit-float-node) {
  animation: orbit-float 5.8s ease-in-out infinite;
}

.vitality-lively :deep(.orbit-float-node) {
  animation: orbit-float 3.4s ease-in-out infinite;
}

.vitality-subtle :deep(.star-corona),
.vitality-subtle :deep(.planet-halo) {
  animation: corona-pulse 4.5s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-lively :deep(.star-corona),
.vitality-lively :deep(.planet-halo) {
  animation: corona-pulse 2.6s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-subtle :deep(.star-diffraction) {
  animation: diffraction-pulse 4.5s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-lively :deep(.star-diffraction) {
  animation: diffraction-pulse 2.6s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-subtle :deep(.photon-pulse) {
  animation: beam-flow 4.2s linear infinite;
}

.vitality-lively :deep(.photon-pulse) {
  animation: beam-flow 2.2s linear infinite;
}

@keyframes trace-flow {
  to {
    stroke-dashoffset: -36;
  }
}

:deep(.trace-flow) {
  animation: trace-flow 0.9s linear infinite;
}

.orbit-drop-ring {
  animation: drop-ring-spin 8s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}

@media (prefers-reduced-motion: reduce) {
  .star-twinkle,
  :deep(.orbit-float-node),
  :deep(.star-corona),
  :deep(.planet-halo),
  :deep(.star-diffraction),
  :deep(.photon-pulse),
  :deep(.trace-flow),
  .orbit-drop-ring {
    animation: none !important;
  }
}
</style>
