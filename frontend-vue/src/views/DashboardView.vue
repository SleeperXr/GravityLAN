<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useMediaQuery, useStorage } from '@vueuse/core';
import { useRouter } from 'vue-router';
import { Check, LayoutGrid, List, Pencil, Radar, RefreshCw, RotateCcw, Search, Server, Trash2, X } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device } from '@/types';
import { useNetworkStore } from '@/stores/network';
import { useDashboardScan } from '@/composables/useDashboardScan';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { swapGroupOrder } from '@shared/components/Dashboard/overview/layout';
import { isAgentOutdated } from '@/lib/agent';
import { deviceLabel } from '@/lib/networks';
import PageHeader from '@/components/ui/PageHeader.vue';
import Button from '@/components/ui/Button.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import ErrorState from '@/components/ui/ErrorState.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import GroupSection from '@/components/dashboard/GroupSection.vue';
import GatewaysPopover from '@/components/dashboard/GatewaysPopover.vue';
import NotificationCenter from '@/components/dashboard/NotificationCenter.vue';
import ScanDialog from '@/components/dashboard/ScanDialog.vue';
import AgentUpdateCenter from '@/components/dashboard/AgentUpdateCenter.vue';
import DeviceEditor from '@/components/editor/DeviceEditor.vue';
import LineStatusBoard from '@/components/dashboard/LineStatusBoard.vue';
import ServiceNotices from '@/components/dashboard/ServiceNotices.vue';
import NetworkPulse from '@/components/dashboard/NetworkPulse.vue';
import OrbitMap from '@/components/orbit/OrbitMap.vue';
import type { EditorTab } from '@shared/components/Dashboard/editor/deviceForm';
import { t } from '@/i18n';

const store = useNetworkStore();
const router = useRouter();
const scan = useDashboardScan();
const { showToast } = useToast();
const { confirm } = useConfirm();

const isMobile = useMediaQuery('(max-width: 767px)');
/** Map and notices sit side by side from xl; stacked below, the notices come first and do not scroll inside */
const isWide = useMediaQuery('(min-width: 1280px)');
const STACKED_NOTICES = 4;
const storedView = useStorage<'grid' | 'list'>('gravityui.dashboard.view', 'grid');
const viewMode = computed(() => (isMobile.value ? 'list' : storedView.value));
const collapsed = useStorage<(number | 'none')[]>('gravityui.dashboard.collapsed', []);

const editMode = ref(false);
const selectedIds = ref(new Set<number>());
const refreshingAll = ref(false);
const updateCenterOpen = ref(false);
const query = ref('');
const searchInputRef = ref<HTMLInputElement | null>(null);
const statusFilter = ref<'all' | 'online' | 'offline'>('all');
/** Network orbit chosen on the status board; the overview then shows only that network. */
const lineFilter = ref<number | null>(null);

const editorDevice = ref<Device | null>(null);
const editorTab = ref<EditorTab>('settings');
const editorOpen = ref(false);

function onGlobalKeyDown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    searchInputRef.value?.focus();
    searchInputRef.value?.select();
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKeyDown));

// Keep the overview current outside edit mode: every 10 s during a scan, 30 s otherwise.
let timer: number | undefined;
watch(
  () => [editMode.value, store.isScanning] as const,
  ([editing, scanning]) => {
    window.clearInterval(timer);
    timer = editing ? undefined : window.setInterval(() => void store.loadData(true), scanning ? 10000 : 30000);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  window.clearInterval(timer);
  window.removeEventListener('keydown', onGlobalKeyDown);
});
if (!store.loaded) void store.loadData();

const outdatedAgents = computed(
  () => store.devices.filter((d) => d.has_agent && isAgentOutdated(d.agent_info?.agent_version, d.agent_info?.latest_version)).length,
);
const filtering = computed(() => !editMode.value && (query.value.trim() !== '' || statusFilter.value !== 'all' || lineFilter.value !== null));

const filteredDevices = computed(() => {
  if (!filtering.value) return store.devices;
  const words = query.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return store.devices.filter((d) => {
    if (statusFilter.value === 'online' && !d.is_online) return false;
    if (statusFilter.value === 'offline' && d.is_online) return false;
    if (lineFilter.value !== null && d.subnet_id !== lineFilter.value && !d.interfaces?.some((i) => i.subnet_id === lineFilter.value)) return false;
    if (words.length === 0) return true;
    const hay = [deviceLabel(d), d.hostname, d.ip, d.mac, d.vendor, d.notes, d.parent_name, ...(d.interfaces ?? []).map((i) => i.ip), ...d.services.map((s) => `${s.name} ${s.port}`)]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return words.every((w) => hay.includes(w));
  });
});

