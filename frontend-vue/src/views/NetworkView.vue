<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useMediaQuery, useStorage } from '@vueuse/core';
import { Grid3x3, LayoutGrid, Plus, Radar, Search, Settings2, Trash2 } from 'lucide-vue-next';
import { api, createScanSocket } from '@/api/client';
import type { Device, Subnet } from '@/types';
import { buildTiles, countOnline, parseAreas, prefixOf, recentFindings, type AreasByPrefix, type NetworkArea } from '@/lib/subnetModel';
import { useNetworkStore } from '@/stores/network';
import { useDiscoveryStore } from '@/stores/discovery';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import PageHeader from '@/components/ui/PageHeader.vue';
import Button from '@/components/ui/Button.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import IpTile from '@/components/network/IpTile.vue';
import LineBullet from '@/components/common/LineBullet.vue';
import { lineLabel, networkColor } from '@/lib/networks';
import { busiestPrefix } from '@/lib/subnetPick';
import { stackedLayers } from '@/lib/meter';
import SubnetModeBadge from '@/components/network/SubnetModeBadge.vue';
import AddSubnetDialog from '@/components/network/AddSubnetDialog.vue';
import SubnetSettingsDialog from '@/components/network/SubnetSettingsDialog.vue';
import AreaManagerDialog from '@/components/network/AreaManagerDialog.vue';
import DeviceEditor from '@/components/editor/DeviceEditor.vue';
import { formatNumber, t } from '@/i18n';

const store = useNetworkStore();
const discovery = useDiscoveryStore();
const { showToast } = useToast();
const { confirm } = useConfirm();
const isMobile = useMediaQuery('(max-width: 767px)');

const zoom = useStorage('gravityui.network.zoom', 1);
const prefix = ref('');
const areas = ref<AreasByPrefix>({});
const busy = ref<Record<string, boolean>>({});
const addOpen = ref(false);
const adding = ref(false);
const settingsOpen = ref(false);
const areasOpen = ref(false);
const editorDevice = ref<Device | null>(null);
const editorOpen = ref(false);
let lastScanned: string | null = null;

const columns = computed(() => Math.max(1, Math.floor(16 / (zoom.value || 1))));
const currentSubnet = computed(() => store.subnets.find((s) => prefixOf(s.cidr) === prefix.value));
const currentAreas = computed<NetworkArea[]>(() => areas.value[prefix.value] || []);
const tiles = computed(() => (prefix.value ? buildTiles(prefix.value, store.devices, discovery.hosts, currentAreas.value, columns.value) : []));
const visibleTiles = computed(() => (isMobile.value ? tiles.value.filter((tile) => tile.status !== 'empty') : tiles.value));
const onlineCount = computed(() => (prefix.value ? countOnline(prefix.value, store.devices, discovery.hosts) : 0));
const findings = computed(() => recentFindings(discovery.hosts, store.devices));

/** Address usage of the /24 (254 hosts) for the utilization bar. */
const usage = computed(() => {
  const counts = { device: 0, discovered: 0, offline: 0, reserved: 0 };
  for (const tile of tiles.value) {
    if (tile.i === 0 || tile.i === 255) continue;
    if (tile.device) counts[tile.device.is_online ? 'device' : 'offline']++;
    else if (tile.discovered) counts[tile.discovered.is_online ? 'discovered' : 'offline']++;
    else if (tile.isReserved) counts.reserved++;
  }
  const used = counts.device + counts.discovered + counts.offline + counts.reserved;
  return { ...counts, free: 254 - used, used };
});

const segments = computed(() => [
  { key: 'device', label: t('gv.network.legend_device'), value: usage.value.device, cls: 'bg-accent' },
  { key: 'discovered', label: t('gv.network.legend_discovered'), value: usage.value.discovered, cls: 'bg-info' },
  { key: 'offline', label: t('network.offline'), value: usage.value.offline, cls: 'bg-danger' },
  { key: 'reserved', label: t('gv.network.legend_reserved'), value: usage.value.reserved, cls: 'bg-fg-subtle' },
]);
/** The usage bar as layers that move with `transform`, so a changing count does not relayout the bar */
const segmentLayers = computed(() => stackedLayers(segments.value, 254));

async function loadAreas() {
  try {
    const settings = await api.getSettings();
    if (settings['network_groups']) areas.value = parseAreas(settings['network_groups'], prefix.value);
  } catch {
    // no areas
  }
}

/** Until the user picks a subnet, open on the busiest one rather than the first (often an empty guest net). */
function pickDefaultPrefix() {
  if (prefix.value) return;
  prefix.value = busiestPrefix(store.subnets, store.devices, discovery.hosts);
}

