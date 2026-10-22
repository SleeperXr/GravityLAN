<script setup lang="ts">
import { computed, markRaw, onMounted, ref, watch } from 'vue';
import { ConnectionMode, VueFlow, useVueFlow, type Connection, type EdgeMouseEvent, type NodeDragEvent, type NodeMouseEvent } from '@vue-flow/core';
import '@vue-flow/core/dist/style.css';
import { Check, Maximize, Minus, MousePointer2, Pencil, Plus, Trash2, Wand2, X } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device } from '@/types';
import { useNetworkStore } from '@/stores/network';
import { useAppearance } from '@/stores/appearance';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import Button from '@/components/ui/Button.vue';
import StationNode from './StationNode.vue';
import TransitEdge from './TransitEdge.vue';
import { LINK_TYPES, alignStations, autoLayout, lineSlots, linkColor, snapToNeighbours, stationState, type PlanLink, type StationData } from './netzplan';
import { deviceLabel, networkColor } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * The network map. Read-only on the overview (a click opens the device); in edit mode stations
 * drag (position saved per device), dragging from a station's edge to another adds a link, and
 * a selected link gets its colour and type, or is removed.
 */
const props = withDefaults(defineProps<{ editable?: boolean; startEditing?: boolean; flowId?: string }>(), {
  editable: false,
  startEditing: false,
  flowId: 'netzplan',
});
const emit = defineEmits<{ openDevice: [device: Device] }>();

const store = useNetworkStore();
const appearance = useAppearance();
const { showToast } = useToast();
const { confirm } = useConfirm();
const { fitView, zoomIn, zoomOut } = useVueFlow(props.flowId);
// Viewport tweens run in JS, outside the CSS reduced-motion rule
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const motion = (ms: number) => (reduceMotion?.matches ? 0 : ms);

const editing = ref(props.editable && props.startEditing);
const links = ref<PlanLink[]>([]);
const gatewayIds = ref(new Set<number>());
const positions = ref(new Map<number, { x: number; y: number }>());
const selectedLinkId = ref<number | null>(null);
const selectedDeviceId = ref<number | null>(null);
const loaded = ref(false);

const nodeTypes = { station: markRaw(StationNode) };
const edgeTypes = { transit: markRaw(TransitEdge) };

async function load() {
  try {
    const [linkList, gateways] = await Promise.all([api.getTopologyLinks() as Promise<PlanLink[]>, api.getGateways().catch(() => [])]);
    links.value = linkList;
    gatewayIds.value = new Set(gateways.map((g) => g.device_id).filter((id): id is number => id != null));
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
});

const devicesById = computed(() => new Map(store.devices.map((d) => [d.id, d])));

/** Saved position, else the drag position of this session, else the automatic layout. */
const auto = computed(() => autoLayout(store.devices.filter((d) => d.topology_x == null || d.topology_y == null), gatewayIds.value));
function rawPositionOf(d: Device) {
  return positions.value.get(d.id) ?? (d.topology_x != null && d.topology_y != null ? { x: d.topology_x, y: d.topology_y } : auto.value.get(d.id) ?? { x: 0, y: 0 });
}
/** Drawn positions: linked stations a few pixels off one axis are drawn on it (straight lines). */
const drawn = computed(() => alignStations(new Map(store.devices.map((d) => [d.id, rawPositionOf(d)])), links.value));
function positionOf(d: Device) {
  return drawn.value.get(d.id) ?? rawPositionOf(d);
}

const slots = computed(() => lineSlots(links.value, gatewayIds.value));
const colorOf = (l: PlanLink) => linkColor(l, devicesById.value.get(l.source_id), devicesById.value.get(l.target_id), slots.value.get(l.id));

/** Colours meeting at a station: its lines, else the networks it answers in. */
function linesAt(d: Device): string[] {
  const colors = links.value.filter((l) => l.source_id === d.id || l.target_id === d.id).map(colorOf);
  if (colors.length > 1) return [...new Set(colors)];
  return [...new Set([networkColor(d.subnet_id, d.ip), ...(d.interfaces ?? []).map((i) => networkColor(i.subnet_id, i.ip)), ...colors])];
}

const nodes = computed(() =>
  store.devices.map((d) => ({
    id: String(d.id),
    type: 'station',
    position: positionOf(d),
    draggable: editing.value,
    selectable: true,
    data: {
      device: d,
      state: stationState(d),
      interchange: gatewayIds.value.has(d.id) || (d.interfaces?.length ?? 0) > 0 || linesAt(d).length > 2,
      lines: linesAt(d),
      editable: editing.value,
    } satisfies StationData,
  })),
);

