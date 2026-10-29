<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId } from 'vue';
import { useEventListener, useMediaQuery, useStorage } from '@vueuse/core';
import { Loader2, PanelRight, Pencil, Plus, RotateCcw, Server, Shrink, Sparkles, Trash2, ZoomIn } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, Rack, RackCable, RackCabling, RackItem, RackPort } from '@/types';
import Button from '@/components/ui/Button.vue';
import Dialog from '@/components/ui/Dialog.vue';
import Input from '@/components/ui/Input.vue';
import Sheet from '@/components/ui/Sheet.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import { useNetworkStore } from '@/stores/network';
import { deviceLabel, networkColor } from '@/lib/networks';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { apiErrorMessage } from '@/lib/apiErrors';
import { t } from '@/i18n';
import RackItemDialog from './RackItemDialog.vue';
import RackInspector, { type CableDetail, type CableRow, type RackOverview } from './RackInspector.vue';
import RackPalette from './RackPalette.vue';
import RackStage from './RackStage.vue';
import { kindOf } from './rackKinds';
import { useVitality } from './rackMotion';
import {
  cableDefaults,
  deviceEntry,
  entryKey,
  firstFreeUnit,
  fitsAt,
  itemEntry,
  occupiedUnits,
  nearestFreeUnit,
  ownerKeyOf,
  placementIssues,
  portsOf,
  rackCandidates,
  type PlacementIssue,
  type PortSide,
  type RackEntry,
} from './rackModel';
import { placeTargets } from './rackPlacement';
import { useRackDrag, type DragState, type DragSubject } from './useRackDrag';

/**
 * Racks as a living picture: the rack in the middle, what can go in on the left, details on the right. Pull
 * faceplates to move them, pull equipment in from the palette, pull a jack to another jack for a cable. Every
 * change is saved at once, shows in the device editor as well, and can be undone from its toast.
 */
const props = defineProps<{ devices: Device[] }>();
const emit = defineEmits<{ openDevice: [device: Device]; changed: [] }>();

const { showToast, removeToast, isShowing } = useToast();
const store = useNetworkStore();
const id = useId();
const { vitality, cycle: cycleVitality } = useVitality();
const isLg = useMediaQuery('(min-width: 1024px)');
const isXl = useMediaQuery('(min-width: 1280px)');
/** Whole rack in view, or every unit at full height with room for the details of each faceplate */
const density = useStorage<'fit' | 'detail'>('gravityui.rack.density', 'fit');

/** Width of the palette column on the left, dragged at its edge and remembered */
const PALETTE_MIN = 208;
const PALETTE_MAX = 448;
const PALETTE_DEFAULT = 208;
const paletteWidth = useStorage('gravityui.rack.palette_width', PALETTE_DEFAULT);
const paletteResize = ref<{ startX: number; start: number } | null>(null);
const setPaletteWidth = (width: number) => (paletteWidth.value = Math.round(Math.min(PALETTE_MAX, Math.max(PALETTE_MIN, width))));

function startPaletteResize(event: PointerEvent) {
  if (event.button !== 0) return;
  event.preventDefault();
  paletteResize.value = { startX: event.clientX, start: paletteWidth.value };
  const move = (e: PointerEvent) => paletteResize.value && setPaletteWidth(paletteResize.value.start + e.clientX - paletteResize.value.startX);
  const up = () => {
    paletteResize.value = null;
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', up);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', up);
}

const racks = ref<Rack[]>([]);
const selectedRackId = ref<number | null>(null);
const cabling = ref<RackCabling>({ items: [], ports: [], cables: [] });
const loading = ref(true);
const selectedKey = ref<string | null>(null);
const focusCableId = ref<number | null>(null);
const hoverCableId = ref<number | null>(null);
/** A cable that was just plugged in lights up for a moment */
const flashCableId = ref<number | null>(null);
const pendingPortId = ref<number | null>(null);
const side = ref<PortSide>('front');
const itemDialog = ref(false);
const editingItem = ref<RackItem | null>(null);
const rackDialog = ref(false);
const rackEditing = ref(false);
const rackForm = ref({ name: '', units: 42, width: 19 });
const savingRack = ref(false);
const paletteOpen = ref(false);
const inspectorOpen = ref(false);
const stageRef = ref<InstanceType<typeof RackStage> | null>(null);

async function load(select?: number) {
  try {
    const [list, cables] = await Promise.all([api.getRacks(), api.getCabling()]);
    racks.value = Array.isArray(list) ? list : [];
    cabling.value = cables;
    const keep = select ?? selectedRackId.value;
    selectedRackId.value = racks.value.some((r) => r.id === keep) ? keep : (racks.value[0]?.id ?? null);
  } catch (err) {
    showToast('error', t('topology.tab_rack'), apiErrorMessage(err));
  } finally {
    loading.value = false;
  }
}

async function refreshCabling() {
  try {
    cabling.value = await api.getCabling();
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), apiErrorMessage(err));
  }
}

onMounted(() => load());

