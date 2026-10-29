<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useResizeObserver } from '@vueuse/core';
import { GripVertical } from 'lucide-vue-next';
import StatusDot from '@/components/common/StatusDot.vue';
import { t } from '@/i18n';
import type { RackCable, RackPort } from '@/types';
import { draggingKey } from './rackDrag';
import { kindOf } from './rackKinds';
import { channelWidth, laneCount, laneX } from './cableLanes';
import { cableRoute, fitsAt, ownerKeyOf, portsOnSide, rackSlots, sideOf, type PortSide, type RackEntry } from './rackModel';
import { placeTargets, stepTarget } from './rackPlacement';

/**
 * The rack as one row per unit, seen from the front or the rear. Entries are dragged to a free place (a place
 * that does not fit shows why before the mouse is released) or moved one unit at a time with the arrow keys.
 *
 * Cables run in a channel on the right of the rail: a thick line with a dark edge from each jack to its lane,
 * so each cable is visible on its own. A cable whose other end is not on this side (or not in this rack) leaves
 * as a dashed line to the edge with a label. Selecting an entry highlights its cables and dims the others.
 */
const props = defineProps<{
  name: string;
  units: number;
  /** Rack width in inches: 19 or 10 */
  width: number;
  /** Entries of this rack, placed or waiting in the tray */
  entries: RackEntry[];
  /** Network devices without a rack that may be dragged in */
  candidates: RackEntry[];
  selectedKey: string | null;
  portStats: Record<string, { cabled: number; total: number }>;
  side: PortSide;
  /** Every port of the rack's devices and rack items */
  ports: RackPort[];
  cables: RackCable[];
  colourOfPort: Record<number, string>;
  /** An entry picked in the tray: free units turn into buttons that put it there */
  placing?: RackEntry | null;
}>();
const emit = defineEmits<{
  select: [key: string];
  open: [key: string];
  move: [key: string, unit: number];
  place: [key: string, unit: number];
}>();

const UNIT_REM = 1.75;

const slots = computed(() => rackSlots(props.units, props.entries));
const dragCandidates = computed(() => [...props.entries, ...props.candidates]);
const hover = ref<{ unit: number; valid: boolean } | null>(null);
const portById = computed(() => new Map(props.ports.map((p) => [p.id, p])));
/** One lane per cable, the channel widening as needed: lanes reused after eight drew cable 9 over cable 1 */
const channelPx = computed(() => channelWidth(laneCount(props.cables, portById.value, props.side)));
const keysHere = computed(() => new Set(dragCandidates.value.map((e) => e.key)));

const railRef = ref<HTMLElement | null>(null);
type CableDraw = {
  id: number;
  d: string;
  colour: string;
  active: boolean;
  stub: boolean;
  label: { x: number; y: number; text: string } | null;
};
const cableDraws = ref<CableDraw[]>([]);

/** Where each cable is drawn, measured from the jacks as they are on screen. */
function measure() {
  const rail = railRef.value;
  if (!rail) return;
  const origin = rail.getBoundingClientRect();
  const width = rail.clientWidth;
  const channel = rail.querySelector<HTMLElement>('[data-channel]');
  const channelLeft = channel ? channel.getBoundingClientRect().left - origin.left : width - channelPx.value;
  const centre = (portId: number) => {
    const el = rail.querySelector<HTMLElement>('[data-port="' + portId + '"]');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2 - origin.left, y: r.top + r.height / 2 - origin.top };
  };
  const draws: CableDraw[] = [];
  let lane = 0;
  for (const cable of props.cables) {
    const pa = portById.value.get(cable.a_port_id);
    const pb = portById.value.get(cable.b_port_id);
    if (!pa || !pb) continue;
    const colour = cable.color ?? '#c3cad4';
    const active = props.selectedKey !== null && (ownerKeyOf(pa) === props.selectedKey || ownerKeyOf(pb) === props.selectedKey);
    const a = centre(pa.id);
    const b = centre(pb.id);
    if (a && b) {
      draws.push({ id: cable.id, d: cableRoute(a, b, laneX(channelLeft, lane)), colour, active, stub: false, label: null });
      lane += 1;
    } else if (a || b) {
      // The other end is not drawn here: on the other side of the rack, or in another rack
      const end = (a ?? b)!;
      const other = a ? pb : pa;
      const text = !keysHere.value.has(ownerKeyOf(other))
        ? t('gv.rack.stub_elsewhere')
        : sideOf(other) === 'rear'
          ? t('gv.rack.stub_rear')
          : t('gv.rack.stub_front');
      const endX = width - 4;
      draws.push({ id: cable.id, d: 'M ' + end.x + ' ' + end.y + ' H ' + endX, colour, active, stub: true, label: { x: endX - 2, y: end.y - 4, text } });
    }
  }
  cableDraws.value = draws;
}