const edges = computed(() =>
  links.value
    .filter((l) => devicesById.value.has(l.source_id) && devicesById.value.has(l.target_id))
    .map((l) => {
      const source = devicesById.value.get(l.source_id)!;
      const target = devicesById.value.get(l.target_id)!;
      return {
        id: `l-${l.id}`,
        type: 'transit',
        source: String(l.source_id),
        target: String(l.target_id),
        sourceHandle: l.source_handle ?? undefined,
        targetHandle: l.target_handle ?? undefined,
        selected: selectedLinkId.value === l.id,
        data: { color: colorOf(l), interrupted: !source.is_online || !target.is_online, linkType: l.link_type, editable: editing.value },
      };
    }),
);

const selectedLink = computed(() => links.value.find((l) => l.id === selectedLinkId.value) ?? null);
const selectedDevice = computed(() => (selectedDeviceId.value ? devicesById.value.get(selectedDeviceId.value) ?? null : null));

/** Palette slots resolved to hex: the link column stores plain #rrggbb. */
const swatches = computed(() => {
  void appearance.lineColors;
  const style = getComputedStyle(document.documentElement);
  return Array.from({ length: 10 }, (_, i) => style.getPropertyValue(`--line-${i + 1}`).trim()).filter(Boolean);
});

function onNodeClick({ node }: NodeMouseEvent) {
  const device = devicesById.value.get(Number(node.id));
  if (!device) return;
  if (editing.value) {
    selectedDeviceId.value = device.id;
    selectedLinkId.value = null;
  } else {
    emit('openDevice', device);
  }
}

function onEdgeClick({ edge }: EdgeMouseEvent) {
  if (!editing.value) return;
  selectedLinkId.value = Number(edge.id.replace('l-', ''));
  selectedDeviceId.value = null;
}

