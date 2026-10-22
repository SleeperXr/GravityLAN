<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useStorage } from '@vueuse/core';
import {
  Check,
  Maximize,
  Minus,
  MousePointer2,
  Orbit,
  Pencil,
  Plus,
  Route,
  Search,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device } from '@/types';
import { useNetworkStore } from '@/stores/network';
import { useAppearance } from '@/stores/appearance';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import Button from '@/components/ui/Button.vue';
import {
  LINK_TYPES,
  autoOrbitLayout,
  computeLightBeams,
  computeOrbitRings,
  findDropTargetBody,
  getDescendantIds,
  moveWithDescendants,
  resolveOrbitSystem,
  snapToOrbitRing,
  type OrbitBody,
  type OrbitLink,
  type Point,
} from './orbitModel';
import {
  computeFocusSet,
  easeInOutCubic,
  findPath,
  fitTransform,
  focusSetFromIds,
  lerpView,
  matchBodies,
  zoomAround,
  type FocusSet,
  type TracedPath,
  type ViewTransform,
} from './orbitFocus';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

const props = withDefaults(
  defineProps<{ editable?: boolean; startEditing?: boolean; flowId?: string }>(),
  {
    editable: false,
    startEditing: false,
    flowId: 'orbit',
  },
);
const emit = defineEmits<{ openDevice: [device: Device] }>();

const store = useNetworkStore();
const appearance = useAppearance();
const { showToast } = useToast();
const { confirm } = useConfirm();

const reduceMotionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const prefersReducedMotion = ref(Boolean(reduceMotionQuery?.matches));

/**
 * Vitality mode: 'off' | 'subtle' | 'lively'
 * Defaults to 'off' when OS reduced-motion is set, otherwise 'subtle', and is manually adjustable by the user.
 */
const vitalityMode = useStorage<'off' | 'subtle' | 'lively'>(
  'gravityui.orbit.vitality',
  prefersReducedMotion.value ? 'off' : 'subtle',
);

function cycleVitality() {
  const order: ('off' | 'subtle' | 'lively')[] = ['off', 'subtle', 'lively'];
  const nextIdx = (order.indexOf(vitalityMode.value) + 1) % order.length;
  vitalityMode.value = order[nextIdx];
}

const editing = ref(props.editable && props.startEditing);
const links = ref<OrbitLink[]>([]);
const gatewayIds = ref(new Set<number>());
const localPositions = ref(new Map<number, Point>());
const selectedLinkId = ref<number | null>(null);
const selectedDeviceId = ref<number | null>(null);
const hoveredBodyId = ref<number | null>(null);
const hoveredBeamId = ref<number | null>(null);
const loaded = ref(false);

// Viewport pan & zoom state
const svgRef = ref<SVGSVGElement | null>(null);
const viewX = ref(0);
const viewY = ref(0);
const zoom = ref(1);
const isPanning = ref(false);
const panStart = ref<Point>({ x: 0, y: 0 });

// Drag state (moving a body or drawing a light beam)
const draggingBodyId = ref<number | null>(null);
const dragStartWorld = ref<Point>({ x: 0, y: 0 });
const dragStartPositions = ref(new Map<number, Point>());
const dragMoved = ref(false);
const dropTarget = ref<OrbitBody | null>(null);

// Focus mode (view mode): a clicked hub/device dims everything unrelated
const focusedId = ref<number | null>(null);
const searchQuery = ref('');
// Path tracing: pick a start (focus card), then click the destination
const traceFromId = ref<number | null>(null);
const traceToId = ref<number | null>(null);
const activePointers = new Map<number, Point>();
let pinchStartDistance = 0;
let pinchStartView: ViewTransform | null = null;
let viewAnimationFrame = 0;

const connectingFromId = ref<number | null>(null);
const connectingCursor = ref<Point>({ x: 0, y: 0 });

async function load() {
  try {
    const [linkList, gateways] = await Promise.all([
      api.getTopologyLinks() as Promise<OrbitLink[]>,
      api.getGateways().catch(() => []),
    ]);
    links.value = linkList;
    gatewayIds.value = new Set(
      gateways.map((g) => g.device_id).filter((id): id is number => id != null),
    );
  } catch {
    links.value = [];
  } finally {
    loaded.value = true;
  }
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
  cancelViewAnimation();
});

const devicesById = computed(() => new Map(store.devices.map((d) => [d.id, d])));

const bodies = computed(() =>
  resolveOrbitSystem(store.devices, links.value, gatewayIds.value),
);

const bodyList = computed(() => [...bodies.value.values()]);

const fallbackLayout = computed(() =>
  autoOrbitLayout(store.devices, links.value, gatewayIds.value),
);

const positions = computed(() => {
  const map = new Map<number, Point>();
  for (const d of store.devices) {
    const local = localPositions.value.get(d.id);
    if (local) {
      map.set(d.id, local);
    } else if (d.topology_x != null && d.topology_y != null) {
      map.set(d.id, { x: d.topology_x, y: d.topology_y });
    } else {
      map.set(d.id, fallbackLayout.value.get(d.id) ?? { x: 0, y: 0 });
    }
  }
  return map;
});

function posOf(id: number): Point {
  return positions.value.get(id) ?? { x: 0, y: 0 };
}

const orbitRings = computed(() => computeOrbitRings(bodies.value, positions.value));
const lightBeams = computed(() => computeLightBeams(links.value, bodies.value));

/**
 * Deterministic Deep-Space Starfield points (astronomical coordinates with varying magnitudes)
 */
interface CosmicStar {
  id: number;
  x: number;
  y: number;
  r: number;
  opacity: number;
  twinkle: boolean;
  delay: string;
}

const cosmicStars = computed<CosmicStar[]>(() => {
  let seed = 1337;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  const list: CosmicStar[] = [];
  for (let i = 0; i < 96; i++) {
    const x = Math.round((rand() - 0.48) * 3600);
    const y = Math.round((rand() - 0.48) * 2600);
    const r = rand() > 0.86 ? 1.4 : rand() > 0.45 ? 1.0 : 0.65;
    const opacity = Math.round((0.25 + rand() * 0.55) * 100) / 100;
    const twinkle = rand() > 0.4;
    const delay = `${Math.round(rand() * 45) / 10}s`;
    list.push({ id: i, x, y, r, opacity, twinkle, delay });
  }
  return list;
});

/**
 * Cluster under active inspection (hover or selection).
 * In Cosmic Constellation mode, orbit rings are contextual and ONLY appear around
 * the inspected hub, preventing the whole screen from turning into a chaotic spiderweb of circles.
 */
const activeClusterCenterId = computed(() => {
  if (draggingBodyId.value) {
    const b = bodies.value.get(draggingBodyId.value);
    return b?.parentId ?? null;
  }
  const activeId = hoveredBodyId.value ?? selectedDeviceId.value;
  if (!activeId) return null;
  const b = bodies.value.get(activeId);
  if (!b) return null;
  return b.kind === 'moon' ? b.parentId : b.id;
});

const visibleOrbitRings = computed(() => {
  if (editing.value) return orbitRings.value;
  if (!activeClusterCenterId.value) return [];
  return orbitRings.value.filter((r) => r.centerId === activeClusterCenterId.value);
});

/** Active preview radius while dragging a body in space */
const activeDragOrbit = computed(() => {
  if (draggingBodyId.value == null || dropTarget.value) return null;
  const body = bodies.value.get(draggingBodyId.value);
  if (!body || body.parentId == null) return null;
  const center = posOf(body.parentId);
  const curr = posOf(body.id);
  const r = Math.hypot(curr.x - center.x, curr.y - center.y);
  return r >= 16 ? { center, radius: Math.round(r), color: body.color } : null;
});

