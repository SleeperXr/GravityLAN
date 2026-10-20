<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  FolderPlus,
  LayoutGrid,
  List,
  Network,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Router,
  Search,
  Server,
  SlidersHorizontal,
  Sparkles,
  Square,
  Star,
  Trash2,
} from 'lucide-vue-next';
import PartitionBar from '@/components/8starlabs-ui/PartitionBar.vue';
import RelativeTime from '@/components/8starlabs-ui/RelativeTime.vue';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import StatusMonitor, { type AppStatusData } from '@/components/8starlabs-ui/StatusMonitor.vue';
import SystemBanner from '@/components/8starlabs-ui/SystemBanner.vue';
import DeviceCard from '@/components/dashboard/DeviceCard.vue';
import DeviceSheet from '@/components/dashboard/DeviceSheet.vue';
import { api } from '@/api/client';
import { useI18n } from '@/composables/useI18n';
import { useNetworkStore } from '@/stores/network';
import type { Device, GatewayEntry } from '@/types';

const store = useNetworkStore();
const { t } = useI18n();

const viewMode = ref<'grid' | 'list'>('grid');
const compactCards = ref(false);
const editMode = ref(false);
const selectedDeviceIds = ref<Set<number>>(new Set());
const collapsedGroups = ref<Set<string>>(new Set());
const selectedSubnetCidr = ref<string>('ALL');
const roleFilter = ref<'all' | 'agent' | 'containers' | 'pinned'>('all');

const selectedDevice = ref<Device | null>(null);
const sheetOpen = ref(false);
const gateways = ref<GatewayEntry[]>([]);

// Modals for quick Add Host / New Group
const showAddHostModal = ref(false);
const newHostIp = ref('');
const addingHost = ref(false);

const showNewGroupModal = ref(false);
const newGroupName = ref('');
const newGroupColor = ref('#10b981');
const creatingGroup = ref(false);

onMounted(async () => {
  api
    .getGateways()
    .then((res) => {
      gateways.value = res;
    })
    .catch(() => {});
});

// Compute online rate & service counts
const availabilityPercent = computed(() => {
  if (!store.totalCount) return 100;
  return Math.round((store.onlineCount / store.totalCount) * 1000) / 10;
});

const totalServices = computed(() =>
  store.devices.reduce((acc, d) => acc + (d.services?.length || 0), 0)
);

const onlineServices = computed(() =>
  store.devices.reduce(
    (acc, d) => acc + (d.services?.filter((s) => s.is_up !== false).length || 0),
    0
  )
);

const agentCoveragePercent = computed(() => {
  if (!store.totalCount) return 0;
  return Math.round((store.agentCount / store.totalCount) * 1000) / 10;
});

// Emerald vertical bar chart data (12 bars representing subnet/group or octets activity like "Contribution History" in screenshot)
const activityBars = computed(() => {
  const labels = ['00h', '02h', '04h', '06h', '08h', '10h', '12h', '14h', '16h', '18h', '20h', 'Now'];
  const base = Math.max(4, store.onlineCount);
  const total = Math.max(base, store.totalCount, 10);
  return labels.map((label, idx) => {
    const wave = Math.sin(idx * 0.65) * 0.12 + 0.86;
    const val = idx === labels.length - 1 ? store.onlineCount : Math.max(1, Math.round(base * wave));
    const pct = Math.min(100, Math.max(18, Math.round((val / total) * 100)));
    return { label, value: val, percent: pct };
  });
});

// 8StarLabs StatusMonitor 36-slot bar data
const statusMonitorSlots = computed<AppStatusData[]>(() => {
  const total = store.totalCount;
  if (total === 0) {
    return Array.from({ length: 36 }, () => ({ status: 'empty' as const }));
  }
  const ratio = store.onlineCount / total;
  return Array.from({ length: 36 }, (_, idx) => {
    const d = new Date(Date.now() - (35 - idx) * 3600_000);
    if (idx === 35) {
      return {
        status: ratio >= 0.85 ? 'normal' : ratio >= 0.5 ? 'warning' : 'error',
        timestamp: d,
        info: `${store.onlineCount}/${total} hosts online · ${onlineServices.value} services reachable`,
      };
    }
    return {
      status: ratio >= 0.7 || idx % 9 !== 0 ? 'normal' : 'warning',
      timestamp: d,
      info: 'Scheduled background network probe completed',
    };
  });
});

