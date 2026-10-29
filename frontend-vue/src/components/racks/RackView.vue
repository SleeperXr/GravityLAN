<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue';
import { useEventListener } from '@vueuse/core';
import { AlertTriangle, Loader2, Pencil, Plus, Server, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, Rack, RackCable, RackCabling, RackItem, RackPort } from '@/types';
import Button from '@/components/ui/Button.vue';
import Dialog from '@/components/ui/Dialog.vue';
import Input from '@/components/ui/Input.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import { useNetworkStore } from '@/stores/network';
import { deviceLabel } from '@/lib/networks';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';
import RackElevation from './RackElevation.vue';
import RackItemDialog from './RackItemDialog.vue';
import RackPortsPanel, { type CableRow } from './RackPortsPanel.vue';
import RackTray from './RackTray.vue';
import { cableDefaults, deviceEntry, entryKey, fitsAt, itemEntry, occupiedUnits, ownerKeyOf, placementIssues, portsOf, type PortSide, type RackEntry } from './rackModel';

/**
 * Racks with their equipment: network devices and rack equipment (unmanaged switches, UPS, patch panels,
 * blanks, cable management). Drag entries onto free units; click a port and then a port elsewhere to cable
 * them. Every change is saved at once and shows in the device editor as well.
 */
const props = defineProps<{ devices: Device[] }>();
const emit = defineEmits<{ openDevice: [device: Device]; changed: [] }>();

const { showToast } = useToast();
const store = useNetworkStore();
const id = useId();

const racks = ref<Rack[]>([]);
const selectedRackId = ref<number | null>(null);
const cabling = ref<RackCabling>({ items: [], ports: [], cables: [] });
const loading = ref(true);
const selectedKey = ref<string | null>(null);
const pendingPortId = ref<number | null>(null);
const itemDialog = ref(false);
const editingItem = ref<RackItem | null>(null);
const creatingRack = ref(false);
const rackForm = ref({ name: '', units: 42, width: 19 });
const savingRack = ref(false);
const side = ref<PortSide>('front');
const sides: PortSide[] = ['front', 'rear'];
const rackEditing = ref(false);
/** Tray entry picked for placing by click or keyboard, waiting for a free unit */
const placingKey = ref<string | null>(null);
/** What the screen reader hears about placing: the pick, then where it went */
const placeAnnouncement = ref('');
const elevationRef = ref<InstanceType<typeof RackElevation> | null>(null);
const rackColumnRef = ref<HTMLElement | null>(null);
/** The tray button that started placing, to give focus back when it is cancelled */
let placeOrigin: HTMLElement | null = null;

async function load(select?: number) {
  try {
    const [list, cables] = await Promise.all([api.getRacks(), api.getCabling()]);
    racks.value = Array.isArray(list) ? list : [];
    cabling.value = cables;
    const keep = select ?? selectedRackId.value;
    selectedRackId.value = racks.value.some((r) => r.id === keep) ? keep : (racks.value[0]?.id ?? null);
  } catch (err) {
    showToast('error', t('topology.tab_rack'), (err as Error).message);
  } finally {
    loading.value = false;
  }
}

async function refreshCabling() {
  try {
    cabling.value = await api.getCabling();
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), (err as Error).message);
  }
}

onMounted(() => load());

// ── What is shown ────────────────────────────────────────────────────────────
const rack = computed(() => racks.value.find((r) => r.id === selectedRackId.value) ?? null);
const entries = computed<RackEntry[]>(() => {
  if (!rack.value) return [];
  const devices = props.devices.filter((d) => d.rack_id === rack.value!.id).map((d) => deviceEntry(d, deviceLabel(d)));
  const items = cabling.value.items.filter((i) => i.rack_id === rack.value!.id).map(itemEntry);
  return [...devices, ...items];
});
const unplaced = computed(() => entries.value.filter((e) => e.unit === null));
const unracked = computed<RackEntry[]>(() =>
  props.devices.filter((d) => d.rack_id === null).map((d) => ({ ...deviceEntry(d, deviceLabel(d)), unit: null })),
);
const occupied = computed(() => occupiedUnits(entries.value));
const issues = computed(() => (rack.value ? placementIssues(rack.value.units, entries.value).filter((i) => i.reason !== 'no_position') : []));

