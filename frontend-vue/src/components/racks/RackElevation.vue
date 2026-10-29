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
import { cableRoute, fitsAt, overlappingKeys, ownerKeyOf, portsOnSide, rackSlots, sideOf, type PortSide, type RackEntry, type RackSlot } from './rackModel';
import { placeTargets, stepTarget } from './rackPlacement';

/**
 * The rack as one row per unit, seen from the front or the rear. Entries are dragged to a free place (a place
 * that does not fit shows why before the mouse is released) or moved one unit at a time with the arrow keys.
 * One unit is `--rack-unit` tall (set on the rail, taller on phones); rows, entries, overlap offsets and
 * placement targets all derive from it, and the cables are measured from the jacks as drawn.
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
  /** Where the cable on a port leads, for the jack's name; ports without a cable are left out */
  cableTargets?: Record<number, string>;
}>();
const emit = defineEmits<{
  select: [key: string];
  open: [key: string];
  move: [key: string, unit: number];
  place: [key: string, unit: number];
  /** A jack was used: the start or the end of a cable */
  pickPort: [key: string, port: RackPort];
}>();

const slots = computed(() => rackSlots(props.units, props.entries));
const overlapping = computed(() => overlappingKeys(props.entries));
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

/** Height and place of an entry in its row: on its own top unit, cut off at the bottom of the rack. */
function entryStyle(slot: RackSlot, entry: RackEntry): Record<string, string | undefined> {
  const offset = slot.unit - (entry.unit ?? slot.unit);
  const height = Math.min(entry.height, entry.unit ?? 1);
  return {
    height: 'calc(' + height + ' * var(--rack-unit) - 2px)',
    marginTop: offset > 0 ? 'calc(' + offset + ' * var(--rack-unit) + 1px)' : undefined,
  };
}

/** What a screen reader says for an entry: name, state, place, and a clash with another entry. */
function entryName(entry: RackEntry): string {
  const parts = [entry.label];
  if (entry.kind === 'device') parts.push(entry.online ? t('network.online') : t('network.offline'));
  if (entry.unit !== null) parts.push(t('gv.rack.position', { unit: entry.unit, count: entry.height }));
  if (overlapping.value.has(entry.key)) parts.push(t('gv.racks.issue_overlap'));
  return parts.join(', ');
}

/** A jack's name: port number, kind, side, and where its cable leads. */
function jackName(port: RackPort): string {
  const side = sideOf(port) === 'rear' ? t('gv.rack.side_rear') : t('gv.rack.side_front');
  const target = props.cableTargets?.[port.id] ?? t('gv.rack.ports_free');
  return t('gv.rack.port') + ' ' + port.number + ', ' + port.kind + ', ' + side + ', ' + target;
}

// The jacks of an entry are one tab stop; the arrow keys move between them
const jackFocus = ref<Record<string, number>>({});
const jackIndex = (entry: RackEntry): number => Math.min(jackFocus.value[entry.key] ?? 0, jacksOf(entry).length - 1);

function jackKey(event: KeyboardEvent, entry: RackEntry, index: number) {
  const last = jacksOf(entry).length - 1;
  const next = { ArrowRight: index + 1, ArrowDown: index + 1, ArrowLeft: index - 1, ArrowUp: index - 1, Home: 0, End: last }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  const target = Math.min(last, Math.max(0, next));
  const jacks = (event.currentTarget as HTMLElement).closest('ul')?.querySelectorAll<HTMLElement>('button');
  jacks?.[target]?.focus();
}

