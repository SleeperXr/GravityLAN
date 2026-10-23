<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { ArrowDown, ArrowUp, ChevronRight, Layers, Lock, RefreshCw, Search, ShieldAlert } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, DeviceHealthItem, HealthOverviewResponse } from '@/types';
import { useNetworkStore } from '@/stores/network';
import PageHeader from '@/components/ui/PageHeader.vue';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import Select from '@/components/ui/Select.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import ErrorState from '@/components/ui/ErrorState.vue';
import HealthStatusBadge from '@/components/health/HealthStatusBadge.vue';
import StatusMonitor from '@/components/common/StatusMonitor.vue';
import Sparkline from '@/components/health/Sparkline.vue';
import IncidentList from '@/components/health/IncidentList.vue';
import HealthDetailSheet from '@/components/health/HealthDetailSheet.vue';
import DeviceEditor from '@/components/editor/DeviceEditor.vue';
import { hasAgentWarning, ms, periodHours, scoreText, scoreTone, sslWarnings } from '@/components/health/healthModel';
import { t } from '@/i18n';

/** Health & availability (port of React HealthView): network score, per-device SLA table, incidents. */
type Period = '24h' | '7d' | '30d';
type Filter = 'all' | 'healthy' | 'degraded' | 'flapping' | 'critical';
type SortKey = 'score' | 'latency' | 'name' | 'uptime';

const store = useNetworkStore();
const data = ref<HealthOverviewResponse | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref<string | null>(null);
const period = ref<Period>('24h');
const search = ref('');
const filter = ref<Filter>('all');
const sortBy = ref<SortKey>('score');
const sortOrder = ref<'asc' | 'desc'>('asc');
const selected = ref<DeviceHealthItem | null>(null);
const sheetOpen = ref(false);
const editorDevice = ref<Device | null>(null);
const editorOpen = ref(false);