const selected = computed<RackEntry | null>(() => entries.value.find((e) => e.key === selectedKey.value) ?? null);
const selectedPosition = computed(() => {
  const entry = selected.value;
  return entry && entry.unit !== null ? t('gv.rack.position', { unit: entry.unit, count: entry.height }) : null;
});

// ── Ports and cables ─────────────────────────────────────────────────────────
const portById = computed(() => new Map(cabling.value.ports.map((p) => [p.id, p])));
const ownerLabels = computed(() => {
  const labels = new Map<string, string>();
  for (const d of props.devices) labels.set(entryKey('device', d.id), deviceLabel(d));
  for (const item of cabling.value.items) labels.set(entryKey('item', item.id), item.name);
  return labels;
});
const cableOfPort = computed(() => {
  const map = new Map<number, RackCable>();
  for (const cable of cabling.value.cables) {
    map.set(cable.a_port_id, cable);
    map.set(cable.b_port_id, cable);
  }
  return map;
});
const colourOfPort = computed(() => {
  const colours: Record<number, string> = {};
  for (const [portId, cable] of cableOfPort.value) colours[portId] = cable.color ?? '#c3cad4';
  return colours;
});
const portStats = computed(() => {
  const stats: Record<string, { cabled: number; total: number }> = {};
  for (const port of cabling.value.ports) {
    const stat = (stats[ownerKeyOf(port)] ??= { cabled: 0, total: 0 });
    stat.total += 1;
    if (cableOfPort.value.has(port.id)) stat.cabled += 1;
  }
  return stats;
});
/** Whether any placed entry has a cable: only then are there lines for the legend to explain */
const hasCables = computed(() => entries.value.some((e) => e.unit !== null && (portStats.value[e.key]?.cabled ?? 0) > 0));
const selectedPorts = computed<RackPort[]>(() => (selected.value ? portsOf(selected.value, cabling.value.ports) : []));
const cableRows = computed<CableRow[]>(() => {
  const own = new Set(selectedPorts.value.map((p) => p.id));
  const rows: CableRow[] = [];
  for (const cable of cabling.value.cables) {
    const ownId = own.has(cable.a_port_id) ? cable.a_port_id : own.has(cable.b_port_id) ? cable.b_port_id : null;
    if (ownId === null) continue;
    const peer = portById.value.get(ownId === cable.a_port_id ? cable.b_port_id : cable.a_port_id);
    const ownPort = portById.value.get(ownId);
    if (!peer || !ownPort) continue;
    rows.push({
      id: cable.id,
      cable: cable.cable,
      colour: cable.color ?? '#c3cad4',
      ownPortId: ownId,
      ownNumber: ownPort.number,
      peerLabel: ownerLabels.value.get(ownerKeyOf(peer)) ?? '?',
      peerNumber: peer.number,
    });
  }
  return rows.sort((a, b) => a.ownNumber - b.ownNumber);
});
const pendingLabel = computed(() => {
  const port = pendingPortId.value !== null ? portById.value.get(pendingPortId.value) : undefined;
  return port ? `${ownerLabels.value.get(ownerKeyOf(port)) ?? '?'} · ${t('gv.rack.port')} ${port.number}` : null;
});

// ── Selecting and opening ────────────────────────────────────────────────────
function selectEntry(key: string) {
  selectedKey.value = key;
}

function openItemEditor(item: RackItem) {
  editingItem.value = item;
  itemDialog.value = true;
}

function openEntry(key: string) {
  const entry = findEntry(key);
  if (!entry) return;
  if (entry.kind === 'device') {
    const device = props.devices.find((d) => d.id === entry.id);
    if (device) emit('openDevice', device);
    return;
  }
  const item = cabling.value.items.find((i) => i.id === entry.id);
  if (item) openItemEditor(item);
}

function addItem() {
  editingItem.value = null;
  itemDialog.value = true;
}

// ── Moving entries ───────────────────────────────────────────────────────────
/** The rack's own entries, or a network device that has no rack yet. */
function findEntry(key: string): RackEntry | undefined {
  return entries.value.find((e) => e.key === key) ?? unracked.value.find((e) => e.key === key);
}