function startDrag(event: DragEvent, entry: RackEntry) {
  draggingKey.value = entry.key;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', entry.key);
    // The button is an empty layer over the entry, so the entry itself is what is seen while dragging
    const row = (event.currentTarget as HTMLElement | null)?.parentElement;
    if (row) event.dataTransfer.setDragImage(row, event.offsetX, event.offsetY);
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

/** Arrow keys: one unit up or down. The entry is drawn anew on its new row, so focus follows it there. */
function nudge(entry: RackEntry, delta: number) {
  if (entry.unit === null) return;
  const unit = entry.unit + delta;
  if (fitsAt(props.units, props.entries, unit, entry.height, entry.key)) followFocus(entry.key, unit);
  emit('move', entry.key, unit);
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
/**
 * An entry about to be drawn on another row (placed, nudged, moved to a free place) gets a new button there, so
 * focus is handed to it once it sits on `unit`, unless the user has meanwhile moved on outside the rack.
 */
let pendingFocus: { key: string; unit: number } | null = null;

function followFocus(key: string, unit: number) {
  pendingFocus = { key, unit };
}

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
defineExpose({ focusPlaceTarget, followFocus });

function stepPlace(unit: number, direction: 'up' | 'down') {
  const next = stepTarget(targets.value, unit, direction);
  if (next === null) return;
  activeTarget.value = next;
  targetEl(next)?.focus();
}

/** A free unit was chosen (click, Enter or Space): the targets go away, so focus goes to the placed entry. */
function placeAt(unit: number) {
  if (!props.placing) return;
  if (targets.value.includes(unit)) followFocus(props.placing.key, unit);
  emit('place', props.placing.key, unit);
}

watch(
  () => props.entries,
  () => {
    const wanted = pendingFocus;
    if (!wanted || !props.entries.some((e) => e.key === wanted.key && e.unit === wanted.unit)) return;
    pendingFocus = null;
    void nextTick(() => {
      const active = document.activeElement;
      const lost = !active || active === document.body || !!railRef.value?.contains(active);
      if (lost) railRef.value?.querySelector<HTMLElement>('[data-key="' + wanted.key + '"]')?.focus();
    });
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
          class="font-mono text-micro"
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
      <span class="w-6 shrink-0 text-right font-mono text-micro leading-[var(--rack-unit)] text-fg-subtle tabular" aria-hidden="true">{{ slot.unit }}</span>

      <!-- Entries that overlap share the row, side by side, each on its own units -->
      <div v-if="slot.entries.length" class="flex min-w-0 flex-1 items-start gap-1" :style="{ height: 'calc(' + slot.height + ' * var(--rack-unit))' }">
        <!-- The button covers the entry; the jacks sit above it as buttons of their own -->
        <div
          v-for="entry in slot.entries"
          :key="entry.key"
          role="listitem"
          class="rack-entry group relative my-px flex min-w-0 flex-1 items-center gap-2 overflow-hidden rounded-[5px] border bg-raised pr-2 pl-1 text-left transition-[opacity,background-color,border-color] duration-150 hover:bg-control-hover has-[>button:focus-visible]:ring-2 has-[>button:focus-visible]:ring-accent"
          :class="[
            selectedKey === entry.key ? 'border-accent ring-1 ring-accent' : overlapping.has(entry.key) ? 'border-warn' : 'border-line',
            entry.itemKind === 'blank' && 'rack-blank',
            !entry.online && 'shadow-[inset_2px_0_0_var(--gl-danger)]',
            draggingKey === entry.key && 'opacity-40',
          ]"
          :style="entryStyle(slot, entry)"
        >
          <button
            type="button"
            draggable="true"
            :data-key="entry.key"
            class="absolute inset-0 cursor-grab rounded-[5px] focus-visible:outline-none active:cursor-grabbing"
            :aria-label="entryName(entry)"
            :aria-pressed="selectedKey === entry.key"
            aria-keyshortcuts="ArrowUp ArrowDown"
            :title="t('gv.rack.entry_hint')"
            @click="emit('select', entry.key)"
            @dblclick="emit('open', entry.key)"
            @keydown.up.prevent="nudge(entry, 1)"
            @keydown.down.prevent="nudge(entry, -1)"
            @dragstart="startDrag($event, entry)"
            @dragend="endDrag"
          />
          <GripVertical class="size-3.5 shrink-0 text-fg-subtle opacity-60" aria-hidden="true" />
          <StatusDot v-if="entry.kind === 'device'" :state="entry.online ? 'online' : 'offline'" size="sm" />
          <component :is="kindOf(entry.itemKind ?? 'other').icon" v-else class="size-3.5 shrink-0 text-fg-muted" aria-hidden="true" />
          <span class="min-w-[5rem] flex-1" aria-hidden="true">
            <span class="block truncate text-xs leading-3.5 font-semibold text-fg">{{ entry.label }}</span>
            <span v-if="entry.detail || entry.height > 1" class="block truncate font-mono text-micro leading-3 text-fg-subtle">
              {{ entry.detail }}<template v-if="entry.height > 1"> · {{ t('rack.units', { count: entry.height }) }}</template>
            </span>
          </span>
          <ul
            v-if="jacksOf(entry).length"
            role="list"
            class="relative flex max-w-[11rem] shrink-0 flex-wrap justify-end gap-[2px]"
            :aria-label="t('gv.rack.entry_ports', { label: entry.label })"
          >
            <li v-for="(p, i) in jacksOf(entry)" :key="p.id" class="flex">
              <button
                type="button"
                :data-port="p.id"
                :tabindex="i === jackIndex(entry) ? 0 : -1"
                :aria-label="jackName(p)"
                :title="jackName(p)"
                class="rounded-[1px] border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                :class="[jackClass(jacksOf(entry).length), colourOfPort[p.id] ? '' : 'border-fg-subtle/60']"
                :style="colourOfPort[p.id] ? { backgroundColor: colourOfPort[p.id], borderColor: colourOfPort[p.id] } : undefined"
                @click="emit('pickPort', entry.key, p)"
                @focus="jackFocus[entry.key] = i"
                @keydown="jackKey($event, entry, i)"
              />
            </li>
          </ul>
          <span v-if="portSummary(entry)" class="shrink-0 rounded-sm bg-sunken px-1.5 font-mono text-micro text-fg-muted tabular" :title="t('gv.rack.ports_summary')" aria-hidden="true">
            {{ portSummary(entry) }}
          </span>
        </div>
      </div>

      <!-- While placing, the free units join the list as buttons that put the picked entry there -->
      <div v-else-if="placing" role="listitem" class="flex min-w-0 flex-1">
        <button
          type="button"
          :data-place-unit="slot.unit"
          class="my-px flex h-[calc(var(--rack-unit)_-_2px)] min-w-0 flex-1 items-center rounded-[5px] border border-dashed px-2 text-left text-xs text-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          :class="
            targets.includes(slot.unit)
              ? 'border-accent/60 hover:bg-accent/10 hover:text-fg-muted focus-visible:bg-accent/10 focus-visible:text-fg-muted'
              : 'cursor-not-allowed border-line/70 hover:text-fg-subtle'
          "
          :tabindex="slot.unit === activeTarget ? 0 : -1"
          :aria-disabled="!targets.includes(slot.unit) || undefined"
          :aria-label="t('gv.rack.place_at', { label: placing.label, unit: slot.unit }) + (targets.includes(slot.unit) ? '' : ', ' + t('gv.rack.drop_blocked'))"
          @click="placeAt(slot.unit)"
          @focus="targets.includes(slot.unit) && (activeTarget = slot.unit)"
          @keydown.up.prevent="stepPlace(slot.unit, 'up')"
          @keydown.down.prevent="stepPlace(slot.unit, 'down')"
        >
          <span class="truncate">{{ targets.includes(slot.unit) ? t('gv.rack.drop_here') : t('gv.rack.drop_blocked') }}</span>
        </button>
      </div>

      <!-- A free unit outside placing is only a drop zone for the mouse; it says nothing to a screen reader -->
      <span
        v-else
        class="my-px flex h-[calc(var(--rack-unit)_-_2px)] flex-1 items-center rounded-[5px] border border-dashed px-2 text-xs transition-colors"
        :class="[slotClass(slot.unit), hover?.unit === slot.unit ? 'text-fg-muted' : 'text-transparent']"
        aria-hidden="true"
      >
        <template v-if="hover?.unit === slot.unit">{{ hover.valid ? t('gv.rack.drop_here') : t('gv.rack.drop_blocked') }}</template>
      </span>

      <span data-channel class="shrink-0" :style="{ width: channelPx + 'px' }" aria-hidden="true" />

      <span class="w-6 shrink-0 font-mono text-micro leading-[var(--rack-unit)] text-fg-subtle tabular max-sm:hidden" aria-hidden="true">{{ slot.unit }}</span>
    </div>
  </div>
</template>

<style scoped>
/* One rack unit; every height in the elevation is a multiple of it */
.rack-rail {
  --rack-unit: 1.75rem;
}

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