// ── What is in the rack ──────────────────────────────────────────────────────
const rack = computed(() => racks.value.find((r) => r.id === selectedRackId.value) ?? null);
const rackName = (rackId: number | null) => racks.value.find((r) => r.id === rackId)?.name ?? '';
const entries = computed<RackEntry[]>(() => {
  const current = rack.value;
  if (!current) return [];
  const devices = props.devices.filter((d) => d.rack_id === current.id).map((d) => deviceEntry(d, deviceLabel(d)));
  const items = cabling.value.items.filter((i) => i.rack_id === current.id).map(itemEntry);
  return [...devices, ...items];
});
const issueOf = computed(() => {
  const map = new Map<string, PlacementIssue>();
  if (rack.value) for (const issue of placementIssues(rack.value.units, entries.value)) map.set(issue.entry.key, issue.reason);
  return map;
});
/** On the stage: everything with a unit that works */
const placed = computed(() => entries.value.filter((e) => e.unit !== null && !issueOf.value.has(e.key)));
/** In the store: this rack's entries without a unit, or with one that does not work */
const stored = computed(() =>
  entries.value
    .filter((e) => e.unit === null || issueOf.value.has(e.key))
    .map((e) => ({ entry: e, issue: e.unit === null ? null : (issueOf.value.get(e.key) ?? null) })),
);
/** Devices in no rack; VMs, containers, access points and wireless clients only once "show all" is on */
const showAllDevices = ref(false);
const allUnracked = computed(() => props.devices.filter((d) => d.rack_id === null));
const unracked = computed<RackEntry[]>(() => rackCandidates(allUnracked.value, showAllDevices.value).map((d) => deviceEntry(d, deviceLabel(d))));
const hiddenDevices = computed(() => allUnracked.value.length - rackCandidates(allUnracked.value, false).length);

const selected = computed<RackEntry | null>(() => {
  const key = selectedKey.value;
  return key ? (entries.value.find((e) => e.key === key) ?? unracked.value.find((e) => e.key === key) ?? null) : null;
});
const selectedInRack = computed(() => Boolean(selected.value && entries.value.some((e) => e.key === selected.value!.key)));
const selectedPosition = computed(() => {
  const entry = selected.value;
  if (!entry || entry.unit === null || !selectedInRack.value || issueOf.value.has(entry.key)) return null;
  return t('gv.rack.position', { unit: entry.unit, count: entry.height });
});
const selectedMaxHeight = computed(() => {
  const entry = selected.value;
  const current = rack.value;
  if (!entry || !current || entry.unit === null) return 10;
  let height = entry.height;
  while (height < 10 && fitsAt(current.units, placed.value, entry.unit, height + 1, entry.key)) height++;
  return height;
});

// ── Ports and cables ─────────────────────────────────────────────────────────
const portById = computed(() => new Map(cabling.value.ports.map((p) => [p.id, p])));
const ownerLabels = computed(() => {
  const labels: Record<string, string> = {};
  for (const d of props.devices) labels[entryKey('device', d.id)] = deviceLabel(d);
  for (const item of cabling.value.items) labels[entryKey('item', item.id)] = item.name;
  return labels;
});
const onlineOf = computed(() => {
  const online: Record<string, boolean> = {};
  for (const d of props.devices) online[entryKey('device', d.id)] = d.is_online;
  return online;
});
const cableOfPort = computed(() => {
  const map = new Map<number, RackCable>();
  for (const cable of cabling.value.cables) {
    map.set(cable.a_port_id, cable);
    map.set(cable.b_port_id, cable);
  }
  return map;
});
const colourOfCable = (cable: RackCable) => cable.color ?? cableDefaults(portById.value.get(cable.a_port_id)?.kind ?? 'RJ45').colour;
const colourOfPort = computed(() => {
  const colours: Record<number, string> = {};
  for (const [portId, cable] of cableOfPort.value) colours[portId] = colourOfCable(cable);
  return colours;
});
/** Cabled ports whose link cannot be up: this end's device or the other end's device is offline */
const downPorts = computed(() => {
  const down = new Set<number>();
  for (const cable of cabling.value.cables) {
    const a = portById.value.get(cable.a_port_id);
    const b = portById.value.get(cable.b_port_id);
    if (!a || !b) continue;
    if (onlineOf.value[ownerKeyOf(a)] === false || onlineOf.value[ownerKeyOf(b)] === false) down.add(a.id).add(b.id);
  }
  return down;
});
const accentOf = computed(() => {
  const accents: Record<string, string | null> = {};
  for (const e of entries.value) {
    if (e.kind !== 'device') continue;
    accents[e.key] = networkColor(e.subnetId, e.detail);
  }
  return accents;
});