/** Put an entry on `unit`; true once it is saved there. */
async function moveEntry(key: string, unit: number): Promise<boolean> {
  const entry = findEntry(key);
  const current = rack.value;
  if (!entry || !current) return false;
  const inThisRack = entries.value.some((e) => e.key === key);
  if (inThisRack && entry.unit === unit) return true;
  if (!fitsAt(current.units, entries.value, unit, entry.height, key)) {
    showToast('error', t('gv.rack.drop_title'), t('gv.rack.no_room'));
    return false;
  }
  try {
    if (entry.kind === 'device') {
      const patch = { rack_id: current.id, rack_unit: unit, rack_height: entry.height };
      store.patchDevice(entry.id, patch);
      await api.updateDevice(entry.id, patch);
    } else {
      await api.updateRackItem(entry.id, { rack_unit: unit });
      cabling.value = { ...cabling.value, items: cabling.value.items.map((i) => (i.id === entry.id ? { ...i, rack_unit: unit } : i)) };
    }
    emit('changed');
    return true;
  } catch (err) {
    showToast('error', t('gv.rack.drop_title'), (err as Error).message);
    void load(current.id);
    return false;
  }
}

// ── Placing without a drag ───────────────────────────────────────────────────
/** The picked entry while it still waits for a unit (a drag may have placed it meanwhile). */
const placing = computed<RackEntry | null>(() => {
  const entry = placingKey.value ? findEntry(placingKey.value) : undefined;
  return entry && entry.unit === null ? entry : null;
});
const placingMessage = computed(() => (placing.value ? t('gv.rack.place_pending', { label: placing.value.label, count: placing.value.height }) : ''));

/**
 * A tray entry was clicked (or Enter / Space): it waits for a free unit. From the keyboard, focus goes to the
 * first free unit; with a pointer, the rack scrolls into view when it is out of sight (phones, rack above the tray).
 */
async function startPlacing(key: string, keyboard: boolean) {
  if (placingKey.value === key) return cancelPlacing();
  placeOrigin = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  placingKey.value = key;
  placeAnnouncement.value = '';
  await nextTick();
  if (keyboard && elevationRef.value?.focusPlaceTarget()) return;
  const column = rackColumnRef.value;
  const box = column?.getBoundingClientRect();
  if (column && box && (box.bottom < 120 || box.top > window.innerHeight - 120)) {
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    column.scrollIntoView({ block: 'start', behavior: still ? 'auto' : 'smooth' });
  }
}

function cancelPlacing() {
  if (!placingKey.value) return;
  placingKey.value = null;
  placeAnnouncement.value = t('gv.rack.place_cancelled');
  if (placeOrigin?.isConnected) placeOrigin.focus();
  placeOrigin = null;
}

/** A free unit was chosen: the same fit check and save as a drop. */
async function placeAt(key: string, unit: number) {
  const entry = findEntry(key);
  if (!entry || !(await moveEntry(key, unit))) return;
  placingKey.value = null;
  placeOrigin = null;
  selectedKey.value = key;
  placeAnnouncement.value = t('gv.rack.placed', { label: entry.label, unit });
}

// Another rack shows other free units: drop the pick
watch(selectedRackId, () => {
  placingKey.value = null;
  placeOrigin = null;
});

/** Take an entry off its unit; it stays in the rack, in the tray. */
async function unplace(key: string) {
  const entry = entries.value.find((e) => e.key === key);
  if (!entry || entry.unit === null) return;
  try {
    if (entry.kind === 'device') {
      store.patchDevice(entry.id, { rack_unit: null });
      await api.updateDevice(entry.id, { rack_unit: null });
    } else {
      await api.updateRackItem(entry.id, { rack_unit: null });
      cabling.value = { ...cabling.value, items: cabling.value.items.map((i) => (i.id === entry.id ? { ...i, rack_unit: null } : i)) };
    }
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.rack.drop_title'), (err as Error).message);
    void load(rack.value?.id);
  }
}

/** Take a network device out of the rack altogether. */
async function detach(key: string) {
  const entry = entries.value.find((e) => e.key === key);
  if (!entry || entry.kind !== 'device') return;
  try {
    store.patchDevice(entry.id, { rack_id: null, rack_unit: null });
    await api.updateDevice(entry.id, { rack_id: null, rack_unit: null });
    if (selectedKey.value === key) selectedKey.value = null;
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.rack.drop_title'), (err as Error).message);
    void load(rack.value?.id);
  }
}