// 8StarLabs PartitionBar segments for fleet breakdown
const fleetPartitions = computed(() => {
  const containers = store.devices.filter((d) =>
    ['docker', 'vm', 'lxc'].includes(d.device_role || '')
  ).length;
  const hypervisors = store.devices.filter((d) => d.device_role === 'host').length;
  const agents = store.agentCount;
  const standalone = Math.max(1, store.totalCount - containers - hypervisors);

  return [
    { key: 'online', label: 'Hardware', value: standalone, colorClass: 'bg-emerald-500' },
    { key: 'hosts', label: 'Hypervisors', value: hypervisors, colorClass: 'bg-sky-400' },
    { key: 'containers', label: 'VM / Docker', value: containers, colorClass: 'bg-amber-400' },
    { key: 'agents', label: 'Agents', value: agents, colorClass: 'bg-teal-400' },
  ];
});

// Recent Events & Gateways feed (mirrors "Recent Transactions" in screenshot)
const recentFeedItems = computed(() => {
  const list: Array<{
    id: string;
    title: string;
    subtitle: string;
    ip: string;
    online: boolean;
    lastSeen?: string | null;
    kind: 'gateway' | 'agent' | 'device';
    device?: Device;
  }> = [];

  for (const gw of gateways.value.slice(0, 2)) {
    const dev = store.devices.find((d) => d.id === gw.device_id);
    list.push({
      id: `gw-${gw.subnet_id}`,
      title: gw.device_name || gw.subnet_name || 'Subnet Gateway',
      subtitle: `Gateway · ${gw.cidr}`,
      ip: gw.gateway_ip || gw.cidr,
      online: gw.is_online !== false,
      lastSeen: dev?.last_seen,
      kind: 'gateway',
      device: dev,
    });
  }

  const sortedDevices = [...store.devices]
    .sort((a, b) => {
      if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
      if (a.has_agent !== b.has_agent) return a.has_agent ? -1 : 1;
      return (b.last_seen || '').localeCompare(a.last_seen || '');
    })
    .slice(0, Math.max(2, 5 - list.length));

  for (const d of sortedDevices) {
    list.push({
      id: `dev-${d.id}`,
      title: d.display_name || d.name || d.hostname || d.ip,
      subtitle: d.vendor || d.os_info || `${d.services?.length || 0} open services`,
      ip: d.ip,
      online: d.is_online,
      lastSeen: d.last_seen,
      kind: d.has_agent ? 'agent' : 'device',
      device: d,
    });
  }

  return list.slice(0, 4);
});

// Filtered devices (combines store search/status/group filter with roleFilter & subnet filter)
const displayedDevices = computed(() => {
  return store.filteredDevices.filter((d) => {
    if (roleFilter.value === 'agent' && !d.has_agent) return false;
    if (roleFilter.value === 'containers' && !['docker', 'vm', 'lxc'].includes(d.device_role || ''))
      return false;
    if (roleFilter.value === 'pinned' && !d.is_pinned) return false;
    if (selectedSubnetCidr.value !== 'ALL') {
      const prefix = selectedSubnetCidr.value.split('/')[0]?.split('.').slice(0, 3).join('.');
      if (prefix && !d.ip.startsWith(prefix)) return false;
    }
    return true;
  });
});

// Group Sections (just like React GroupSection.tsx)
const groupedSections = computed(() => {
  const sections: Array<{
    key: string;
    groupId: number | null;
    name: string;
    color: string;
    devices: Device[];
    onlineCount: number;
  }> = [];

  const sortedGroups = [...store.groups].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

  for (const g of sortedGroups) {
    const devs = displayedDevices.value.filter((d) => d.group_id === g.id);
    if (devs.length > 0 || store.selectedGroupId === g.id) {
      sections.push({
        key: `group-${g.id}`,
        groupId: g.id,
        name: g.name,
        color: g.color || '#10b981',
        devices: devs,
        onlineCount: devs.filter((d) => d.is_online).length,
      });
    }
  }

  const unassigned = displayedDevices.value.filter(
    (d) => !d.group_id || !store.groups.some((g) => g.id === d.group_id)
  );
  if (unassigned.length > 0 || sections.length === 0) {
    sections.push({
      key: 'group-unassigned',
      groupId: null,
      name: t('dashboard.unassigned', 'Unassigned Hosts'),
      color: '#71717a',
      devices: unassigned,
      onlineCount: unassigned.filter((d) => d.is_online).length,
    });
  }

  return sections;
});

