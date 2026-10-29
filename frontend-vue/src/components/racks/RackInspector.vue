<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useDebounceFn } from '@vueuse/core';
import { AlertTriangle, ArrowRightLeft, Hand, LogOut, Minus, Pencil, Plus, RotateCcw, Trash2, Undo2, X } from 'lucide-vue-next';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import { t } from '@/i18n';
import type { RackPort } from '@/types';
import { kindOf } from './rackKinds';
import { PORT_KINDS, type PlacementIssue, type PortSide, type RackEntry } from './rackModel';

/** One cable as the selected entry sees it: its own port, the port at the other end, and the colour. */
export interface CableRow {
  id: number;
  cable: string;
  colour: string;
  ownPortId: number;
  ownNumber: number;
  peerKey: string;
  peerLabel: string;
  peerNumber: number;
}

/** A cable picked on its own, with both ends. */
export interface CableDetail {
  id: number;
  cable: string;
  colour: string;
  ends: { key: string; label: string; number: number }[];
}

export interface RackOverview {
  name: string;
  units: number;
  occupied: number;
  devices: number;
  offline: number;
  cables: number;
  issues: { key: string; label: string; reason: PlacementIssue }[];
}

/**
 * Details next to the rack. With an entry selected: what it is and where, its height, its ports (count, kind,
 * side, applied at once) and its cables. With a cable picked: both ends, type and colour. With nothing picked:
 * how full the rack is, what does not fit, and the few gestures worth knowing.
 */
const props = defineProps<{
  entry: RackEntry | null;
  /** The entry belongs to this rack (it may still have no unit) */
  inRack: boolean;
  position: string | null;
  ports: RackPort[];
  cables: CableRow[];
  colourOfPort: Record<number, string>;
  pendingPortId: number | null;
  pendingLabel: string | null;
  /** Largest height the entry can take where it sits */
  maxHeight: number;
  cable: CableDetail | null;
  swatches: string[];
  overview: RackOverview;
  /** Units where the entry can go, while it has no working place; picked here with the keyboard as well */
  targets: number[];
  /** Its unit does not work (overlap, outside the rack) */
  issue: boolean;
  /** Where the cable of each cabled port goes */
  peerOfPort: Record<number, string>;
}>();
const emit = defineEmits<{
  close: [];
  open: [];
  edit: [];
  remove: [];
  unplace: [];
  detach: [];
  place: [];
  placeAt: [unit: number];
  rename: [name: string];
  setHeight: [height: number];
  setPorts: [key: string, count: number, kind: string, side: PortSide];
  pick: [port: RackPort];
  cancelPick: [];
  hoverCable: [id: number | null];
  removeCable: [id: number];
  patchCable: [id: number, patch: { cable?: string; color?: string }];
  select: [key: string];
}>();

// ── Ports, applied as they change ────────────────────────────────────────────
const count = ref(props.ports.length);
const kind = ref(props.ports[0]?.kind ?? 'RJ45');
const side = ref<PortSide>(props.ports[0]?.side === 'rear' ? 'rear' : 'front');
watch(
  () => [props.entry?.key, props.ports.length, props.ports[0]?.kind, props.ports[0]?.side],
  () => {
    count.value = props.ports.length;
    kind.value = props.ports[0]?.kind ?? 'RJ45';
    side.value = props.ports[0]?.side === 'rear' ? 'rear' : 'front';
  },
);
/** The entry goes along, so a count still waiting when another entry gets selected lands on the right one */
const emitPorts = (key: string, n: number, k: string, s: PortSide) => emit('setPorts', key, Math.min(96, Math.max(0, Math.round(n) || 0)), k, s);
const applyCountLater = useDebounceFn(emitPorts, 450);
function applyPorts() {
  if (props.entry) emitPorts(props.entry.key, count.value, kind.value, side.value);
}
function stepCount(delta: number) {
  count.value = Math.min(96, Math.max(0, count.value + delta));
  if (props.entry) void applyCountLater(props.entry.key, count.value, kind.value, side.value);
}
function setCount(value: number) {
  count.value = value;
  applyPorts();
}
function setKind(value: string) {
  kind.value = value;
  if (count.value) applyPorts();
}
function setSide(value: PortSide) {
  side.value = value;
  if (count.value) applyPorts();
}
const PRESETS = [8, 16, 24, 48];
const pending = computed(() => props.ports.some((p) => p.id === props.pendingPortId));