/** Where an owner that is not on this rack's stage is: another rack, or no place at all */
function elsewhere(ownerKey: string): { label: string; rackId: number | null } {
  const [kind, raw] = ownerKey.split('-');
  const ownerId = Number(raw);
  const rackId = kind === 'device' ? (props.devices.find((d) => d.id === ownerId)?.rack_id ?? null) : (cabling.value.items.find((i) => i.id === ownerId)?.rack_id ?? null);
  if (rackId === null || rackId === rack.value?.id) return { label: '', rackId: null };
  return { label: rackName(rackId), rackId };
}

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
      colour: colourOfCable(cable),
      ownPortId: ownId,
      ownNumber: ownPort.number,
      peerKey: ownerKeyOf(peer),
      peerLabel: ownerLabels.value[ownerKeyOf(peer)] ?? '?',
      peerNumber: peer.number,
    });
  }
  return rows.sort((a, b) => a.ownNumber - b.ownNumber);
});
/** For each cabled port, where its cable goes ("Kabel zu sw-core · Port 5"), for tooltips and screen readers */
const peerOfPort = computed(() => {
  const peers: Record<number, string> = {};
  for (const cable of cabling.value.cables) {
    const a = portById.value.get(cable.a_port_id);
    const b = portById.value.get(cable.b_port_id);
    if (!a || !b) continue;
    peers[a.id] = t('gv.rack.jack_cabled', { peer: ownerLabels.value[ownerKeyOf(b)] ?? '?', number: b.number });
    peers[b.id] = t('gv.rack.jack_cabled', { peer: ownerLabels.value[ownerKeyOf(a)] ?? '?', number: a.number });
  }
  return peers;
});
const cableDetail = computed<CableDetail | null>(() => {
  const cable = cabling.value.cables.find((c) => c.id === focusCableId.value);
  if (!cable) return null;
  const ends = [cable.a_port_id, cable.b_port_id]
    .map((portId) => portById.value.get(portId))
    .filter((p): p is RackPort => Boolean(p))
    .map((p) => ({ key: ownerKeyOf(p), label: ownerLabels.value[ownerKeyOf(p)] ?? '?', number: p.number }));
  return { id: cable.id, cable: cable.cable, colour: colourOfCable(cable), ends };
});
const pendingLabel = computed(() => {
  const port = pendingPortId.value !== null ? portById.value.get(pendingPortId.value) : undefined;
  return port ? `${ownerLabels.value[ownerKeyOf(port)] ?? '?'} · ${t('gv.rack.port')} ${port.number}` : null;
});
/** Cables with an end in this rack */
const rackCables = computed(() => {
  const keys = new Set(entries.value.map((e) => e.key));
  return cabling.value.cables.filter((c) => {
    const a = portById.value.get(c.a_port_id);
    const b = portById.value.get(c.b_port_id);
    return (a && keys.has(ownerKeyOf(a))) || (b && keys.has(ownerKeyOf(b)));
  });
});
const swatches = computed(() => {
  const style = getComputedStyle(document.documentElement);
  const lines = Array.from({ length: 10 }, (_, i) => style.getPropertyValue(`--line-${i + 1}`).trim()).filter(Boolean);
  return [...new Set([...lines, '#c3cad4'])];
});

const offlineDevices = computed(() => placed.value.filter((e) => e.kind === 'device' && !e.online));
const overview = computed<RackOverview>(() => ({
  name: rack.value?.name ?? '',
  units: rack.value?.units ?? 0,
  occupied: occupiedUnits(placed.value, rack.value?.units),
  devices: entries.value.filter((e) => e.kind === 'device').length,
  offline: offlineDevices.value.length,
  cables: rackCables.value.length,
  issues: [...issueOf.value].map(([key, reason]) => ({ key, label: entries.value.find((e) => e.key === key)?.label ?? '?', reason })),
}));

// ── Selecting ────────────────────────────────────────────────────────────────
function select(key: string | null) {
  selectedKey.value = key;
  focusCableId.value = null;
  if (key && !isXl.value && entries.value.some((e) => e.key === key && e.unit === null)) inspectorOpen.value = true;
}

/** Select and bring into view, e.g. the other end of a cable */
async function reveal(key: string) {
  select(key);
  await nextTick();
  stageRef.value?.reveal(key);
}

function nextOffline() {
  const list = offlineDevices.value;
  if (!list.length) return;
  const at = list.findIndex((e) => e.key === selectedKey.value);
  void reveal(list[(at + 1) % list.length].key);
}

function openEntry(key: string) {
  const entry = entries.value.find((e) => e.key === key) ?? unracked.value.find((e) => e.key === key);
  if (!entry) return;
  if (entry.kind === 'device') {
    const device = props.devices.find((d) => d.id === entry.id);
    if (device) emit('openDevice', device);
    return;
  }
  const item = cabling.value.items.find((i) => i.id === entry.id);
  if (item) {
    editingItem.value = item;
    itemDialog.value = true;
  }
}

/** The toast that can undo the last move of an entry; moving it again (arrow keys) keeps its first place. */
let lastMove: { toastId: number; key: string; revert: () => void } | null = null;

/** Confirms a change with a toast that can undo it; changes of one entry in a row share one toast. */
function undoable(title: string, message: string, revert: () => void, seriesKey?: string) {
  const series = seriesKey !== undefined && lastMove !== null && lastMove.key === seriesKey && isShowing(lastMove.toastId);
  const run = series && lastMove ? lastMove.revert : revert;
  if (series && lastMove) removeToast(lastMove.toastId);
  const toastId = showToast('success', title, message, { label: t('gv.toast.undo'), run });
  lastMove = seriesKey !== undefined ? { toastId, key: seriesKey, revert: run } : null;
}

// ── Moving ───────────────────────────────────────────────────────────────────
function findEntry(key: string): RackEntry | undefined {
  return entries.value.find((e) => e.key === key) ?? unracked.value.find((e) => e.key === key);
}

/** Saves where an entry is; a device can come from another rack or from no rack */
async function savePlace(entry: RackEntry, rackId: number | null, unit: number | null) {
  if (entry.kind === 'device') {
    const patch = { rack_id: rackId, rack_unit: unit, rack_height: entry.height };
    store.patchDevice(entry.id, patch);
    await api.updateDevice(entry.id, patch);
  } else {
    await api.updateRackItem(entry.id, { rack_unit: unit });
    cabling.value = { ...cabling.value, items: cabling.value.items.map((i) => (i.id === entry.id ? { ...i, rack_unit: unit } : i)) };
  }
  emit('changed');
}

async function moveEntry(key: string, unit: number, withUndo = true) {
  const entry = findEntry(key);
  const current = rack.value;
  if (!entry || !current) return;
  const before = { rackId: entry.kind === 'device' ? (props.devices.find((d) => d.id === entry.id)?.rack_id ?? null) : current.id, unit: entry.unit };
  if (before.rackId === current.id && before.unit === unit) return;
  if (!fitsAt(current.units, placed.value, unit, entry.height, key)) {
    showToast('error', t('gv.rack.drop_title'), t('gv.rack.no_room'));
    return;
  }
  try {
    await savePlace(entry, current.id, unit);
    if (withUndo) undoable(t('gv.rack.moved_title'), t('gv.rack.moved', { label: entry.label, unit }), () => void restorePlace(key, before.rackId, before.unit), key);
  } catch (err) {
    showToast('error', t('gv.rack.drop_title'), apiErrorMessage(err));
    void load(current.id);
  }
}