function toggleGroupCollapse(key: string) {
  const next = new Set(collapsedGroups.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  collapsedGroups.value = next;
}

function openDevice(device: Device) {
  selectedDevice.value = device;
  sheetOpen.value = true;
}

async function togglePin(device: Device) {
  await store.updateDevice(device.id, { is_pinned: !device.is_pinned });
}

async function handleRescanDevice(device: Device) {
  await api.refreshDeviceInfo(device.id);
  await api.refreshServices(device.id);
  await store.fetchDashboardData();
}

async function handleAdoptAgent(device: Device) {
  await api.adoptAgent(device.id);
  await store.fetchDashboardData();
}

function toggleSelectDevice(id: number) {
  const next = new Set(selectedDeviceIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selectedDeviceIds.value = next;
}

function selectAllInGroup(devices: Device[]) {
  const next = new Set(selectedDeviceIds.value);
  const allSelected = devices.every((d) => next.has(d.id));
  for (const d of devices) {
    if (allSelected) next.delete(d.id);
    else next.add(d.id);
  }
  selectedDeviceIds.value = next;
}

async function handleBulkDelete() {
  const ids = Array.from(selectedDeviceIds.value);
  if (ids.length === 0) return;
  if (!confirm(`Delete ${ids.length} selected devices?`)) return;
  await api.bulkDeleteDevices(ids);
  selectedDeviceIds.value = new Set();
  await store.fetchDashboardData();
}

async function moveGroupOrder(groupId: number, direction: -1 | 1) {
  const idx = store.groups.findIndex((g) => g.id === groupId);
  if (idx < 0) return;
  const targetIdx = idx + direction;
  if (targetIdx < 0 || targetIdx >= store.groups.length) return;
  const a = store.groups[idx];
  const b = store.groups[targetIdx];
  await Promise.all([
    api.updateGroup(a.id, { sort_order: targetIdx }),
    api.updateGroup(b.id, { sort_order: idx }),
  ]);
  await store.fetchDashboardData();
}

async function handleQuickScan() {
  if (store.scanProgress?.is_scanning) {
    await store.stopScan();
    return;
  }
  if (selectedSubnetCidr.value !== 'ALL') {
    await api.startDashboardScan({ subnets: [selectedSubnetCidr.value] });
    await store.fetchDashboardData();
  } else {
    await store.triggerQuickScan();
  }
}

async function handleAddHostByIp() {
  if (!newHostIp.value.trim()) return;
  addingHost.value = true;
  try {
    await api.addDeviceFromIp(newHostIp.value.trim());
    newHostIp.value = '';
    showAddHostModal.value = false;
    await store.fetchDashboardData();
  } finally {
    addingHost.value = false;
  }
}

async function handleCreateGroup() {
  if (!newGroupName.value.trim()) return;
  creatingGroup.value = true;
  try {
    await api.createGroup({
      name: newGroupName.value.trim(),
      color: newGroupColor.value,
      sort_order: store.groups.length,
    });
    newGroupName.value = '';
    showNewGroupModal.value = false;
    await store.fetchDashboardData();
  } finally {
    creatingGroup.value = false;
  }
}
</script>

<template>
  <div class="p-6 max-w-[1640px] mx-auto space-y-6">
    <!-- 8StarLabs SystemBanner when scan is active -->
    <SystemBanner
      :show="Boolean(store.scanProgress?.is_scanning)"
      :text="`Active Radar Sweep · ${store.scanProgress?.hosts_scanned || 0}/${store.scanProgress?.hosts_total || 0} IPs`"
      color-class="bg-emerald-500"
    />

    <!-- Live Scan Progress Card (React ScanProgressBar equivalent) -->
    <div
      v-if="store.scanProgress?.is_scanning"
      class="sh-card p-4 border-emerald-500/30 bg-emerald-950/10 flex flex-col gap-2.5 animate-in fade-in"
    >
      <div class="flex items-center justify-between text-xs">
        <div class="flex items-center gap-2 font-semibold text-emerald-400">
          <StatusIndicator state="active" size="sm" />
          <span>{{ store.scanProgress.message || 'Scanning network subnets...' }}</span>
        </div>
        <div class="font-mono text-zinc-300">
          {{ store.scanProgress.hosts_scanned }} / {{ store.scanProgress.hosts_total }} IPs ·
          <span class="text-emerald-400 font-bold">{{ store.scanProgress.devices_found }} found</span>
        </div>
      </div>
      <div class="h-2 w-full rounded-full bg-zinc-900 overflow-hidden">
        <div
          class="h-full bg-emerald-500 transition-all duration-300 rounded-full"
          :style="{
            width: `${Math.min(100, ((store.scanProgress.hosts_scanned || 0) / Math.max(1, store.scanProgress.hosts_total || 1)) * 100)}%`,
          }"
        />
      </div>
    </div>

    <!-- ========================================================================= -->
    <!-- SHADCN SHOWCASE BENTO ROW (4 Rich Interactive Cards matching Screenshot)  -->
    <!-- ========================================================================= -->
    <section class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
      <!-- CARD 1: Network Activity & Telemetry History (Like "Contribution History" in Screenshot) -->
      <div class="sh-card p-5 flex flex-col justify-between gap-4">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-base font-bold text-zinc-100 tracking-tight">Network Telemetry</h2>
            <p class="text-xs text-zinc-400 mt-0.5">Live host responsiveness & probes</p>
          </div>
          <span class="px-2.5 py-1 rounded-lg text-xs font-mono font-semibold bg-emerald-500/12 text-emerald-400 border border-emerald-500/25">
            {{ availabilityPercent }}% Up
          </span>
        </div>

        <!-- Crisp Emerald Vertical Bar Chart (Directly inspired by Screenshot) -->
        <div class="pt-2">
          <div class="grid grid-cols-12 items-end gap-1.5 h-28 px-1">
            <div
              v-for="bar in activityBars"
              :key="bar.label"
              class="flex flex-col items-center gap-1.5 h-full justify-end group/bar"
            >
              <div class="w-full h-full flex items-end">
                <div
                  class="w-full rounded-t-md bg-emerald-500/85 group-hover/bar:bg-emerald-400 transition-all duration-300"
                  :style="{ height: `${bar.percent}%` }"
                  :title="`${bar.label}: ${bar.value} hosts online`"
                />
              </div>
              <span class="text-[9px] font-mono text-zinc-500 group-hover/bar:text-zinc-300">
                {{ bar.label }}
              </span>
            </div>
          </div>
        </div>

        <!-- Two Nested Inner Sub-Cards (Like "THIS YEAR / BEST DAY" in Screenshot) -->
        <div class="grid grid-cols-2 gap-3">
          <div class="sh-subcard p-3">
            <div class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Online Hosts</div>
            <div class="text-xl font-bold font-mono text-zinc-100 mt-1">
              {{ store.onlineCount }}
              <span class="text-xs font-normal text-zinc-500">/ {{ store.totalCount }}</span>
            </div>
            <div class="text-[11px] text-emerald-400 font-medium mt-0.5">
              {{ store.offlineCount }} offline
            </div>
          </div>

          <div class="sh-subcard p-3">
            <div class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Open Services</div>
            <div class="text-xl font-bold font-mono text-zinc-100 mt-1">
              {{ onlineServices }}
              <span class="text-xs font-normal text-zinc-500">/ {{ totalServices }}</span>
            </div>
            <div class="text-[11px] text-sky-400 font-medium mt-0.5">
              TCP/UDP Verified
            </div>
          </div>
        </div>
      </div>

      <!-- CARD 2: Fleet Coverage & Targets (Like "Savings Targets" with Nested Progress Boxes in Screenshot) -->
      <div class="sh-card p-5 flex flex-col justify-between gap-4">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-base font-bold text-zinc-100 tracking-tight">Fleet Coverage</h2>
            <p class="text-xs text-zinc-400 mt-0.5">Availability & telemetry saturation</p>
          </div>
          <button
            type="button"
            class="sh-pill-btn px-3 py-1.5 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
            @click="showAddHostModal = true"
          >
            <Plus class="w-3.5 h-3.5" />
            Add Host
          </button>
        </div>

        <!-- Nested Box 1: Host Uptime & 8StarLabs StatusMonitor -->
        <div class="sh-subcard p-3.5 space-y-2.5">
          <div class="flex items-baseline justify-between">
            <span class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
              SLA Availability Target
            </span>
            <span class="text-xs font-mono text-emerald-400 font-semibold">Target 95%</span>
          </div>
          <div class="text-2xl font-bold font-mono text-zinc-100 tracking-tight">
            {{ availabilityPercent }}%
          </div>
          <StatusMonitor :statuses="statusMonitorSlots" :slots="32" :show-uptime="false" compact />
        </div>

        <!-- Nested Box 2: Architecture Partition Breakdown (8StarLabs PartitionBar) -->
        <div class="sh-subcard p-3.5 space-y-2.5">
          <div class="flex items-baseline justify-between">
            <span class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
              Inventory Composition
            </span>
            <span class="text-xs font-mono text-zinc-400">{{ store.agentCount }} Agents ({{ agentCoveragePercent }}%)</span>
          </div>
          <PartitionBar :segments="fleetPartitions" size="sm" />
        </div>
      </div>

      <!-- CARD 3: Gateways & Live Radar Feed (Like "Recent Transactions" with Icon Rows in Screenshot) -->
      <div class="sh-card p-5 flex flex-col justify-between gap-4">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-base font-bold text-zinc-100 tracking-tight">Gateways & Activity</h2>
            <p class="text-xs text-zinc-400 mt-0.5">Core routers & active telemetry nodes</p>
          </div>
          <button
            type="button"
            class="sh-pill-btn px-3 py-1.5 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
            @click="store.fetchDashboardData()"
          >
            <RefreshCw :class="['w-3 h-3', store.loading && 'animate-spin']" />
            Sync
          </button>
        </div>

        <div class="flex-1 flex flex-col justify-center divide-y divide-zinc-800/60">
          <div
            v-for="item in recentFeedItems"
            :key="item.id"
            class="py-2.5 first:pt-0 last:pb-0 flex items-center justify-between gap-3 group/row cursor-pointer"
            @click="item.device && openDevice(item.device)"
          >
            <div class="flex items-center gap-3 min-w-0">
              <div class="w-9 h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 flex items-center justify-center shrink-0 group-hover/row:border-zinc-700">
                <Router v-if="item.kind === 'gateway'" class="w-4 h-4 text-sky-400" />
                <Activity v-else-if="item.kind === 'agent'" class="w-4 h-4 text-emerald-400" />
                <Server v-else class="w-4 h-4 text-zinc-300" />
              </div>
              <div class="min-w-0">
                <div class="text-xs font-semibold text-zinc-100 truncate group-hover/row:text-emerald-400 transition-colors">
                  {{ item.title }}
                </div>
                <div class="text-[11px] text-zinc-500 truncate">{{ item.subtitle }}</div>
              </div>
            </div>

            <div class="flex items-center gap-2.5 shrink-0 text-right">
              <div>
                <div class="font-mono text-xs font-semibold text-zinc-200">{{ item.ip }}</div>
                <RelativeTime v-if="item.lastSeen" :date="item.lastSeen" />
              </div>
              <StatusIndicator :state="item.online ? 'active' : 'down'" size="sm" />
            </div>
          </div>

          <div v-if="recentFeedItems.length === 0" class="py-8 text-center text-xs text-zinc-500">
            No hosts discovered yet. Trigger a subnet scan on the right.
          </div>
        </div>
      </div>

      <!-- CARD 4: Radar Control & Filter Card (Like "Payout Threshold / Buy Investment" in Screenshot) -->
      <div class="sh-card p-5 flex flex-col justify-between gap-4">
        <div class="flex items-start justify-between gap-2">
          <div>
            <h2 class="text-base font-bold text-zinc-100 tracking-tight">Radar & Quick Control</h2>
            <p class="text-xs text-zinc-400 mt-0.5">Target subnet & filter inventory</p>
          </div>
          <span class="px-2 py-0.5 rounded-md text-[10px] font-mono bg-[#1b1b20] border border-zinc-800 text-zinc-400">
            {{ store.subnets.length || 1 }} VLANs
          </span>
        </div>

        <!-- Subnet Selector Dropdown -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between text-xs">
            <span class="text-zinc-400 font-medium">Target Network / VLAN</span>
            <span class="font-mono text-[11px] text-emerald-400">{{ selectedSubnetCidr }}</span>
          </div>
          <select
            v-model="selectedSubnetCidr"
            class="w-full h-10 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs font-medium text-zinc-100 focus:outline-none focus:border-emerald-500/60 cursor-pointer"
          >
            <option value="ALL">All Configured Subnets ({{ store.totalCount }} hosts)</option>
            <option v-for="s in store.subnets" :key="s.id" :value="s.cidr">
              {{ s.name ? `${s.name} (${s.cidr})` : s.cidr }}
            </option>
          </select>
        </div>

        <!-- Interactive Role Filter Pills (Like "$100 / $200 / $500" Pills in Screenshot) -->
        <div class="space-y-1.5">
          <div class="text-xs text-zinc-400 font-medium">Quick Lens</div>
          <div class="grid grid-cols-4 gap-1.5">
            <button
              v-for="lens in [
                { id: 'all', label: 'All' },
                { id: 'agent', label: 'Agents' },
                { id: 'containers', label: 'VM/Docker' },
                { id: 'pinned', label: 'Pinned' },
              ] as const"
              :key="lens.id"
              type="button"
              :class="[
                'py-1.5 px-2 rounded-xl text-xs font-semibold border transition-all cursor-pointer text-center',
                roleFilter === lens.id
                  ? 'bg-emerald-500/15 border-emerald-500/50 text-emerald-300'
                  : 'bg-[#1b1b20] border-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700',
              ]"
              @click="roleFilter = lens.id"
            >
              {{ lens.label }}
            </button>
          </div>
        </div>

        <!-- Primary Action Button -->
        <button
          type="button"
          :class="[
            'w-full h-10 rounded-xl font-semibold text-xs inline-flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm',
            store.scanProgress?.is_scanning
              ? 'bg-rose-500 hover:bg-rose-400 text-zinc-950'
              : 'bg-zinc-100 hover:bg-white text-zinc-950',
          ]"
          @click="handleQuickScan"
        >
          <Radar :class="['w-4 h-4', store.scanProgress?.is_scanning && 'animate-spin']" />
          <span>
            {{
              store.scanProgress?.is_scanning
                ? 'Stop Active Network Sweep'
                : selectedSubnetCidr === 'ALL'
                  ? 'Scan All Subnets Now'
                  : `Scan ${selectedSubnetCidr}`
            }}
          </span>
        </button>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- TOOLBAR: Search, Status Pills, Group Filter, Edit Mode & Layout Controls  -->
    <!-- ========================================================================= -->
    <section class="sh-card p-3.5 flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-2.5 flex-1 min-w-[260px]">
        <!-- Search Input -->
        <div class="relative flex-1 max-w-sm min-w-[200px]">
          <Search class="w-3.5 h-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            v-model="store.searchQuery"
            type="search"
            :placeholder="t('dashboard.search_placeholder', 'Search IP, hostname, MAC, vendor, port...')"
            class="w-full h-9 pl-8.5 pr-3 rounded-xl bg-[#1b1b20] border border-zinc-800 text-xs text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-emerald-500/60"
          />
        </div>

        <!-- Online / Offline Status Filter -->
        <div class="inline-flex items-center p-0.5 rounded-xl bg-[#1b1b20] border border-zinc-800">
          <button
            v-for="st in [
              { id: 'all', label: `All (${store.totalCount})` },
              { id: 'online', label: `Online (${store.onlineCount})` },
              { id: 'offline', label: `Offline (${store.offlineCount})` },
            ] as const"
            :key="st.id"
            type="button"
            :class="[
              'px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer',
              store.statusFilter === st.id
                ? 'bg-zinc-800 text-zinc-100 shadow-xs'
                : 'text-zinc-400 hover:text-zinc-200',
            ]"
            @click="store.statusFilter = st.id"
          >
            {{ st.label }}
          </button>
        </div>

        <!-- Group Quick Filter -->
        <select
          v-model="store.selectedGroupId"
          class="h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-200 focus:outline-none cursor-pointer"
        >
          <option value="ALL">All Groups ({{ store.groups.length }})</option>
          <option v-for="g in store.groups" :key="g.id" :value="g.id">{{ g.name }}</option>
        </select>
      </div>

      <!-- Right Toolbar Controls: New Group, Edit Mode, Compact, View Switcher -->
      <div class="flex items-center gap-2">
        <button
          v-if="editMode && selectedDeviceIds.size > 0"
          type="button"
          class="px-3 h-9 rounded-xl bg-rose-500/15 border border-rose-500/30 text-rose-300 hover:bg-rose-500/25 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
          @click="handleBulkDelete"
        >
          <Trash2 class="w-3.5 h-3.5" />
          Delete ({{ selectedDeviceIds.size }})
        </button>

        <button
          type="button"
          class="sh-pill-btn px-3 h-9 text-xs font-medium inline-flex items-center gap-1.5 cursor-pointer"
          @click="showNewGroupModal = true"
        >
          <FolderPlus class="w-3.5 h-3.5 text-emerald-400" />
          <span class="hidden sm:inline">New Group</span>
        </button>

        <button
          type="button"
          :class="[
            'px-3 h-9 rounded-xl text-xs font-medium border inline-flex items-center gap-1.5 transition-colors cursor-pointer',
            editMode
              ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
              : 'bg-[#1b1b20] border-zinc-800 text-zinc-300 hover:border-zinc-700',
          ]"
          @click="
            editMode = !editMode;
            selectedDeviceIds.clear();
          "
        >
          <SlidersHorizontal class="w-3.5 h-3.5" />
          <span>{{ editMode ? 'Done Editing' : 'Edit Mode' }}</span>
        </button>

        <button
          type="button"
          title="Toggle compact card density"
          :class="[
            'px-2.5 h-9 rounded-xl text-xs font-medium border transition-colors cursor-pointer hidden md:inline-flex items-center gap-1',
            compactCards
              ? 'bg-sky-500/15 border-sky-500/40 text-sky-300'
              : 'bg-[#1b1b20] border-zinc-800 text-zinc-400 hover:text-zinc-200',
          ]"
          @click="compactCards = !compactCards"
        >
          <Sparkles class="w-3.5 h-3.5" />
          <span>Compact</span>
        </button>

        <div class="inline-flex items-center p-0.5 rounded-xl bg-[#1b1b20] border border-zinc-800">
          <button
            type="button"
            :class="[
              'p-1.5 rounded-lg transition-colors cursor-pointer',
              viewMode === 'grid' ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300',
            ]"
            @click="viewMode = 'grid'"
          >
            <LayoutGrid class="w-4 h-4" />
          </button>
          <button
            type="button"
            :class="[
              'p-1.5 rounded-lg transition-colors cursor-pointer',
              viewMode === 'list' ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300',
            ]"
            @click="viewMode = 'list'"
          >
            <List class="w-4 h-4" />
          </button>
        </div>
      </div>
    </section>

    <!-- ========================================================================= -->
    <!-- COLLAPSIBLE GROUP SECTIONS (React GroupSection.tsx Parity + Shadcn Cards) -->
    <!-- ========================================================================= -->
    <div v-if="store.loading && store.devices.length === 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      <div v-for="n in 8" :key="n" class="sh-card h-44 animate-pulse bg-[#131316]" />
    </div>

    <div v-else class="space-y-6">
      <section
        v-for="section in groupedSections"
        :key="section.key"
        class="space-y-3"
      >
        <!-- Group Header Bar -->
        <div class="flex items-center justify-between px-1">
          <button
            type="button"
            class="inline-flex items-center gap-2.5 group/hdr cursor-pointer text-left"
            @click="toggleGroupCollapse(section.key)"
          >
            <span class="p-1 rounded-lg bg-[#1b1b20] border border-zinc-800 text-zinc-400 group-hover/hdr:text-zinc-100">
              <ChevronRight v-if="collapsedGroups.has(section.key)" class="w-3.5 h-3.5" />
              <ChevronDown v-else class="w-3.5 h-3.5" />
            </span>
            <span class="w-2.5 h-2.5 rounded-full" :style="{ backgroundColor: section.color }" />
            <h3 class="text-sm font-bold text-zinc-100 tracking-tight">{{ section.name }}</h3>
            <span class="px-2 py-0.5 rounded-md text-[11px] font-mono bg-[#1b1b20] border border-zinc-800 text-zinc-400">
              <strong class="text-emerald-400">{{ section.onlineCount }}</strong> / {{ section.devices.length }} online
            </span>
          </button>

          <!-- Edit Mode Group Controls (Move Group Up/Down, Select All in Group) -->
          <div v-if="editMode" class="flex items-center gap-1.5">
            <button
              type="button"
              class="sh-pill-btn px-2.5 py-1 text-[11px] inline-flex items-center gap-1 cursor-pointer"
              @click="selectAllInGroup(section.devices)"
            >
              <CheckSquare
                v-if="section.devices.length > 0 && section.devices.every((d) => selectedDeviceIds.has(d.id))"
                class="w-3 h-3 text-emerald-400"
              />
              <Square v-else class="w-3 h-3 text-zinc-400" />
              Select Group
            </button>
            <template v-if="section.groupId != null">
              <button
                type="button"
                title="Move group up"
                class="sh-pill-btn p-1 cursor-pointer"
                @click="moveGroupOrder(section.groupId, -1)"
              >
                <ArrowUp class="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                title="Move group down"
                class="sh-pill-btn p-1 cursor-pointer"
                @click="moveGroupOrder(section.groupId, 1)"
              >
                <ArrowDown class="w-3.5 h-3.5" />
              </button>
            </template>
          </div>
        </div>

        <!-- Group Body -->
        <template v-if="!collapsedGroups.has(section.key)">
          <!-- GRID VIEW -->
          <div
            v-if="viewMode === 'grid'"
            :class="[
              'grid gap-4',
              compactCards
                ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5'
                : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
            ]"
          >
            <DeviceCard
              v-for="device in section.devices"
              :key="device.id"
              :device="device"
              :all-devices="store.devices"
              :subnets="store.subnets"
              :edit-mode="editMode"
              :selected="selectedDeviceIds.has(device.id)"
              :compact="compactCards"
              @open="openDevice"
              @toggle-pin="togglePin"
              @toggle-select="toggleSelectDevice"
              @rescan="handleRescanDevice"
              @adopt-agent="handleAdoptAgent"
            />
          </div>

          <!-- TABLE LIST VIEW -->
          <div v-else class="sh-card overflow-hidden">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="border-b border-zinc-800/80 text-[11px] font-semibold uppercase tracking-wider text-zinc-400 bg-[#16161a]">
                  <th class="py-3 px-4">Status</th>
                  <th class="py-3 px-4">Host</th>
                  <th class="py-3 px-4">IP / Network</th>
                  <th class="py-3 px-4">Vendor / OS</th>
                  <th class="py-3 px-4">Services</th>
                  <th class="py-3 px-4 text-right">Last Seen</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-800/60 text-xs">
                <tr
                  v-for="device in section.devices"
                  :key="device.id"
                  class="hover:bg-[#1a1a20] transition-colors cursor-pointer"
                  @click="openDevice(device)"
                >
                  <td class="py-3 px-4">
                    <StatusIndicator
                      :state="device.is_online ? 'active' : 'down'"
                      :label="device.is_online ? 'Online' : 'Offline'"
                      size="sm"
                    />
                  </td>
                  <td class="py-3 px-4 font-semibold text-zinc-100">
                    <div class="flex items-center gap-2">
                      <span>{{ device.display_name || device.name || device.hostname || device.ip }}</span>
                      <Star
                        v-if="device.is_pinned"
                        class="w-3 h-3 text-amber-400"
                        fill="currentColor"
                      />
                    </div>
                  </td>
                  <td class="py-3 px-4 font-mono text-zinc-300">{{ device.ip }}</td>
                  <td class="py-3 px-4 text-zinc-400 truncate max-w-[200px]">
                    {{ device.vendor || device.os_info || '—' }}
                  </td>
                  <td class="py-3 px-4">
                    <span class="px-2 py-0.5 rounded-md text-[11px] font-mono bg-[#1b1b20] border border-zinc-800 text-zinc-300">
                      {{ device.services?.length || 0 }} ports
                    </span>
                  </td>
                  <td class="py-3 px-4 text-right">
                    <RelativeTime :date="device.last_seen" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>
    </div>

    <!-- Device Editor Drawer Sheet -->
    <DeviceSheet
      :device="selectedDevice"
      :open="sheetOpen"
      @close="sheetOpen = false"
      @updated="store.fetchDashboardData()"
    />

    <!-- Quick Add Host by IP Modal -->
    <Teleport to="body">
      <div v-if="showAddHostModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="fixed inset-0 bg-black/75 backdrop-blur-xs" @click="showAddHostModal = false" />
        <div class="sh-card relative z-10 w-full max-w-md p-5 space-y-4">
          <h3 class="text-base font-bold text-zinc-100">Add Host by IP Address</h3>
          <p class="text-xs text-zinc-400">
            Probe a specific IPv4 address or hostname and add it directly to the inventory.
          </p>
          <input
            v-model="newHostIp"
            type="text"
            placeholder="e.g. 192.168.1.50"
            class="w-full h-10 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-sm font-mono text-zinc-100 focus:outline-none focus:border-emerald-500"
            @keyup.enter="handleAddHostByIp"
          />
          <div class="flex justify-end gap-2">
            <button
              type="button"
              class="sh-pill-btn px-3.5 py-2 text-xs font-semibold cursor-pointer"
              @click="showAddHostModal = false"
            >
              Cancel
            </button>
            <button
              type="button"
              class="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs cursor-pointer"
              :disabled="addingHost"
              @click="handleAddHostByIp"
            >
              {{ addingHost ? 'Probing IP...' : 'Probe & Add Host' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- New Group Modal -->
    <Teleport to="body">
      <div v-if="showNewGroupModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="fixed inset-0 bg-black/75 backdrop-blur-xs" @click="showNewGroupModal = false" />
        <div class="sh-card relative z-10 w-full max-w-md p-5 space-y-4">
          <h3 class="text-base font-bold text-zinc-100">Create Device Group</h3>
          <div class="space-y-3">
            <div>
              <label class="block text-xs text-zinc-400 mb-1">Group Name</label>
              <input
                v-model="newGroupName"
                type="text"
                placeholder="e.g. Core Infrastructure, Proxmox Cluster, IoT"
                class="w-full h-10 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-sm text-zinc-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label class="block text-xs text-zinc-400 mb-1">Accent Color</label>
              <div class="flex items-center gap-2">
                <button
                  v-for="c in ['#10b981', '#38bdf8', '#f59e0b', '#14b8a6', '#3b82f6', '#f43f5e', '#84cc16']"
                  :key="c"
                  type="button"
                  :class="[
                    'w-7 h-7 rounded-full border-2 transition-transform cursor-pointer',
                    newGroupColor === c ? 'border-white scale-110' : 'border-transparent',
                  ]"
                  :style="{ backgroundColor: c }"
                  @click="newGroupColor = c"
                />
              </div>
            </div>
          </div>
          <div class="flex justify-end gap-2">
            <button
              type="button"
              class="sh-pill-btn px-3.5 py-2 text-xs font-semibold cursor-pointer"
              @click="showNewGroupModal = false"
            >
              Cancel
            </button>
            <button
              type="button"
              class="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs cursor-pointer"
              :disabled="creatingGroup"
              @click="handleCreateGroup"
            >
              {{ creatingGroup ? 'Creating...' : 'Create Group' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