async function load(spinner = true) {
  if (spinner) loading.value = true;
  refreshing.value = true;
  try {
    data.value = await api.getHealthOverview(period.value);
    error.value = null;
    if (selected.value) selected.value = data.value.devices.find((d) => d.id === selected.value!.id) ?? selected.value;
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

let timer: number | undefined;
watch(
  period,
  () => {
    void load(true);
    window.clearInterval(timer);
    timer = window.setInterval(() => void load(false), 30000);
  },
  { immediate: true },
);
onBeforeUnmount(() => window.clearInterval(timer));

const kpis = computed(() => data.value?.kpis);

const rows = computed(() => {
  if (!data.value) return [];
  let list = [...data.value.devices];
  if (filter.value === 'critical') list = list.filter((d) => d.health_status === 'critical' || d.health_status === 'offline');
  else if (filter.value !== 'all') list = list.filter((d) => d.health_status === filter.value);
  const q = search.value.trim().toLowerCase();
  if (q) list = list.filter((d) => [d.display_name, d.ip, d.hostname, d.group_name].filter(Boolean).join(' ').toLowerCase().includes(q));
  const dir = sortOrder.value === 'asc' ? 1 : -1;
  list.sort((a, b) => {
    if (sortBy.value === 'score') return (a.health_score - b.health_score) * dir;
    if (sortBy.value === 'latency') return ((a.latency.avg_ms ?? 999999) - (b.latency.avg_ms ?? 999999)) * dir;
    if (sortBy.value === 'uptime') return (a.uptime.uptime_pct - b.uptime.uptime_pct) * dir;
    return a.display_name.localeCompare(b.display_name) * dir;
  });
  return list;
});

function select(device: DeviceHealthItem) {
  selected.value = device;
  sheetOpen.value = true;
}

function selectById(id: number) {
  const target = data.value?.devices.find((d) => d.id === id);
  if (target) select(target);
}

async function openEditor(id: number) {
  sheetOpen.value = false;
  const known = store.devices.find((d) => d.id === id);
  editorDevice.value = known ?? (await api.getDevice(id).catch(() => null));
  if (editorDevice.value) editorOpen.value = true;
}

const periods: Period[] = ['24h', '7d', '30d'];
const filters: Filter[] = ['all', 'healthy', 'degraded', 'flapping', 'critical'];
const sortOptions = computed(() => [
  { value: 'score' as SortKey, label: t('health_page.sort_score') },
  { value: 'latency' as SortKey, label: t('health_page.sort_latency') },
  { value: 'uptime' as SortKey, label: t('health_page.sort_uptime') },
  { value: 'name' as SortKey, label: t('health_page.sort_name') },
]);
</script>

<template>
  <div class="mx-auto max-w-[1800px] space-y-5 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('health_page.title')" :description="t('health_page.subtitle')">
      <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.health.period')">
        <button
          v-for="p in periods"
          :key="p"
          type="button"
          class="h-8 rounded-[7px] px-3 font-mono text-xs font-semibold transition-colors"
          :class="period === p ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="period === p"
          @click="period = p"
        >
          {{ t(`health_page.period_${p}`) }}
        </button>
      </div>
      <Button size="icon" :aria-label="t('common.retry')" :title="t('common.retry')" :disabled="refreshing" @click="load(false)">
        <RefreshCw :class="refreshing && 'animate-spin'" aria-hidden="true" />
      </Button>
    </PageHeader>

    <div class="gl-card flex flex-wrap items-center gap-x-5 gap-y-2.5 px-4 py-3" :aria-label="t('health_page.network_health_score')">
      <div class="flex items-baseline gap-2">
        <span class="text-xs font-semibold text-fg-subtle">{{ t('health_page.network_health_score') }}</span>
        <span class="font-mono text-xl font-bold tabular" :class="scoreText(kpis?.network_health_score ?? 100)">{{ kpis?.network_health_score ?? '–' }}</span>
        <span class="font-mono text-xs text-fg-subtle">/ 100</span>
      </div>
      <span class="hidden h-4 w-px bg-line sm:inline-block" aria-hidden="true" />
      <div class="flex items-baseline gap-1.5 text-xs">
        <span class="font-mono font-semibold text-accent-text tabular">{{ kpis?.online_devices ?? 0 }}</span>
        <span class="text-fg-muted">{{ t('health_page.devices_online').toLowerCase() }}</span>
        <span class="font-mono text-fg-subtle">· {{ kpis?.offline_devices ?? 0 }} {{ t('health_page.devices_offline').toLowerCase() }}</span>
      </div>
      <span class="hidden h-4 w-px bg-line sm:inline-block" aria-hidden="true" />
      <div class="flex items-baseline gap-1.5 text-xs">
        <span class="text-fg-subtle">{{ t('health_page.devices_flapping') }}:</span>
        <span class="font-mono font-semibold tabular" :class="(kpis?.flapping_devices ?? 0) > 0 ? 'text-warn-text' : 'text-fg'">{{ kpis?.flapping_devices ?? 0 }}</span>
      </div>
      <span class="hidden h-4 w-px bg-line sm:inline-block" aria-hidden="true" />
      <div class="flex items-baseline gap-1.5 font-mono text-xs">
        <span class="font-sans text-fg-subtle">{{ t('health_page.avg_latency') }}:</span>
        <span class="font-semibold text-info-text tabular">{{ ms(kpis?.avg_latency_ms) }}</span>
        <span class="text-fg-subtle">±{{ ms(kpis?.avg_jitter_ms) }}</span>
      </div>
      <div class="ml-auto flex flex-wrap items-center gap-1.5 text-xs">
        <Badge v-if="kpis && kpis.active_issues_count > 0" tone="danger" mono>{{ kpis.active_issues_count }} {{ t('health_page.active_issues') }}</Badge>
        <Badge v-if="kpis && kpis.ssl_warning_count > 0" tone="warn" mono>{{ kpis.ssl_warning_count }} SSL</Badge>
        <Badge v-if="kpis && kpis.patch_warning_count > 0" tone="danger" mono>{{ kpis.patch_warning_count }} Patches</Badge>
        <span v-if="kpis && !kpis.active_issues_count && !kpis.ssl_warning_count && !kpis.patch_warning_count" class="text-fg-subtle">{{ t('health_page.no_security_warnings') }}</span>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <label class="relative min-w-0 flex-1 sm:max-w-xs">
        <span class="sr-only">{{ t('health_page.search_placeholder') }}</span>
        <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
        <input v-model="search" type="search" :placeholder="t('health_page.search_placeholder')" class="h-9 w-full rounded-md border border-line bg-surface pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:outline-none" />
      </label>
      <div class="flex max-w-full overflow-x-auto rounded-md border border-line bg-sunken p-0.5 [scrollbar-width:none]" role="group" :aria-label="t('gv.health.filter')">
        <button
          v-for="f in filters"
          :key="f"
          type="button"
          class="h-8 shrink-0 rounded-[7px] px-3 text-xs font-semibold transition-colors"
          :class="filter === f ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="filter === f"
          @click="filter = f"
        >
          {{ t(`health_page.filter_${f}`) }}
        </button>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button size="icon" :aria-label="sortOrder === 'asc' ? t('health_page.sort_asc') : t('health_page.sort_desc')" :title="sortOrder === 'asc' ? t('health_page.sort_asc') : t('health_page.sort_desc')" @click="sortOrder = sortOrder === 'asc' ? 'desc' : 'asc'">
          <component :is="sortOrder === 'asc' ? ArrowUp : ArrowDown" aria-hidden="true" />
        </Button>
        <Select v-model="sortBy" :options="sortOptions" class="w-40" :aria-label="t('gv.health.sort')" />
      </div>
    </div>

    <div v-if="loading && !data" class="space-y-2" aria-busy="true"><Skeleton v-for="i in 6" :key="i" class="h-16" /></div>
    <div v-else-if="error && !data" class="gl-card"><ErrorState :message="error" @retry="load()" /></div>
    <div v-else-if="rows.length === 0" class="gl-card"><EmptyState compact :icon="Search" :title="t('health_page.no_devices_found')" /></div>

    <template v-else>
      <div class="gl-card hidden overflow-x-auto md:block">
        <table class="w-full table-fixed text-left">
          <thead>
            <tr class="border-b border-line text-xs font-semibold text-fg-subtle">
              <th class="w-[32%] px-5 py-3">{{ t('health_page.table_device') }}</th>
              <th class="w-44 px-4 py-3">{{ t('health_page.table_status') }}</th>
              <th class="w-56 px-4 py-3">{{ t('health_page.table_uptime') }}</th>
              <th class="w-56 px-4 py-3">{{ t('health_page.table_latency') }}</th>
              <th class="w-40 px-4 py-3">{{ t('health_page.table_services') }}</th>
              <th class="w-12" />
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="d in rows" :key="d.id" class="group cursor-pointer transition-colors hover:bg-raised" :class="selected?.id === d.id && sheetOpen && 'bg-raised'" @click="select(d)">
              <td class="px-5 py-3">
                <button type="button" class="block max-w-full truncate text-left text-sm font-bold text-fg group-hover:text-accent-text" @click.stop="select(d)">{{ d.display_name }}</button>
                <p class="mt-0.5 flex items-center gap-2 truncate font-mono text-xs text-fg-subtle">
                  {{ d.ip }}<span v-if="d.group_name" class="rounded-sm bg-raised px-1.5 font-sans text-[10px] text-fg-muted">{{ d.group_name }}</span>
                </p>
              </td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-2">
                  <HealthStatusBadge :status="d.health_status" />
                  <Badge :tone="scoreTone(d.health_score, d.health_status)" mono :title="`Health Score ${d.health_score}/100`">{{ d.health_score }}</Badge>
                </div>
              </td>
              <td class="px-4 py-3">
                <div class="flex items-baseline justify-between text-xs">
                  <span class="font-mono font-semibold text-fg">{{ d.uptime.uptime_pct.toFixed(1) }}%</span>
                  <span class="font-mono text-[11px] text-fg-subtle">24h {{ d.uptime.uptime_24h.toFixed(0) }}%</span>
                </div>
                <StatusMonitor class="mt-1" compact size="sm" :bars="d.uptime.history_bars" :span-hours="periodHours(period)" :uptime="d.uptime.uptime_pct" :title="d.display_name" />
              </td>
              <td class="px-4 py-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="font-mono text-xs">
                    <p class="font-semibold text-fg">{{ ms(d.latency.current_ms) }}</p>
                    <p class="text-[10px] text-fg-subtle">Ø {{ ms(d.latency.avg_ms) }}<span v-if="d.latency.jitter_ms !== null"> ±{{ d.latency.jitter_ms.toFixed(1) }}</span></p>
                  </div>
                  <Sparkline :values="d.latency.sparkline" />
                </div>
              </td>
              <td class="px-4 py-3">
                <div class="flex flex-wrap items-center gap-1.5">
                  <Badge v-if="d.services.length" mono><Layers aria-hidden="true" />{{ d.services.filter((s) => s.is_up).length }}/{{ d.services.length }}</Badge>
                  <span v-else class="font-mono text-xs text-fg-subtle">–</span>
                  <Badge v-if="sslWarnings(d.services) > 0" tone="warn" :title="t('health_page.ssl_expiring_soon', { count: sslWarnings(d.services) })"><Lock aria-hidden="true" />SSL</Badge>
                  <Badge v-if="hasAgentWarning(d)" tone="danger" :title="t('health_page.agent_warning_title')"><ShieldAlert aria-hidden="true" />{{ d.agent?.reboot_required ? 'Reboot' : 'Patch' }}</Badge>
                </div>
              </td>
              <td class="pr-4 text-right"><ChevronRight class="ml-auto size-4 text-fg-subtle" aria-hidden="true" /></td>
            </tr>
          </tbody>
        </table>
      </div>

      <ul class="space-y-2.5 md:hidden">
        <li v-for="d in rows" :key="d.id">
          <button type="button" class="gl-card w-full space-y-3 p-4 text-left" @click="select(d)">
            <div class="flex items-start gap-3">
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-fg">{{ d.display_name }}</p>
                <p class="font-mono text-xs text-fg-subtle">{{ d.ip }}</p>
              </div>
              <Badge :tone="scoreTone(d.health_score, d.health_status)" mono>{{ d.health_score }}</Badge>
            </div>
            <div class="flex items-center justify-between gap-2 text-xs">
              <HealthStatusBadge :status="d.health_status" />
              <span class="font-mono text-fg">{{ d.uptime.uptime_pct.toFixed(1) }}% <span class="text-fg-subtle">· {{ ms(d.latency.current_ms) }}</span></span>
            </div>
            <StatusMonitor compact size="sm" :focusable="false" :bars="d.uptime.history_bars" :span-hours="periodHours(period)" :uptime="d.uptime.uptime_pct" />
          </button>
        </li>
      </ul>
    </template>

    <section class="gl-card space-y-4 p-5" aria-labelledby="incidents-title">
      <div class="flex items-baseline justify-between">
        <h2 id="incidents-title" class="text-base font-bold text-fg">{{ t('health_page.incidents_title') }}</h2>
        <span class="font-mono text-xs text-fg-subtle">{{ data?.recent_incidents?.length ?? 0 }}</span>
      </div>
      <IncidentList :incidents="data?.recent_incidents ?? []" @select="selectById" />
    </section>

    <HealthDetailSheet v-model:open="sheetOpen" :device="selected" :period="period" @updated="load(false)" @open-editor="openEditor" />
    <DeviceEditor v-if="editorDevice" v-model:open="editorOpen" :device="editorDevice" @saved="store.loadData(true); load(false)" @after-leave="editorDevice = null" />
  </div>
</template>