/** Named groups with devices, then the unassigned devices (also shown alone when there are no groups). */
const sections = computed(() => {
  const groups = store.sortedGroups;
  return [...groups, null]
    .map((group) => ({ group, devices: filteredDevices.value.filter((d) => d.group_id === (group ? group.id : null)) }))
    .filter(({ group, devices }) => devices.length > 0 || (!group && groups.length === 0 && !filtering.value));
});

const groupRefs = ref<InstanceType<typeof GroupSection>[]>([]);

function keyOf(groupId: number | null): number | 'none' {
  return groupId ?? 'none';
}
function toggleGroup(groupId: number | null) {
  const key = keyOf(groupId);
  collapsed.value = collapsed.value.includes(key) ? collapsed.value.filter((k) => k !== key) : [...collapsed.value, key];
}

function openEditor(device: Device, tab: EditorTab = 'settings') {
  editorDevice.value = device;
  editorTab.value = tab;
  editorOpen.value = true;
}
async function openDeviceById(id: number, tab?: EditorTab) {
  const known = store.devices.find((d) => d.id === id);
  if (known) return openEditor(known, tab);
  try {
    openEditor(await api.getDevice(id), tab);
  } catch {
    // device vanished in the meantime
  }
}

function toggleSelected(id: number, selected: boolean) {
  const next = new Set(selectedIds.value);
  if (selected) next.add(id);
  else next.delete(id);
  selectedIds.value = next;
}

function toggleEdit() {
  editMode.value = !editMode.value;
  if (!editMode.value) selectedIds.value = new Set();
}

async function bulkDelete() {
  const count = selectedIds.value.size;
  if (count === 0) return;
  const ok = await confirm({ title: t('dashboard.delete_selected', { count }), message: t('dashboard.bulk_delete_confirm', { count }), danger: true, confirmLabel: t('common.delete') });
  if (!ok) return;
  try {
    await api.bulkDeleteDevices([...selectedIds.value]);
    selectedIds.value = new Set();
    showToast('success', t('notifications.deleted'), '');
  } catch (err) {
    showToast('error', t('notifications.delete_failed'), (err as Error).message);
  }
  await store.loadData(true);
}