// ── Ports and cables ─────────────────────────────────────────────────────────
async function setPorts(count: number, kind: string, side: PortSide) {
  const entry = selected.value;
  if (!entry) return;
  try {
    await api.setPorts({ owner_type: entry.kind, owner_id: entry.id, count, kind, side });
    await refreshCabling();
    showToast('success', t('gv.rack.ports_title'), t('gv.rack.ports_saved', { label: entry.label, count }));
  } catch (err) {
    showToast('error', t('gv.rack.ports_title'), (err as Error).message);
  }
}

/** First click chooses the start port; the second click on another device's port makes the cable. */
async function pickPort(port: RackPort) {
  if (pendingPortId.value === null) {
    if (cableOfPort.value.has(port.id)) {
      showToast('info', t('gv.rack.cables_title'), t('gv.rack.port_busy'));
      return;
    }
    pendingPortId.value = port.id;
    return;
  }
  if (pendingPortId.value === port.id) {
    pendingPortId.value = null;
    return;
  }
  const from = portById.value.get(pendingPortId.value);
  if (!from) {
    pendingPortId.value = null;
    return;
  }
  if (ownerKeyOf(from) === ownerKeyOf(port)) {
    showToast('info', t('gv.rack.cables_title'), t('gv.rack.port_same_owner'));
    return;
  }
  if (cableOfPort.value.has(port.id)) {
    showToast('info', t('gv.rack.cables_title'), t('gv.rack.port_busy'));
    return;
  }
  const defaults = cableDefaults(from.kind);
  try {
    await api.createCable({ a_port_id: from.id, b_port_id: port.id, cable: defaults.cable, color: defaults.colour });
    pendingPortId.value = null;
    await refreshCabling();
    showToast(
      'success',
      t('gv.rack.cables_title'),
      t('gv.rack.cable_connected', { a: ownerLabels.value.get(ownerKeyOf(from)) ?? '?', b: ownerLabels.value.get(ownerKeyOf(port)) ?? '?' }),
    );
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), (err as Error).message);
  }
}

async function removeCable(cableId: number) {
  try {
    await api.deleteCable(cableId);
    await refreshCabling();
    showToast('success', t('gv.rack.cables_title'), t('gv.rack.cable_removed'));
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), (err as Error).message);
  }
}

async function deleteItem() {
  const entry = selected.value;
  if (!entry || entry.kind !== 'item') return;
  const ok = await confirmAction({
    title: t('gv.rack.delete_item'),
    message: t('gv.rack.delete_item_confirm', { name: entry.label }),
    confirmLabel: t('gv.rack.delete_item'),
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteRackItem(entry.id);
    selectedKey.value = null;
    await refreshCabling();
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.rack.delete_item'), (err as Error).message);
  }
}

async function onItemSaved() {
  await refreshCabling();
  emit('changed');
}

// Escape drops a pick for placing or a half-made cable before it closes anything else
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.key !== 'Escape') return;
  if (placingKey.value !== null) cancelPlacing();
  else if (pendingPortId.value !== null) pendingPortId.value = null;
});

// ── Racks ────────────────────────────────────────────────────────────────────
function openCreate() {
  rackEditing.value = false;
  rackForm.value = { name: '', units: 42, width: 19 };
  creatingRack.value = true;
}

function openEditRack() {
  if (!rack.value) return;
  rackEditing.value = true;
  rackForm.value = { name: rack.value.name, units: rack.value.units, width: rack.value.width };
  creatingRack.value = true;
}

/** Saves a new rack, or the changes to the open one; a smaller rack is refused while something would not fit. */
async function saveRack() {
  if (!rackEditing.value) return createRack();
  const current = rack.value;
  if (!current) return;
  savingRack.value = true;
  try {
    await api.updateRack(current.id, { name: rackForm.value.name.trim() || current.name, units: rackForm.value.units, width: rackForm.value.width });
    creatingRack.value = false;
    await load(current.id);
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.rack.save_rack'), (err as Error).message);
  } finally {
    savingRack.value = false;
  }
}