watch(
  () => [props.entries, props.ports, props.cables, props.side, props.units, props.selectedKey],
  () => nextTick(measure),
);
onMounted(() => nextTick(measure));
useResizeObserver(railRef, measure);

const dragged = (): RackEntry | null => dragCandidates.value.find((e) => e.key === draggingKey.value) ?? null;

function jacksOf(entry: RackEntry): RackPort[] {
  return portsOnSide(entry, props.ports, props.side);
}

/** Jacks shrink with the number of ports, so a 48-port panel still fits on one unit */
function jackClass(count: number): string {
  if (count <= 12) return 'size-2';
  if (count <= 24) return 'size-[6px]';
  return 'size-1';
}

function startDrag(event: DragEvent, entry: RackEntry) {
  draggingKey.value = entry.key;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', entry.key);
  }
}

function endDrag() {
  draggingKey.value = null;
  hover.value = null;
}

function over(event: DragEvent, unit: number) {
  const entry = dragged();
  if (!entry) return;
  const valid = fitsAt(props.units, props.entries, unit, entry.height, entry.key);
  hover.value = { unit, valid };
  if (event.dataTransfer) event.dataTransfer.dropEffect = valid ? 'move' : 'none';
  // Only a place that fits accepts the drop
  if (valid) event.preventDefault();
}

function drop(event: DragEvent, unit: number) {
  event.preventDefault();
  const entry = dragged();
  hover.value = null;
  draggingKey.value = null;
  if (entry) emit('move', entry.key, unit);
}

function leave(unit: number) {
  if (hover.value?.unit === unit) hover.value = null;
}

function nudge(entry: RackEntry, delta: number) {
  if (entry.unit !== null) emit('move', entry.key, entry.unit + delta);
}

function slotClass(unit: number): string {
  if (hover.value?.unit !== unit) return 'border-line/70 hover:border-line-strong';
  return hover.value.valid ? 'border-accent bg-accent/10' : 'border-warn/70 bg-warn/10';
}

// ── Placing a picked entry ───────────────────────────────────────────────────
/** Units that take the picked entry, top first; one of them is in the tab order, the arrow keys walk them */
const targets = computed(() => (props.placing ? placeTargets(props.units, props.entries, props.placing) : []));
const activeTarget = ref<number | null>(null);
watch(targets, (list) => {
  if (activeTarget.value === null || !list.includes(activeTarget.value)) activeTarget.value = list[0] ?? null;
});
/** After a place by keyboard, focus goes to the placed entry once it is drawn */
let focusAfterPlace: string | null = null;

function targetEl(unit: number): HTMLElement | null {
  return railRef.value?.querySelector<HTMLElement>('[data-place-unit="' + unit + '"]') ?? null;
}

/** Focus the first free unit that fits (Enter or Space in the tray); false when there is none. */
function focusPlaceTarget(): boolean {
  const unit = activeTarget.value ?? targets.value[0];
  if (unit === undefined || unit === null) return false;
  targetEl(unit)?.focus();
  return true;
}
defineExpose({ focusPlaceTarget });

function stepPlace(unit: number, direction: 'up' | 'down') {
  const next = stepTarget(targets.value, unit, direction);
  if (next === null) return;
  activeTarget.value = next;
  targetEl(next)?.focus();
}

function placeAt(unit: number, event: MouseEvent) {
  if (!props.placing) return;
  if (event.detail === 0) focusAfterPlace = props.placing.key;
  emit('place', props.placing.key, unit);
}

