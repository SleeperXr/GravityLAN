<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { GridStack, type GridStackNode } from 'gridstack';
import 'gridstack/dist/gridstack.min.css';
import { ChevronDown, ChevronUp } from 'lucide-vue-next';
import type { Device, DeviceGroup } from '@/types';
import { gridItemAttrs } from '@shared/components/Dashboard/overview/layout';
import DeviceCard from './DeviceCard.vue';
import DeviceList from './DeviceList.vue';
import { t } from '@/i18n';

/**
 * One group of the overview. Grid view: a GridStack (positions shared with the React UI);
 * static outside edit mode, in edit mode tiles move, resize and move to other groups.
 */
const props = defineProps<{
  group: DeviceGroup | null;
  devices: Device[];
  isFirst: boolean;
  isLast: boolean;
  collapsed: boolean;
  editMode: boolean;
  viewMode: 'grid' | 'list';
  selectedIds: Set<number>;
}>();

const emit = defineEmits<{
  toggle: [];
  move: [direction: 'up' | 'down'];
  select: [id: number, selected: boolean];
  edit: [device: Device];
  refresh: [];
  /** a tile was moved or resized inside this group */
  tileChange: [id: number, layout: { x?: number; y?: number; w?: number; h?: number }];
  /** a tile was dropped here from another group */
  tileMoved: [id: number, groupId: number | null, layout: { x?: number; y?: number; w?: number; h?: number }];
}>();

const gridEl = ref<HTMLElement | null>(null);
let grid: GridStack | null = null;
const groupId = computed(() => (props.group ? props.group.id : null));
const sectionId = computed(() => `group-${props.group ? props.group.id : 'none'}`);

const layoutKey = computed(() => props.devices.map((d) => `${d.id}:${d.w}:${d.h}:${d.x}:${d.y}`).join(','));

function destroy() {
  try {
    grid?.destroy(false);
  } catch {
    // already gone
  }
  grid = null;
}

const tileId = (el: Element | undefined) => parseInt(el?.getAttribute('gs-id') || '0', 10);

async function init() {
  destroy();
  if (props.collapsed || props.viewMode !== 'grid' || props.devices.length === 0) return;
  await nextTick();
  if (!gridEl.value) return;
  grid = GridStack.init(
    {
      column: 12,
      cellHeight: 50,
      margin: 6,
      float: true,
      staticGrid: !props.editMode,
      alwaysShowResizeHandle: props.editMode,
      resizable: { handles: 'se' },
      acceptWidgets: true,
      // Whole tile drags in edit mode; outside it the grid is static anyway.
      // No column breakpoints: positions are shared with the React UI's 12-column grid,
      // so phones get the list view instead of a re-flowed grid.
    },
    gridEl.value,
  );

  if (props.editMode) {
    grid.on('dropped', (_event: Event, previous: GridStackNode | undefined, dropped: GridStackNode) => {
      const el = dropped?.el;
      const id = tileId(el);
      const home = previous?.grid?.el;
      if (!el || !id || !home || !grid) return;
      // Vue rendered this tile in the old group: hand the element back, hidden, and let the
      // reload after saving render it in its new group.
      grid.removeWidget(el, false);
      el.style.display = 'none';
      home.appendChild(el);
      emit('tileMoved', id, groupId.value, { x: dropped.x, y: dropped.y, w: dropped.w, h: dropped.h });
    });
    const save = (_event: Event, el: HTMLElement) => {
      const node = (el as HTMLElement & { gridstackNode?: GridStackNode }).gridstackNode;
      const id = tileId(el);
      if (node && id) emit('tileChange', id, { x: node.x, y: node.y, w: node.w, h: node.h });
    };
    grid.on('dragstop', save);
    grid.on('resizestop', save);
  } else if (props.devices.some((d) => d.x === null)) {
    // Tiles without a saved position get one compact pass
    grid.batchUpdate();
    grid.compact();
    grid.batchUpdate(false);
  }
}

/** Close the gaps between tiles. */
function compact() {
  if (!grid) return;
  grid.float(false);
  grid.compact();
  grid.float(true);
}

watch(() => [layoutKey.value, props.editMode, props.collapsed, props.viewMode], () => void init(), { immediate: true, flush: 'post' });
onBeforeUnmount(destroy);
defineExpose({ compact });
</script>

<template>
  <section :aria-labelledby="`${sectionId}-title`" class="space-y-3">
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left"
        :aria-expanded="!collapsed"
        :aria-controls="`${sectionId}-body`"
        @click="emit('toggle')"
      >
        <ChevronDown class="size-4 shrink-0 text-fg-subtle transition-transform duration-200" :class="collapsed && '-rotate-90'" aria-hidden="true" />
        <h2 :id="`${sectionId}-title`" class="truncate text-sm font-semibold text-fg">
          {{ group ? group.name : t('dashboard.unassigned_devices') }}
        </h2>
        <span class="rounded-sm bg-raised px-1.5 font-mono text-[11px] text-fg-subtle tabular">{{ devices.length }}</span>
      </button>
      <div v-if="editMode && group" class="flex gap-1">
        <button
          type="button"
          class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg disabled:opacity-30"
          :disabled="isFirst"
          :aria-label="t('dashboard.move_group_up')"
          :title="t('dashboard.move_group_up')"
          @click="emit('move', 'up')"
        >
          <ChevronUp class="size-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg disabled:opacity-30"
          :disabled="isLast"
          :aria-label="t('dashboard.move_group_down')"
          :title="t('dashboard.move_group_down')"
          @click="emit('move', 'down')"
        >
          <ChevronDown class="size-4" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-show="!collapsed" :id="`${sectionId}-body`">
      <div
        v-if="viewMode === 'grid'"
        ref="gridEl"
        class="grid-stack gl-grid"
        :class="editMode && 'is-editing'"
        :style="{ minHeight: devices.length > 0 ? '140px' : '0' }"
      >
        <div
          v-for="device in devices"
          :key="device.id"
          class="grid-stack-item"
          :gs-id="device.id"
          :gs-x="gridItemAttrs(device).x"
          :gs-y="gridItemAttrs(device).y"
          :gs-w="gridItemAttrs(device).w"
          :gs-h="gridItemAttrs(device).h"
          gs-min-w="2"
          gs-min-h="2"
          :gs-auto-position="gridItemAttrs(device).autoPosition ? 'true' : undefined"
        >
          <div class="grid-stack-item-content group/tile">
            <DeviceCard
              :device="device"
              :edit-mode="editMode"
              :selected="selectedIds.has(device.id)"
              @select="(value) => emit('select', device.id, value)"
              @edit="emit('edit', device)"
              @refresh="emit('refresh')"
            />
          </div>
        </div>
      </div>
      <DeviceList v-else :devices="devices" @edit="(device) => emit('edit', device)" />
    </div>
  </section>
</template>

<style>
.gl-grid.is-editing {
  border-radius: var(--radius-lg);
  outline: 1px dashed var(--gl-line-strong);
  outline-offset: 4px;
  background-image: radial-gradient(var(--gl-line-strong) 1px, transparent 1px);
  background-size: calc(100% / 12) 50px;
}
.gl-grid .grid-stack-item-content {
  overflow: visible !important;
}
.gl-grid .grid-stack-placeholder > .placeholder-content {
  border: 1px dashed var(--gl-accent);
  border-radius: var(--radius-lg);
  background: color-mix(in oklab, var(--gl-accent) 8%, transparent);
}
.gl-grid .ui-resizable-se {
  opacity: 0.6;
}
</style>