async function reload() {
  await store.loadData(true);
  pickDefaultPrefix();
}

// Reload on a finished scan; poll 10 s during a discovery, else 30 s; discovered hosts every 15 s
const socket = createScanSocket((data) => {
  if (String(data.status).toLowerCase() === 'completed') {
    void reload();
    void discovery.load();
  }
});
let pollTimer: number | undefined;
watch(
  () => discovery.isDiscovering,
  (discovering) => {
    window.clearInterval(pollTimer);
    pollTimer = window.setInterval(() => void reload(), discovering ? 10000 : 30000);
  },
  { immediate: true },
);
const hostTimer = window.setInterval(() => void discovery.load(), 15000);
onBeforeUnmount(() => {
  socket.close();
  window.clearInterval(pollTimer);
  window.clearInterval(hostTimer);
});

void Promise.all([reload(), discovery.load(), loadAreas()]);

// Quick-scan each /24 once when it is first shown
watch(prefix, (value) => {
  if (!value || value === lastScanned) return;
  lastScanned = value;
  api.quickSubnetScan(value).then(() => reload()).catch(() => {});
});

async function withBusy(key: string, run: () => Promise<void>) {
  busy.value = { ...busy.value, [key]: true };
  try {
    await run();
  } finally {
    busy.value = { ...busy.value, [key]: false };
  }
}

const scanBusy = (ip: string) => !!(busy.value[`${ip}-services`] || busy.value[`${ip}-disc`]);

function scanDevice(id: number, ip: string) {
  void withBusy(`${ip}-services`, async () => {
    showToast('info', `${t('network.nmap_scan')}...`, `${t('common.loading')} ${ip}...`);
    try {
      await api.refreshServices(id);
      await reload();
      showToast('success', t('common.success'), t('notifications.changes_applied'));
    } catch {
      showToast('error', t('common.error'), t('notifications.save_failed'));
    }
  });
}

function scanHost(ip: string) {
  void withBusy(`${ip}-disc`, async () => {
    showToast('info', `${t('network.nmap_scan')}...`, `${t('common.loading')} ${ip}...`);
    try {
      const result = await api.scanIp(ip);
      const ports = (result as { ports?: number[] }).ports || [];
      discovery.patchLocal(ip, { ports, last_scan: new Date().toISOString() } as never);
      showToast('success', t('notifications.scan_completed'), t('network.ports_found', { ports: ports.join(', ') || t('network.no_ports_found') }));
    } catch {
      showToast('error', t('notifications.scan_failed'), t('notifications.scan_failed_text'));
    }
  });
}

function addDevice(ip: string) {
  void withBusy(`${ip}-add`, async () => {
    try {
      await api.addDeviceFromIp(ip);
      showToast('success', t('common.success'), t('notifications.device_added', { ip }));
      await reload();
      discovery.dropLocal(ip);
    } catch (err) {
      showToast('error', t('common.error'), (err as Error).message || t('notifications.save_failed'));
    }
  });
}

async function updateDevice(id: number, data: Partial<Device>) {
  try {
    await api.updateDevice(id, data);
    showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
    await reload();
  } catch {
    showToast('error', t('common.error'), t('notifications.save_failed'));
  }
}

async function addSubnet(cidr: string, name: string) {
  adding.value = true;
  try {
    await api.createSubnet({ cidr, name, is_enabled: true });
    showToast('success', t('notifications.saved'), t('network.add_subnet'));
    addOpen.value = false;
    await reload();
    prefix.value = prefixOf(cidr);
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message || t('notifications.save_failed'));
  } finally {
    adding.value = false;
  }
}

async function deleteSubnet(sub: Subnet) {
  const ok = await confirm({ title: `${t('common.delete')} ${sub.cidr}?`, danger: true, confirmLabel: t('common.delete') });
  if (!ok) return;
  try {
    await api.deleteSubnet(sub.id);
    showToast('success', t('common.success'), t('notifications.deleted'));
    if (prefix.value === prefixOf(sub.cidr)) prefix.value = '';
    await reload();
  } catch {
    showToast('error', t('common.error'), t('notifications.save_failed'));
  }
}

async function updateSubnet(id: number, patch: Partial<Subnet>) {
  try {
    await api.updateSubnet(id, patch);
    await reload();
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message || t('notifications.save_failed'));
  }
}

