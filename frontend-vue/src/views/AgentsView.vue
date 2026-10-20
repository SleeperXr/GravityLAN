<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Cpu, HardDrive, MemoryStick, RefreshCw, Server, Thermometer } from 'lucide-vue-next';
import RelativeTime from '@/components/8starlabs-ui/RelativeTime.vue';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import DeviceMetricsBar from '@/components/dashboard/DeviceMetricsBar.vue';
import { api } from '@/api/client';
import type { AgentSummary } from '@/types';

const agents = ref<AgentSummary[]>([]);
const avgCpu = ref(0);
const avgRam = ref(0);
const activeCount = ref(0);
const totalPoints = ref(0);
const loading = ref(false);

async function loadAgents() {
  loading.value = true;
  try {
    const res = await api.getAgentsOverview();
    agents.value = res.agents;
    avgCpu.value = res.avg_cpu;
    avgRam.value = res.avg_ram;
    activeCount.value = res.active_agents;
    totalPoints.value = res.total_data_points;
  } finally {
    loading.value = false;
  }
}

onMounted(loadAgents);
</script>

<template>
  <div class="p-6 max-w-[1640px] mx-auto space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-lg font-bold text-zinc-100 tracking-tight">Linux & Docker Telemetry Agents</h2>
        <p class="text-xs text-zinc-400">
          Real-time WebSocket host utilization, thermal sensors & package patch status
        </p>
      </div>
      <button
        type="button"
        class="sh-pill-btn px-3.5 py-2 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
        @click="loadAgents"
      >
        <RefreshCw :class="['w-3.5 h-3.5', loading && 'animate-spin text-emerald-400']" />
        Refresh Fleet
      </button>
    </div>

    <!-- Top Bento Summary Cards -->
    <div class="grid grid-cols-1 gap-5 sm:grid-cols-3">
      <div class="sh-card p-5 flex flex-col justify-between gap-3">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Connected Agents</span>
          <Server class="w-4 h-4 text-emerald-400" />
        </div>
        <div class="font-mono text-3xl font-bold text-zinc-100">
          {{ activeCount }} <span class="text-base font-normal text-zinc-500">/ {{ agents.length }}</span>
        </div>
        <div class="sh-subcard p-2.5 flex items-center justify-between text-xs">
          <span class="text-zinc-400">Telemetry Snapshots</span>
          <span class="font-mono font-semibold text-emerald-400">{{ totalPoints.toLocaleString() }}</span>
        </div>
      </div>

      <div class="sh-card p-5 flex flex-col justify-between gap-3">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Fleet Avg CPU Load</span>
          <Cpu class="w-4 h-4 text-sky-400" />
        </div>
        <div class="font-mono text-3xl font-bold text-zinc-100">{{ avgCpu.toFixed(1) }}%</div>
        <div class="h-2 w-full rounded-full bg-zinc-900 overflow-hidden">
          <div class="h-full bg-emerald-500 rounded-full transition-all" :style="{ width: `${Math.min(100, avgCpu)}%` }" />
        </div>
      </div>

      <div class="sh-card p-5 flex flex-col justify-between gap-3">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Fleet Avg Memory</span>
          <MemoryStick class="w-4 h-4 text-amber-400" />
        </div>
        <div class="font-mono text-3xl font-bold text-zinc-100">{{ avgRam.toFixed(1) }}%</div>
        <div class="h-2 w-full rounded-full bg-zinc-900 overflow-hidden">
          <div class="h-full bg-sky-400 rounded-full transition-all" :style="{ width: `${Math.min(100, avgRam)}%` }" />
        </div>
      </div>
    </div>

    <!-- Agent Cards Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      <div
        v-for="ag in agents"
        :key="ag.device_id"
        class="sh-card-interactive p-5 flex flex-col gap-4"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-[#1b1b20] border border-zinc-800 flex items-center justify-center relative">
              <Server class="w-4.5 h-4.5 text-emerald-400" />
              <div class="absolute -bottom-1 -right-1 bg-[#131316] p-0.5 rounded-full">
                <StatusIndicator :state="ag.is_online || ag.is_active ? 'active' : 'down'" size="sm" />
              </div>
            </div>
            <div>
              <h3 class="text-sm font-bold text-zinc-100">{{ ag.hostname }}</h3>
              <div class="font-mono text-xs text-zinc-400">{{ ag.ip }} · v{{ ag.agent_version || '1.0' }}</div>
            </div>
          </div>

          <span
            v-if="ag.patch_security > 0"
            class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30"
          >
            {{ ag.patch_available }} ({{ ag.patch_security }} Sec)
          </span>
          <span
            v-else-if="ag.patch_available > 0"
            class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30"
          >
            {{ ag.patch_available }} Updates
          </span>
          <span
            v-else
            class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-emerald-500/12 text-emerald-400 border border-emerald-500/25"
          >
            Up to date
          </span>
        </div>

        <!-- Live WebSocket DeviceMetricsBar -->
        <DeviceMetricsBar :device-id="ag.device_id" />

        <div class="flex items-center justify-between text-[11px] text-zinc-500 pt-1 border-t border-zinc-800/70">
          <div class="inline-flex items-center gap-3">
            <span v-if="ag.temp !== null" class="inline-flex items-center gap-1 font-mono text-zinc-300">
              <Thermometer class="w-3 h-3 text-amber-400" />
              {{ ag.temp.toFixed(0) }}°C
            </span>
            <span class="inline-flex items-center gap-1 font-mono text-zinc-400">
              <HardDrive class="w-3 h-3" />
              Max Disk {{ (ag.disk_max_usage ?? 0).toFixed(0) }}%
            </span>
          </div>
          <RelativeTime v-if="ag.last_seen" :date="ag.last_seen" />
        </div>
      </div>
    </div>
  </div>
</template>
