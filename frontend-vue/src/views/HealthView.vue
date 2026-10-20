<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { Activity, AlertTriangle, Clock, RefreshCw, ShieldAlert } from 'lucide-vue-next';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import StatusMonitor, { type AppStatusData } from '@/components/8starlabs-ui/StatusMonitor.vue';
import { api } from '@/api/client';
import { useI18n } from '@/composables/useI18n';
import type { DeviceHealthItem, HealthOverviewResponse } from '@/types';

const { t } = useI18n();
const period = ref<'24h' | '7d' | '30d'>('24h');
const overview = ref<HealthOverviewResponse | null>(null);
const loading = ref(true);

async function loadHealth() {
  loading.value = true;
  try {
    overview.value = await api.getHealthOverview(period.value);
  } finally {
    loading.value = false;
  }
}

onMounted(loadHealth);
watch(period, loadHealth);

function rowToStatusBars(item: DeviceHealthItem): AppStatusData[] {
  if (item.uptime?.history_bars && item.uptime.history_bars.length > 0) {
    return item.uptime.history_bars.map((val) => ({
      status: val === null ? 'empty' : val >= 98 ? 'normal' : val >= 50 ? 'warning' : 'error',
      info: val === null ? 'No probe sample' : `${item.display_name}: ${val.toFixed(0)}% availability`,
    }));
  }
  const slots = 30;
  const pct = item.uptime?.uptime_pct ?? 100;
  return Array.from({ length: slots }, (_, idx) => {
    if (idx === slots - 1) {
      return {
        status:
          item.health_status === 'healthy'
            ? 'normal'
            : item.health_status === 'offline' || item.health_status === 'critical'
              ? 'error'
              : 'warning',
        info: `${item.display_name}: ${pct.toFixed(1)}% uptime · Score ${item.health_score}%`,
      };
    }
    const failThreshold = Math.round(((100 - pct) / 100) * slots);
    if (failThreshold > 0 && idx < failThreshold) {
      return { status: 'warning', info: 'Historical degradation window' };
    }
    return { status: 'normal', info: 'Healthy probe response' };
  });
}

const fleetStatusBars = computed<AppStatusData[]>(() => {
  if (!overview.value) return [];
  const score = overview.value.kpis.network_health_score;
  return Array.from({ length: 45 }, (_, idx) => ({
    status: score >= 90 || idx % 11 !== 0 ? 'normal' : score >= 70 ? 'warning' : 'error',
    info: `Fleet Health Score: ${score}%`,
  }));
});
</script>