async function createRack() {
  savingRack.value = true;
  try {
    const created = await api.createRack({
      name: rackForm.value.name.trim() || `Rack ${racks.value.length + 1}`,
      units: rackForm.value.units,
      width: rackForm.value.width,
    });
    creatingRack.value = false;
    await load(created.id);
  } catch (err) {
    showToast('error', t('gv.racks.create'), (err as Error).message);
  } finally {
    savingRack.value = false;
  }
}

async function removeRack() {
  if (!rack.value) return;
  const ok = await confirmAction({
    title: t('gv.racks.delete'),
    message: t('gv.racks.delete_confirm', { name: rack.value.name, count: entries.value.length }),
    confirmLabel: t('gv.racks.delete'),
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteRack(rack.value.id);
    selectedKey.value = null;
    await load();
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.racks.delete'), (err as Error).message);
  }
}
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
            class="h-7 shrink-0 rounded-sm px-3 text-xs font-semibold transition-colors max-md:h-11"
            :class="r.id === selectedRackId ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="r.id === selectedRackId"
            @click="selectedRackId = r.id"
          >
            {{ r.name }}
          </button>
        </div>
        <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.rack.side_title')">
          <button
            v-for="s in sides"
            :key="s"
            type="button"
            class="h-7 rounded-sm px-3 text-xs font-semibold transition-colors max-md:h-11"
            :class="side === s ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="side === s"
            @click="side = s"
          >
            {{ t('gv.rack.side_' + s) }}
          </button>
        </div>
        <div class="ml-auto flex flex-wrap justify-end gap-1">
          <Button size="sm" @click="openEditRack"><Pencil aria-hidden="true" />{{ t('gv.rack.edit_rack') }}</Button>
          <Button size="sm" @click="addItem"><Plus aria-hidden="true" />{{ t('gv.rack.add_item') }}</Button>
          <Button size="sm" @click="openCreate"><Plus aria-hidden="true" />{{ t('gv.racks.new') }}</Button>
          <Button size="icon-sm" variant="danger-ghost" :aria-label="t('gv.racks.delete')" :title="t('gv.racks.delete')" @click="removeRack"><Trash2 aria-hidden="true" /></Button>
        </div>
      </header>

      <!-- From lg the tray is a column beside the rack and each column scrolls on its own, so both stay in reach -->
      <div
        class="grid min-h-0 flex-1 grid-cols-1 gap-5 overflow-y-auto p-4 lg:grid-cols-[minmax(0,1fr)_minmax(15rem,18rem)] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]"
      >
        <div ref="rackColumnRef" class="min-w-0 space-y-3 lg:min-h-0 lg:overflow-y-auto">
          <p class="sr-only" aria-live="polite">{{ placing ? placingMessage : placeAnnouncement }}</p>
          <div v-if="placing" class="sticky top-0 z-10 flex items-center gap-2 rounded-md border border-accent bg-surface px-3 py-1.5 text-xs text-fg shadow-pop">
            <p class="min-w-0 flex-1">{{ placingMessage }}</p>
            <Button size="sm" variant="ghost" @click="cancelPlacing">{{ t('common.cancel') }}</Button>
          </div>
          <RackElevation
            ref="elevationRef"
            :name="rack.name"
            :units="rack.units"
            :entries="entries"
            :candidates="unracked"
            :selected-key="selectedKey"
            :port-stats="portStats"
            :side="side"
            :width="rack.width"
            :ports="cabling.ports"
            :cables="cabling.cables"
            :colour-of-port="colourOfPort"
            :placing="placing"
            @select="selectEntry"
            @open="openEntry"
            @move="moveEntry"
            @place="placeAt"
          />
          <p class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.place_hint') }} {{ t('gv.rack.entry_hint') }}</p>
          <p v-if="hasCables" class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.legend') }}</p>
          <div class="gl-subcard space-y-2 p-4">
            <div class="flex items-baseline justify-between gap-3">
              <p class="gl-eyebrow">{{ t('rack.occupied') }}</p>
              <p class="font-mono text-sm text-fg tabular"><span class="text-xl font-semibold">{{ occupied }}</span> / {{ rack.units }} HE</p>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-sunken" role="progressbar" :aria-label="t('rack.occupied')" aria-valuemin="0" :aria-valuemax="rack.units" :aria-valuenow="occupied">
              <div class="h-full rounded-full bg-accent" :style="{ width: `${Math.min(100, (occupied / rack.units) * 100)}%` }" />
            </div>
            <p class="text-xs text-fg-subtle">
              {{ t('rack.devices') }}: <span class="font-mono text-fg">{{ entries.length }}</span> · {{ t('gv.racks.free', { count: Math.max(0, rack.units - occupied) }) }}
            </p>
          </div>
          <div v-if="issues.length" class="space-y-2 rounded-lg border border-warn/40 bg-warn/10 p-3 text-xs" role="status">
            <p class="flex items-center gap-2 font-semibold text-warn-text"><AlertTriangle class="size-4" aria-hidden="true" />{{ t('gv.racks.issues', { count: issues.length }) }}</p>
            <ul class="space-y-1">
              <li v-for="i in issues" :key="i.entry.key">
                <button type="button" class="text-left text-fg underline-offset-2 hover:underline" @click="selectEntry(i.entry.key)">
                  {{ i.entry.label }}: {{ t(`gv.racks.issue_${i.reason}`) }}
                </button>
              </li>
            </ul>
          </div>
        </div>

        <aside class="min-w-0 space-y-4 lg:min-h-0 lg:overflow-y-auto">
          <RackPortsPanel
            v-if="selected"
            :key="selected.key"
            :entry="selected"
            :ports="selectedPorts"
            :cables="cableRows"
            :colour-of-port="colourOfPort"
            :pending-port-id="pendingPortId"
            :pending-label="pendingLabel"
            :position="selectedPosition"
            @set-ports="setPorts"
            @pick="pickPort"
            @cancel="pendingPortId = null"
            @remove-cable="removeCable"
            @open="openEntry(selected.key)"
            @remove="deleteItem"
          />
          <p v-else class="gl-subcard p-4 text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.select_hint') }}</p>

          <RackTray
            :rack-entries="entries"
            :unplaced="unplaced"
            :unracked="unracked"
            :selected-key="selectedKey"
            :placing-key="placing?.key ?? null"
            @select="selectEntry"
            @open="openEntry"
            @unplace="unplace"
            @detach="detach"
            @place="startPlacing"
          />
        </aside>
      </div>
    </template>

    <RackItemDialog v-if="rack" v-model:open="itemDialog" :rack-id="rack.id" :item="editingItem" @saved="onItemSaved" />

    <Dialog v-model:open="creatingRack" :title="rackEditing ? t('gv.rack.edit_rack') : t('gv.racks.new')" size="sm">
      <form :id="`${id}-form`" class="space-y-4" @submit.prevent="saveRack">
        <div class="space-y-1.5">
          <label :for="`${id}-name`" class="text-xs font-medium text-fg">{{ t('gv.racks.name') }}</label>
          <Input :id="`${id}-name`" v-model="rackForm.name" :placeholder="`Rack ${racks.length + 1}`" autofocus />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <label :for="`${id}-units`" class="text-xs font-medium text-fg">{{ t('gv.racks.units') }}</label>
            <Input :id="`${id}-units`" :model-value="rackForm.units" type="number" min="1" max="60" mono required @update:model-value="(v) => (rackForm.units = Math.min(60, Math.max(1, Number(v) || 42)))" />
          </div>
          <div class="space-y-1.5">
            <span class="text-xs font-medium text-fg">{{ t('gv.racks.width') }}</span>
            <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.racks.width')">
              <button
                v-for="w in [19, 10]"
                :key="w"
                type="button"
                class="h-7 flex-1 rounded-sm font-mono text-xs transition-colors"
                :class="rackForm.width === w ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
                :aria-pressed="rackForm.width === w"
                @click="rackForm.width = w"
              >
                {{ w }}″
              </button>
            </div>
          </div>
        </div>
      </form>
      <template #footer>
        <Button @click="creatingRack = false">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" :form="`${id}-form`" :loading="savingRack"><Plus v-if="!savingRack" aria-hidden="true" />{{ rackEditing ? t('gv.rack.save_rack') : t('gv.racks.create') }}</Button>
      </template>
    </Dialog>
  </div>
</template>