watch(
  () => props.entries,
  () => {
    const key = focusAfterPlace;
    if (!key || !props.entries.some((e) => e.key === key && e.unit !== null)) return;
    focusAfterPlace = null;
    void nextTick(() => railRef.value?.querySelector<HTMLElement>('[data-key="' + key + '"]')?.focus());
  },
);

function portSummary(entry: RackEntry): string | null {
  const stat = props.portStats[entry.key];
  return stat && stat.total > 0 ? stat.cabled + '/' + stat.total : null;
}
</script>

<template>
  <div
    ref="railRef"
    class="rack-rail relative rounded-lg border-[6px] border-[color-mix(in_oklab,var(--gl-line-strong)_70%,transparent)] bg-sunken p-1.5 shadow-inner"
    :style="{ maxWidth: width === 10 ? '24rem' : undefined }"
    role="list"
    :aria-label="name + ', ' + (side === 'front' ? t('gv.rack.side_front') : t('gv.rack.side_rear'))"
  >
    <svg class="pointer-events-none absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
      <g v-for="c in cableDraws" :key="c.id" :opacity="selectedKey && !c.active ? 0.3 : 1">
        <path :d="c.d" fill="none" stroke="var(--gl-sunken)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" />
        <path
          :d="c.d"
          fill="none"
          :stroke="c.colour"
          :stroke-width="c.active ? 4.5 : 3"
          :stroke-dasharray="c.stub ? '5 4' : undefined"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <text
          v-if="c.label"
          :x="c.label.x"
          :y="c.label.y"
          text-anchor="end"
          fill="var(--gl-fg-muted)"
          font-size="9"
          class="font-mono"
        >
          {{ c.label.text }}
        </text>
      </g>
    </svg>

    <div
      v-for="slot in slots"
      :key="slot.unit"
      class="flex items-stretch gap-1.5"
      @dragover="over($event, slot.unit)"
      @dragleave="leave(slot.unit)"
      @drop="drop($event, slot.unit)"
    >
      <span class="w-6 shrink-0 text-right font-mono text-[10px] leading-[var(--rack-unit,1.75rem)] text-fg-subtle tabular" aria-hidden="true">{{ slot.unit }}</span>

      <button
        v-if="slot.entry"
        type="button"
        role="listitem"
        draggable="true"
        :data-key="slot.entry.key"
        class="rack-entry group relative my-px flex min-w-0 flex-1 cursor-grab items-center gap-2 overflow-hidden rounded-[5px] border bg-raised pr-2 pl-1 text-left transition-[opacity,background-color,border-color] duration-150 hover:bg-control-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent active:cursor-grabbing"
        :class="[
          selectedKey === slot.entry.key ? 'border-accent ring-1 ring-accent' : 'border-line',
          slot.entry.itemKind === 'blank' && 'rack-blank',
          !slot.entry.online && 'opacity-70',
          draggingKey === slot.entry.key && 'opacity-40',
        ]"
        :style="{ height: 'calc(' + slot.entry.height + ' * var(--rack-unit, ' + UNIT_REM + 'rem) - 2px)' }"
        :aria-label="slot.entry.label + ', ' + t('gv.rack.position', { unit: slot.unit, count: slot.entry.height })"
        :aria-pressed="selectedKey === slot.entry.key"
        :title="t('gv.rack.entry_hint')"
        @click="emit('select', slot.entry.key)"
        @dblclick="emit('open', slot.entry.key)"
        @keydown.up.prevent="nudge(slot.entry, 1)"
        @keydown.down.prevent="nudge(slot.entry, -1)"
        @dragstart="startDrag($event, slot.entry)"
        @dragend="endDrag"
      >
        <GripVertical class="size-3.5 shrink-0 text-fg-subtle opacity-60" aria-hidden="true" />
        <StatusDot
          v-if="slot.entry.kind === 'device'"
          :state="slot.entry.online ? 'online' : 'offline'"
          size="sm"
          :label="slot.entry.online ? t('network.online') : t('network.offline')"
        />
        <component :is="kindOf(slot.entry.itemKind ?? 'other').icon" v-else class="size-3.5 shrink-0 text-fg-muted" aria-hidden="true" />
        <span class="min-w-[5rem] flex-1">
          <span class="block truncate text-xs font-semibold text-fg">{{ slot.entry.label }}</span>
          <span v-if="slot.entry.detail || slot.entry.height > 1" class="block truncate font-mono text-[10px] text-fg-subtle">
            {{ slot.entry.detail }}<template v-if="slot.entry.height > 1"> · {{ t('rack.units', { count: slot.entry.height }) }}</template>
          </span>
        </span>
        <span v-if="jacksOf(slot.entry).length" class="flex max-w-[11rem] shrink-0 flex-wrap justify-end gap-[2px]">
          <span
            v-for="p in jacksOf(slot.entry)"
            :key="p.id"
            :data-port="p.id"
            :title="t('gv.rack.port') + ' ' + p.number + ' · ' + p.kind"
            class="rounded-[1px] border"
            :class="[jackClass(jacksOf(slot.entry).length), colourOfPort[p.id] ? '' : 'border-fg-subtle/60']"
            :style="colourOfPort[p.id] ? { backgroundColor: colourOfPort[p.id], borderColor: colourOfPort[p.id] } : undefined"
          />
        </span>
        <span v-if="portSummary(slot.entry)" class="shrink-0 rounded-sm bg-sunken px-1.5 font-mono text-[10px] text-fg-muted tabular" :title="t('gv.rack.ports_summary')">
          {{ portSummary(slot.entry) }}
        </span>
      </button>

      <button
        v-else-if="placing"
        type="button"
        :data-place-unit="slot.unit"
        class="my-px flex h-[calc(var(--rack-unit,1.75rem)_-_2px)] min-w-0 flex-1 items-center rounded-[5px] border border-dashed px-2 text-left text-xs text-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        :class="
          targets.includes(slot.unit)
            ? 'border-accent/60 hover:bg-accent/10 hover:text-fg-muted focus-visible:bg-accent/10 focus-visible:text-fg-muted'
            : 'cursor-not-allowed border-line/70 hover:text-fg-subtle'
        "
        :tabindex="slot.unit === activeTarget ? 0 : -1"
        :aria-disabled="!targets.includes(slot.unit) || undefined"
        :aria-label="t('gv.rack.place_at', { label: placing.label, unit: slot.unit }) + (targets.includes(slot.unit) ? '' : ', ' + t('gv.rack.drop_blocked'))"
        @click="placeAt(slot.unit, $event)"
        @focus="targets.includes(slot.unit) && (activeTarget = slot.unit)"
        @keydown.up.prevent="stepPlace(slot.unit, 'up')"
        @keydown.down.prevent="stepPlace(slot.unit, 'down')"
      >
        <span class="truncate">{{ targets.includes(slot.unit) ? t('gv.rack.drop_here') : t('gv.rack.drop_blocked') }}</span>
      </button>

      <span
        v-else
        class="my-px flex h-[calc(var(--rack-unit,1.75rem)_-_2px)] flex-1 items-center rounded-[5px] border border-dashed px-2 text-[10px] transition-colors"
        :class="[slotClass(slot.unit), hover?.unit === slot.unit ? 'text-fg-muted' : 'text-transparent']"
      >
        <template v-if="hover?.unit === slot.unit">{{ hover.valid ? t('gv.rack.drop_here') : t('gv.rack.drop_blocked') }}</template>
      </span>

      <span data-channel class="shrink-0" :style="{ width: channelPx + 'px' }" aria-hidden="true" />

      <span class="w-6 shrink-0 font-mono text-[10px] leading-[var(--rack-unit,1.75rem)] text-fg-subtle tabular max-sm:hidden" aria-hidden="true">{{ slot.unit }}</span>
    </div>
  </div>
</template>

<style scoped>
/* Phones: one unit is a 44 px touch target (46 px row, 44 px entry) */
@media (width < 48rem) {
  .rack-rail {
    --rack-unit: 2.875rem;
  }
}

/* A blank panel is a faceplate without ports: hatched, so it reads as "nothing here" */
.rack-blank {
  background-image: repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in oklab, var(--gl-line-strong) 45%, transparent) 5px 6px);
}
</style>