const selectedLink = computed(
  () => links.value.find((l) => l.id === selectedLinkId.value) ?? null,
);
const selectedDevice = computed(() =>
  selectedDeviceId.value ? devicesById.value.get(selectedDeviceId.value) ?? null : null,
);
const selectedBody = computed(() =>
  selectedDeviceId.value ? bodies.value.get(selectedDeviceId.value) ?? null : null,
);

/** Potential orbit parents for the selected device in the inspector dropdown */
const assignableParents = computed(() => {
  const sel = selectedBody.value;
  if (!sel) return [];
  const invalid = new Set([sel.id, ...getDescendantIds(sel.id, bodies.value)]);
  return bodyList.value.filter(
    (b) => !invalid.has(b.id) && (b.kind === 'star' || b.kind === 'planet'),
  );
});

const swatches = computed(() => {
  void appearance.lineColors;
  const style = getComputedStyle(document.documentElement);
  return Array.from({ length: 10 }, (_, i) =>
    style.getPropertyValue(`--line-${i + 1}`).trim(),
  ).filter(Boolean);
});

const linkEnds = computed(() => {
  const l = selectedLink.value;
  if (!l) return '';
  const a = devicesById.value.get(l.source_id);
  const b = devicesById.value.get(l.target_id);
  return `${a ? deviceLabel(a) : '?'} – ${b ? deviceLabel(b) : '?'}`;
});

function bodyRadius(kind: OrbitBody['kind']): number {
  if (kind === 'star') return 22;
  if (kind === 'planet') return 16;
  return 10.5;
}

function roleBadge(device: Device): string | null {
  if (device.is_ap) return 'AP';
  if (device.is_host) return 'HOST';
  const dt = (device.device_type || '').toLowerCase();
  const sub = (device.device_subtype || '').toLowerCase();
  if (dt === 'switch' || sub === 'switch') return 'SW';
  return null;
}

function screenToWorld(clientX: number, clientY: number): Point {
  const svg = svgRef.value;
  if (!svg) return { x: 0, y: 0 };
  const rect = svg.getBoundingClientRect();
  return {
    x: (clientX - rect.left - viewX.value) / zoom.value,
    y: (clientY - rect.top - viewY.value) / zoom.value,
  };
}

function currentView(): ViewTransform {
  return { x: viewX.value, y: viewY.value, zoom: zoom.value };
}

function applyView(v: ViewTransform) {
  viewX.value = v.x;
  viewY.value = v.y;
  zoom.value = v.zoom;
}

function cancelViewAnimation() {
  if (viewAnimationFrame) cancelAnimationFrame(viewAnimationFrame);
  viewAnimationFrame = 0;
}

/** Smoothly glide the viewport to `target` (instant with reduced motion). */
function animateViewTo(target: ViewTransform, duration = 520) {
  cancelViewAnimation();
  if (prefersReducedMotion.value || duration <= 0) {
    applyView(target);
    return;
  }
  const from = currentView();
  const startedAt = performance.now();
  const step = (now: number) => {
    const t = Math.min(1, (now - startedAt) / duration);
    applyView(lerpView(from, target, easeInOutCubic(t)));
    viewAnimationFrame = t < 1 ? requestAnimationFrame(step) : 0;
  };
  viewAnimationFrame = requestAnimationFrame(step);
}

function viewportSize(): { width: number; height: number } | null {
  const svg = svgRef.value;
  if (!svg) return null;
  const rect = svg.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 ? { width: rect.width, height: rect.height } : null;
}

function fitView(animated = false) {
  const size = viewportSize();
  if (!size || store.devices.length === 0) return;

  const points: Point[] = store.devices.map((d) => posOf(d.id));
  // Orbit rings extend the content area; approximate them by four extreme points each
  for (const r of visibleOrbitRings.value) {
    const c = posOf(r.centerId);
    const reach = r.radius - 60;
    points.push(
      { x: c.x - reach, y: c.y },
      { x: c.x + reach, y: c.y },
      { x: c.x, y: c.y - reach },
      { x: c.x, y: c.y + reach },
    );
  }
  const target = fitTransform(points, size.width, size.height, { padding: 0.84 });
  if (!target) return;
  if (animated) animateViewTo(target);
  else applyView(target);
}

/** Fly to a set of bodies (focus / search hit). */
function flyToBodies(ids: number[]) {
  const size = viewportSize();
  if (!size || ids.length === 0) return;
  const target = fitTransform(
    ids.map((id) => posOf(id)),
    size.width,
    size.height,
    { margin: 140, padding: 0.72, maxZoom: 1.5 },
  );
  if (target) animateViewTo(target);
}

function zoomBy(factor: number) {
  const size = viewportSize();
  if (!size) return;
  cancelViewAnimation();
  applyView(
    zoomAround(currentView(), { x: size.width / 2, y: size.height / 2 }, factor),
  );
}

function onWheel(e: WheelEvent) {
  e.preventDefault();
  const svg = svgRef.value;
  if (!svg) return;
  cancelViewAnimation();
  const rect = svg.getBoundingClientRect();
  const factor = e.deltaY < 0 ? 1.12 : 0.89;
  applyView(
    zoomAround(currentView(), { x: e.clientX - rect.left, y: e.clientY - rect.top }, factor),
  );
}

function pointerDistance(): number {
  const [a, b] = [...activePointers.values()];
  return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
}

function pointerMidpoint(): Point {
  const [a, b] = [...activePointers.values()];
  return a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : { x: 0, y: 0 };
}

function onCanvasPointerDown(e: PointerEvent) {
  if (e.button !== 0) return;
  cancelViewAnimation();
  activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

  if (activePointers.size === 2) {
    // Second finger: switch from panning to pinch-zoom
    isPanning.value = false;
    pinchStartDistance = pointerDistance();
    pinchStartView = currentView();
    return;
  }

  isPanning.value = true;
  panStart.value = { x: e.clientX - viewX.value, y: e.clientY - viewY.value };
  selectedLinkId.value = null;
  selectedDeviceId.value = null;
  clearFocus();
}

function onCanvasDoubleClick() {
  clearFocus();
  fitView(true);
}

function onBodyPointerDown(body: OrbitBody, e: PointerEvent) {
  e.stopPropagation();
  if (!editing.value) return;
  draggingBodyId.value = body.id;
  dragMoved.value = false;
  dragStartWorld.value = screenToWorld(e.clientX, e.clientY);
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
  if (activePointers.has(e.pointerId)) {
    activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  }

  if (activePointers.size >= 2 && pinchStartView && pinchStartDistance > 0) {
    const svg = svgRef.value;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const mid = pointerMidpoint();
    const factor = pointerDistance() / pinchStartDistance;
    applyView(
      zoomAround(
        pinchStartView,
        { x: mid.x - rect.left, y: mid.y - rect.top },
        factor,
      ),
    );
    return;
  }

  if (isPanning.value) {
    viewX.value = e.clientX - panStart.value.x;
    viewY.value = e.clientY - panStart.value.y;
    return;
  }

  if (connectingFromId.value != null) {
    connectingCursor.value = screenToWorld(e.clientX, e.clientY);
    return;
  }

  if (draggingBodyId.value != null) {
    const id = draggingBodyId.value;
    const world = screenToWorld(e.clientX, e.clientY);
    const dx = world.x - dragStartWorld.value.x;
    const dy = world.y - dragStartWorld.value.y;
    if (Math.hypot(dx, dy) > 3) dragMoved.value = true;

    const startPos = dragStartPositions.value.get(id) ?? { x: 0, y: 0 };
    const rawCandidate = { x: startPos.x + dx, y: startPos.y + dy };

    // Check if cursor is hovering over another Planet/Star to reassign orbit
    const target = findDropTargetBody(id, rawCandidate, bodies.value, dragStartPositions.value);
    dropTarget.value = target && target.id !== bodies.value.get(id)?.parentId ? target : null;

    const body = bodies.value.get(id);
    if (!body) return;

    if (body.kind === 'star' || body.kind === 'planet') {
      // Moving a Planet or Star moves all of its moons along with it
      localPositions.value = moveWithDescendants(
        id,
        { x: dx, y: dy },
        bodies.value,
        dragStartPositions.value,
      );
    } else {
      // Moving a Moon snaps to sibling orbit rings when not dropping onto a new planet
      const snapped = dropTarget.value
        ? rawCandidate
        : snapToOrbitRing(id, rawCandidate, bodies.value, dragStartPositions.value);
      const next = new Map(localPositions.value);
      next.set(id, snapped);
      localPositions.value = next;
    }
  }
}

