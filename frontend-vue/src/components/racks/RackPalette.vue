<script setup lang="ts">
import { computed, ref } from 'vue';
import { AlertTriangle, Search } from 'lucide-vue-next';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';
import { RACK_KINDS, faceOfItem, kindOf, type RackKind } from './rackKinds';
import type { PlacementIssue, RackEntry } from './rackModel';
import type { DragState, DragSubject } from './useRackDrag';

/**
 * What can go into the rack. "Install" holds every kind of rack equipment: pull one onto a unit, or tap it to
 * put it into the highest free gap. The store holds what belongs to this rack but has no unit (or one that does
 * not work), and the network devices that are in no rack yet. Pulling a faceplate out of the rack onto the store
 * takes it off its unit; onto "No rack" takes a device out of the rack altogether.
 */
const props = defineProps<{
  /** Entries of this rack without a usable unit, with the reason when their unit does not work */
  stored: { entry: RackEntry; issue: PlacementIssue | null }[];
  /** Network devices in no rack */
  unracked: RackEntry[];
  selectedKey: string | null;
  drag: DragState | null;
  /** In a sheet over the rack nothing can be dragged: a tap places, a swipe scrolls */
  tapOnly?: boolean;
  /** Devices left out of "No rack" because they are not rack gear (VMs, containers, APs, wireless clients) */
  hiddenCount: number;
  showAll: boolean;
}>();
const emit = defineEmits<{
  grab: [subject: DragSubject, event: PointerEvent, grab: { x: number; y: number }];
  place: [subject: DragSubject];
  select: [key: string];
  toggleAll: [];
}>();

const query = ref('');
const shownUnracked = computed(() => {
  const q = query.value.trim().toLowerCase();
  const list = q ? props.unracked.filter((e) => `${e.label} ${e.detail}`.toLowerCase().includes(q)) : props.unracked;
  return list.slice(0, 60);
});

const kindSubject = (kind: RackKind): DragSubject => ({
  key: `new:${kind.value}`,
  label: t(`gv.rack.kind_${kind.value}`),
  face: faceOfItem(kind.value),
  height: kind.height,
  itemKind: kind.value,
  entry: null,
  from: 'palette',
});
const entrySubject = (entry: RackEntry): DragSubject => ({
  key: entry.key,
  label: entry.label,
  face: entry.face,
  height: entry.height,
  itemKind: entry.itemKind,
  entry,
  from: 'store',
});

function grab(subject: DragSubject, event: PointerEvent) {
  if (props.tapOnly) return;
  if (event.pointerType === 'mouse') event.preventDefault();
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  emit('grab', subject, event, { x: event.clientX - rect.left, y: event.clientY - rect.top });
}

/** Keyboard clicks (detail 0) act at once; pointer clicks are decided by the drag (moved or not), unless there is no drag */
function onKeyClick(event: MouseEvent, run: () => void) {
  if (event.detail === 0 || props.tapOnly) run();
}

const dragging = computed(() => (props.drag?.lifted ? props.drag : null));
const storeActive = computed(() => dragging.value?.from === 'rack');
const unrackActive = computed(() => dragging.value?.entry?.kind === 'device' && dragging.value.from !== 'palette');
</script>