// ── Name of a rack item, edited in place ─────────────────────────────────────
const naming = ref(false);
const name = ref('');
function startNaming() {
  if (props.entry?.kind !== 'item') return;
  name.value = props.entry.label;
  naming.value = true;
}
function saveName() {
  naming.value = false;
  const next = name.value.trim();
  if (next && next !== props.entry?.label) emit('rename', next);
}
watch(
  () => props.entry?.key,
  () => (naming.value = false),
);

const cableType = ref('');
watch(
  () => props.cable?.id,
  () => (cableType.value = props.cable?.cable ?? ''),
  { immediate: true },
);
function saveCableType() {
  const next = cableType.value.trim();
  if (props.cable && next && next !== props.cable.cable) emit('patchCable', props.cable.id, { cable: next });
}

const free = computed(() => Math.max(0, props.overview.units - props.overview.occupied));

/** Placing: in the store, in another rack or none, or on a unit that does not work */
const needsPlace = computed(() => Boolean(props.entry && (props.entry.unit === null || !props.inRack || props.issue)));
const target = ref<number | null>(null);
watch(
  () => props.targets.join(','),
  () => (target.value = props.targets[0] ?? null),
  { immediate: true },
);
const targetOptions = computed(() => props.targets.map((unit) => ({ value: unit, label: t('gv.rack.position', { unit, count: props.entry?.height ?? 1 }) })));
const fill = computed(() => Math.min(100, (props.overview.occupied / Math.max(1, props.overview.units)) * 100));
</script>