async function onWindowPointerUp(e: PointerEvent) {
  activePointers.delete(e.pointerId);
  if (activePointers.size < 2) {
    pinchStartView = null;
    pinchStartDistance = 0;
  }

  if (isPanning.value) {
    isPanning.value = false;
    return;
  }

  if (connectingFromId.value != null) {
    const fromId = connectingFromId.value;
    connectingFromId.value = null;
    const world = screenToWorld(e.clientX, e.clientY);
    const hit = bodyList.value.find((b) => {
      if (b.id === fromId) return false;
      const p = posOf(b.id);
      return Math.hypot(world.x - p.x, world.y - p.y) <= bodyRadius(b.kind) + 18;
    });
    if (hit) {
      await createBeamBetween(fromId, hit.id);
    }
    return;
  }

  if (draggingBodyId.value != null) {
    const id = draggingBodyId.value;
    const moved = dragMoved.value;
    const target = dropTarget.value;
    draggingBodyId.value = null;
    dropTarget.value = null;

    if (!moved) {
      const dev = devicesById.value.get(id);
      if (dev) {
        selectedDeviceId.value = dev.id;
        selectedLinkId.value = null;
      }
      return;
    }

    if (target) {
      await assignOrbitToTarget(id, target);
      return;
    }

    // Persist updated coordinates for the moved body and any descendants that moved with it
    const body = bodies.value.get(id);
    const idsToSave =
      body && (body.kind === 'star' || body.kind === 'planet')
        ? [id, ...getDescendantIds(id, bodies.value)]
        : [id];

    try {
      await Promise.all(
        idsToSave.map((devId) => {
          const pos = posOf(devId);
          store.patchDevice(devId, { topology_x: pos.x, topology_y: pos.y });
          return api.updateDevice(devId, { topology_x: pos.x, topology_y: pos.y });
        }),
      );
    } catch (err) {
      showToast('error', t('notifications.save_failed'), (err as Error).message);
    }
  }
}

function onBodyClick(body: OrbitBody, e: MouseEvent) {
  e.stopPropagation();
  if (editing.value) {
    selectedDeviceId.value = body.id;
    selectedLinkId.value = null;
  } else if (traceFromId.value != null) {
    if (body.id !== traceFromId.value) setTraceTarget(body.id);
  } else {
    focusBody(body.id);
  }
}

function startTrace(fromId: number) {
  traceFromId.value = fromId;
  traceToId.value = null;
  focusedId.value = null;
  searchQuery.value = '';
  flyToBodies([fromId]);
}

function setTraceTarget(toId: number) {
  traceToId.value = toId;
  const path = tracedPath.value;
  flyToBodies(path ? path.bodyIds : [traceFromId.value!, toId]);
}

function cancelTrace() {
  traceFromId.value = null;
  traceToId.value = null;
  fitView(true);
}

const tracedPath = computed<TracedPath | null>(() =>
  traceFromId.value != null && traceToId.value != null
    ? findPath(traceFromId.value, traceToId.value, lightBeams.value)
    : null,
);

const traceHops = computed(() => {
  const path = tracedPath.value;
  if (!path) return [];
  return path.bodyIds.map((id, i) => {
    const beam = i > 0 ? lightBeams.value.find((b) => b.id === path.beamIds[i - 1]) : null;
    const body = bodies.value.get(id);
    return {
      id,
      label: body ? deviceLabel(body.device) : '?',
      linkType: beam?.linkType ?? null,
      interrupted: beam?.interrupted ?? false,
    };
  });
});

/** Line segments of the traced path, in travel order. */
const traceSegments = computed(() => {
  const path = tracedPath.value;
  if (!path) return [];
  return path.beamIds.map((beamId, i) => ({
    key: beamId,
    from: path.bodyIds[i],
    to: path.bodyIds[i + 1],
    interrupted: lightBeams.value.find((b) => b.id === beamId)?.interrupted ?? false,
  }));
});

const traceStartLabel = computed(() => {
  const b = traceFromId.value != null ? bodies.value.get(traceFromId.value) : null;
  return b ? deviceLabel(b.device) : '?';
});

/** Double click / double tap opens the device straight away (view mode). */
function onBodyDoubleClick(body: OrbitBody, e: MouseEvent) {
  e.stopPropagation();
  if (!editing.value) emit('openDevice', body.device);
}

function focusBody(id: number) {
  focusedId.value = id;
  searchQuery.value = '';
  const set = computeFocusSet(id, bodies.value, lightBeams.value);
  flyToBodies([...set.bodyIds]);
}

function clearFocus() {
  focusedId.value = null;
}

function clearSearch() {
  searchQuery.value = '';
}

/** Enter in the search box flies to the matches. */
function submitSearch() {
  const ids = searchHits.value.map((b) => b.id);
  if (ids.length > 0) flyToBodies(ids);
}

function onWindowKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return;
  if (traceFromId.value != null) cancelTrace();
  else if (searchQuery.value) clearSearch();
  else if (focusedId.value != null) {
    clearFocus();
    fitView(true);
  }
}

const searchHits = computed(() =>
  matchBodies(searchQuery.value, bodyList.value, (b) => deviceLabel(b.device)),
);

/**
 * Which bodies/beams stay fully lit. `strong` dims the rest hard (focus, search),
 * hover only dims softly so the map stays calm while moving the mouse.
 */
const spotlight = computed<{ set: FocusSet; strong: boolean } | null>(() => {
  if (editing.value) return null;
  if (traceFromId.value != null) {
    const path = tracedPath.value;
    return {
      set: {
        bodyIds: new Set(path ? path.bodyIds : [traceFromId.value]),
        beamIds: new Set(path ? path.beamIds : []),
      },
      strong: true,
    };
  }
  if (searchQuery.value.trim()) {
    return {
      set: focusSetFromIds(
        searchHits.value.map((b) => b.id),
        lightBeams.value,
      ),
      strong: true,
    };
  }
  if (focusedId.value != null) {
    return { set: computeFocusSet(focusedId.value, bodies.value, lightBeams.value), strong: true };
  }
  if (hoveredBodyId.value != null) {
    return {
      set: computeFocusSet(hoveredBodyId.value, bodies.value, lightBeams.value),
      strong: false,
    };
  }
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
  const parent = b.parentId != null ? bodies.value.get(b.parentId) : null;
  const children = bodyList.value.filter((o) => o.parentId === b.id);
  const beamCount = lightBeams.value.filter(
    (l) => l.sourceId === b.id || l.targetId === b.id,
  ).length;
  const roleName =
    b.kind === 'star' ? 'Stern (Gateway)' : b.kind === 'planet' ? 'Planet (Hub)' : 'Mond';
  return { body: b, parent, children, beamCount, roleName, badge: roleBadge(b.device) };
});

