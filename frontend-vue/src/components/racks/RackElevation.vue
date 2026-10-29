<script setup lang="ts">
import { computed, ref } from 'vue';
import { GripVertical } from 'lucide-vue-next';
import StatusDot from '@/components/common/StatusDot.vue';
import { t } from '@/i18n';
import { draggingKey } from './rackDrag';
import { kindOf } from './rackKinds';
import { fitsAt, rackSlots, type RackEntry } from './rackModel';

/**
 * The rack as one row per unit. Entries are dragged to a free place (a place that does not fit shows why
 * before the mouse is released) or moved one unit at a time with the arrow keys. A click selects, a double
 * click opens. The parent decides what a move means and saves it.
 */
const props = defineProps<{
  name: string;
  units: number;
  /** Entries of this rack, placed or waiting in the tray */
  entries: RackEntry[];
  /** Network devices without a rack that may be dragged in */
  candidates: RackEntry[];
  selectedKey: string | null;
  portStats: Record<string, { cabled: number; total: number }>;
}>();
const emit = defineEmits<{
  select: [key: string];
  open: [key: string];
  move: [key: string, unit: number];
}>();

const UNIT_REM = 1.75;
const slots = computed(() => rackSlots(props.units, props.entries));
const dragCandidates = computed(() => [...props.entries, ...props.candidates]);
const hover = ref<{ unit: number; valid: boolean } | null>(null);

const dragged = (): RackEntry | null => dragCandidates.value.find((e) => e.key === draggingKey.value) ?? null;

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

function portSummary(entry: RackEntry): string | null {
  const stat = props.portStats[entry.key];
  return stat && stat.total > 0 ? `${stat.cabled}/${stat.total}` : null;
}
</script>

<template>
  <div
    class="rack-rail rounded-lg border-[6px] border-[color-mix(in_oklab,var(--gl-line-strong)_70%,transparent)] bg-sunken p-1.5 shadow-inner"
    role="list"
    :aria-label="name"
  >
    <div
      v-for="slot in slots"
      :key="slot.unit"
      class="flex gap-1.5"
      @dragover="over($event, slot.unit)"
      @dragleave="leave(slot.unit)"
      @drop="drop($event, slot.unit)"
    >
      <span class="w-6 shrink-0 text-right font-mono text-[10px] leading-7 text-fg-subtle tabular" aria-hidden="true">{{ slot.unit }}</span>

      <button
        v-if="slot.entry"
        type="button"
        role="listitem"
        draggable="true"
        class="rack-entry group relative my-px flex min-w-0 flex-1 cursor-grab items-center gap-2 overflow-hidden rounded-[5px] border bg-raised pr-2.5 pl-1 text-left transition-[opacity,background-color,border-color] duration-150 hover:bg-control-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent active:cursor-grabbing"
        :class="[
          selectedKey === slot.entry.key ? 'border-accent ring-1 ring-accent' : 'border-line',
          slot.entry.itemKind === 'blank' && 'rack-blank',
          !slot.entry.online && 'opacity-70',
          draggingKey === slot.entry.key && 'opacity-40',
        ]"
        :style="{ height: `calc(${slot.entry.height * UNIT_REM}rem - 2px)` }"
        :aria-label="`${slot.entry.label}, ${t('gv.rack.position', { unit: slot.unit, count: slot.entry.height })}`"
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
        <span class="min-w-0 flex-1">
          <span class="block truncate text-xs font-semibold text-fg">{{ slot.entry.label }}</span>
          <span v-if="slot.entry.detail || slot.entry.height > 1" class="block truncate font-mono text-[10px] text-fg-subtle">
            {{ slot.entry.detail }}<template v-if="slot.entry.height > 1"> · {{ t('rack.units', { count: slot.entry.height }) }}</template>
          </span>
        </span>
        <span v-if="portSummary(slot.entry)" class="shrink-0 rounded-sm bg-sunken px-1.5 font-mono text-[10px] text-fg-muted tabular" :title="t('gv.rack.ports_summary')">
          {{ portSummary(slot.entry) }}
        </span>
      </button>

      <span
        v-else
        class="my-px flex h-[calc(1.75rem-2px)] flex-1 items-center rounded-[5px] border border-dashed px-2 text-[10px] transition-colors"
        :class="[slotClass(slot.unit), hover?.unit === slot.unit ? 'text-fg-muted' : 'text-transparent']"
      >
        <template v-if="hover?.unit === slot.unit">{{ hover.valid ? t('gv.rack.drop_here') : t('gv.rack.drop_blocked') }}</template>
      </span>

      <span class="w-6 shrink-0 font-mono text-[10px] leading-7 text-fg-subtle tabular" aria-hidden="true">{{ slot.unit }}</span>
    </div>
  </div>
</template>

<style scoped>
/* A blank panel is a faceplate without ports: hatched, so it reads as "nothing here" */
.rack-blank {
  background-image: repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in oklab, var(--gl-line-strong) 45%, transparent) 5px 6px);
}
</style>