<template>
  <!-- A cable picked on its own -->
  <section v-if="cable" class="space-y-4 p-4" :aria-label="t('gv.rack.cable_title')">
    <header class="flex items-start gap-3">
      <span class="mt-1 size-3 shrink-0 rounded-full" :style="{ backgroundColor: cable.colour }" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h3 class="truncate text-sm font-bold text-fg">{{ t('gv.rack.cable_title') }}</h3>
        <p class="truncate text-xs text-fg-subtle">{{ cable.cable }}</p>
      </div>
      <Button size="icon-sm" variant="ghost" :aria-label="t('common.close')" @click="emit('close')"><X aria-hidden="true" /></Button>
    </header>
    <ul class="space-y-1">
      <li v-for="end in cable.ends" :key="end.key">
        <button type="button" class="flex w-full items-center gap-2 rounded-md border border-line bg-raised px-2.5 py-2 text-left text-sm hover:border-line-strong" @click="emit('select', end.key)">
          <span class="min-w-0 flex-1 truncate text-fg">{{ end.label }}</span>
          <span class="font-mono text-xs text-fg-muted">{{ t('gv.rack.port') }} {{ end.number }}</span>
        </button>
      </li>
    </ul>
    <label class="block space-y-1.5 text-xs font-medium text-fg">
      {{ t('gv.rack.cable_type') }}
      <Input v-model="cableType" class="h-8 text-xs" @change="saveCableType" @keydown.enter.prevent="saveCableType" />
    </label>
    <div class="space-y-1.5">
      <p class="text-xs font-medium text-fg">{{ t('gv.rack.cable_colour') }}</p>
      <div class="flex flex-wrap gap-1.5" role="group" :aria-label="t('gv.rack.cable_colour')">
        <button
          v-for="swatch in swatches"
          :key="swatch"
          type="button"
          class="size-6 rounded-full border-2 transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          :class="swatch.toLowerCase() === cable.colour.toLowerCase() ? 'border-fg' : 'border-transparent'"
          :style="{ backgroundColor: swatch }"
          :aria-label="swatch"
          :aria-pressed="swatch.toLowerCase() === cable.colour.toLowerCase()"
          @click="emit('patchCable', cable.id, { color: swatch })"
        />
      </div>
    </div>
    <Button size="sm" variant="danger-ghost" @click="emit('removeCable', cable.id)"><Trash2 aria-hidden="true" />{{ t('gv.rack.cable_remove') }}</Button>
  </section>

  <!-- An entry -->
  <section v-else-if="entry" class="space-y-5 p-4" :aria-label="entry.label">
    <header class="flex items-start gap-3">
      <span v-if="entry.kind === 'device'" class="mt-1.5 size-2 shrink-0 rounded-full" :class="entry.online ? 'bg-accent' : 'bg-danger'" aria-hidden="true" />
      <component :is="kindOf(entry.itemKind ?? 'other').icon" v-else class="mt-0.5 size-4 shrink-0 text-fg-muted" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <form v-if="naming" @submit.prevent="saveName">
          <Input v-model="name" class="h-8 text-sm font-bold" autofocus :aria-label="t('gv.rack.item_name')" @blur="saveName" @keydown.esc.stop="naming = false" />
        </form>
        <h3 v-else class="flex min-w-0 items-center gap-1.5 text-sm font-bold text-fg">
          <span class="truncate">{{ entry.label }}</span>
          <button v-if="entry.kind === 'item'" type="button" class="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg" :aria-label="t('gv.rack.rename')" :title="t('gv.rack.rename')" @click="startNaming">
            <Pencil class="size-3" aria-hidden="true" />
          </button>
        </h3>
        <p class="truncate font-mono text-xs text-fg-subtle">
          {{ entry.kind === 'device' ? entry.detail : t(`gv.rack.kind_${entry.itemKind ?? 'other'}`) }}
          · {{ position ?? (inRack ? t('gv.rack.not_placed') : t('gv.rack.no_rack')) }}
        </p>
      </div>
      <Button size="icon-sm" variant="ghost" :aria-label="t('common.close')" @click="emit('close')"><X aria-hidden="true" /></Button>
    </header>

    <div class="flex flex-wrap gap-1.5">
      <Button size="sm" @click="entry.kind === 'device' ? emit('open') : emit('edit')">
        <Pencil aria-hidden="true" />{{ entry.kind === 'device' ? t('gv.rack.open_device') : t('gv.rack.edit_item') }}
      </Button>
      <Button v-if="needsPlace" size="sm" variant="primary" @click="emit('place')"><Hand aria-hidden="true" />{{ issue ? t('gv.racks.find_free') : t('gv.rack.place') }}</Button>
      <Button v-else size="sm" @click="emit('unplace')"><Undo2 aria-hidden="true" />{{ t('gv.rack.unplace') }}</Button>
      <Button v-if="entry.kind === 'device' && inRack" size="sm" variant="ghost" @click="emit('detach')"><LogOut aria-hidden="true" />{{ t('gv.rack.detach') }}</Button>
      <Button v-if="entry.kind === 'item'" size="icon-sm" variant="danger-ghost" :aria-label="t('gv.rack.delete_item')" :title="t('gv.rack.delete_item')" @click="emit('remove')"><Trash2 aria-hidden="true" /></Button>
    </div>

    <div v-if="needsPlace && targets.length" class="flex items-end gap-2">
      <label class="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-fg">
        {{ t('gv.rack.place_on') }}
        <Select v-model="target" :options="targetOptions" />
      </label>
      <Button
        size="sm"
        :disabled="target === null"
        :aria-label="target !== null ? t('gv.rack.place_at', { label: entry.label, unit: target }) : undefined"
        @click="target !== null && emit('placeAt', target)"
      >
        {{ t('gv.rack.place_go') }}
      </Button>
    </div>
    <p v-else-if="needsPlace" class="text-xs text-warn-text">{{ t('gv.racks.no_free') }}</p>

    <div v-if="inRack" class="flex items-center justify-between gap-3">
      <span class="text-xs font-medium text-fg">{{ t('gv.rack.item_height') }}</span>
      <div class="rack-stepper" role="group" :aria-label="t('gv.rack.item_height')">
        <button type="button" :disabled="entry.height <= 1" :aria-label="t('gv.rack.less')" @click="emit('setHeight', entry.height - 1)"><Minus class="size-3.5" aria-hidden="true" /></button>
        <span class="font-mono text-sm text-fg tabular">{{ t('gv.rack.units_label', { count: entry.height }) }}</span>
        <button type="button" :disabled="entry.height >= maxHeight" :title="entry.height >= maxHeight ? t('gv.rack.height_blocked') : undefined" :aria-label="t('gv.rack.more')" @click="emit('setHeight', entry.height + 1)">
          <Plus class="size-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div class="space-y-3">
      <div class="flex items-center justify-between gap-3">
        <h4 class="text-xs font-semibold text-fg">{{ t('gv.rack.ports_title') }}</h4>
        <div class="rack-stepper" role="group" :aria-label="t('gv.rack.ports_count')">
          <button type="button" :disabled="count <= 0" :aria-label="t('gv.rack.less')" @click="stepCount(-1)"><Minus class="size-3.5" aria-hidden="true" /></button>
          <span class="min-w-8 text-center font-mono text-sm text-fg tabular">{{ count }}</span>
          <button type="button" :disabled="count >= 96" :aria-label="t('gv.rack.more')" @click="stepCount(1)"><Plus class="size-3.5" aria-hidden="true" /></button>
        </div>
      </div>
      <div class="flex flex-wrap gap-1" role="group" :aria-label="t('gv.rack.ports_presets')">
        <button v-for="n in PRESETS" :key="n" type="button" class="rack-chip-btn" :class="count === n && 'is-on'" :aria-pressed="count === n" @click="setCount(n)">{{ n }}</button>
      </div>
      <div class="flex flex-wrap gap-1" role="group" :aria-label="t('gv.rack.ports_kind')">
        <button v-for="k in PORT_KINDS" :key="k" type="button" class="rack-chip-btn" :class="kind === k && 'is-on'" :aria-pressed="kind === k" @click="setKind(k)">{{ k }}</button>
      </div>
      <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.rack.side_label')">
        <button
          v-for="s in (['front', 'rear'] as const)"
          :key="s"
          type="button"
          class="h-7 flex-1 rounded-sm text-xs font-semibold transition-colors"
          :class="side === s ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="side === s"
          @click="setSide(s)"
        >
          {{ t(`gv.rack.side_${s}`) }}
        </button>
      </div>

      <div v-if="ports.length" class="flex flex-wrap gap-1" role="group" :aria-label="t('gv.rack.entry_ports', { label: entry.label })">
        <button
          v-for="port in ports"
          :key="port.id"
          type="button"
          class="rack-port"
          :class="[colourOfPort[port.id] && 'is-cabled', pendingPortId === port.id && 'is-pending']"
          :style="colourOfPort[port.id] ? { '--plug': colourOfPort[port.id] } : undefined"
          :aria-label="`${t('gv.rack.port')} ${port.number}, ${port.kind}, ${peerOfPort[port.id] ?? t('gv.rack.ports_free')}`"
          :title="peerOfPort[port.id]"
          :aria-pressed="pendingPortId === port.id"
          @click="emit('pick', port)"
        >
          {{ port.number }}
        </button>
      </div>
      <p v-if="pendingPortId !== null" class="flex items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-2.5 py-2 text-xs text-warn-text" aria-live="polite">
        <span class="min-w-0 flex-1">{{ pending ? t('gv.rack.pending_here') : t('gv.rack.pending_elsewhere', { label: pendingLabel ?? '' }) }}</span>
        <button type="button" class="inline-flex size-6 shrink-0 items-center justify-center rounded-md hover:bg-control-hover" :aria-label="t('gv.rack.pending_cancel')" :title="t('gv.rack.pending_cancel')" @click="emit('cancelPick')">
          <X class="size-3.5" aria-hidden="true" />
        </button>
      </p>
      <p v-else-if="ports.length" class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.ports_hint_drag') }}</p>
    </div>

    <div class="space-y-2">
      <h4 class="text-xs font-semibold text-fg">{{ t('gv.rack.cables_title') }}</h4>
      <ul v-if="cables.length" class="divide-y divide-line" @pointerleave="emit('hoverCable', null)">
        <li v-for="c in cables" :key="c.id" class="flex items-center gap-2 py-1.5 text-xs" @pointerenter="emit('hoverCable', c.id)">
          <span class="size-2.5 shrink-0 rounded-full" :style="{ backgroundColor: c.colour }" aria-hidden="true" />
          <button type="button" class="min-w-0 flex-1 truncate text-left text-fg hover:underline" @click="emit('select', c.peerKey)">
            <span class="font-mono">{{ c.ownNumber }}</span> → {{ c.peerLabel }} <span class="font-mono text-fg-muted">· {{ c.peerNumber }}</span>
            <span class="block truncate text-fg-subtle">{{ c.cable }}</span>
          </button>
          <button type="button" class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-danger-text max-md:size-11" :aria-label="t('gv.rack.cable_remove')" :title="t('gv.rack.cable_remove')" @click="emit('removeCable', c.id)">
            <Trash2 class="size-3.5" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <p v-else class="text-xs text-fg-subtle">{{ t('gv.rack.cables_none') }}</p>
    </div>
  </section>

  <!-- Nothing picked: the rack at a glance -->
  <section v-else class="space-y-5 p-4" :aria-label="overview.name">
    <div class="space-y-2">
      <div class="flex items-baseline justify-between gap-3">
        <h3 class="truncate text-sm font-bold text-fg">{{ overview.name }}</h3>
        <p class="shrink-0 font-mono text-xs text-fg-muted tabular"><span class="text-base font-semibold text-fg">{{ overview.occupied }}</span> / {{ t('gv.rack.units_label', { count: overview.units }) }}</p>
      </div>
      <div class="h-1.5 overflow-hidden rounded-full bg-sunken" role="progressbar" :aria-label="t('rack.occupied')" aria-valuemin="0" :aria-valuemax="overview.units" :aria-valuenow="overview.occupied">
        <div class="rack-fill h-full rounded-full bg-accent" :style="{ width: `${fill}%` }" />
      </div>
      <p class="text-xs text-fg-subtle">
        {{ t('gv.racks.free', { count: free }) }} · {{ t('gv.rack.overview_devices', { count: overview.devices }) }} · {{ t('gv.rack.overview_cables', { count: overview.cables }) }}
      </p>
    </div>

    <div v-if="overview.issues.length" class="space-y-1.5 rounded-lg border border-warn/40 bg-warn/10 p-3 text-xs" role="status">
      <p class="flex items-center gap-2 font-semibold text-warn-text"><AlertTriangle class="size-4" aria-hidden="true" />{{ t('gv.racks.issues', { count: overview.issues.length }) }}</p>
      <ul class="space-y-1">
        <li v-for="i in overview.issues" :key="i.key">
          <button type="button" class="text-left text-fg underline-offset-2 hover:underline" @click="emit('select', i.key)">{{ i.label }}: {{ t(`gv.racks.issue_${i.reason}`) }}</button>
        </li>
      </ul>
    </div>

    <ul class="space-y-2.5 text-xs leading-snug text-fg-muted">
      <li class="flex gap-2.5"><Hand class="mt-px size-3.5 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.rack.howto_move') }}</li>
      <li class="flex gap-2.5"><Plus class="mt-px size-3.5 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.rack.howto_add') }}</li>
      <li class="flex gap-2.5"><ArrowRightLeft class="mt-px size-3.5 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.rack.howto_cable') }}</li>
      <li class="flex gap-2.5"><RotateCcw class="mt-px size-3.5 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.rack.howto_side') }}</li>
    </ul>

    <div class="space-y-1.5 border-t border-line pt-4 text-xs text-fg-subtle">
      <p class="flex items-center gap-2">
        <svg width="28" height="8" aria-hidden="true"><path d="M2 4 H26" stroke="var(--line-1)" stroke-width="3" stroke-linecap="round" /></svg>{{ t('gv.rack.legend_cable') }}
      </p>
      <p class="flex items-center gap-2">
        <svg width="28" height="8" aria-hidden="true"><path d="M2 4 H26" stroke="var(--line-3)" stroke-width="3" stroke-linecap="round" stroke-dasharray="5 4" /></svg>{{ t('gv.rack.legend_stub') }}
      </p>
    </div>
  </section>