const STATE_LABEL: Record<OrbitBody['state'], string> = {
  online: 'Online',
  degraded: 'Eingeschränkt',
  offline: 'Offline',
};

function onBeamClick(beamId: number, e: MouseEvent) {
  e.stopPropagation();
  if (!editing.value) return;
  selectedLinkId.value = beamId;
  selectedDeviceId.value = null;
}

/**
 * Reassign a dragged or selected body to orbit around `target` (Planet / AP / Switch / Star)
 * and place it on a clean orbit ring around `target`.
 */
async function assignOrbitToTarget(childId: number, target: OrbitBody) {
  const child = bodies.value.get(childId);
  if (!child || child.id === target.id) return;

  const tPos = posOf(target.id);
  const siblingCount = bodyList.value.filter((b) => b.parentId === target.id).length;
  const radius = target.kind === 'star' ? 190 : 120 + Math.floor(siblingCount / 6) * 44;
  const angle = (siblingCount * (2 * Math.PI)) / Math.max(1, siblingCount + 1);
  const newPos = {
    x: Math.round(tPos.x + radius * Math.cos(angle)),
    y: Math.round(tPos.y + radius * Math.sin(angle)),
  };

  localPositions.value = new Map(localPositions.value).set(childId, newPos);
  store.patchDevice(childId, { topology_x: newPos.x, topology_y: newPos.y });

  try {
    await api.updateDevice(childId, { topology_x: newPos.x, topology_y: newPos.y });

    // Remove existing parent link if one was previously stored
    if (child.parentLinkId != null) {
      await api.deleteTopologyLink(child.parentLinkId).catch(() => {});
      links.value = links.value.filter((l) => l.id !== child.parentLinkId);
    }

    // Create a new topology link connecting the child to the target hub
    const defaultType =
      child.device.is_ap || target.device.is_ap || child.device.is_wlan ? 'WLAN' : '1GbE';
    const created = (await api.createTopologyLink({
      source_id: target.id,
      target_id: childId,
      link_type: defaultType,
    })) as OrbitLink;

    links.value = [...links.value, created];
    showToast('success', t('gv.plan.assigned_to', { parent: deviceLabel(target.device) }), '');
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
    void load();
  }
}

