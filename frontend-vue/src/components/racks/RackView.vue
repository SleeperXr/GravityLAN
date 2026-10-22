<script setup lang="ts">
import { computed, onMounted, ref, useId } from 'vue';
import { AlertTriangle, Loader2, Plus, Server, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, Rack } from '@/types';
import Button from '@/components/ui/Button.vue';
import Dialog from '@/components/ui/Dialog.vue';
import Input from '@/components/ui/Input.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { deviceLabel, networkColor } from '@/lib/networks';
import { heightOf, occupiedUnits, placementIssues, rackSlots } from './rackModel';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Racks with the devices placed in them (rack, top unit and height are set in the device
 * editor). Each device carries its network's line colour; a click opens the editor.
 */
const props = defineProps<{ devices: Device[] }>();
const emit = defineEmits<{ openDevice: [device: Device]; changed: [] }>();
const { showToast } = useToast();
const id = useId();

const racks = ref<Rack[]>([]);
const selectedId = ref<number | null>(null);
const loading = ref(true);

async function load(select?: number) {
  try {
    const data = await api.getRacks();
    racks.value = Array.isArray(data) ? data : [];
    const keep = select ?? selectedId.value;
    selectedId.value = racks.value.some((r) => r.id === keep) ? keep : (racks.value[0]?.id ?? null);
  } catch (err) {
    showToast('error', t('topology.tab_rack'), (err as Error).message);
  } finally {
    loading.value = false;
  }
}
onMounted(() => load());

const rack = computed(() => racks.value.find((r) => r.id === selectedId.value) ?? null);
const rackDevices = computed(() => (rack.value ? props.devices.filter((d) => d.rack_id === rack.value!.id) : []));
const slots = computed(() => (rack.value ? rackSlots(rack.value.units, rackDevices.value) : []));
const occupied = computed(() => occupiedUnits(rackDevices.value));
const issues = computed(() => (rack.value ? placementIssues(rack.value.units, rackDevices.value) : []));
const issueIds = computed(() => new Set(issues.value.map((i) => i.device.id)));
const inventory = computed(() => [...rackDevices.value].sort((a, b) => (b.rack_unit ?? 0) - (a.rack_unit ?? 0)));

// ── Create / delete ──────────────────────────────────────────────────────────
const creating = ref(false);
const form = ref({ name: '', units: 42, width: 19 });
const saving = ref(false);

function openCreate() {
  form.value = { name: racks.value.length ? '' : 'Main Rack', units: 42, width: 19 };
  creating.value = true;
}

