<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Pencil, Trash2, X } from 'lucide-vue-next';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import { t } from '@/i18n';
import type { RackPort } from '@/types';
import { PORT_KINDS, type PortSide, type RackEntry } from './rackModel';

/** One cable as the selected entry sees it: its own port, the port at the other end, and the colour. */
export interface CableRow {
  id: number;
  cable: string;
  colour: string;
  ownPortId: number;
  ownNumber: number;
  peerLabel: string;
  peerNumber: number;
}

const props = defineProps<{
  entry: RackEntry;
  /** The entry's ports, in order */
  ports: RackPort[];
  cables: CableRow[];
  /** Colour of the cable on each cabled port */
  colourOfPort: Record<number, string>;
  /** Port chosen as the start of a new cable, on any entry */
  pendingPortId: number | null;
  pendingLabel: string | null;
  /** Where the entry sits, for the subtitle; null while it is in the tray */
  position: string | null;
}>();
const emit = defineEmits<{
  setPorts: [count: number, kind: string, side: PortSide];
  pick: [port: RackPort];
  cancel: [];
  removeCable: [id: number];
  open: [];
  remove: [];
}>();

const count = ref(props.ports.length);
const kind = ref(props.ports[0]?.kind ?? 'RJ45');
const side = ref<PortSide>((props.ports[0]?.side as PortSide | undefined) ?? 'front');
watch(
  () => [props.entry.key, props.ports.length, props.ports[0]?.kind],
  () => {
    count.value = props.ports.length;
    kind.value = props.ports[0]?.kind ?? 'RJ45';
    side.value = (props.ports[0]?.side as PortSide | undefined) ?? 'front';
  },
);

const kindOptions = PORT_KINDS.map((k) => ({ value: k, label: k }));
const sideOptions = [
  { value: 'front', label: t('gv.rack.side_front') },
  { value: 'rear', label: t('gv.rack.side_rear') },
];
const pending = computed(() => props.ports.some((p) => p.id === props.pendingPortId));

function apply() {
  emit('setPorts', Math.min(96, Math.max(0, Math.round(count.value) || 0)), kind.value, side.value);
}
</script>

<template>
  <section class="gl-subcard space-y-4 p-4" :aria-label="entry.label">
    <header class="flex items-start gap-3">
      <div class="min-w-0 flex-1">
        <h3 class="truncate text-sm font-bold text-fg">{{ entry.label }}</h3>
        <p class="truncate font-mono text-xs text-fg-subtle">
          {{ entry.kind === 'device' ? entry.detail : t(`gv.rack.kind_${entry.itemKind ?? 'other'}`) }}
          <span v-if="position"> · {{ position }}</span>
          <span v-else> · {{ t('gv.rack.not_placed') }}</span>
        </p>
      </div>
      <div class="flex shrink-0 gap-1">
        <Button size="sm" @click="emit('open')">
          <Pencil aria-hidden="true" />{{ entry.kind === 'device' ? t('gv.rack.open_device') : t('gv.rack.edit_item') }}
        </Button>
        <Button v-if="entry.kind === 'item'" size="icon-sm" variant="danger-ghost" :aria-label="t('gv.rack.delete_item')" :title="t('gv.rack.delete_item')" @click="emit('remove')">
          <Trash2 aria-hidden="true" />
        </Button>
      </div>
    </header>

    <form class="flex flex-wrap items-end gap-2" @submit.prevent="apply">
      <label class="flex w-24 flex-col gap-1 text-xs font-medium text-fg">
        {{ t('gv.rack.ports_count') }}
        <Input :model-value="count" type="number" min="0" max="96" mono @update:model-value="(v) => (count = Number(v))" />
      </label>
      <label class="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-fg">
        {{ t('gv.rack.ports_kind') }}
        <Select v-model="kind" :options="kindOptions" />
      </label>
      <label class="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-fg">
        {{ t('gv.rack.side_label') }}
        <Select v-model="side" :options="sideOptions" />
      </label>
      <Button size="sm" type="submit">{{ t('gv.rack.ports_apply') }}</Button>
    </form>

    <div v-if="ports.length" class="space-y-3">
      <div class="flex flex-wrap gap-1.5" role="group" :aria-label="t('gv.rack.ports_title')">
        <button
          v-for="port in ports"
          :key="port.id"
          type="button"
          class="flex size-7 items-center justify-center rounded-[4px] border font-mono text-xs font-semibold tabular transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          :class="[
            colourOfPort[port.id] ? 'text-[#0c0f14]' : 'border-line text-fg-muted hover:border-accent hover:text-fg',
            pendingPortId === port.id && 'ring-2 ring-warn ring-offset-2 ring-offset-surface',
          ]"
          :style="colourOfPort[port.id] ? { backgroundColor: colourOfPort[port.id], borderColor: colourOfPort[port.id] } : undefined"
          :aria-label="`${t('gv.rack.port')} ${port.number}, ${port.kind}, ${colourOfPort[port.id] ? t('gv.rack.ports_cabled') : t('gv.rack.ports_free')}`"
          :aria-pressed="pendingPortId === port.id"
          :title="`${port.kind} · ${colourOfPort[port.id] ? t('gv.rack.ports_cabled') : t('gv.rack.ports_free')}`"
          @click="emit('pick', port)"
        >
          {{ port.number }}
        </button>
      </div>

      <p v-if="pendingPortId !== null" class="flex items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-2.5 py-2 text-xs text-warn-text" aria-live="polite">
        <span class="min-w-0 flex-1">{{ pending ? t('gv.rack.pending_here') : t('gv.rack.pending_elsewhere', { label: pendingLabel ?? '' }) }}</span>
        <button type="button" class="inline-flex size-6 shrink-0 items-center justify-center rounded-md hover:bg-control-hover" :aria-label="t('gv.rack.pending_cancel')" :title="t('gv.rack.pending_cancel')" @click="emit('cancel')">
          <X class="size-3.5" aria-hidden="true" />
        </button>
      </p>
      <p v-else class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.ports_hint') }}</p>
    </div>
    <p v-else class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.ports_none') }}</p>

    <div class="space-y-2">
      <h4 class="text-xs font-semibold text-fg">{{ t('gv.rack.cables_title') }}</h4>
      <ul v-if="cables.length" class="divide-y divide-line">
        <li v-for="c in cables" :key="c.id" class="flex items-center gap-2 py-2 text-xs">
          <span class="size-2.5 shrink-0 rounded-full" :style="{ backgroundColor: c.colour }" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-fg">
            <span class="font-mono">{{ c.ownNumber }}</span> → {{ c.peerLabel }} <span class="font-mono text-fg-muted">· {{ c.peerNumber }}</span>
            <span class="block truncate text-fg-subtle">{{ c.cable }}</span>
          </span>
          <button type="button" class="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-danger-text" :aria-label="t('gv.rack.cable_remove')" :title="t('gv.rack.cable_remove')" @click="emit('removeCable', c.id)">
            <Trash2 class="size-3.5" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <p v-else class="text-xs text-fg-subtle">{{ t('gv.rack.cables_none') }}</p>
    </div>
  </section>
</template>