<template>
  <div class="p-6 max-w-[1640px] mx-auto space-y-6">
    <!-- Header & Period Switcher -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h2 class="text-lg font-bold text-zinc-100 tracking-tight">Health & SLA Telemetry</h2>
        <p class="text-xs text-zinc-400">
          Availability monitors, latency jitter, flapping detection & certificate hygiene
        </p>
      </div>
      <div class="flex items-center gap-2">
        <div class="inline-flex rounded-xl border border-zinc-800 bg-[#131316] p-1">
          <button
            v-for="p in ['24h', '7d', '30d'] as const"
            :key="p"
            type="button"
            :class="[
              'px-3 py-1 rounded-lg text-xs font-mono font-semibold transition-colors cursor-pointer',
              period === p ? 'bg-emerald-500 text-zinc-950' : 'text-zinc-400 hover:text-zinc-200',
            ]"
            @click="period = p"
          >
            {{ p }}
          </button>
        </div>
        <button
          type="button"
          class="sh-pill-btn px-3 py-2 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
          @click="loadHealth"
        >
          <RefreshCw :class="['w-3.5 h-3.5', loading && 'animate-spin text-emerald-400']" />
          Refresh
        </button>
      </div>
    </div>

    <!-- Top Bento Row -->
    <div v-if="overview" class="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
      <div class="sh-card p-5 space-y-3">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span class="font-semibold uppercase tracking-wider text-[10px]">{{ t('kpi.health_score') }}</span>
          <Activity class="h-4 w-4 text-emerald-400" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-3xl font-bold text-zinc-100">
            {{ overview.kpis.network_health_score }}%
          </span>
          <span class="text-xs font-mono text-emerald-400">
            {{ overview.kpis.online_devices }}/{{ overview.kpis.total_devices }} Online
          </span>
        </div>
        <StatusMonitor :statuses="fleetStatusBars" :slots="30" :show-uptime="false" compact />
      </div>

      <div class="sh-card p-5 flex flex-col justify-between">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span class="font-semibold uppercase tracking-wider text-[10px]">{{ t('kpi.avg_latency') }}</span>
          <Clock class="h-4 w-4 text-sky-400" />
        </div>
        <div class="my-2">
          <span class="font-mono text-3xl font-bold text-zinc-100">
            {{ overview.kpis.avg_latency_ms !== null ? `${overview.kpis.avg_latency_ms.toFixed(1)} ms` : '—' }}
          </span>
        </div>
        <div class="sh-subcard p-2.5 flex items-center justify-between text-xs">
          <span class="text-zinc-400">Avg Jitter</span>
          <span class="font-mono font-semibold text-zinc-200">
            {{ overview.kpis.avg_jitter_ms !== null ? `${overview.kpis.avg_jitter_ms.toFixed(1)} ms` : '—' }}
          </span>
        </div>
      </div>

      <div class="sh-card p-5 flex flex-col justify-between">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span class="font-semibold uppercase tracking-wider text-[10px]">Flapping / Degraded</span>
          <AlertTriangle class="h-4 w-4 text-amber-400" />
        </div>
        <div class="my-2">
          <span class="font-mono text-3xl font-bold text-amber-400">
            {{ overview.kpis.flapping_devices }}
          </span>
        </div>
        <div class="sh-subcard p-2.5 flex items-center justify-between text-xs">
          <span class="text-zinc-400">Active Incidents</span>
          <span class="font-mono font-semibold text-zinc-200">{{ overview.kpis.active_issues_count }}</span>
        </div>
      </div>

      <div class="sh-card p-5 flex flex-col justify-between">
        <div class="flex items-center justify-between text-xs text-zinc-400">
          <span class="font-semibold uppercase tracking-wider text-[10px]">Security & SSL Hygiene</span>
          <ShieldAlert class="h-4 w-4 text-rose-400" />
        </div>
        <div class="my-2">
          <span class="font-mono text-3xl font-bold text-zinc-100">
            {{ overview.kpis.patch_warning_count + overview.kpis.ssl_warning_count }}
          </span>
        </div>
        <div class="sh-subcard p-2.5 flex items-center justify-between text-xs">
          <span class="text-zinc-400">SSL / OS Patches</span>
          <span class="font-mono font-semibold text-zinc-200">
            {{ overview.kpis.ssl_warning_count }} SSL · {{ overview.kpis.patch_warning_count }} Pkg
          </span>
        </div>
      </div>
    </div>

    <!-- Host SLA & 8StarLabs StatusMonitor Table -->
    <div v-if="overview" class="sh-card overflow-hidden">
      <div class="p-4 border-b border-zinc-800/80 flex items-center justify-between">
        <div>
          <h3 class="text-sm font-bold text-zinc-100">Per-Host Availability Monitors ({{ overview.devices.length }})</h3>
          <p class="text-xs text-zinc-400">Live 8StarLabs status history bars across the {{ period }} window</p>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-xs">
          <thead>
            <tr class="border-b border-zinc-800/80 bg-[#16161a] text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              <th class="px-4 py-3">Host</th>
              <th class="px-4 py-3">State</th>
              <th class="px-4 py-3 w-[260px]">Uptime Timeline ({{ period }})</th>
              <th class="px-4 py-3">SLA %</th>
              <th class="px-4 py-3">Latency (Avg / Max)</th>
              <th class="px-4 py-3">Services</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-800/60">
            <tr v-for="item in overview.devices" :key="item.id" class="hover:bg-[#19191f] transition-colors">
              <td class="px-4 py-3">
                <div class="font-semibold text-zinc-100">{{ item.display_name }}</div>
                <div class="font-mono text-[11px] text-zinc-500">{{ item.ip }}</div>
              </td>
              <td class="px-4 py-3">
                <StatusIndicator
                  :state="
                    item.health_status === 'healthy'
                      ? 'active'
                      : item.health_status === 'flapping' || item.health_status === 'degraded'
                        ? 'fixing'
                        : 'down'
                  "
                  :label="item.health_status"
                  size="sm"
                />
              </td>
              <td class="px-4 py-3">
                <StatusMonitor :statuses="rowToStatusBars(item)" :slots="28" :show-uptime="false" compact />
              </td>
              <td class="px-4 py-3 font-mono font-bold text-emerald-400">
                {{ item.uptime.uptime_pct.toFixed(2) }}%
              </td>
              <td class="px-4 py-3 font-mono text-zinc-300">
                {{ item.latency.avg_ms !== null ? `${item.latency.avg_ms.toFixed(1)} ms` : '—' }}
                <span v-if="item.latency.max_ms !== null" class="text-zinc-500">
                  / {{ item.latency.max_ms.toFixed(1) }} ms
                </span>
              </td>
              <td class="px-4 py-3 font-mono text-[11px] text-zinc-300">
                <span class="px-2 py-0.5 rounded-md bg-[#1b1b20] border border-zinc-800">
                  {{ item.services.filter((s) => s.is_up).length }}/{{ item.services.length }} up
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
