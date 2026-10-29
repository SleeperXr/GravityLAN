<script setup lang="ts">
import { computed, ref } from 'vue';
import { GripVertical, Search } from 'lucide-vue-next';
import Input from '@/components/ui/Input.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { t } from '@/i18n';
import { draggingKey } from './rackDrag';
import { kindOf } from './rackKinds';
import type { RackEntry } from './rackModel';

/**
 * Everything that is not on a unit yet. Drag a tray entry onto a free place in the rack. Drag a placed entry
 * back here to take it off its unit; drag a network device onto "No rack" to take it out of the rack.
 */
const props = defineProps<{
  /** Entries of this rack, placed or not, to decide what a drop onto a zone means */
  rackEntries: RackEntry[];
  /** Entries of this rack without a unit */
  unplaced: RackEntry[];
  /** Network devices that are in no rack at all */
  unracked: RackEntry[];
  selectedKey: string | null;
  /** The entry picked for placing by click or keyboard, waiting for a free unit */
  placingKey: string | null;
}>();
const emit = defineEmits<{
  select: [key: string];
  open: [key: string];
  unplace: [key: string];
  detach: [key: string];
  /** Pick an entry for placing (again: drop the pick); `keyboard` when it came from Enter or Space */
  place: [key: string, keyboard: boolean];
}>();

const query = ref('');
const shownUnracked = computed(() => {
  const q = query.value.trim().toLowerCase();
  const list = q ? props.unracked.filter((e) => `${e.label} ${e.detail}`.toLowerCase().includes(q)) : props.unracked;
  return list.slice(0, 60);
});

const dragged = (): RackEntry | undefined => props.rackEntries.find((e) => e.key === draggingKey.value);

function startDrag(event: DragEvent, entry: RackEntry) {
  draggingKey.value = entry.key;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', entry.key);
  }
}

function endDrag() {
  draggingKey.value = null;
}

/** A click, Enter or Space picks the entry for placing; an entry of this rack is selected as well. */
function pick(entry: RackEntry, event: MouseEvent) {
  if (props.rackEntries.some((e) => e.key === entry.key)) emit('select', entry.key);
  // A click from the keyboard has no pointer clicks (detail 0)
  emit('place', entry.key, event.detail === 0);
}

/** Dropping a placed entry on the unplaced zone takes it off its unit */
function acceptUnplace(event: DragEvent) {
  const entry = dragged();
  if (!entry || entry.unit === null) return;
  event.preventDefault();
}

/** Dropping a network device from this rack on the free zone removes it from the rack */
function acceptDetach(event: DragEvent) {
  const entry = dragged();
  if (!entry || entry.kind !== 'device') return;
  event.preventDefault();
}

function onUnplace(event: DragEvent) {
  const entry = dragged();
  draggingKey.value = null;
  if (entry && entry.unit !== null) {
    event.preventDefault();
    emit('unplace', entry.key);
  }
}

function onDetach(event: DragEvent) {
  const entry = dragged();
  draggingKey.value = null;
  if (entry && entry.kind === 'device') {
    event.preventDefault();
    emit('detach', entry.key);
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="gl-subcard space-y-2 p-3" @dragover="acceptUnplace" @drop="onUnplace">
      <h3 class="text-sm font-bold text-fg">{{ t('gv.rack.tray_unplaced') }}</h3>
      <p class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.tray_hint') }}</p>
      <ul v-if="unplaced.length" class="space-y-1">
        <li v-for="e in unplaced" :key="e.key">
          <button
            type="button"
            draggable="true"
            class="flex w-full cursor-grab items-center gap-2 rounded-md border border-line bg-raised px-2 py-1.5 text-left text-sm transition-colors hover:bg-control-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent max-md:min-h-11"
            :class="[(selectedKey === e.key || placingKey === e.key) && 'border-accent ring-1 ring-accent', placingKey === e.key && 'bg-accent/10']"
            :aria-pressed="placingKey === e.key"
            :title="t('gv.rack.tray_entry_hint')"
            @click="pick(e, $event)"
            @dblclick="emit('open', e.key)"
            @dragstart="startDrag($event, e)"
            @dragend="endDrag"
          >
            <GripVertical class="size-3.5 shrink-0 text-fg-subtle opacity-60" aria-hidden="true" />
            <StatusDot v-if="e.kind === 'device'" :state="e.online ? 'online' : 'offline'" size="sm" :label="e.online ? t('network.online') : t('network.offline')" />
            <component :is="kindOf(e.itemKind ?? 'other').icon" v-else class="size-3.5 shrink-0 text-fg-muted" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate text-fg">{{ e.label }}</span>
            <span class="shrink-0 font-mono text-[10px] text-fg-subtle">{{ e.detail }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="text-xs text-fg-subtle">{{ t('gv.rack.tray_none') }}</p>
    </section>

    <section class="gl-subcard space-y-2 p-3" @dragover="acceptDetach" @drop="onDetach">
      <h3 class="text-sm font-bold text-fg">{{ t('gv.rack.tray_unracked') }}</h3>
      <p class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.tray_unracked_hint') }}</p>
      <label class="relative block">
        <span class="sr-only">{{ t('gv.rack.tray_search') }}</span>
        <Search class="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
        <Input v-model="query" class="pl-8" :placeholder="t('gv.rack.tray_search')" />
      </label>
      <ul v-if="shownUnracked.length" class="max-h-72 space-y-1 overflow-y-auto pr-1 lg:max-h-none lg:overflow-visible">
        <li v-for="e in shownUnracked" :key="e.key">
          <button
            type="button"
            draggable="true"
            class="flex w-full cursor-grab items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-control-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent max-md:min-h-11"
            :class="placingKey === e.key && 'bg-accent/10 ring-1 ring-accent'"
            :aria-pressed="placingKey === e.key"
            :title="t('gv.rack.tray_entry_hint')"
            @click="pick(e, $event)"
            @dragstart="startDrag($event, e)"
            @dragend="endDrag"
            @dblclick="emit('open', e.key)"
          >
            <GripVertical class="size-3.5 shrink-0 text-fg-subtle opacity-60" aria-hidden="true" />
            <StatusDot :state="e.online ? 'online' : 'offline'" size="sm" :label="e.online ? t('network.online') : t('network.offline')" />
            <span class="min-w-0 flex-1 truncate text-fg">{{ e.label }}</span>
            <span class="shrink-0 font-mono text-[10px] text-fg-subtle">{{ e.detail }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="text-xs text-fg-subtle">{{ t('gv.rack.tray_unracked_none') }}</p>
    </section>
  </div>
</template>