async function moveGroup(groupId: number | null, direction: 'up' | 'down') {
  const group = store.sortedGroups.find((g) => g.id === groupId);
  if (!group) return;
  const change = swapGroupOrder(store.sortedGroups, group, direction);
  if (!change) return;
  store.groups = change.groups;
  try {
    for (const { id, sort_order } of change.updates) await api.updateGroup(id, { sort_order });
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
  await store.loadData(true);
}

async function refreshAll() {
  refreshingAll.value = true;
  showToast('info', t('dashboard.refreshing'), t('notifications.refresh_started_details'));
  try {
    await api.refreshAllDevices();
    window.setTimeout(() => void store.loadData(true), 1500);
    showToast('success', t('dashboard.refresh_all'), t('notifications.info_updated'));
  } catch (err) {
    showToast('error', t('common.error'), t('notifications.refresh_failed', { error: (err as Error).message }));
  } finally {
    refreshingAll.value = false;
  }
}

async function resetLayout() {
  const ok = await confirm({ title: t('dashboard.reset_layout'), message: t('dashboard.reset_layout_confirm'), danger: true });
  if (!ok) return;
  try {
    await Promise.all(store.devices.map((d) => api.updateDevice(d.id, { x: null, y: null, w: null, h: null })));
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
  await store.loadData(true);
}

function compactAll() {
  groupRefs.value.forEach((section) => section?.compact());
}

async function saveTile(id: number, layout: { x?: number; y?: number; w?: number; h?: number }) {
  store.patchDevice(id, { x: layout.x ?? null, y: layout.y ?? null, w: layout.w ?? null, h: layout.h ?? null });
  await api.updateDevice(id, layout).catch((err) => showToast('error', t('notifications.save_failed'), (err as Error).message));
}

async function moveTile(id: number, groupId: number | null, layout: { x?: number; y?: number; w?: number; h?: number }) {
  try {
    await api.updateDevice(id, { group_id: groupId, ...layout });
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  }
  await store.loadData(true);
}

function clearFilters() {
  query.value = '';
  statusFilter.value = 'all';
  lineFilter.value = null;
}
</script>

<template>
  <div class="mx-auto max-w-[1800px] space-y-6 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('sidebar.dashboard')" :description="t('dashboard.devices_sections', { devices: store.totalCount, groups: store.groups.length })">
      <template v-if="!editMode">
        <!-- A row of its own on phones; squeezed between the buttons it shrank to its icon -->
        <label v-if="store.totalCount > 0" class="relative w-full sm:w-64">
          <span class="sr-only">{{ t('gv.dashboard.search') }}</span>
          <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
          <input
            ref="searchInputRef"
            v-model="query"
            type="search"
            :placeholder="t('gv.dashboard.search')"
            class="h-9 w-full rounded-md border border-line bg-sunken pr-14 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-line-strong focus:border-info focus:ring-2 focus:ring-info/25 focus:outline-none"
          />
          <kbd class="pointer-events-none absolute top-1/2 right-2.5 hidden -translate-y-1/2 rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-fg-subtle sm:inline">
            Ctrl K
          </kbd>
        </label>
        <div v-if="!isMobile" class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('dashboard.view_mode')">
          <button
            v-for="mode in [{ id: 'grid', icon: LayoutGrid, label: t('dashboard.view_grid') }, { id: 'list', icon: List, label: t('dashboard.view_list') }] as const"
            :key="mode.id"
            type="button"
            class="inline-flex size-8 items-center justify-center rounded-[5px] transition-colors"
            :class="storedView === mode.id ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="storedView === mode.id"
            :aria-label="mode.label"
            :title="mode.label"
            @click="storedView = mode.id"
          >
            <component :is="mode.icon" class="size-4" aria-hidden="true" />
          </button>
        </div>
        <GatewaysPopover @open-device="(id, tab) => openDeviceById(id, tab)" />
        <NotificationCenter />
        <Button v-if="outdatedAgents > 0" class="border-warn/40 text-warn-text" @click="updateCenterOpen = true">
          <RefreshCw aria-hidden="true" />{{ outdatedAgents }}<span class="hidden sm:inline">{{ t('dashboard.agent_updates') }}</span>
        </Button>
        <Button :aria-label="t('dashboard.edit_layout')" :title="t('dashboard.edit_layout')" @click="toggleEdit">
          <Pencil aria-hidden="true" /><span class="hidden xl:inline">{{ t('dashboard.edit_layout') }}</span>
        </Button>
        <Button :disabled="refreshingAll || store.isScanning" :aria-label="t('dashboard.refresh_all')" @click="refreshAll">
          <RefreshCw :class="refreshingAll && 'animate-spin'" aria-hidden="true" /><span class="hidden xl:inline">{{ refreshingAll ? t('dashboard.refreshing') : t('dashboard.refresh_all') }}</span>
        </Button>
        <Button variant="primary" :disabled="store.isScanning" @click="scan.openDialog()">
          <Radar :class="store.isScanning && 'animate-spin'" aria-hidden="true" />{{ store.isScanning ? t('dashboard.scanning') : t('dashboard.scan') }}
        </Button>
      </template>
      <template v-else>
        <Button v-if="selectedIds.size > 0" variant="danger" @click="bulkDelete">
          <Trash2 aria-hidden="true" />{{ t('dashboard.delete_selected', { count: selectedIds.size }) }}
        </Button>
        <Button v-if="viewMode === 'grid'" :title="t('dashboard.compact_hint')" @click="compactAll">
          <LayoutGrid aria-hidden="true" />{{ t('dashboard.compact') }}
        </Button>
        <Button @click="resetLayout"><RotateCcw aria-hidden="true" />{{ t('dashboard.reset_layout') }}</Button>
        <Button variant="primary" @click="toggleEdit"><Check aria-hidden="true" />{{ t('dashboard.edit_finish') }}</Button>
      </template>
    </PageHeader>

    <!-- Status first: the one-line answer, the status board, what needs attention, then the orbit map -->
    <template v-if="store.loaded && store.totalCount > 0 && !editMode">
      <div class="space-y-3">
        <NetworkPulse :devices="store.devices" :updated="store.lastUpdated" :failed="!!store.error" />
        <LineStatusBoard v-if="store.subnets.length > 0" :subnets="store.subnets" :devices="store.devices" :active="lineFilter" @select="(id) => (lineFilter = id)" />
      </div>
      <!-- Notices left of the map from xl, so reading, tab and screen order are the same -->
      <div class="grid gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <ServiceNotices
          :class="isWide && 'max-h-[32rem]'"
          :limit="isWide ? undefined : STACKED_NOTICES"
          :devices="store.devices"
          @open-device="(d) => openEditor(d)"
          @open-updates="updateCenterOpen = true"
          @open-patches="router.push('/agents')"
        />
        <!-- Title and edit link sit above the map: on top of it the map's own search covered them -->
        <div class="gl-card flex h-[24rem] flex-col overflow-hidden md:h-[32rem]">
          <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <div class="min-w-0">
              <p class="text-sm font-bold text-fg">{{ t('gv.plan.title') }}</p>
              <p class="text-xs text-fg-subtle">{{ t('gv.plan.live', { online: store.onlineCount, total: store.totalCount }) }}</p>
            </div>
            <RouterLink to="/topology" class="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 text-xs font-semibold text-fg hover:border-line-strong">
              <Pencil class="size-3.5" aria-hidden="true" />{{ t('gv.plan.edit') }}
            </RouterLink>
          </div>
          <div class="min-h-0 flex-1">
            <OrbitMap flow-id="dashboard-plan" @open-device="(d) => openEditor(d)" />
          </div>
        </div>
      </div>
    </template>

    <!-- Active Filter Bar -->
    <div v-if="filtering" class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-fg-subtle" role="status">{{ t('gv.dashboard.matches', { count: filteredDevices.length, total: store.totalCount }) }}</span>
      <Button variant="ghost" size="sm" @click="clearFilters">
        <X aria-hidden="true" />{{ t('gv.dashboard.clear_filter') }}
      </Button>
    </div>

    <!-- States -->
    <div v-if="store.isLoading && !store.loaded" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true" :aria-label="t('dashboard.loading')">
      <Skeleton v-for="i in 8" :key="i" class="h-40" />
    </div>
    <div v-else-if="store.error && !store.loaded" class="gl-card">
      <ErrorState :message="store.error" @retry="store.loadData()" />
    </div>
    <div v-else-if="store.totalCount === 0" class="gl-card">
      <EmptyState :icon="Server" :title="t('dashboard.no_devices_title')" :description="t('dashboard.no_devices_text')">
        <Button variant="primary" @click="scan.openDialog()"><Radar aria-hidden="true" />{{ t('dashboard.scan_now') }}</Button>
      </EmptyState>
    </div>
    <div v-else-if="filtering && filteredDevices.length === 0" class="gl-card">
      <EmptyState compact :icon="Search" :title="t('gv.dashboard.no_match')">
        <Button size="sm" @click="clearFilters">{{ t('gv.dashboard.clear_filter') }}</Button>
      </EmptyState>
    </div>

    <div v-else class="space-y-7">
      <GroupSection
        v-for="({ group, devices }, index) in sections"
        :key="group ? group.id : 'none'"
        ref="groupRefs"
        :group="group"
        :devices="devices"
        :is-first="index === 0"
        :is-last="group ? store.sortedGroups.findIndex((g) => g.id === group.id) === store.sortedGroups.length - 1 : true"
        :collapsed="collapsed.includes(keyOf(group ? group.id : null))"
        :edit-mode="editMode"
        :view-mode="viewMode"
        :selected-ids="selectedIds"
        @toggle="toggleGroup(group ? group.id : null)"
        @move="(direction) => moveGroup(group ? group.id : null, direction)"
        @select="toggleSelected"
        @edit="(device) => openEditor(device)"
        @refresh="store.loadData(true)"
        @tile-change="saveTile"
        @tile-moved="moveTile"
      />
    </div>

    <ScanDialog v-model:open="scan.dialogOpen.value" :targets="scan.targets.value" :starting="scan.starting.value" @start="scan.startScan" />
    <AgentUpdateCenter v-model:open="updateCenterOpen" :devices="store.devices" @complete="store.loadData(true)" />
    <DeviceEditor
      v-if="editorDevice"
      v-model:open="editorOpen"
      :device="editorDevice"
      :initial-tab="editorTab"
      @saved="store.loadData(true)"
      @after-leave="editorDevice = null"
    />
  </div>
</template>