<template>
  <div class="flex min-h-0 flex-col gap-5 overflow-y-auto p-3">
    <section :aria-label="t('gv.rack.palette_title')">
      <h3 class="px-1 pb-2 text-xs font-semibold text-fg">{{ t('gv.rack.palette_title') }}</h3>
      <!-- As many columns as the (resizable) column has room for -->
      <div class="grid grid-cols-[repeat(auto-fill,minmax(5.25rem,1fr))] gap-1.5">
        <button
          v-for="kind in RACK_KINDS"
          :key="kind.value"
          type="button"
          class="rack-tile"
          :title="t('gv.rack.palette_hint')"
          @pointerdown="grab(kindSubject(kind), $event)"
          @click="onKeyClick($event, () => emit('place', kindSubject(kind)))"
        >
          <component :is="kind.icon" class="size-4 text-fg-muted" aria-hidden="true" />
          <span class="w-full text-xs leading-tight font-medium break-words hyphens-auto text-fg">{{ t(`gv.rack.kind_${kind.value}`) }}</span>
          <span class="font-mono text-micro text-fg-subtle">{{ t('gv.rack.units_label', { count: kind.height }) }}</span>
        </button>
      </div>
    </section>

    <section data-rack-drop="store" class="rack-zone" :class="[storeActive && 'is-armed', drag?.zone === 'store' && storeActive && 'is-over']" :aria-label="t('gv.rack.store_title')">
      <h3 class="flex items-baseline justify-between px-1 text-xs font-semibold text-fg">
        {{ t('gv.rack.store_title') }}
        <span class="font-mono text-micro font-normal text-fg-subtle">{{ stored.length }}</span>
      </h3>
      <p class="px-1 text-xs leading-snug text-fg-subtle">{{ storeActive ? t('gv.rack.store_drop') : t('gv.rack.store_hint') }}</p>
      <ul v-if="stored.length" class="space-y-1">
        <li v-for="s in stored" :key="s.entry.key">
          <button
            type="button"
            class="rack-row"
            :class="selectedKey === s.entry.key && 'is-selected'"
            @pointerdown="grab(entrySubject(s.entry), $event)"
            @click="onKeyClick($event, () => emit('select', s.entry.key))"
          >
            <span v-if="s.entry.kind === 'device'" class="rack-dot" :class="s.entry.online ? 'is-on' : 'is-off'" aria-hidden="true" />
            <component :is="kindOf(s.entry.itemKind ?? 'other').icon" v-else class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
            <span class="min-w-14 flex-1 truncate">{{ s.entry.label }}</span>
            <span v-if="s.issue" class="inline-flex shrink-0 items-center gap-1 text-micro text-warn-text" :title="t(`gv.racks.issue_${s.issue}`)">
              <AlertTriangle class="size-3" aria-hidden="true" />{{ t(`gv.rack.issue_short_${s.issue}`) }}
            </span>
            <span v-else class="shrink-0 font-mono text-micro text-fg-subtle">{{ t('gv.rack.units_label', { count: s.entry.height }) }}</span>
          </button>
        </li>
      </ul>

      <div data-rack-drop="unrack" class="rack-zone is-nested" :class="[unrackActive && 'is-armed', drag?.zone === 'unrack' && unrackActive && 'is-over']">
        <h4 class="px-1 text-xs font-semibold text-fg">{{ t('gv.rack.tray_unracked') }}</h4>
        <p class="px-1 text-xs leading-snug text-fg-subtle">{{ unrackActive ? t('gv.rack.unrack_drop') : t('gv.rack.unrack_hint') }}</p>
        <label class="relative block">
          <span class="sr-only">{{ t('gv.rack.tray_search') }}</span>
          <Search class="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
          <Input v-model="query" class="h-8 pl-8 text-xs" :placeholder="t('gv.rack.tray_search')" />
        </label>
        <ul v-if="shownUnracked.length" class="max-h-80 space-y-0.5 overflow-y-auto">
          <li v-for="e in shownUnracked" :key="e.key">
            <button
              type="button"
              class="rack-row is-plain"
              :class="selectedKey === e.key && 'is-selected'"
              @pointerdown="grab(entrySubject(e), $event)"
              @click="onKeyClick($event, () => emit('select', e.key))"
            >
              <span class="rack-dot" :class="e.online ? 'is-on' : 'is-off'" aria-hidden="true" />
              <span class="min-w-14 flex-1 truncate">{{ e.label }}</span>
              <span class="min-w-0 shrink-[3] truncate font-mono text-micro text-fg-subtle">{{ e.detail }}</span>
            </button>
          </li>
        </ul>
        <p v-else class="px-1 text-xs text-fg-subtle">{{ t('gv.rack.tray_unracked_none') }}</p>
        <div v-if="hiddenCount || showAll" class="space-y-1 px-1">
          <button type="button" class="text-xs font-semibold text-accent-text underline-offset-2 hover:underline" @click="emit('toggleAll')">
            {{ showAll ? t('gv.rack.tray_show_rackable') : t('gv.rack.tray_show_all', { count: hiddenCount }) }}
          </button>
          <p v-if="!showAll" class="text-xs leading-snug text-fg-subtle">{{ t('gv.rack.tray_filter_hint') }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rack-tile {
  display: flex;
  min-width: 0;
  min-height: 4.25rem;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.25rem;
  padding: 0.5rem;
  border: 1px solid var(--gl-line);
  border-radius: 8px;
  background: var(--gl-raised);
  text-align: left;
  cursor: grab;
  touch-action: pan-y;
  transition:
    border-color 120ms ease-out,
    transform 160ms var(--ease-out-expo);
}
.rack-tile:hover {
  border-color: var(--gl-line-strong);
  transform: translateY(-1px);
}
.rack-tile:active {
  cursor: grabbing;
  transform: scale(0.98);
}
.rack-tile:focus-visible,
.rack-row:focus-visible {
  outline: 2px solid var(--gl-accent);
  outline-offset: 1px;
}
.rack-zone {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px dashed transparent;
  border-radius: 10px;
  transition:
    border-color 150ms ease-out,
    background-color 150ms ease-out;
}
.rack-zone.is-nested {
  margin-top: 0.25rem;
  border-color: var(--gl-line);
}
.rack-zone.is-armed {
  border-color: var(--gl-line-strong);
  background: color-mix(in oklab, var(--gl-warn) 5%, transparent);
}
.rack-zone.is-over {
  border-color: var(--gl-warn);
  background: color-mix(in oklab, var(--gl-warn) 12%, transparent);
}
.rack-row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.5rem;
  border: 1px solid var(--gl-line);
  border-radius: 6px;
  background: var(--gl-raised);
  color: var(--gl-fg);
  font-size: 0.8125rem;
  text-align: left;
  cursor: grab;
  touch-action: pan-y;
  transition: border-color 120ms ease-out;
}
.rack-row.is-plain {
  border-color: transparent;
  background: transparent;
}
.rack-row:hover {
  border-color: var(--gl-line-strong);
}
.rack-row.is-selected {
  border-color: var(--gl-accent);
}
.rack-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 9999px;
}
.rack-dot.is-on {
  background: var(--gl-accent);
}
.rack-dot.is-off {
  background: var(--gl-danger);
}
</style>