async function onDragStop({ node }: NodeDragEvent) {
  const id = Number(node.id);
  // Drop onto the axis of a linked neighbour when close, so the line runs dead straight
  const neighbours = links.value
    .filter((l) => l.source_id === id || l.target_id === id)
    .map((l) => drawn.value.get(l.source_id === id ? l.target_id : l.source_id))
    .filter((p): p is { x: number; y: number } => !!p);
  const pos = snapToNeighbours({ x: Math.round(node.position.x), y: Math.round(node.position.y) }, neighbours);
  positions.value = new Map(positions.value).set(id, pos);
  try {
    await api.updateDevice(id, { topology_x: pos.x, topology_y: pos.y });
    store.patchDevice(id, { topology_x: pos.x, topology_y: pos.y });
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

async function onConnect(connection: Connection) {
  const source = Number(connection.source);
  const target = Number(connection.target);
  if (!source || !target || source === target) return;
  if (links.value.some((l) => (l.source_id === source && l.target_id === target) || (l.source_id === target && l.target_id === source))) {
    showToast('info', t('gv.plan.link_exists'), '');
    return;
  }
  try {
    const created = (await api.createTopologyLink({
      source_id: source,
      target_id: target,
      source_handle: connection.sourceHandle ?? null,
      target_handle: connection.targetHandle ?? null,
      link_type: '1GbE',
    })) as PlanLink;
    links.value = [...links.value, created];
    selectedLinkId.value = created.id;
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
}

async function patchLink(patch: Partial<PlanLink>) {
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

/** Every station back to the automatic layout, saved for all devices. */
async function arrange() {
  const ok = await confirm({ title: t('gv.plan.arrange'), message: t('gv.plan.arrange_confirm') });
  if (!ok) return;
  const layout = autoLayout(store.devices, gatewayIds.value);
  positions.value = new Map(layout);
  await Promise.all(
    [...layout].map(([id, pos]) => api.updateDevice(id, { topology_x: pos.x, topology_y: pos.y }).catch(() => {})),
  );
  await store.loadData(true);
  window.setTimeout(() => fitView({ padding: 0.15, duration: motion(400) }), 50);
}

function toggleEditing() {
  editing.value = !editing.value;
  selectedLinkId.value = null;
  selectedDeviceId.value = null;
}

watch(loaded, (isLoaded) => {
  if (isLoaded) window.setTimeout(() => fitView({ padding: 0.15 }), 60);
});

const linkEnds = computed(() => {
  const l = selectedLink.value;
  if (!l) return '';
  const a = devicesById.value.get(l.source_id);
  const b = devicesById.value.get(l.target_id);
  return `${a ? deviceLabel(a) : '?'} – ${b ? deviceLabel(b) : '?'}`;
});
</script>

<template>
  <div class="plan relative h-full w-full overflow-hidden" :class="editing && 'is-editing'">
    <VueFlow
      :id="flowId"
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :nodes-draggable="editing"
      :nodes-connectable="editing"
      :elements-selectable="true"
      :connection-mode="ConnectionMode.Loose"
      :delete-key-code="null"
      :min-zoom="0.2"
      :max-zoom="2.5"
      :zoom-on-double-click="false"
      :connection-line-style="{ stroke: 'var(--gl-accent)', strokeWidth: 6, strokeLinecap: 'round' }"
      :aria-label="t('gv.plan.title')"
      @node-click="onNodeClick"
      @edge-click="onEdgeClick"
      @node-drag-stop="onDragStop"
      @connect="onConnect"
      @pane-click="selectedLinkId = null; selectedDeviceId = null"
    />

    <!-- Map controls -->
    <div class="absolute right-3 bottom-3 z-10 flex flex-col overflow-hidden rounded-md border border-line bg-surface shadow-pop">
      <button type="button" class="flex size-8 items-center justify-center text-fg-muted hover:bg-control-hover hover:text-fg" :aria-label="t('gv.plan.zoom_in')" @click="zoomIn()"><Plus class="size-4" /></button>
      <button type="button" class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg" :aria-label="t('gv.plan.zoom_out')" @click="zoomOut()"><Minus class="size-4" /></button>
      <button type="button" class="flex size-8 items-center justify-center border-t border-line text-fg-muted hover:bg-control-hover hover:text-fg" :aria-label="t('gv.plan.fit')" @click="fitView({ padding: 0.15, duration: motion(300) })"><Maximize class="size-3.5" /></button>
    </div>

    <div v-if="editable" class="absolute top-3 right-3 z-10 flex gap-2">
      <Button v-if="editing" size="sm" @click="arrange"><Wand2 aria-hidden="true" />{{ t('gv.plan.arrange') }}</Button>
      <Button size="sm" :variant="editing ? 'primary' : 'secondary'" @click="toggleEditing">
        <component :is="editing ? Check : Pencil" aria-hidden="true" />{{ editing ? t('dashboard.edit_finish') : t('gv.plan.edit') }}
      </Button>
    </div>

    <p v-if="editing && !selectedLink && !selectedDevice" class="absolute bottom-3 left-3 z-10 flex max-w-sm items-start gap-2 rounded-md border border-line bg-surface/95 px-3 py-2 text-xs text-fg-muted shadow-pop backdrop-blur">
      <MousePointer2 class="mt-0.5 size-3.5 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.plan.edit_hint') }}
    </p>

    <!-- Selected link: colour, type, remove -->
    <div v-if="editing && selectedLink" class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-3 rounded-lg border border-line-strong bg-surface p-3.5 shadow-pop" role="dialog" :aria-label="t('gv.plan.link')">
      <div class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-semibold text-fg">{{ t('gv.plan.link') }}</p>
          <p class="truncate text-xs text-fg-subtle">{{ linkEnds }}</p>
        </div>
        <button type="button" class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="selectedLinkId = null"><X class="size-4" /></button>
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
          <label class="relative size-7 cursor-pointer overflow-hidden rounded-full border border-dashed border-line-strong" :title="t('gv.plan.custom_color')">
            <span class="sr-only">{{ t('gv.plan.custom_color') }}</span>
            <input type="color" class="absolute inset-0 size-full cursor-pointer opacity-0" :value="selectedLink.color ?? '#2ec4a6'" @change="patchLink({ color: ($event.target as HTMLInputElement).value })" />
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
        <Button variant="danger-ghost" @click="deleteLink"><Trash2 aria-hidden="true" />{{ t('common.delete') }}</Button>
      </div>
    </div>

    <!-- Selected station in edit mode -->
    <div v-if="editing && selectedDevice" class="absolute bottom-3 left-3 z-10 flex items-center gap-3 rounded-lg border border-line-strong bg-surface p-3 shadow-pop">
      <div class="min-w-0">
        <p class="truncate text-sm font-semibold text-fg">{{ deviceLabel(selectedDevice) }}</p>
        <p class="font-mono text-xs text-fg-subtle">{{ selectedDevice.ip }}</p>
      </div>
      <Button size="sm" @click="emit('openDevice', selectedDevice)">{{ t('dashboard.edit_device') }}</Button>
    </div>
  </div>
</template>

<style>
.plan {
  background-color: var(--gl-sunken);
  background-image: radial-gradient(var(--gl-line) 1px, transparent 1px);
  background-size: 28px 28px;
}
/* The daytime map is the whitest surface on the page */
:root[data-theme='light'] .plan {
  background-color: var(--gl-surface);
}
.plan.is-editing {
  background-image: radial-gradient(var(--gl-line-strong) 1px, transparent 1px);
}
.plan .vue-flow__node {
  padding: 0;
  border: 0;
  background: transparent;
}
.plan .vue-flow__node.selected,
.plan .vue-flow__node:focus-visible {
  outline: none;
}
.plan .vue-flow__edge-path {
  transition: stroke-dasharray 300ms ease;
}
</style>