async function saveAreas(updated: NetworkArea[]) {
  const next = { ...areas.value, [prefix.value]: updated };
  areas.value = next;
  try {
    await api.updateSettings({ network_groups: JSON.stringify(next) });
    showToast('success', t('notifications.saved'), t('notifications.area_saved'));
  } catch {
    showToast('error', t('common.error'), t('notifications.save_failed'));
  }
}

function openEditor(device: Device) {
  editorDevice.value = store.devices.find((d) => d.id === device.id) ?? device;
  editorOpen.value = true;
}
</script>

<template>
  <div class="mx-auto max-w-[1800px] space-y-5 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('sidebar.network_planner')" :description="currentSubnet ? `${currentSubnet.name} · ${currentSubnet.cidr}` : prefix ? `${prefix}.0/24` : undefined">
      <label v-if="!isMobile" class="flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-3 text-xs text-fg-muted">
        {{ t('network.zoom') }}
        <input v-model.number="zoom" type="range" min="0.5" max="2" step="0.1" class="w-24 accent-[var(--gl-accent)]" :aria-label="t('network.zoom')" />
      </label>
      <Button :disabled="!prefix" @click="areasOpen = true"><LayoutGrid aria-hidden="true" /><span class="hidden sm:inline">{{ t('network.manage_areas') }}</span></Button>
      <Button :disabled="store.subnets.length === 0" @click="settingsOpen = true"><Settings2 aria-hidden="true" /><span class="hidden sm:inline">{{ t('network.subnet_settings') }}</span></Button>
      <Button variant="primary" :disabled="!prefix" :loading="discovery.isDiscovering" @click="discovery.runDiscovery(prefix)">
        <Radar v-if="!discovery.isDiscovering" aria-hidden="true" />{{ t('dashboard.scan') }}
      </Button>
    </PageHeader>

    <!-- Subnet switcher -->
    <div class="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0" role="tablist" :aria-label="t('network.subnets')">
      <div
        v-for="sub in store.subnets"
        :key="sub.id"
        class="group flex shrink-0 items-center rounded-md border transition-colors"
        :class="prefix === prefixOf(sub.cidr) ? 'bg-raised' : 'border-line bg-surface hover:border-line-strong'"
        :style="prefix === prefixOf(sub.cidr) ? { borderColor: networkColor(sub.id) } : undefined"
      >
        <button
          type="button"
          role="tab"
          :aria-selected="prefix === prefixOf(sub.cidr)"
          :title="sub.is_enabled === false ? t('network.subnet_paused_hint') : sub.cidr"
          class="flex h-9 items-center gap-2 pr-2 pl-3 text-sm"
          :class="sub.is_enabled === false && 'opacity-60'"
          @click="prefix = prefixOf(sub.cidr)"
        >
          <LineBullet :color="networkColor(sub.id)" :label="lineLabel(sub)" size="sm" />
          <span class="font-medium text-fg">{{ sub.name }}</span>
          <span v-if="sub.vlan_id != null" class="font-mono text-xs text-fg-subtle">VLAN {{ sub.vlan_id }}</span>
          <SubnetModeBadge :subnet="sub" />
          <span v-if="sub.is_enabled === false" class="text-xs text-warn-text">{{ t('network.subnet_paused') }}</span>
        </button>
        <button
          v-if="prefix === prefixOf(sub.cidr)"
          type="button"
          class="mr-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-danger/10 hover:text-danger-text"
          :aria-label="`${t('common.delete')} ${sub.cidr}`"
          @click="deleteSubnet(sub)"
        >
          <Trash2 class="size-3.5" aria-hidden="true" />
        </button>
      </div>
      <Button class="shrink-0 border-dashed" @click="addOpen = true"><Plus aria-hidden="true" />{{ t('network.add_subnet') }}</Button>
    </div>

    <div v-if="!store.loaded" class="grid grid-cols-8 gap-2 md:grid-cols-16" aria-busy="true">
      <Skeleton v-for="i in 64" :key="i" class="aspect-square" />
    </div>

    <div v-else-if="!prefix" class="gl-card">
      <EmptyState :icon="Grid3x3" :title="t('gateways.no_subnets')" :description="t('network.new_subnet_prompt')">
        <Button variant="primary" @click="addOpen = true"><Plus aria-hidden="true" />{{ t('network.add_subnet') }}</Button>
      </EmptyState>
    </div>

    <template v-else>
      <!-- Address usage of this /24 -->
      <section class="gl-card p-4" :aria-label="t('gv.network.usage')">
        <div class="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <p class="flex items-baseline gap-2">
            <span class="font-mono text-2xl font-semibold text-fg tabular">{{ onlineCount }}</span>
            <span class="text-sm text-fg-muted">{{ t('network.online') }}</span>
          </p>
          <p class="text-sm text-fg-muted">
            <span class="font-mono text-fg tabular">{{ usage.used }}</span> / 254 {{ t('gv.network.used') }} ·
            <span class="font-mono text-fg tabular">{{ usage.free }}</span> {{ t('gv.network.free') }}
            ({{ formatNumber(usage.free / 254, { style: 'percent' }) }})
          </p>
          <SubnetModeBadge v-if="currentSubnet" :subnet="currentSubnet" long class="ml-auto" />
        </div>
        <!-- Nothing in use yet: say so instead of a bar and a legend of zeros -->
        <p v-if="usage.used === 0" class="mt-2 max-w-[65ch] text-sm text-fg-muted">{{ t('gv.network.empty_subnet') }}</p>
        <div v-else class="relative mt-3 h-2 overflow-hidden rounded-full bg-sunken" role="img" :aria-label="segments.map((s) => `${s.label}: ${s.value}`).join(', ')">
          <div v-for="layer in segmentLayers" :key="layer.key" :class="layer.cls" class="absolute inset-0 origin-left transition-transform duration-500 ease-out" :style="{ transform: layer.transform }" />
        </div>
        <ul class="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-fg-muted">
          <li v-for="seg in usage.used > 0 ? segments : []" :key="seg.key" class="flex items-center gap-1.5"><span class="size-2 rounded-[3px]" :class="seg.cls" aria-hidden="true" />{{ seg.label }} <span class="font-mono text-fg tabular">{{ seg.value }}</span></li>
          <li v-for="area in currentAreas" :key="`area-${area.name}`" class="flex items-center gap-1.5">
            <span class="size-2 rounded-[3px]" :style="{ backgroundColor: area.color }" aria-hidden="true" />{{ area.name }} <span class="font-mono text-fg-subtle">.{{ area.start }}–.{{ area.end }}</span>
          </li>
        </ul>
      </section>

      <div
        class="grid"
        :class="isMobile && 'grid-cols-[repeat(auto-fill,minmax(3.25rem,1fr))] gap-2 text-sm'"
        :style="!isMobile ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, gap: `${Math.floor(10 * (zoom || 1))}px`, fontSize: `${(zoom || 1) * 0.95}rem` } : undefined"
      >
        <IpTile
          v-for="tile in visibleTiles"
          :key="`${prefix}-${tile.i}`"
          :tile="tile"
          :line-color="currentSubnet ? networkColor(currentSubnet.id) : undefined"
          :scan-busy="scanBusy(tile.ip)"
          :add-busy="!!busy[`${tile.ip}-add`]"
          :show-area-label="!!tile.group && tile.i === tile.group.start"
          @open-device="openEditor"
          @update-device="updateDevice"
          @update-host="discovery.update"
          @scan-device="scanDevice"
          @scan-host="scanHost"
          @add-device="addDevice"
          :refresh-busy="!!tile.discovered && discovery.refreshing.has(tile.discovered.id)"
          @refresh-host="discovery.refresh"
          @delete-host="discovery.remove"
        />
      </div>

      <section v-if="findings.length > 0" class="gl-card p-4" aria-labelledby="recent-findings">
        <h2 id="recent-findings" class="flex items-center gap-2 text-sm font-semibold text-fg"><Search class="size-4 text-info-text" aria-hidden="true" />{{ t('network.recent_findings') }}</h2>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button
            v-for="host in findings"
            :key="host.id"
            type="button"
            class="rounded-md border px-2 py-1 font-mono text-xs transition-colors"
            :class="host.is_online ? 'border-accent/30 bg-accent/[0.07] text-accent-text hover:border-accent/60' : 'border-line bg-raised text-fg-muted hover:border-line-strong'"
            @click="prefix = host.ip.split('.').slice(0, 3).join('.')"
          >
            {{ host.ip }}
          </button>
        </div>
      </section>
    </template>

    <AddSubnetDialog v-model:open="addOpen" :busy="adding" @add="addSubnet" />
    <SubnetSettingsDialog v-model:open="settingsOpen" :subnets="store.subnets" @update="updateSubnet" @delete="deleteSubnet" />
    <AreaManagerDialog v-model:open="areasOpen" :areas="currentAreas" :prefix="prefix" @save="saveAreas" />
    <DeviceEditor v-if="editorDevice" v-model:open="editorOpen" :device="editorDevice" @saved="reload" @after-leave="editorDevice = null" />
  </div>
</template>
