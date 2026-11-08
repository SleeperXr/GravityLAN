<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { GridStack, type GridStackNode } from 'gridstack';
import 'gridstack/dist/gridstack.min.css';
import { ChevronDown, ChevronUp } from 'lucide-vue-next';
import type { Device, DeviceGroup } from '@/types';
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
  filtering?: boolean;
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

/** Uniform default height for unsized tiles in this group so every card in a row lines up cleanly. */
const groupDefaultH = computed(() => {
  if (props.devices.some((d) => d.has_agent)) return 5;
  if (props.devices.some((d) => (d.services?.length ?? 0) > 0)) return 3;
  return 3;
});

function tileAttrs(device: Device) {
  const hasSavedPos = !props.filtering && device.x != null && device.y != null;
  return {
    x: hasSavedPos ? device.x : undefined,
    y: hasSavedPos ? device.y : undefined,
    w: device.w ?? 4,
    h: device.h ?? groupDefaultH.value,
    autoPosition: !hasSavedPos,
  };
}

const layoutKey = computed(
  () => `${props.filtering ? 'f' : 'n'}|${props.devices.map((d) => `${d.id}:${d.w ?? 4}:${d.h ?? groupDefaultH.value}:${d.x}:${d.y}`).join(',')}`,
);

function destroy() {
  try {
    grid?.destroy(false);
  } catch (err) {
    // GridStack may throw during teardown if container DOM nodes were already detached by Vue.
    console.debug('[GroupSection] GridStack destroy failed:', err);
  }
  grid = null;
}

const tileId = (el: Element | undefined) => parseInt(el?.getAttribute('gs-id') || '0', 10);

const POSITION_STYLES = ['top', 'left', 'right', 'width', 'height', 'display'] as const;

function setOrRemoveAttr(el: HTMLElement, name: string, value: string | undefined) {
  if (value !== undefined) {
    el.setAttribute(name, value);
  } else {
    el.removeAttribute(name);
  }
}

function syncItemElement(itemEl: HTMLElement, dev: Device) {
  const attrs = tileAttrs(dev);
  for (const prop of POSITION_STYLES) {
    itemEl.style.removeProperty(prop);
  }
  setOrRemoveAttr(itemEl, 'gs-x', attrs.x !== undefined ? String(attrs.x) : undefined);
  setOrRemoveAttr(itemEl, 'gs-y', attrs.y !== undefined ? String(attrs.y) : undefined);
  itemEl.setAttribute('gs-w', String(attrs.w));
  itemEl.setAttribute('gs-h', String(attrs.h));
  itemEl.setAttribute('gs-min-w', '2');
  itemEl.setAttribute('gs-min-h', '2');
  setOrRemoveAttr(itemEl, 'gs-auto-position', attrs.autoPosition ? 'true' : undefined);
}

function syncGridItemElements(container: HTMLElement) {
  const byId = new Map(props.devices.map((d) => [d.id, d]));
  for (const itemEl of container.querySelectorAll<HTMLElement>('.grid-stack-item')) {
    const dev = byId.get(tileId(itemEl));
    if (dev) {
      syncItemElement(itemEl, dev);
    }
  }
}

function setupEditListeners(instance: GridStack) {
  instance.on('dropped', (_event: Event, previous: GridStackNode | undefined, dropped: GridStackNode) => {
    const el = dropped?.el;
    const id = tileId(el);
    const home = previous?.grid?.el;
    if (!el || !id) return;
    if (!home || !grid) return;

    // Vue rendered this tile in the old group: hand the element back, hidden, and let the
    // reload after saving render it in its new group.
    instance.removeWidget(el, false);
    el.style.display = 'none';
    home.appendChild(el);
    emit('tileMoved', id, groupId.value, { x: dropped.x, y: dropped.y, w: dropped.w, h: dropped.h });
  });

  const save = (_event: Event, el: HTMLElement) => {
    const node = (el as HTMLElement & { gridstackNode?: GridStackNode }).gridstackNode;
    const id = tileId(el);
    if (node && id) {
      emit('tileChange', id, { x: node.x, y: node.y, w: node.w, h: node.h });
    }
  };

  instance.on('dragstop', save);
  instance.on('resizestop', save);
}

function applyCompactLayout(instance: GridStack) {
  instance.float(false);
  instance.compact();
  if (!props.filtering) {
    instance.float(true);
  }
}

async function init() {
  destroy();
  if (props.collapsed || props.viewMode !== 'grid' || props.devices.length === 0) return;
  await nextTick();
  if (!gridEl.value) return;

  // GridStack mutates gs-* attributes and inline positioning styles directly on reused DOM nodes.
  // Synchronize each item element from Vue state before initializing GridStack so filtered subsets
  // never inherit stale row/column coordinates from the unfiltered grid.
  syncGridItemElements(gridEl.value);

  grid = GridStack.init(
    {
      column: 12,
      cellHeight: 50,
      margin: 6,
      float: !props.filtering,
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
    setupEditListeners(grid);
  } else if (props.filtering || props.devices.some((d) => d.x === null)) {
    // Filtered views and tiles without a saved position get a top-gravity compact pass
    applyCompactLayout(grid);
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
        class="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left max-md:min-h-11"
        :aria-expanded="!collapsed"
        :aria-controls="`${sectionId}-body`"
        @click="emit('toggle')"
      >
        <ChevronDown class="size-4 shrink-0 text-fg-subtle transition-transform duration-200" :class="collapsed && '-rotate-90'" aria-hidden="true" />
        <h2 :id="`${sectionId}-title`" class="truncate text-sm font-semibold text-fg">
          {{ group ? group.name : t('dashboard.unassigned_devices') }}
        </h2>
        <span class="rounded-sm bg-raised px-1.5 font-mono text-micro text-fg-subtle tabular">{{ devices.length }}</span>
      </button>
      <div v-if="editMode && group" class="flex gap-1">
        <button
          type="button"
          class="inline-flex size-7 max-md:size-11 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg disabled:opacity-30"
          :disabled="isFirst"
          :aria-label="t('dashboard.move_group_up')"
          :title="t('dashboard.move_group_up')"
          @click="emit('move', 'up')"
        >
          <ChevronUp class="size-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="inline-flex size-7 max-md:size-11 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg disabled:opacity-30"
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
          :gs-x="tileAttrs(device).x"
          :gs-y="tileAttrs(device).y"
          :gs-w="tileAttrs(device).w"
          :gs-h="tileAttrs(device).h"
          gs-min-w="2"
          gs-min-h="2"
          :gs-auto-position="tileAttrs(device).autoPosition ? 'true' : undefined"
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