async function restorePlace(key: string, rackId: number | null, unit: number | null) {
  const entry = findEntry(key);
  if (!entry) return;
  try {
    await savePlace(entry, rackId, unit);
  } catch (err) {
    showToast('error', t('gv.toast.undo'), apiErrorMessage(err));
    void load(rack.value?.id);
  }
}

/** Off its unit, into the store; it stays in the rack */
async function unplace(key: string) {
  const entry = entries.value.find((e) => e.key === key);
  const current = rack.value;
  if (!entry || entry.unit === null || !current) return;
  const unit = entry.unit;
  try {
    await savePlace(entry, current.id, null);
    undoable(t('gv.rack.moved_title'), t('gv.rack.unplaced', { label: entry.label }), () => void restorePlace(key, current.id, unit));
  } catch (err) {
    showToast('error', t('gv.rack.drop_title'), apiErrorMessage(err));
    void load(current.id);
  }
}

/** A network device out of the rack altogether */
async function detach(key: string) {
  const entry = entries.value.find((e) => e.key === key);
  const current = rack.value;
  if (!entry || entry.kind !== 'device' || !current) return;
  const unit = entry.unit;
  try {
    await savePlace(entry, null, null);
    if (selectedKey.value === key) selectedKey.value = null;
    undoable(t('gv.rack.moved_title'), t('gv.rack.detached', { label: entry.label }), () => void restorePlace(key, current.id, unit));
  } catch (err) {
    showToast('error', t('gv.rack.drop_title'), apiErrorMessage(err));
    void load(current.id);
  }
}

/** Onto the free place nearest to where it is now (the top of the rack while it has no unit) */
async function placeNear(entry: RackEntry) {
  const current = rack.value;
  if (!current) return;
  const unit = nearestFreeUnit(current.units, placed.value, entry);
  if (unit === null) {
    showToast('error', t('gv.rack.drop_title'), t('gv.racks.no_free'));
    return;
  }
  await placeAt(entry, unit);
}

/** Onto a unit picked in the details, e.g. with the keyboard */
async function placeAt(entry: RackEntry, unit: number) {
  await moveEntry(entry.key, unit);
  void reveal(entry.key);
}

/** Units where the selected entry could go: for one in the store, or one whose place does not work */
const selectedTargets = computed(() => {
  const entry = selected.value;
  const current = rack.value;
  if (!entry || !current || (entry.unit !== null && selectedInRack.value && !issueOf.value.has(entry.key))) return [];
  return placeTargets(current.units, placed.value, entry);
});

function nudge(key: string, delta: number) {
  const entry = entries.value.find((e) => e.key === key);
  const current = rack.value;
  if (!entry || entry.unit === null || !current) return;
  const unit = entry.unit + delta;
  if (fitsAt(current.units, placed.value, unit, entry.height, key)) void moveEntry(key, unit);
}

async function setHeight(height: number) {
  const entry = selected.value;
  const current = rack.value;
  if (!entry || !current || height < 1) return;
  if (entry.unit !== null && !fitsAt(current.units, placed.value, entry.unit, height, entry.key)) {
    showToast('error', t('gv.rack.item_height'), t('gv.rack.height_blocked'));
    return;
  }
  try {
    if (entry.kind === 'device') {
      store.patchDevice(entry.id, { rack_height: height });
      await api.updateDevice(entry.id, { rack_height: height });
    } else {
      await api.updateRackItem(entry.id, { rack_height: height });
      cabling.value = { ...cabling.value, items: cabling.value.items.map((i) => (i.id === entry.id ? { ...i, rack_height: height } : i)) };
    }
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.rack.item_height'), apiErrorMessage(err));
    void load(current.id);
  }
}

// ── New equipment ────────────────────────────────────────────────────────────
async function createItem(kindValue: string, unit: number) {
  const current = rack.value;
  if (!current) return;
  const kind = kindOf(kindValue);
  // Labels may carry soft hyphens for narrow tiles; a name is stored without them
  const label = t(`gv.rack.kind_${kind.value}`).replace(/­/g, '');
  const same = cabling.value.items.filter((i) => i.rack_id === current.id && i.kind === kind.value).length;
  const name = same ? `${label} ${same + 1}` : label;
  try {
    const created = await api.createRackItem({
      rack_id: current.id,
      name,
      kind: kind.value,
      rack_height: kind.height,
      rack_unit: unit,
      notes: null,
      port_count: kind.ports,
      port_kind: kind.portKind,
    });
    await refreshCabling();
    selectedKey.value = entryKey('item', created.id);
    focusCableId.value = null;
    emit('changed');
    undoable(t('gv.rack.created_title'), t('gv.rack.created_msg', { label: name, unit }), () => void deleteItemQuietly(created.id));
  } catch (err) {
    showToast('error', t('gv.rack.add_item'), apiErrorMessage(err));
  }
}

async function deleteItemQuietly(itemId: number) {
  try {
    await api.deleteRackItem(itemId);
    if (selectedKey.value === entryKey('item', itemId)) selectedKey.value = null;
    await refreshCabling();
    emit('changed');
  } catch (err) {
    showToast('error', t('gv.rack.delete_item'), apiErrorMessage(err));
  }
}