</template>

<style scoped>
.rack-stepper {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem;
  border: 1px solid var(--gl-line);
  border-radius: 8px;
  background: var(--gl-sunken);
}
.rack-stepper button {
  display: inline-flex;
  width: 1.75rem;
  height: 1.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--gl-fg-muted);
  transition:
    background-color 120ms,
    color 120ms,
    transform 120ms var(--ease-out-expo);
}
.rack-stepper button:hover:not(:disabled) {
  background: var(--gl-control-hover);
  color: var(--gl-fg);
}
.rack-stepper button:active:not(:disabled) {
  transform: scale(0.9);
}
.rack-stepper button:disabled {
  opacity: 0.35;
}
.rack-chip-btn {
  height: 1.625rem;
  padding: 0 0.5rem;
  border: 1px solid var(--gl-line);
  border-radius: 6px;
  color: var(--gl-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  transition:
    border-color 120ms,
    color 120ms,
    background-color 120ms;
}
.rack-chip-btn:hover {
  border-color: var(--gl-line-strong);
  color: var(--gl-fg);
}
.rack-chip-btn.is-on {
  border-color: var(--gl-accent);
  background: color-mix(in oklab, var(--gl-accent) 14%, transparent);
  color: var(--gl-accent-text);
}
.rack-port {
  display: inline-flex;
  width: 1.75rem;
  height: 1.75rem;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--gl-line);
  border-radius: 4px;
  color: var(--gl-fg-muted);
  font-family: var(--font-mono);
  font-size: var(--text-micro);
  font-weight: 600;
  transition:
    border-color 120ms,
    transform 140ms var(--ease-out-expo);
  animation: rack-port-in 260ms var(--ease-out-expo) both;
}
.rack-port:hover {
  border-color: var(--gl-accent);
  color: var(--gl-fg);
}
.rack-port.is-cabled {
  border-color: var(--plug);
  background: var(--plug);
  /* Sign ink on a full cable colour, as on the network signs */
  color: #0c0f14;
}
.rack-port.is-pending {
  transform: scale(1.12);
  box-shadow: 0 0 0 2px var(--gl-warn);
}
.rack-port:focus-visible {
  outline: 2px solid var(--gl-accent);
  outline-offset: 1px;
}
@keyframes rack-port-in {
  from {
    opacity: 0;
    transform: scale(0.6);
  }
}
.rack-fill {
  transition: width 420ms var(--ease-out-expo);
}
</style>