async function create() {
  saving.value = true;
  try {
    const created = await api.createRack({ name: form.value.name.trim() || `Rack ${racks.value.length + 1}`, units: form.value.units, width: form.value.width });
    creating.value = false;
    await load(created.id);
  } catch (err) {
    showToast('error', t('gv.racks.create'), (err as Error).message);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!rack.value) return;
  const ok = await confirmAction({
    title: t('gv.racks.delete'),
    message: t('gv.racks.delete_confirm', { name: rack.value.name, count: rackDevices.value.length }),
    confirmLabel: t('gv.racks.delete'),
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteRack(rack.value.id);
    await load();
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.racks.delete'), (err as Error).message);
  }
}

const UNIT_REM = 1.75;
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div v-if="loading" class="grid flex-1 place-items-center text-sm text-fg-muted" role="status">
      <span class="flex items-center gap-2"><Loader2 class="size-4 animate-spin" aria-hidden="true" />{{ t('rack.loading') }}</span>
    </div>

    <div v-else-if="!rack" class="grid flex-1 place-items-center p-6">
      <EmptyState :icon="Server" :title="t('rack.empty_title')" :description="t('rack.empty_desc')">
        <Button variant="primary" @click="openCreate"><Plus aria-hidden="true" />{{ t('gv.racks.new') }}</Button>
      </EmptyState>
    </div>

    <template v-else>
      <header class="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <div class="min-w-0">
          <h2 class="truncate text-base font-bold text-fg">{{ rack.name }}</h2>
          <p class="font-mono text-xs text-fg-subtle">{{ t('rack.meta', { width: rack.width, units: rack.units }) }}</p>
        </div>
        <div v-if="racks.length > 1" class="flex max-w-full overflow-x-auto rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('rack.select_rack')">
          <button
            v-for="r in racks"
            :key="r.id"
            type="button"
            class="h-7 shrink-0 rounded-sm px-3 text-xs font-semibold transition-colors"
            :class="r.id === selectedId ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="r.id === selectedId"
            @click="selectedId = r.id"
          >
            {{ r.name }}
          </button>
        </div>
        <div class="ml-auto flex gap-1">
          <Button size="sm" @click="openCreate"><Plus aria-hidden="true" />{{ t('gv.racks.new') }}</Button>
          <Button size="icon-sm" variant="danger-ghost" :aria-label="t('gv.racks.delete')" :title="t('gv.racks.delete')" @click="remove"><Trash2 aria-hidden="true" /></Button>
        </div>
      </header>

      <div class="grid min-h-0 flex-1 gap-5 overflow-y-auto p-4 lg:grid-cols-[minmax(0,28rem)_1fr]">
        <!-- The rack: rails with unit numbers, one row per unit, devices span their height -->
        <div class="rounded-lg border-[6px] border-[color-mix(in_oklab,var(--gl-line-strong)_70%,transparent)] bg-sunken p-1.5 shadow-inner" role="list" :aria-label="rack.name">
          <div v-for="slot in slots" :key="slot.unit" class="flex gap-1.5">
            <span class="w-6 shrink-0 text-right font-mono text-[10px] leading-7 text-fg-subtle tabular" aria-hidden="true">{{ slot.unit }}</span>
            <button
              v-if="slot.device"
              type="button"
              role="listitem"
              class="group relative my-px flex min-w-0 flex-1 items-center gap-2.5 overflow-hidden rounded-[5px] border bg-raised pr-3 pl-4 text-left transition-colors hover:border-line-strong hover:bg-control-hover focus-visible:border-accent"
              :class="[issueIds.has(slot.device.id) ? 'border-warn/60' : 'border-line', !slot.device.is_online && 'opacity-70']"
              :style="{ height: `calc(${heightOf(slot.device) * UNIT_REM}rem - 2px)` }"
              :title="t('gv.racks.open_hint')"
              @click="emit('openDevice', slot.device)"
            >
              <span class="absolute inset-y-0 left-0 w-1.5" :style="{ background: networkColor(slot.device.subnet_id, slot.device.ip) }" aria-hidden="true" />
              <StatusDot :state="slot.device.is_online ? 'online' : 'offline'" size="sm" :label="slot.device.is_online ? t('network.online') : t('network.offline')" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-xs font-semibold text-fg">{{ deviceLabel(slot.device) }}</span>
                <span v-if="heightOf(slot.device) > 1" class="block truncate font-mono text-[10px] text-fg-subtle">{{ slot.device.ip }} · {{ t('rack.units', { count: heightOf(slot.device) }) }}</span>
              </span>
              <span v-if="heightOf(slot.device) === 1" class="hidden font-mono text-[10px] text-fg-subtle sm:inline">{{ slot.device.ip }}</span>
              <span class="flex gap-1 opacity-60" aria-hidden="true">
                <span class="size-1 rounded-full bg-fg-subtle" /><span class="size-1 rounded-full bg-fg-subtle" />
              </span>
            </button>
            <span v-else class="my-px h-[calc(1.75rem-2px)] flex-1 rounded-[5px] border border-dashed border-line/70" aria-hidden="true" />
            <span class="w-6 shrink-0 font-mono text-[10px] leading-7 text-fg-subtle tabular" aria-hidden="true">{{ slot.unit }}</span>
          </div>
        </div>

        <aside class="space-y-4">
          <div class="gl-subcard space-y-2 p-4">
            <div class="flex items-baseline justify-between gap-3">
              <p class="gl-eyebrow">{{ t('rack.occupied') }}</p>
              <p class="font-mono text-sm text-fg tabular"><span class="text-xl font-semibold">{{ occupied }}</span> / {{ rack.units }} HE</p>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-sunken" role="progressbar" :aria-label="t('rack.occupied')" aria-valuemin="0" :aria-valuemax="rack.units" :aria-valuenow="occupied">
              <div class="h-full rounded-full bg-accent" :style="{ width: `${Math.min(100, (occupied / rack.units) * 100)}%` }" />
            </div>
            <p class="text-xs text-fg-subtle">{{ t('rack.devices') }}: <span class="font-mono text-fg">{{ rackDevices.length }}</span> · {{ t('gv.racks.free', { count: Math.max(0, rack.units - occupied) }) }}</p>
          </div>

          <div v-if="issues.length" class="space-y-2 rounded-lg border border-warn/40 bg-warn/10 p-3 text-xs" role="status">
            <p class="flex items-center gap-2 font-semibold text-warn-text"><AlertTriangle class="size-4" aria-hidden="true" />{{ t('gv.racks.issues', { count: issues.length }) }}</p>
            <ul class="space-y-1">
              <li v-for="i in issues" :key="i.device.id">
                <button type="button" class="text-left text-fg underline-offset-2 hover:underline" @click="emit('openDevice', i.device)">
                  {{ deviceLabel(i.device) }}: {{ t(`gv.racks.issue_${i.reason}`) }}
                </button>
              </li>
            </ul>
          </div>

          <div class="gl-subcard p-4">
            <h3 class="mb-2 text-sm font-bold text-fg">{{ t('rack.inventory') }}</h3>
            <p v-if="inventory.length === 0" class="text-xs leading-relaxed text-fg-subtle">{{ t('rack.inventory_empty') }}</p>
            <ul v-else class="divide-y divide-line">
              <li v-for="d in inventory" :key="d.id">
                <button type="button" class="flex w-full items-center gap-2.5 py-2 text-left hover:text-accent-text" @click="emit('openDevice', d)">
                  <span class="h-4 w-1 shrink-0 rounded-full" :style="{ background: networkColor(d.subnet_id, d.ip) }" aria-hidden="true" />
                  <StatusDot :state="d.is_online ? 'online' : 'offline'" size="sm" :label="d.is_online ? t('network.online') : t('network.offline')" />
                  <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ deviceLabel(d) }}</span>
                  <span class="shrink-0 font-mono text-[11px] text-fg-subtle">{{ d.rack_unit ? t('rack.position', { unit: d.rack_unit, count: heightOf(d) }) : '–' }}</span>
                </button>
              </li>
            </ul>
          </div>
        </aside>
      </div>
    </template>

    <Dialog v-model:open="creating" :title="t('gv.racks.new')" size="sm">
      <form :id="`${id}-form`" class="space-y-4" @submit.prevent="create">
        <div class="space-y-1.5">
          <label :for="`${id}-name`" class="text-xs font-medium text-fg">{{ t('gv.racks.name') }}</label>
          <Input :id="`${id}-name`" v-model="form.name" :placeholder="`Rack ${racks.length + 1}`" autofocus />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <label :for="`${id}-units`" class="text-xs font-medium text-fg">{{ t('gv.racks.units') }}</label>
            <Input :id="`${id}-units`" :model-value="form.units" type="number" min="1" max="60" mono required @update:model-value="(v) => (form.units = Math.min(60, Math.max(1, Number(v) || 42)))" />
          </div>
          <div class="space-y-1.5">
            <span class="text-xs font-medium text-fg">{{ t('gv.racks.width') }}</span>
            <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.racks.width')">
              <button
                v-for="w in [19, 10]"
                :key="w"
                type="button"
                class="h-7 flex-1 rounded-sm font-mono text-xs transition-colors"
                :class="form.width === w ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
                :aria-pressed="form.width === w"
                @click="form.width = w"
              >
                {{ w }}″
              </button>
            </div>
          </div>
        </div>
      </form>
      <template #footer>
        <Button @click="creating = false">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" :form="`${id}-form`" :loading="saving"><Plus v-if="!saving" aria-hidden="true" />{{ t('gv.racks.create') }}</Button>
      </template>
    </Dialog>
  </div>
</template>