async function placeKind(kindValue: string) {
  const current = rack.value;
  if (!current) return;
  const kind = kindOf(kindValue);
  const unit = firstFreeUnit(current.units, placed.value, kind.height);
  if (unit === null) {
    showToast('error', t('gv.rack.add_item'), t('gv.rack.no_free_unit', { label: t(`gv.rack.kind_${kind.value}`), count: kind.height }));
    return;
  }
  paletteOpen.value = false;
  await createItem(kind.value, unit);
}

async function renameItem(name: string) {
  const entry = selected.value;
  if (!entry || entry.kind !== 'item') return;
  try {
    await api.updateRackItem(entry.id, { name });
    cabling.value = { ...cabling.value, items: cabling.value.items.map((i) => (i.id === entry.id ? { ...i, name } : i)) };
  } catch (err) {
    showToast('error', t('gv.rack.item_save'), apiErrorMessage(err));
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
  if (ok) await deleteItemQuietly(entry.id);
}

async function onItemSaved() {
  await refreshCabling();
  emit('changed');
}

// ── Dragging ─────────────────────────────────────────────────────────────────
const { drag, start: startDrag } = useRackDrag({
  locate: (d) => stageRef.value?.locate(d) ?? null,
  drop: onDrop,
  click: onDragClick,
});

function grabEntry(entry: RackEntry, event: PointerEvent, grab: { x: number; y: number }) {
  startDrag({ key: entry.key, label: entry.label, face: entry.face, height: entry.height, itemKind: entry.itemKind, entry, from: 'rack' }, event, grab);
}

function onDragClick(subject: DragSubject) {
  if (subject.from === 'palette' && subject.itemKind) void placeKind(subject.itemKind);
  else select(subject.key);
}

function onDrop(d: DragState) {
  if (d.zone === 'stage' && d.target && !d.target.blocker) {
    if (d.from === 'palette' && d.itemKind) void createItem(d.itemKind, d.target.unit);
    else void moveEntry(d.key, d.target.unit);
    return;
  }
  if (d.zone === 'store' && d.from === 'rack') void unplace(d.key);
  else if (d.zone === 'unrack' && d.entry?.kind === 'device' && d.from !== 'palette' && entries.value.some((e) => e.key === d.key)) void detach(d.key);
}

/** Shown next to the pointer while something is dragged outside the rack */
const dragChip = computed(() => {
  const d = drag.value;
  if (!d?.lifted || d.zone === 'stage') return null;
  return { x: d.x, y: d.y, label: d.label, height: d.height, icon: kindOf(d.itemKind ?? 'other').icon, device: d.entry?.kind === 'device', zone: d.zone };
});

// ── Ports and cables ─────────────────────────────────────────────────────────
async function setPorts(key: string, count: number, kind: string, portSide: PortSide) {
  const entry = findEntry(key);
  if (!entry) return;
  try {
    await api.setPorts({ owner_type: entry.kind, owner_id: entry.id, count, kind, side: portSide });
    await refreshCabling();
  } catch (err) {
    showToast('error', t('gv.rack.ports_title'), apiErrorMessage(err));
    await refreshCabling();
  }
}

function flash(cableId: number) {
  flashCableId.value = cableId;
  window.setTimeout(() => {
    if (flashCableId.value === cableId) flashCableId.value = null;
  }, 1400);
}

async function connect(fromId: number, toId: number) {
  const from = portById.value.get(fromId);
  const to = portById.value.get(toId);
  if (!from || !to) return;
  if (ownerKeyOf(from) === ownerKeyOf(to)) {
    showToast('info', t('gv.rack.cables_title'), t('gv.rack.port_same_owner'));
    return;
  }
  if (cableOfPort.value.has(from.id) || cableOfPort.value.has(to.id)) {
    showToast('info', t('gv.rack.cables_title'), t('gv.rack.port_busy'));
    return;
  }
  const defaults = cableDefaults(from.kind);
  try {
    const created = await api.createCable({ a_port_id: from.id, b_port_id: to.id, cable: defaults.cable, color: defaults.colour });
    pendingPortId.value = null;
    await refreshCabling();
    flash(created.id);
    undoable(
      t('gv.rack.cables_title'),
      t('gv.rack.cable_connected', { a: ownerLabels.value[ownerKeyOf(from)] ?? '?', b: ownerLabels.value[ownerKeyOf(to)] ?? '?' }),
      () => void removeCable(created.id, false),
    );
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), apiErrorMessage(err));
  }
}

/** A tap on a port: the first chooses where the cable starts, a tap on another device's port makes it */
function pickPort(portOrId: RackPort | number) {
  const port = typeof portOrId === 'number' ? portById.value.get(portOrId) : portOrId;
  if (!port) return;
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
  void connect(pendingPortId.value, port.id);
}

async function removeCable(cableId: number, withUndo = true) {
  const cable = cabling.value.cables.find((c) => c.id === cableId);
  try {
    await api.deleteCable(cableId);
    if (focusCableId.value === cableId) focusCableId.value = null;
    await refreshCabling();
    if (withUndo && cable) {
      undoable(t('gv.rack.cables_title'), t('gv.rack.cable_removed'), () => {
        void api
          .createCable({ a_port_id: cable.a_port_id, b_port_id: cable.b_port_id, cable: cable.cable, color: cable.color, notes: cable.notes })
          .then(refreshCabling)
          .catch((err: unknown) => showToast('error', t('gv.toast.undo'), apiErrorMessage(err)));
      });
    }
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), apiErrorMessage(err));
  }
}

async function patchCable(cableId: number, patch: { cable?: string; color?: string }) {
  cabling.value = { ...cabling.value, cables: cabling.value.cables.map((c) => (c.id === cableId ? { ...c, ...patch } : c)) };
  try {
    await api.updateCable(cableId, patch);
  } catch (err) {
    showToast('error', t('gv.rack.cables_title'), apiErrorMessage(err));
    await refreshCabling();
  }
}