async function createBeamBetween(source: number, target: number) {
  if (source === target) return;
  if (
    links.value.some(
      (l) =>
        (l.source_id === source && l.target_id === target) ||
        (l.source_id === target && l.target_id === source),
    )
  ) {
    showToast('info', t('gv.plan.link_exists'), '');
    return;
  }
  try {
    const srcDev = devicesById.value.get(source);
    const tgtDev = devicesById.value.get(target);
    const defaultType =
      srcDev?.is_ap || tgtDev?.is_ap || srcDev?.is_wlan || tgtDev?.is_wlan ? 'WLAN' : '1GbE';
    const created = (await api.createTopologyLink({
      source_id: source,
      target_id: target,
      link_type: defaultType,
    })) as OrbitLink;
    links.value = [...links.value, created];
    selectedLinkId.value = created.id;
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

async function patchLink(patch: Partial<OrbitLink>) {
  const link = selectedLink.value;
  if (!link) return;
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
  links.value = links.value.filter((l) => l.id !== link.id);
  selectedLinkId.value = null;
  try {
    await api.deleteTopologyLink(link.id);
  } catch (err) {
    showToast('error', t('notifications.delete_failed'), (err as Error).message);
    void load();
  }
}

async function arrange() {
  const ok = await confirm({
    title: t('gv.plan.arrange'),
    message: t('gv.plan.arrange_confirm'),
  });
  if (!ok) return;
  const layout = autoOrbitLayout(store.devices, links.value, gatewayIds.value);
  localPositions.value = new Map(layout);
  await Promise.all(
    [...layout].map(([id, pos]) =>
      api.updateDevice(id, { topology_x: pos.x, topology_y: pos.y }).catch(() => {}),
    ),
  );
  await store.loadData(true);
  window.setTimeout(() => fitView(), 60);
}

function toggleEditing() {
  editing.value = !editing.value;
  clearFocus();
  traceFromId.value = null;
  traceToId.value = null;
  selectedLinkId.value = null;
  selectedDeviceId.value = null;
}

watch(
  () => [loaded.value, store.devices.length] as const,
  ([isLoaded, count]) => {
    if (isLoaded && count > 0) {
      window.setTimeout(() => fitView(), 60);
    }
  },
  { immediate: true },
);
</script>

<template>
  <div
    :id="flowId"
    class="cosmic-canvas relative h-full w-full overflow-hidden select-none"
    :class="[
      editing && 'is-editing',
      vitalityMode === 'subtle' && 'vitality-subtle',
      vitalityMode === 'lively' && 'vitality-lively',
    ]"
  >
    <svg
      ref="svgRef"
      class="h-full w-full touch-none"
      role="img"
      :aria-label="t('gv.plan.title')"
      @wheel="onWheel"
      @pointerdown="onCanvasPointerDown"
      @dblclick="onCanvasDoubleClick"
    >
      <defs>
        <!-- Soft stardust glow filter for constellation nodes and photon beams -->
        <filter :id="`${flowId}-beam-glow`" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        <!-- Lens flare core glow filter for Central Stars -->
        <filter :id="`${flowId}-star-flare`" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="5" result="flare" />
          <feMerge>
            <feMergeNode in="flare" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        <!-- Dynamic localized cosmic nebula radial gradients for each unique body color -->
        <radialGradient
          v-for="body in bodyList"
          :id="`${flowId}-nebula-${body.id}`"
          :key="`nebula-${body.id}`"
          cx="50%"
          cy="50%"
          r="50%"
        >
          <stop offset="0%" :stop-color="body.color" stop-opacity="0.32" />
          <stop offset="45%" :stop-color="body.color" stop-opacity="0.12" />
          <stop offset="100%" :stop-color="body.color" stop-opacity="0" />
        </radialGradient>
      </defs>

      <g :transform="`translate(${viewX}, ${viewY}) scale(${zoom})`">
        <!-- 0. DEEP-SPACE STARFIELD: Micro-stars with subtle twinkle -->
        <g class="cosmic-starfield pointer-events-none" aria-hidden="true">
          <circle
            v-for="s in cosmicStars"
            :key="s.id"
            :cx="s.x"
            :cy="s.y"
            :r="s.r"
            fill="var(--gl-fg)"
            :fill-opacity="s.opacity"
            class="cosmic-star"
            :class="s.twinkle && 'star-twinkle'"
            :style="{ animationDelay: s.delay }"
          />
        </g>

        <!-- 1. LOCALIZED COSMIC NEBULAE (Ethereal cluster gas auras, no intersecting lines!) -->
        <g class="cosmic-nebulae pointer-events-none" aria-hidden="true">
          <circle
            v-for="body in bodyList.filter((b) => b.kind !== 'moon')"
            :key="`neb-${body.id}`"
            :cx="posOf(body.id).x"
            :cy="posOf(body.id).y"
            :r="body.kind === 'star' ? 120 : 80"
            :fill="`url(#${flowId}-nebula-${body.id})`"
            class="nebula-cloud transition-opacity duration-300"
            :class="[
              activeClusterCenterId === body.id ? 'opacity-90' : 'opacity-40',
              body.kind === 'star' && 'star-nebula-pulse',
            ]"
          />
        </g>

        <!-- 2. CONTEXTUAL CELESTIAL ORBIT RINGS (Shown ONLY around active hovered/selected hub or when dragging) -->
        <g class="orbit-rings pointer-events-none" aria-hidden="true">
          <circle
            v-for="ring in visibleOrbitRings"
            :key="ring.id"
            :cx="posOf(ring.centerId).x"
            :cy="posOf(ring.centerId).y"
            :r="ring.radius"
            fill="none"
            :stroke="ring.style === 'broken' ? 'var(--gl-danger)' : ring.color"
            :stroke-width="1.35"
            :stroke-dasharray="
              ring.style === 'broken'
                ? '4 10'
                : ring.style === 'dashed'
                  ? '6 6'
                  : '3 8'
            "
            :stroke-opacity="ring.style === 'broken' ? 0.45 : 0.28"
            class="celestial-orbit-arc transition-opacity duration-300"
          />

          <!-- Live preview orbit arc while dragging a moon -->
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

          <!-- Visual Drop Highlight Ring when hovering a dragged body over a Target Hub -->
          <g v-if="dropTarget">
            <circle
              :cx="posOf(dropTarget.id).x"
              :cy="posOf(dropTarget.id).y"
              :r="bodyRadius(dropTarget.kind) + 24"
              fill="none"
              stroke="var(--gl-accent)"
              stroke-width="2.5"
              stroke-dasharray="6 4"
              class="orbit-drop-ring"
            />
            <circle
              :cx="posOf(dropTarget.id).x"
              :cy="posOf(dropTarget.id).y"
              :r="bodyRadius(dropTarget.kind) + 14"
              fill="var(--gl-accent)"
              fill-opacity="0.16"
            />
          </g>
        </g>

        <!-- 3. CONSTELLATION ENERGY BEAMS (Star <-> Planets & Explicit Links) -->
        <g class="constellation-beams">
          <g
            v-for="beam in lightBeams"
            :key="beam.id"
            class="cursor-pointer group/beam transition-opacity duration-300"
            :style="{ opacity: beamDim(beam.id) }"
            @click="onBeamClick(beam.id, $event)"
            @pointerenter="hoveredBeamId = beam.id"
            @pointerleave="hoveredBeamId = null"
          >
            <!-- Wide click hit target -->
            <line
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              stroke="transparent"
              stroke-width="20"
            />

            <!-- Outer Constellation Stardust Glow -->
            <line
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              :stroke="beam.interrupted ? 'var(--gl-danger)' : beam.color"
              :stroke-width="selectedLinkId === beam.id ? 9 : beam.isPrimaryBridge ? 6 : 4"
              :stroke-opacity="selectedLinkId === beam.id ? 0.38 : beam.interrupted ? 0.12 : 0.2"
              stroke-linecap="round"
            />

            <!-- Laser-Crisp Constellation Vector Line -->
            <line
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              :stroke="beam.interrupted ? 'var(--gl-danger)' : beam.color"
              :stroke-width="selectedLinkId === beam.id ? 3.2 : beam.isPrimaryBridge ? 2.2 : 1.4"
              :stroke-dasharray="
                beam.interrupted ? '2 9' : beam.isWireless ? '6 6' : undefined
              "
              :stroke-opacity="beam.interrupted ? 0.65 : 0.9"
              stroke-linecap="round"
            />

            <!-- Flowing Photon Pulse along Active Constellation Line -->
            <line
              v-if="!beam.interrupted && vitalityMode !== 'off'"
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              stroke="var(--gl-fg)"
              :stroke-width="beam.isPrimaryBridge ? 2.2 : 1.6"
              stroke-dasharray="8 120"
              stroke-linecap="round"
              class="photon-pulse"
            />

            <!-- Spectral Link Type Badge -->
            <g
              v-if="beam.linkType && (beam.isPrimaryBridge || selectedLinkId === beam.id)"
              :transform="`translate(${(posOf(beam.sourceId).x + posOf(beam.targetId).x) / 2}, ${(posOf(beam.sourceId).y + posOf(beam.targetId).y) / 2})`"
            >
              <rect
                x="-22"
                y="-9"
                width="44"
                height="18"
                rx="9"
                fill="var(--gl-surface)"
                :stroke="selectedLinkId === beam.id ? 'var(--gl-fg)' : 'var(--gl-line-strong)'"
                stroke-width="1"
              />
              <text
                x="0"
                y="3.5"
                text-anchor="middle"
                fill="var(--gl-fg-muted)"
                class="font-mono text-[10px] font-medium pointer-events-none"
              >
                {{ beam.linkType }}
              </text>
            </g>
          </g>

          <!-- Live Constellation Line being drawn in Edit Mode -->
          <line
            v-if="connectingFromId != null"
            :x1="posOf(connectingFromId).x"
            :y1="posOf(connectingFromId).y"
            :x2="connectingCursor.x"
            :y2="connectingCursor.y"
            stroke="var(--gl-accent)"
            stroke-width="2.5"
            stroke-dasharray="6 4"
            stroke-linecap="round"
          />
        </g>

        <!-- 3b. PATH TRACE: animated route between two bodies -->
        <g v-if="traceSegments.length" class="trace-path pointer-events-none" aria-hidden="true">
          <template v-for="seg in traceSegments" :key="`trace-${seg.key}`">
            <line
              :x1="posOf(seg.from).x"
              :y1="posOf(seg.from).y"
              :x2="posOf(seg.to).x"
              :y2="posOf(seg.to).y"
              :stroke="seg.interrupted ? 'var(--gl-danger)' : 'var(--gl-accent)'"
              stroke-width="9"
              stroke-opacity="0.22"
              stroke-linecap="round"
            />
            <line
              :x1="posOf(seg.from).x"
              :y1="posOf(seg.from).y"
              :x2="posOf(seg.to).x"
              :y2="posOf(seg.to).y"
              :stroke="seg.interrupted ? 'var(--gl-danger)' : 'var(--gl-accent)'"
              stroke-width="3"
              stroke-dasharray="10 8"
              stroke-linecap="round"
              class="trace-flow"
            />
          </template>
          <g
            v-for="(hop, i) in traceHops"
            :key="`trace-hop-${hop.id}`"
            :transform="`translate(${posOf(hop.id).x + 20}, ${posOf(hop.id).y - 24})`"
          >
            <circle r="9" fill="var(--gl-accent)" />
            <text
              y="3.5"
              text-anchor="middle"
              fill="var(--gl-sign-ink)"
              class="font-mono text-[10px] font-bold"
            >
              {{ i + 1 }}
            </text>
          </g>
        </g>

        <!-- 4. CELESTIAL LIGHT NODES (Stars, Planets, Moons) -->
        <g class="constellation-nodes">
          <g
            v-for="(body, idx) in bodyList"
            :key="body.id"
            :transform="`translate(${posOf(body.id).x}, ${posOf(body.id).y})`"
            class="constellation-node cursor-pointer transition-opacity duration-300"
            :style="{ opacity: bodyDim(body.id) * (body.state === 'offline' ? 0.7 : 1) }"
            :class="[
              editing && 'cursor-grab active:cursor-grabbing',
            ]"
            role="button"
            tabindex="0"
            :aria-label="`${deviceLabel(body.device)} (${body.device.ip})`"
            @pointerdown="onBodyPointerDown(body, $event)"
            @click="onBodyClick(body, $event)"
            @dblclick="onBodyDoubleClick(body, $event)"
            @pointerenter="hoveredBodyId = body.id"
            @pointerleave="hoveredBodyId = null"
            @keydown.enter.prevent="onBodyClick(body, $event as unknown as MouseEvent)"
          >
            <!-- Gentle cosmic drift when vitality is active -->
            <g
              class="orbit-float-node"
              :style="{ animationDelay: `${(idx % 7) * -0.85}s` }"
            >
              <!-- STAR: 4-Point Optical Diffraction Spikes (Astronomical Lens Flare) -->
              <g
                v-if="body.kind === 'star'"
                class="star-diffraction pointer-events-none"
                :stroke="body.color"
              >
                <line x1="-32" y1="0" x2="32" y2="0" stroke-width="1.2" stroke-opacity="0.8" />
                <line x1="0" y1="-32" x2="0" y2="32" stroke-width="1.2" stroke-opacity="0.8" />
                <!-- Secondary diagonal faint spikes -->
                <line x1="-14" y1="-14" x2="14" y2="14" stroke-width="0.65" stroke-opacity="0.4" />
                <line x1="-14" y1="14" x2="14" y2="-14" stroke-width="0.65" stroke-opacity="0.4" />
                <!-- Pulsing coronal plasma ring -->
                <circle
                  :r="bodyRadius('star') + 12"
                  :fill="body.color"
                  fill-opacity="0.16"
                  class="star-corona"
                />
              </g>

              <!-- PLANET: Atmospheric Ring with Orbital Accent Ticks -->
              <template v-else-if="body.kind === 'planet'">
                <circle
                  :r="bodyRadius('planet') + 7"
                  :fill="body.color"
                  fill-opacity="0.1"
                  class="planet-halo"
                />
                <circle
                  :r="bodyRadius('planet') + 4"
                  fill="none"
                  :stroke="body.color"
                  stroke-width="1.2"
                  :stroke-dasharray="body.device.is_ap ? '4 3' : undefined"
                  stroke-opacity="0.65"
                />
              </template>

              <!-- MOON: WLAN Subtle Satellite Beacon Ring -->
              <template v-else-if="body.device.is_wlan && body.state === 'online'">
                <circle
                  :r="bodyRadius('moon') + 4"
                  fill="none"
                  :stroke="body.color"
                  stroke-width="1"
                  stroke-dasharray="3 3"
                  stroke-opacity="0.45"
                  class="wlan-satellite-ring"
                />
              </template>

              <!-- Selection Ring -->
              <circle
                v-if="selectedDeviceId === body.id"
                :r="bodyRadius(body.kind) + 9"
                fill="none"
                stroke="var(--gl-fg)"
                stroke-width="2"
              />

              <!-- Main Celestial Node Core Sphere -->
              <circle
                :r="bodyRadius(body.kind)"
                :fill="body.kind === 'star' ? body.color : 'var(--gl-station)'"
                :stroke="
                  body.state === 'offline'
                    ? 'var(--gl-danger)'
                    : body.state === 'degraded'
                      ? 'var(--gl-warn)'
                      : body.color
                "
                :stroke-width="body.kind === 'star' ? 3.2 : body.kind === 'planet' ? 3 : 2.5"
              />

              <!-- Multi-VLAN Secondary Inner Ring -->
              <circle
                v-if="body.rings.length > 1 && body.kind !== 'star'"
                :r="Math.max(4, bodyRadius(body.kind) - 4)"
                fill="none"
                :stroke="body.rings[1]"
                stroke-width="2"
              />

              <!-- Star Core Nucleus -->
              <circle
                v-if="body.kind === 'star'"
                r="6.5"
                fill="var(--gl-sign-ink)"
              />
              <circle
                v-else-if="body.kind === 'planet' && body.state === 'online'"
                r="4"
                :fill="body.color"
              />

              <!-- Planetary Role Pill (SW, AP, HOST) -->
              <g
                v-if="body.kind === 'planet' && roleBadge(body.device)"
                :transform="`translate(${bodyRadius('planet') + 1}, ${-bodyRadius('planet') + 2})`"
              >
                <rect
                  x="-2"
                  y="-8"
                  width="26"
                  height="13"
                  rx="4"
                  fill="var(--gl-surface)"
                  :stroke="body.color"
                  stroke-width="0.8"
                />
                <text
                  x="11"
                  y="1.5"
                  text-anchor="middle"
                  :fill="body.color"
                  class="font-mono text-[10px] font-bold"
                >
                  {{ roleBadge(body.device) }}
                </text>
              </g>

              <!-- Offline Strike-Through (State never by color alone) -->
              <line
                v-if="body.state === 'offline'"
                :x1="-bodyRadius(body.kind) + 2"
                :y1="bodyRadius(body.kind) - 2"
                :x2="bodyRadius(body.kind) - 2"
                :y2="-bodyRadius(body.kind) + 2"
                stroke="var(--gl-danger)"
                stroke-width="2.5"
                stroke-linecap="round"
              />

              <!-- Degraded Service Warning Indicator -->
              <g
                v-if="body.state === 'degraded'"
                :transform="`translate(${bodyRadius(body.kind) - 2}, ${-bodyRadius(body.kind) + 2})`"
              >
                <circle r="6" fill="var(--gl-warn)" />
                <text
                  x="0"
                  y="3.5"
                  text-anchor="middle"
                  fill="var(--gl-sign-ink)"
                  class="font-sans text-[10px] font-extrabold"
                >
                  !
                </text>
              </g>

              <!-- Edit Mode: Constellation Beam Handle (+ on right rim) -->
              <g
                v-if="editing"
                :transform="`translate(${bodyRadius(body.kind) + 7}, 0)`"
                class="opacity-80 hover:opacity-100"
                @pointerdown="startBeamConnect(body, $event)"
              >
                <circle
                  r="6.5"
                  fill="var(--gl-surface)"
                  stroke="var(--gl-accent)"
                  stroke-width="1.5"
                />
                <line x1="-3" y1="0" x2="3" y2="0" stroke="var(--gl-accent)" stroke-width="1.5" />
                <line x1="0" y1="-3" x2="0" y2="3" stroke="var(--gl-accent)" stroke-width="1.5" />
              </g>

              <!-- Celestial Label Plate with Deep Space Halo -->
              <g :transform="`translate(0, ${bodyRadius(body.kind) + 15})`">
                <text
                  x="0"
                  y="0"
                  text-anchor="middle"
                  fill="var(--gl-fg)"
                  class="text-[12px] font-bold tracking-tight"
                  :class="body.state === 'offline' && 'line-through opacity-75'"
                  style="paint-order: stroke; stroke: var(--gl-canvas); stroke-width: 4px; stroke-linejoin: round"
                >
                  {{ deviceLabel(body.device) }}
                </text>
                <text
                  x="0"
                  y="13"
                  text-anchor="middle"
                  fill="var(--gl-fg-muted)"
                  class="font-mono text-[10px]"
                  style="paint-order: stroke; stroke: var(--gl-canvas); stroke-width: 3.5px; stroke-linejoin: round"
                >
                  {{ body.device.ip }}
                </text>
                <text
                  v-if="body.state !== 'online'"
                  x="0"
                  y="25"
                  text-anchor="middle"
                  :fill="body.state === 'offline' ? 'var(--gl-danger-text)' : 'var(--gl-warn-text)'"
                  class="text-[10px] font-semibold"
                  style="paint-order: stroke; stroke: var(--gl-canvas); stroke-width: 3.5px; stroke-linejoin: round"
                >
                  {{ body.state === 'offline' ? t('gv.plan.dropped') : t('gv.plan.degraded') }}
                </text>
              </g>
            </g>
          </g>
        </g>
      </g>
    </svg>

    <!-- Drop Assignment Banner while hovering over a Target Planet/Star -->
    <div
      v-if="dropTarget"
      class="pointer-events-none absolute top-3 left-1/2 z-20 -translate-x-1/2 flex items-center gap-2 rounded-full border border-accent bg-surface/95 px-3.5 py-1.5 text-xs font-semibold text-accent-text shadow-pop"
    >
      <Orbit class="size-3.5" aria-hidden="true" />
      <span>Orbit → {{ deviceLabel(dropTarget.device) }}</span>
    </div>

    <!-- Top-Left Search: highlights matches in space, Enter flies there -->
    <div
      v-if="!editing"
      class="absolute top-3 left-3 z-10 flex h-9 w-[min(16rem,calc(100%-6rem))] items-center gap-2 rounded-md border border-line bg-surface/95 px-2.5 shadow-pop backdrop-blur focus-within:border-accent"
      @pointerdown.stop
    >
      <Search class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
      <input
        v-model="searchQuery"
        type="search"
        class="min-w-0 flex-1 bg-transparent text-sm text-fg placeholder:text-fg-subtle focus:outline-none"
        placeholder="Gerät suchen…"
        aria-label="Gerät in der Karte suchen"
        @keydown.enter.prevent="submitSearch"
      />
      <span
        v-if="searchQuery"
        class="font-mono text-[10px] text-fg-subtle"
        aria-live="polite"
      >
        {{ searchHits.length }}
      </span>
    </div>

    <!-- Focus Card (view mode): details of the clicked body and quick actions -->
    <div
      v-if="!editing && focusedInfo && traceFromId == null"
      class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-2.5 rounded-lg border border-line-strong bg-surface/95 p-3.5 shadow-pop backdrop-blur"
      role="dialog"
      :aria-label="deviceLabel(focusedInfo.body.device)"
      @pointerdown.stop
    >
      <div class="flex items-start gap-2">
        <span
          class="mt-1.5 size-2.5 shrink-0 rounded-full"
          :style="{ backgroundColor: focusedInfo.body.color }"
          aria-hidden="true"
        />
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">
            {{ deviceLabel(focusedInfo.body.device) }}
          </p>
          <p class="font-mono text-xs text-fg-subtle">{{ focusedInfo.body.device.ip }}</p>
        </div>
        <button
          type="button"
          class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover"
          :aria-label="t('common.close')"
          @click="clearFocus(); fitView(true)"
        >
          <X class="size-4" />
        </button>
      </div>

      <dl class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt class="text-fg-subtle">Typ</dt>
        <dd class="text-fg">
          {{ focusedInfo.roleName }}
          <span v-if="focusedInfo.badge" class="font-mono text-[10px] text-fg-muted">
            · {{ focusedInfo.badge }}
          </span>
        </dd>
        <dt class="text-fg-subtle">Status</dt>
        <dd class="text-fg">{{ STATE_LABEL[focusedInfo.body.state] }}</dd>
        <dt class="text-fg-subtle">Umkreist</dt>
        <dd class="truncate text-fg">
          {{ focusedInfo.parent ? deviceLabel(focusedInfo.parent.device) : '–' }}
        </dd>
        <dt class="text-fg-subtle">Monde / Links</dt>
        <dd class="text-fg">{{ focusedInfo.children.length }} / {{ focusedInfo.beamCount }}</dd>
      </dl>

      <div class="flex flex-wrap items-center gap-1.5">
        <Button size="sm" @click="emit('openDevice', focusedInfo.body.device)">
          Details öffnen
        </Button>
        <Button
          v-if="focusedInfo.parent"
          size="sm"
          variant="secondary"
          @click="focusBody(focusedInfo.parent.id)"
        >
          Zum Hub
        </Button>
        <Button size="sm" variant="secondary" @click="flyToBodies([focusedInfo.body.id])">
          Zentrieren
        </Button>
        <Button size="sm" variant="secondary" @click="startTrace(focusedInfo.body.id)">
          <Route aria-hidden="true" />Pfad verfolgen
        </Button>
      </div>
    </div>

    <!-- Hint in view mode when nothing is focused -->
    <p
      v-if="!editing && !focusedInfo && !searchQuery && traceFromId == null"
      class="pointer-events-none absolute bottom-3 left-3 z-10 hidden max-w-xs rounded-md border border-line bg-surface/90 px-2.5 py-1.5 text-[11px] text-fg-muted backdrop-blur sm:block"
    >
      Klick: fokussieren · Doppelklick: Details · Esc: zurück · Mausrad / Pinch: Zoom
    </p>

    <!-- Path Trace Panel: pick destination, then show hops -->
    <div
      v-if="!editing && traceFromId != null"
      class="absolute bottom-3 left-3 z-10 w-[min(24rem,calc(100%-4.5rem))] space-y-2.5 rounded-lg border border-accent bg-surface/95 p-3.5 shadow-pop backdrop-blur"
      role="dialog"
      aria-label="Pfad verfolgen"
      @pointerdown.stop
    >
      <div class="flex items-center gap-2">
        <Route class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
        <p class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">
          <template v-if="traceToId == null">Von {{ traceStartLabel }}: Ziel anklicken</template>
          <template v-else-if="tracedPath">
            {{ tracedPath.bodyIds.length - 1 }}
            {{ tracedPath.bodyIds.length === 2 ? 'Hop' : 'Hops' }}
          </template>
          <template v-else>Kein Pfad gefunden</template>
        </p>
        <button
          type="button"
          class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover"
          :aria-label="t('common.close')"
          @click="cancelTrace"
        >
          <X class="size-4" />
        </button>
      </div>

      <p v-if="traceToId != null && !tracedPath" class="text-xs text-fg-muted">
        Zwischen diesen Geräten gibt es keine verbundene Strecke. Verbinde sie im Bearbeiten-Modus
        mit Lichtstrahlen.
      </p>
      <p v-if="tracedPath?.broken" class="text-xs font-medium text-danger-text">
        Die Strecke führt über eine unterbrochene Verbindung (offline).
      </p>

      <ol v-if="traceHops.length" class="max-h-44 space-y-1 overflow-y-auto text-xs">
        <li v-for="(hop, i) in traceHops" :key="hop.id" class="flex items-center gap-2">
          <span
            class="flex size-4 shrink-0 items-center justify-center rounded-full bg-accent font-mono text-[10px] font-bold text-sign-ink"
          >
            {{ i + 1 }}
          </span>
          <span class="min-w-0 flex-1 truncate text-fg">{{ hop.label }}</span>
          <span
            v-if="hop.linkType"
            class="font-mono text-[10px]"
            :class="hop.interrupted ? 'text-danger-text' : 'text-fg-subtle'"
          >
            {{ hop.linkType }}
          </span>
        </li>
      </ol>
    </div>

    <!-- Bottom-Right Zoom & Vitality Controls -->    <div class="absolute right-3 bottom-3 z-10 flex flex-col overflow-hidden rounded-md border border-line bg-surface shadow-pop">
      <button
        type="button"
        class="flex size-8 items-center justify-center text-fg-muted hover:bg-control-hover hover:text-fg"
        :class="vitalityMode !== 'off' && 'text-accent-text'"
        :title="`Galaktische Dynamik: ${vitalityMode}`"
        :aria-label="`Galaktische Dynamik: ${vitalityMode}`"
        @click="cycleVitality"
      >
        <Sparkles class="size-3.5" />
      </button>
      <button
        type="button"
        class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg"
        :aria-label="t('gv.plan.zoom_in')"
        @click="zoomBy(1.2)"
      >
        <Plus class="size-4" />
      </button>
      <button
        type="button"
        class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg"
        :aria-label="t('gv.plan.zoom_out')"
        @click="zoomBy(0.82)"
      >
        <Minus class="size-4" />
      </button>
      <button
        type="button"
        class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg"
        :aria-label="t('gv.plan.fit')"
        @click="fitView(true)"
      >
        <Maximize class="size-3.5" />
      </button>
    </div>

    <!-- Top-Right Edit / Arrange Toolbar (when editable) -->
    <div v-if="editable" class="absolute top-3 right-3 z-10 flex gap-2">
      <Button v-if="editing" size="sm" @click="arrange">
        <Wand2 aria-hidden="true" />{{ t('gv.plan.arrange') }}
      </Button>
      <Button size="sm" :variant="editing ? 'primary' : 'secondary'" @click="toggleEditing">
        <component :is="editing ? Check : Pencil" aria-hidden="true" />
        {{ editing ? t('dashboard.edit_finish') : t('gv.plan.edit') }}
      </Button>
    </div>

    <!-- Edit Hint -->
    <p
      v-if="editing && !selectedLink && !selectedDevice"
      class="absolute bottom-3 left-3 z-10 flex max-w-md items-start gap-2 rounded-md border border-line bg-surface/95 px-3 py-2 text-xs text-fg-muted shadow-pop backdrop-blur"
    >
      <MousePointer2 class="mt-0.5 size-3.5 shrink-0 text-accent-text" aria-hidden="true" />
      {{ t('gv.plan.edit_hint') }}
    </p>

    <!-- Selected Light Beam Inspector: Color, Type, Delete -->
    <div
      v-if="editing && selectedLink"
      class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-3 rounded-lg border border-line-strong bg-surface p-3.5 shadow-pop"
      role="dialog"
      :aria-label="t('gv.plan.link')"
    >
      <div class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-semibold text-fg">{{ t('gv.plan.link') }}</p>
          <p class="truncate text-xs text-fg-subtle">{{ linkEnds }}</p>
        </div>
        <button
          type="button"
          class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover"
          :aria-label="t('common.close')"
          @click="selectedLinkId = null"
        >
          <X class="size-4" />
        </button>
      </div>
      <fieldset>
        <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('gv.plan.line_color') }}</legend>
        <div class="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            class="h-7 rounded-full border border-line-strong px-2.5 text-[11px] font-medium"
            :class="!selectedLink.color ? 'bg-fg text-canvas' : 'text-fg-muted hover:text-fg'"
            :aria-pressed="!selectedLink.color"
            @click="patchLink({ color: null })"
          >
            {{ t('gv.plan.network_color') }}
          </button>
          <button
            v-for="c in swatches"
            :key="c"
            type="button"
            class="size-7 rounded-full ring-offset-2 ring-offset-surface transition-transform hover:scale-110"
            :class="selectedLink.color?.toLowerCase() === c.toLowerCase() && 'ring-2 ring-fg'"
            :style="{ backgroundColor: c }"
            :aria-label="c"
            :aria-pressed="selectedLink.color?.toLowerCase() === c.toLowerCase()"
            @click="patchLink({ color: c })"
          />
          <label
            class="relative size-7 cursor-pointer overflow-hidden rounded-full border border-dashed border-line-strong"
            :title="t('gv.plan.custom_color')"
          >
            <span class="sr-only">{{ t('gv.plan.custom_color') }}</span>
            <input
              type="color"
              class="absolute inset-0 size-full cursor-pointer opacity-0"
              :value="selectedLink.color ?? '#2ec4a6'"
              @change="patchLink({ color: ($event.target as HTMLInputElement).value })"
            />
            <Plus class="absolute inset-0 m-auto size-3.5 text-fg-subtle" aria-hidden="true" />
          </label>
        </div>
      </fieldset>
      <div class="flex items-end gap-2">
        <label class="flex flex-1 flex-col gap-1.5 text-xs font-medium text-fg">
          {{ t('gv.plan.link_type') }}
          <select
            :value="selectedLink.link_type"
            class="h-9 rounded-md border border-line bg-sunken px-2 text-sm text-fg focus:border-accent focus:outline-none"
            @change="patchLink({ link_type: ($event.target as HTMLSelectElement).value })"
          >
            <option v-for="lt in LINK_TYPES" :key="lt" :value="lt">{{ lt }}</option>
          </select>
        </label>
        <Button variant="danger-ghost" @click="deleteLink">
          <Trash2 aria-hidden="true" />{{ t('common.delete') }}
        </Button>
      </div>
    </div>

    <!-- Selected Body Inspector in Edit Mode (Orbit Parent Selector + Edit Device) -->
    <div
      v-if="editing && selectedDevice && selectedBody"
      class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-2.5 rounded-lg border border-line-strong bg-surface p-3.5 shadow-pop"
    >
      <div class="flex items-center justify-between gap-2">
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold text-fg">{{ deviceLabel(selectedDevice) }}</p>
          <p class="font-mono text-xs text-fg-subtle">{{ selectedDevice.ip }}</p>
        </div>
        <div class="flex items-center gap-1.5">
          <Button size="sm" @click="emit('openDevice', selectedDevice)">
            {{ t('dashboard.edit_device') }}
          </Button>
          <button
            type="button"
            class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover"
            :aria-label="t('common.close')"
            @click="selectedDeviceId = null"
          >
            <X class="size-4" />
          </button>
        </div>
      </div>

      <label
        v-if="selectedBody.kind !== 'star' && assignableParents.length > 0"
        class="flex flex-col gap-1 text-xs font-medium text-fg"
      >
        <span>Galaktischer Hub (Planet / Stern)</span>
        <select
          :value="selectedBody.parentId ?? ''"
          class="h-8 rounded-md border border-line bg-sunken px-2 text-xs text-fg focus:border-accent focus:outline-none"
          @change="
            (e) => {
              const targetId = Number((e.target as HTMLSelectElement).value);
              const tgt = bodies.get(targetId);
              if (tgt) assignOrbitToTarget(selectedBody!.id, tgt);
            }
          "
        >
          <option v-for="p in assignableParents" :key="p.id" :value="p.id">
            {{ deviceLabel(p.device) }} ({{ p.kind === 'star' ? 'Stern' : 'Planet' }})
          </option>
        </select>
      </label>
    </div>
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

