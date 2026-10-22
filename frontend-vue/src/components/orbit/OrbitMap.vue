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
});

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onWindowPointerMove);
  window.removeEventListener('pointerup', onWindowPointerUp);
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
  return 11;
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

function fitView() {
  const svg = svgRef.value;
  if (!svg || store.devices.length === 0) return;
  const rect = svg.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const d of store.devices) {
    const p = posOf(d.id);
    minX = Math.min(minX, p.x - 90);
    maxX = Math.max(maxX, p.x + 90);
    minY = Math.min(minY, p.y - 75);
    maxY = Math.max(maxY, p.y + 75);
  }
  for (const r of orbitRings.value) {
    const c = posOf(r.centerId);
    minX = Math.min(minX, c.x - r.radius - 30);
    maxX = Math.max(maxX, c.x + r.radius + 30);
    minY = Math.min(minY, c.y - r.radius - 30);
    maxY = Math.max(maxY, c.y + r.radius + 30);
  }

  const contentW = Math.max(240, maxX - minX);
  const contentH = Math.max(240, maxY - minY);
  const pad = 0.84;
  const nextZoom = Math.min(1.6, Math.max(0.22, Math.min((rect.width * pad) / contentW, (rect.height * pad) / contentH)));
  zoom.value = nextZoom;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  viewX.value = Math.round(rect.width / 2 - cx * nextZoom);
  viewY.value = Math.round(rect.height / 2 - cy * nextZoom);
}

function zoomBy(factor: number) {
  const svg = svgRef.value;
  if (!svg) return;
  const rect = svg.getBoundingClientRect();
  const cx = rect.width / 2;
  const cy = rect.height / 2;
  const next = Math.min(2.5, Math.max(0.2, zoom.value * factor));
  const ratio = next / zoom.value;
  viewX.value = cx - (cx - viewX.value) * ratio;
  viewY.value = cy - (cy - viewY.value) * ratio;
  zoom.value = next;
}

function onWheel(e: WheelEvent) {
  e.preventDefault();
  const svg = svgRef.value;
  if (!svg) return;
  const rect = svg.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const factor = e.deltaY < 0 ? 1.12 : 0.89;
  const next = Math.min(2.5, Math.max(0.2, zoom.value * factor));
  const ratio = next / zoom.value;
  viewX.value = mx - (mx - viewX.value) * ratio;
  viewY.value = my - (my - viewY.value) * ratio;
  zoom.value = next;
}