function pickCable(cableId: number) {
  focusCableId.value = cableId;
  selectedKey.value = null;
  if (!isXl.value) inspectorOpen.value = true;
}

/** A label at the end of a stub: turn the rack around, or go to the other rack, and show the other end */
async function followStub(target: { ownerKey: string; side: PortSide | null; rackId: number | null }) {
  if (target.rackId !== null && target.rackId !== selectedRackId.value) selectedRackId.value = target.rackId;
  if (target.side && target.side !== side.value) side.value = target.side;
  await nextTick();
  void reveal(target.ownerKey);
}

const highlightCableId = computed(() => hoverCableId.value ?? focusCableId.value ?? flashCableId.value);

// Escape drops a half-made cable first, then a picked cable, then the selection
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (event.key !== 'Escape' || itemDialog.value || rackDialog.value || drag.value) return;
  if (pendingPortId.value !== null) pendingPortId.value = null;
  else if (focusCableId.value !== null) focusCableId.value = null;
  else if (selectedKey.value !== null) selectedKey.value = null;
});

// ── Racks ────────────────────────────────────────────────────────────────────
function openCreate() {
  rackEditing.value = false;
  rackForm.value = { name: '', units: 42, width: 19 };
  rackDialog.value = true;
}

function openEditRack() {
  if (!rack.value) return;
  rackEditing.value = true;
  rackForm.value = { name: rack.value.name, units: rack.value.units, width: rack.value.width };
  rackDialog.value = true;
}

async function patchRack(patch: Partial<Rack>) {
  const current = rack.value;
  if (!current) return false;
  try {
    const saved = await api.updateRack(current.id, patch);
    racks.value = racks.value.map((r) => (r.id === saved.id ? saved : r));
    emit('changed');
    return true;
  } catch (err) {
    showToast('error', t('gv.rack.save_rack'), apiErrorMessage(err));
    return false;
  }
}

/** Saves a new rack, or the changes to the open one; a smaller rack is refused while something would not fit. */
async function saveRack() {
  savingRack.value = true;
  try {
    if (rackEditing.value) {
      const current = rack.value;
      if (current && (await patchRack({ name: rackForm.value.name.trim() || current.name, units: rackForm.value.units, width: rackForm.value.width }))) rackDialog.value = false;
      return;
    }
    const created = await api.createRack({
      name: rackForm.value.name.trim() || `Rack ${racks.value.length + 1}`,
      units: rackForm.value.units,
      width: rackForm.value.width,
    });
    rackDialog.value = false;
    await load(created.id);
  } catch (err) {
    showToast('error', t('gv.racks.create'), apiErrorMessage(err));
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
    showToast('error', t('gv.racks.delete'), apiErrorMessage(err));
  }
}

/** Switching the density keeps the selected faceplate in view */
async function setDensity(next: 'fit' | 'detail') {
  density.value = next;
  await nextTick();
  if (selectedKey.value) stageRef.value?.reveal(selectedKey.value);
}

function switchRack(rackId: number) {
  selectedRackId.value = rackId;
  selectedKey.value = null;
  focusCableId.value = null;
  pendingPortId.value = null;
}