/* Starfield micro-twinkle */
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

/* Subtle stellar drifting for vitality mode */
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

.vitality-subtle .orbit-float-node {
  animation: orbit-float 5.8s ease-in-out infinite;
}

.vitality-lively .orbit-float-node {
  animation: orbit-float 3.4s ease-in-out infinite;
}

.vitality-subtle .star-corona,
.vitality-subtle .planet-halo {
  animation: corona-pulse 4.5s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-lively .star-corona,
.vitality-lively .planet-halo {
  animation: corona-pulse 2.6s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-subtle .star-diffraction {
  animation: diffraction-pulse 4.5s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-lively .star-diffraction {
  animation: diffraction-pulse 2.6s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}

.vitality-subtle .photon-pulse {
  animation: beam-flow 4.2s linear infinite;
}

.vitality-lively .photon-pulse {
  animation: beam-flow 2.2s linear infinite;
}

@keyframes trace-flow {
  to {
    stroke-dashoffset: -36;
  }
}

.trace-flow {
  animation: trace-flow 0.9s linear infinite;
}

.orbit-drop-ring {
  animation: drop-ring-spin 8s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}

@media (prefers-reduced-motion: reduce) {
  .star-twinkle,
  .orbit-float-node,
  .star-corona,
  .planet-halo,
  .star-diffraction,
  .photon-pulse,
  .trace-flow,
  .orbit-drop-ring {
    animation: none !important;
  }
}
</style>