function onCanvasPointerDown(e: PointerEvent) {
  if (e.button !== 0) return;
  isPanning.value = true;
  panStart.value = { x: e.clientX - viewX.value, y: e.clientY - viewY.value };
  selectedLinkId.value = null;
  selectedDeviceId.value = null;
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
      localPositions.value = moveWithDescendants(id, { x: dx, y: dy }, bodies.value, dragStartPositions.value);
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
  } else {
    emit('openDevice', body.device);
  }
}

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
  const orbitR = target.kind === 'star' ? (child.kind !== 'moon' ? 260 : 140) : 96;
  const angle = -Math.PI / 2 + siblingCount * 0.9;
  const newPos = {
    x: Math.round(tPos.x + orbitR * Math.cos(angle)),
    y: Math.round(tPos.y + orbitR * Math.sin(angle)),
  };

  localPositions.value = new Map(localPositions.value).set(childId, newPos);
  store.patchDevice(childId, { topology_x: newPos.x, topology_y: newPos.y });

  try {
    // Remove old parent topology link if one existed
    if (child.parentLinkId != null) {
      await api.deleteTopologyLink(child.parentLinkId).catch(() => {});
      links.value = links.value.filter((l) => l.id !== child.parentLinkId);
    }

    // Create new topology link to the target Planet/AP/Switch/Star if not already linked
    const exists = links.value.some(
      (l) =>
        (l.source_id === target.id && l.target_id === childId) ||
        (l.source_id === childId && l.target_id === target.id),
    );
    if (!exists) {
      const linkType = target.device.is_ap || child.device.is_wlan ? 'WLAN' : '1GbE';
      const created = (await api.createTopologyLink({
        source_id: target.id,
        target_id: childId,
        link_type: linkType,
      })) as OrbitLink;
      links.value = [...links.value, created];
    }

    // Update parent_id if moving a VM/Container onto a Host, or clear it if moving to a Switch/AP
    const nextParentId = target.device.is_host && child.device.virtual_type ? target.id : null;
    await api.updateDevice(childId, {
      topology_x: newPos.x,
      topology_y: newPos.y,
      ...(child.device.parent_id !== nextParentId ? { parent_id: nextParentId } : {}),
    });
    store.patchDevice(childId, { parent_id: nextParentId });
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

async function createBeamBetween(source: number, target: number) {
  if (!source || !target || source === target) return;
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
    const defaultType = srcDev?.is_ap || tgtDev?.is_ap || srcDev?.is_wlan || tgtDev?.is_wlan ? 'WLAN' : '1GbE';
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
    class="orbit-canvas relative h-full w-full overflow-hidden select-none"
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
    >
      <defs>
        <!-- Soft glow filter for Stars, Planets, and Light Beams -->
        <filter :id="`${flowId}-beam-glow`" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <g :transform="`translate(${viewX}, ${viewY}) scale(${zoom})`">
        <!-- 1. CONCENTRIC ORBIT RINGS -->
        <g class="orbit-rings">
          <circle
            v-for="ring in orbitRings"
            :key="ring.id"
            :cx="posOf(ring.centerId).x"
            :cy="posOf(ring.centerId).y"
            :r="ring.radius"
            fill="none"
            :stroke="ring.style === 'broken' ? 'var(--gl-danger)' : ring.color"
            :stroke-width="ring.style === 'broken' ? 1.5 : 1.35"
            :stroke-dasharray="
              ring.style === 'broken'
                ? '4 10'
                : ring.style === 'dashed'
                  ? '7 6'
                  : undefined
            "
            :stroke-opacity="ring.style === 'broken' ? 0.45 : 0.28"
            class="orbit-ring"
          />

          <!-- Live preview orbit ring while dragging a moon -->
          <circle
            v-if="activeDragOrbit"
            :cx="activeDragOrbit.center.x"
            :cy="activeDragOrbit.center.y"
            :r="activeDragOrbit.radius"
            fill="none"
            :stroke="activeDragOrbit.color"
            stroke-width="1.75"
            stroke-dasharray="4 4"
            stroke-opacity="0.7"
          />

          <!-- Visual Drop Highlight Ring when hovering a dragged body over a Planet/AP/Switch/Star -->
          <g v-if="dropTarget">
            <circle
              :cx="posOf(dropTarget.id).x"
              :cy="posOf(dropTarget.id).y"
              :r="bodyRadius(dropTarget.kind) + 22"
              fill="none"
              stroke="var(--gl-accent)"
              stroke-width="2.5"
              stroke-dasharray="6 4"
              class="orbit-drop-ring"
            />
            <circle
              :cx="posOf(dropTarget.id).x"
              :cy="posOf(dropTarget.id).y"
              :r="bodyRadius(dropTarget.kind) + 12"
              fill="var(--gl-accent)"
              fill-opacity="0.14"
            />
          </g>
        </g>

        <!-- 2. LIGHT BEAMS (Star <-> Planets / Switches / APs & Explicit Links) -->
        <g class="light-beams">
          <g
            v-for="beam in lightBeams"
            :key="beam.id"
            class="cursor-pointer group/beam"
            @click="onBeamClick(beam.id, $event)"
          >
            <!-- Wide click hit target -->
            <line
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              stroke="transparent"
              stroke-width="18"
            />

            <!-- Outer Light Beam Halo -->
            <line
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              :stroke="beam.interrupted ? 'var(--gl-danger)' : beam.color"
              :stroke-width="selectedLinkId === beam.id ? 11 : beam.isPrimaryBridge ? 8 : 5"
              :stroke-opacity="selectedLinkId === beam.id ? 0.32 : beam.interrupted ? 0.12 : 0.18"
              stroke-linecap="round"
            />

            <!-- Core Light Beam -->
            <line
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              :stroke="beam.interrupted ? 'var(--gl-danger)' : beam.color"
              :stroke-width="selectedLinkId === beam.id ? 3.5 : beam.isPrimaryBridge ? 2.6 : 1.9"
              :stroke-dasharray="
                beam.interrupted ? '2 9' : beam.isWireless ? '7 6' : undefined
              "
              :stroke-opacity="beam.interrupted ? 0.65 : 0.88"
              stroke-linecap="round"
            />

            <!-- Travelling Energy Pulse on Online Light Beams -->
            <line
              v-if="!beam.interrupted && vitalityMode !== 'off'"
              :x1="posOf(beam.sourceId).x"
              :y1="posOf(beam.sourceId).y"
              :x2="posOf(beam.targetId).x"
              :y2="posOf(beam.targetId).y"
              stroke="var(--gl-fg)"
              :stroke-width="beam.isPrimaryBridge ? 2.2 : 1.6"
              stroke-dasharray="10 130"
              stroke-linecap="round"
              class="light-beam-pulse"
            />

            <!-- Link Type Badge on Primary Bridges or Selected Link -->
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
                class="font-mono text-[9.5px] font-medium pointer-events-none"
              >
                {{ beam.linkType }}
              </text>
            </g>
          </g>

          <!-- Live Light Beam being drawn in Edit Mode -->
          <line
            v-if="connectingFromId != null"
            :x1="posOf(connectingFromId).x"
            :y1="posOf(connectingFromId).y"
            :x2="connectingCursor.x"
            :y2="connectingCursor.y"
            stroke="var(--gl-accent)"
            stroke-width="3"
            stroke-dasharray="6 4"
            stroke-linecap="round"
          />
        </g>

        <!-- 3. CELESTIAL BODIES (Stars, Planets, Moons) -->
        <g class="orbit-bodies">
          <g
            v-for="(body, idx) in bodyList"
            :key="body.id"
            :transform="`translate(${posOf(body.id).x}, ${posOf(body.id).y})`"
            class="orbit-body-group cursor-pointer"
            :class="[
              editing && 'cursor-grab active:cursor-grabbing',
              body.state === 'offline' && 'opacity-75',
            ]"
            role="button"
            tabindex="0"
            :aria-label="`${deviceLabel(body.device)} (${body.device.ip})`"
            @pointerdown="onBodyPointerDown(body, $event)"
            @click="onBodyClick(body, $event)"
            @keydown.enter.prevent="onBodyClick(body, $event as unknown as MouseEvent)"
          >
            <!-- Inner wrapper with gentle floating animation when vitality is enabled -->
            <g
              class="orbit-float-node"
              :style="{ animationDelay: `${(idx % 7) * -0.85}s` }"
            >
              <!-- STAR Corona & Outer Gravity Halo -->
              <template v-if="body.kind === 'star'">
                <circle
                  :r="bodyRadius('star') + 12"
                  :fill="body.color"
                  fill-opacity="0.14"
                  class="star-corona"
                />
                <circle
                  :r="bodyRadius('star') + 6"
                  fill="none"
                  :stroke="body.color"
                  stroke-width="1.5"
                  stroke-opacity="0.45"
                  stroke-dasharray="3 5"
                />
              </template>

              <!-- PLANET Outer Atmosphere Ring (Switches, APs, Hypervisors) -->
              <template v-else-if="body.kind === 'planet'">
                <circle
                  :r="bodyRadius('planet') + 6"
                  :fill="body.color"
                  fill-opacity="0.1"
                  class="planet-halo"
                />
                <circle
                  :r="bodyRadius('planet') + 4"
                  fill="none"
                  :stroke="body.color"
                  stroke-width="1.25"
                  :stroke-dasharray="body.device.is_ap ? '4 3' : undefined"
                  stroke-opacity="0.55"
                />
              </template>

              <!-- Selection Ring -->
              <circle
                v-if="selectedDeviceId === body.id"
                :r="bodyRadius(body.kind) + 8"
                fill="none"
                stroke="var(--gl-fg)"
                stroke-width="2"
              />

              <!-- Main Celestial Body Sphere -->
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
                :stroke-width="body.kind === 'star' ? 3 : body.kind === 'planet' ? 3.5 : 2.75"
              />

              <!-- Multi-VLAN secondary inner ring if device answers in multiple subnets -->
              <circle
                v-if="body.rings.length > 1 && body.kind !== 'star'"
                :r="Math.max(4, bodyRadius(body.kind) - 4)"
                fill="none"
                :stroke="body.rings[1]"
                stroke-width="2"
              />

              <!-- Star Core Emblem / Planet Role Indicator -->
              <circle
                v-if="body.kind === 'star'"
                r="6"
                fill="var(--gl-sign-ink)"
              />
              <circle
                v-else-if="body.kind === 'planet' && body.state === 'online'"
                r="4"
                :fill="body.color"
              />

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

              <!-- Degraded Service Exclamation Badge -->
              <g
                v-if="body.state === 'degraded'"
                :transform="`translate(${bodyRadius(body.kind) - 2}, ${-bodyRadius(body.kind) + 2})`"
              >
                <circle r="6.5" fill="var(--gl-warn)" />
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

              <!-- Edit Mode: Beam Connection Handle (+ on right rim) -->
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

              <!-- Label Plate below Celestial Body -->
              <g :transform="`translate(0, ${bodyRadius(body.kind) + 15})`">
                <text
                  x="0"
                  y="0"
                  text-anchor="middle"
                  fill="var(--gl-fg)"
                  class="text-[12.5px] font-bold"
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
                <!-- Explicit Non-Color Status Text for Offline / Degraded -->
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

    <!-- Bottom-Right Zoom & Vitality Controls -->
    <div class="absolute right-3 bottom-3 z-10 flex flex-col overflow-hidden rounded-md border border-line bg-surface shadow-pop">
      <button
        type="button"
        class="flex size-8 items-center justify-center text-fg-muted hover:bg-control-hover hover:text-fg"
        :class="vitalityMode !== 'off' && 'text-accent-text'"
        :title="`Orbit-Dynamik: ${vitalityMode}`"
        :aria-label="`Orbit-Dynamik: ${vitalityMode}`"
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
        @click="fitView"
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
        <span>Umlaufbahn (Planet / Stern)</span>
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
.orbit-canvas {
  background-color: var(--gl-sunken);
  background-image: radial-gradient(var(--gl-line) 1px, transparent 1px);
  background-size: 28px 28px;
}

:root[data-theme='light'] .orbit-canvas {
  background-color: var(--gl-surface);
}

.orbit-canvas.is-editing {
  background-image: radial-gradient(var(--gl-line-strong) 1px, transparent 1px);
}

/* Subtle life & floating animations when vitalityMode is 'subtle' or 'lively' */
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
    opacity: 0.14;
  }
  50% {
    transform: scale(1.16);
    opacity: 0.26;
  }
}

@keyframes beam-flow {
  from {
    stroke-dashoffset: 140;
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
  animation: orbit-float 5.5s ease-in-out infinite;
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

.vitality-subtle .light-beam-pulse {
  animation: beam-flow 4.2s linear infinite;
}

.vitality-lively .light-beam-pulse {
  animation: beam-flow 2.2s linear infinite;
}

.orbit-drop-ring {
  animation: drop-ring-spin 8s linear infinite;
  transform-box: fill-box;
  transform-origin: center;
}
</style>