const inspectorTitle = computed(() => (cableDetail.value ? t('gv.rack.cable_title') : (selected.value?.label ?? rack.value?.name ?? '')));
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
      <header class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2.5">
        <div class="flex max-w-full min-w-0 items-center gap-1">
          <div class="flex min-w-0 overflow-x-auto rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('rack.select_rack')">
            <button
              v-for="r in racks"
              :key="r.id"
              type="button"
              class="h-7 shrink-0 rounded-sm px-3 text-xs font-semibold transition-colors max-md:h-9"
              :class="r.id === selectedRackId ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="r.id === selectedRackId"
              @click="switchRack(r.id)"
            >
              {{ r.name }}
            </button>
          </div>
          <Button size="icon-sm" variant="ghost" :aria-label="t('gv.racks.new')" :title="t('gv.racks.new')" @click="openCreate"><Plus aria-hidden="true" /></Button>
        </div>

        <p class="hidden flex-wrap items-center gap-x-2.5 font-mono text-xs text-fg-muted tabular sm:flex" aria-live="polite">
          <span>{{ overview.occupied }}/{{ t('gv.rack.units_label', { count: overview.units }) }}</span>
          <span>{{ t('gv.rack.overview_devices', { count: overview.devices }) }}</span>
          <button v-if="overview.offline" type="button" class="font-semibold text-danger-text underline-offset-2 hover:underline" :title="t('gv.rack.next_offline')" @click="nextOffline">
            {{ t('gv.rack.offline_count', { count: overview.offline }) }}
          </button>
          <span>{{ t('gv.rack.overview_cables', { count: overview.cables }) }}</span>
        </p>

        <div class="ml-auto flex flex-wrap items-center gap-1.5">
          <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.rack.side_title')">
            <button
              v-for="s in (['front', 'rear'] as const)"
              :key="s"
              type="button"
              class="inline-flex h-7 items-center gap-1.5 rounded-sm px-2.5 text-xs font-semibold transition-colors max-md:h-9"
              :class="side === s ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="side === s"
              @click="side = s"
            >
              <RotateCcw v-if="side !== s" class="size-3" aria-hidden="true" />{{ t(`gv.rack.side_${s}`) }}
            </button>
          </div>
          <div class="hidden rounded-md border border-line bg-sunken p-0.5 sm:flex" role="group" :aria-label="t('gv.racks.width')">
            <button
              v-for="w in [19, 10]"
              :key="w"
              type="button"
              class="h-7 rounded-sm px-2 font-mono text-xs transition-colors max-md:h-9"
              :class="rack.width === w ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="rack.width === w"
              @click="rack.width !== w && patchRack({ width: w })"
            >
              {{ w }}″
            </button>
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            :class="vitality !== 'off' ? 'text-accent-text' : ''"
            :title="t('gv.orbit.motion', { mode: t(`gv.orbit.motion_${vitality}`) })"
            :aria-label="t('gv.orbit.motion', { mode: t(`gv.orbit.motion_${vitality}`) })"
            @click="cycleVitality"
          >
            <Sparkles aria-hidden="true" />
          </Button>
          <Button size="icon-sm" variant="ghost" :aria-label="t('gv.rack.edit_rack')" :title="t('gv.rack.edit_rack')" @click="openEditRack"><Pencil aria-hidden="true" /></Button>
          <Button size="icon-sm" variant="danger-ghost" :aria-label="t('gv.racks.delete')" :title="t('gv.racks.delete')" @click="removeRack"><Trash2 aria-hidden="true" /></Button>
          <Button v-if="!isLg" size="sm" @click="paletteOpen = true"><Plus aria-hidden="true" />{{ t('gv.rack.palette_title') }}</Button>
        </div>
      </header>

      <div class="flex min-h-0 flex-1">
        <div v-if="isLg" class="relative flex shrink-0 border-r border-line" :style="{ width: `${paletteWidth}px` }">
          <RackPalette
            class="min-w-0 flex-1"
            :stored="stored"
            :unracked="unracked"
            :selected-key="selectedKey"
            :drag="drag"
            :hidden-count="hiddenDevices"
            :show-all="showAllDevices"
            @toggle-all="showAllDevices = !showAllDevices"
            @grab="startDrag"
            @place="(subject) => subject.itemKind && placeKind(subject.itemKind)"
            @select="select"
          />
          <!-- Drag the edge to make the column wider; arrow keys while it has focus, a double click resets it -->
          <div
            class="rack-column-grip"
            :class="paletteResize && 'is-active'"
            role="separator"
            aria-orientation="vertical"
            tabindex="0"
            :aria-label="t('gv.rack.palette_width')"
            :aria-valuenow="paletteWidth"
            :aria-valuemin="PALETTE_MIN"
            :aria-valuemax="PALETTE_MAX"
            :title="t('gv.rack.palette_width_hint')"
            @pointerdown="startPaletteResize"
            @dblclick="paletteWidth = PALETTE_DEFAULT"
            @keydown.left.prevent="setPaletteWidth(paletteWidth - 16)"
            @keydown.right.prevent="setPaletteWidth(paletteWidth + 16)"
          />
        </div>

        <div class="relative min-w-0 flex-1">
          <RackStage
            ref="stageRef"
            class="h-full"
            :rack-name="rack.name"
            :units="rack.units"
            :inches="rack.width"
            :entries="placed"
            :ports="cabling.ports"
            :cables="cabling.cables"
            :side="side"
            :selected-key="selectedKey"
            :colour-of-port="colourOfPort"
            :down-ports="downPorts"
            :accent-of="accentOf"
            :owner-label="ownerLabels"
            :elsewhere="elsewhere"
            :ambient="vitality !== 'off'"
            :pending-port-id="pendingPortId"
            :highlight-cable-id="highlightCableId"
          :peer-of-port="peerOfPort"
            :drag="drag"
            :detail="density === 'detail'"
            @grab="grabEntry"
            @select="select"
            @open="openEntry"
            @nudge="nudge"
            @remove="unplace"
            @connect="connect"
            @pick="pickPort"
            @pick-cable="pickCable"
            @stub="followStub"
            @resize="(units) => patchRack({ units })"
          />
          <div class="absolute right-3 bottom-3 z-10 flex overflow-hidden rounded-md border border-line bg-surface shadow-pop" role="group" :aria-label="t('gv.rack.density')">
            <button
              v-for="d in ([{ id: 'fit', icon: Shrink }, { id: 'detail', icon: ZoomIn }] as const)"
              :key="d.id"
              type="button"
              class="inline-flex h-8 items-center gap-1.5 px-2.5 text-xs font-semibold transition-colors max-md:h-11"
              :class="density === d.id ? 'bg-control-hover text-fg' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="density === d.id"
              :title="t(`gv.rack.density_${d.id}_hint`)"
              @click="setDensity(d.id)"
            >
              <component :is="d.icon" class="size-3.5" aria-hidden="true" />{{ t(`gv.rack.density_${d.id}`) }}
            </button>
          </div>
        </div>

        <aside v-if="isXl" class="w-72 shrink-0 overflow-y-auto border-l border-line">
          <RackInspector
            :entry="selected"
            :in-rack="selectedInRack"
            :position="selectedPosition"
            :ports="selectedPorts"
            :cables="cableRows"
            :colour-of-port="colourOfPort"
            :pending-port-id="pendingPortId"
            :pending-label="pendingLabel"
            :max-height="selectedMaxHeight"
            :cable="cableDetail"
            :swatches="swatches"
            :overview="overview"
            :targets="selectedTargets"
            :issue="selected ? issueOf.has(selected.key) : false"
            :peer-of-port="peerOfPort"
            @place-at="(unit) => selected && placeAt(selected, unit)"
            @close="select(null)"
            @open="selected && openEntry(selected.key)"
            @edit="selected && openEntry(selected.key)"
            @remove="deleteItem"
            @unplace="selected && unplace(selected.key)"
            @detach="selected && detach(selected.key)"
            @place="selected && placeNear(selected)"
            @rename="renameItem"
            @set-height="setHeight"
            @set-ports="setPorts"
            @pick="pickPort"
            @cancel-pick="pendingPortId = null"
            @hover-cable="(cableId) => (hoverCableId = cableId)"
            @remove-cable="removeCable"
            @patch-cable="patchCable"
            @select="reveal"
          />
        </aside>
      </div>

      <!-- Below xl the details open as a sheet; a slim bar says what is selected -->
      <div v-if="!isXl && (selected || cableDetail)" class="flex items-center gap-3 border-t border-line px-4 py-2">
        <p class="min-w-0 flex-1 truncate text-sm">
          <span class="font-semibold text-fg">{{ inspectorTitle }}</span>
          <span v-if="selectedPosition" class="ml-2 font-mono text-xs text-fg-subtle">{{ selectedPosition }}</span>
        </p>
        <Button size="sm" @click="inspectorOpen = true"><PanelRight aria-hidden="true" />{{ t('gv.rack.details') }}</Button>
      </div>
    </template>

    <Sheet v-if="rack && !isXl" v-model:open="inspectorOpen" :title="inspectorTitle" width="md">
      <RackInspector
        class="-mx-4 -my-4"
        :entry="selected"
        :in-rack="selectedInRack"
        :position="selectedPosition"
        :ports="selectedPorts"
        :cables="cableRows"
        :colour-of-port="colourOfPort"
        :pending-port-id="pendingPortId"
        :pending-label="pendingLabel"
        :max-height="selectedMaxHeight"
        :cable="cableDetail"
        :swatches="swatches"
        :overview="overview"
        :targets="selectedTargets"
        :issue="selected ? issueOf.has(selected.key) : false"
        :peer-of-port="peerOfPort"
        @place-at="(unit) => selected && placeAt(selected, unit)"
        @close="inspectorOpen = false"
        @open="selected && openEntry(selected.key)"
        @edit="selected && openEntry(selected.key)"
        @remove="deleteItem"
        @unplace="selected && unplace(selected.key)"
        @detach="selected && detach(selected.key)"
        @place="selected && placeNear(selected)"
        @rename="renameItem"
        @set-height="setHeight"
        @set-ports="setPorts"
        @pick="(port) => { pickPort(port); inspectorOpen = false; }"
        @cancel-pick="pendingPortId = null"
        @hover-cable="(cableId) => (hoverCableId = cableId)"
        @remove-cable="removeCable"
        @patch-cable="patchCable"
        @select="(key) => { inspectorOpen = false; reveal(key); }"
      />
    </Sheet>

    <Sheet v-if="rack && !isLg" v-model:open="paletteOpen" :title="t('gv.rack.palette_title')" width="md">
      <RackPalette
        class="-mx-5 -my-4"
        :stored="stored"
        :unracked="unracked"
        :selected-key="selectedKey"
        :drag="null"
        :hidden-count="hiddenDevices"
        :show-all="showAllDevices"
        tap-only
        @toggle-all="showAllDevices = !showAllDevices"
        @place="(subject) => subject.itemKind && placeKind(subject.itemKind)"
        @select="(key) => { const entry = findEntry(key); paletteOpen = false; if (entry) placeNear(entry); }"
      />
    </Sheet>

    <!-- What is being dragged, next to the pointer while it is outside the rack -->
    <div
      v-if="dragChip"
      class="pointer-events-none fixed z-50 flex items-center gap-2 rounded-md border bg-surface px-2.5 py-1.5 text-xs shadow-pop"
      :class="dragChip.zone === 'store' || dragChip.zone === 'unrack' ? 'border-warn text-warn-text' : 'border-line-strong text-fg'"
      :style="{ left: `${dragChip.x + 14}px`, top: `${dragChip.y + 12}px` }"
      aria-hidden="true"
    >
      <span v-if="dragChip.device" class="size-2 rounded-full bg-accent" />
      <component :is="dragChip.icon" v-else class="size-3.5 text-fg-muted" />
      <span class="font-semibold">{{ dragChip.label }}</span>
      <span class="font-mono text-micro text-fg-subtle">{{ t('gv.rack.units_label', { count: dragChip.height }) }}</span>
    </div>

    <RackItemDialog v-if="rack" v-model:open="itemDialog" :rack-id="rack.id" :item="editingItem" @saved="onItemSaved" />

    <Dialog v-model:open="rackDialog" :title="rackEditing ? t('gv.rack.edit_rack') : t('gv.racks.new')" size="sm">
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
        <p class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.rack.size_hint') }}</p>
      </form>
      <template #footer>
        <Button @click="rackDialog = false">{{ t('common.cancel') }}</Button>
        <Button variant="primary" type="submit" :form="`${id}-form`" :loading="savingRack">
          <Plus v-if="!savingRack && !rackEditing" aria-hidden="true" />{{ rackEditing ? t('gv.rack.save_rack') : t('gv.racks.create') }}
        </Button>
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
/* The edge of the palette column: a slim strip that lights up and shows the resize cursor */
.rack-column-grip {
  position: absolute;
  top: 0;
  right: -4px;
  bottom: 0;
  z-index: 10;
  width: 8px;
  cursor: col-resize;
  touch-action: none;
  outline: none;
}
.rack-column-grip::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 3px;
  width: 2px;
  background: transparent;
  transition: background-color 120ms ease-out;
}
.rack-column-grip:hover::after,
.rack-column-grip:focus-visible::after,
.rack-column-grip.is-active::after {
  background: var(--gl-accent);
}
</style>
