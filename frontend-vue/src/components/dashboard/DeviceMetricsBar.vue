<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { api, createMetricsSocket } from '@/api/client';

const props = defineProps<{
  deviceId: number;
  expanded?: boolean;
}>();

interface RawMetrics {
  cpu_percent?: number;
  ram?: { total_mb?: number; used_mb?: number; percent?: number };
  disk?: Array<{ path: string; total_gb?: number; used_gb?: number; percent?: number }>;
  temperature?: number | null;
}

const metrics = ref<RawMetrics | null>(null);
let ws: WebSocket | null = null;

function normalizeSnapshot(snap: unknown): RawMetrics | null {
  if (!snap || typeof snap !== 'object') return null;
  const s = snap as Record<string, unknown>;
  if ('cpu_percent' in s) {
    return {
      cpu_percent: Number(s.cpu_percent ?? 0),
      ram: s.ram_percent != null
        ? {
            total_mb: Number(s.ram_total_mb ?? 0),
            used_mb: Number(s.ram_used_mb ?? 0),
            percent: Number(s.ram_percent ?? 0),
          }
        : (s.ram as RawMetrics['ram']),
      disk: (Array.isArray(s.disk_json) ? s.disk_json : Array.isArray(s.disk) ? s.disk : []) as RawMetrics['disk'],
      temperature: s.temperature != null ? Number(s.temperature) : null,
    };
  }
  return null;
}

async function connectMetrics(id: number) {
  if (ws) {
    ws.close();
    ws = null;
  }
  try {
    const res = await api.getAgentMetrics(id, 1);
    if (res.snapshots && res.snapshots.length > 0) {
      metrics.value = normalizeSnapshot(res.snapshots[res.snapshots.length - 1]);
    }
  } catch {
    // Ignore initial snapshot error if agent has no history yet
  }

  ws = createMetricsSocket(id, (data) => {
    const normalized = normalizeSnapshot(data);
    if (normalized) metrics.value = normalized;
  });
}

onMounted(() => {
  connectMetrics(props.deviceId);
});

watch(
  () => props.deviceId,
  (newId) => {
    connectMetrics(newId);
  }
);

onUnmounted(() => {
  if (ws) {
    ws.close();
    ws = null;
  }
});

function barColorClass(pct: number, warn = 80, crit = 92): string {
  if (pct >= crit) return 'bg-rose-500';
  if (pct >= warn) return 'bg-amber-500';
  return 'bg-emerald-500';
}

function textColorClass(pct: number, warn = 80, crit = 92): string {
  if (pct >= crit) return 'text-rose-400';
  if (pct >= warn) return 'text-amber-400';
  return 'text-zinc-200';
}

const meterItems = computed(() => {
  if (!metrics.value) return [];
  const m = metrics.value;
  const cpu = m.cpu_percent ?? 0;
  const ram = m.ram?.percent ?? 0;
  const fullestDisk = (m.disk || []).reduce< NonNullable<RawMetrics['disk']>[number] | null >(
    (max, d) => (!max || (d.percent ?? 0) > (max.percent ?? 0) ? d : max),
    null
  );

  const list = [
    {
      key: 'cpu',
      label: 'CPU',
      percent: Math.min(100, Math.max(0, cpu)),
      text: `${cpu.toFixed(0)}%`,
      barClass: barColorClass(cpu, 80, 95),
      textClass: textColorClass(cpu, 80, 95),
    },
    {
      key: 'ram',
      label: 'RAM',
      percent: Math.min(100, Math.max(0, ram)),
      text: `${ram.toFixed(0)}%`,
      barClass: barColorClass(ram, 85, 95),
      textClass: textColorClass(ram, 85, 95),
    },
  ];

  if (fullestDisk) {
    const dPct = fullestDisk.percent ?? 0;
    list.push({
      key: 'disk',
      label: 'DISK',
      percent: Math.min(100, Math.max(0, dPct)),
      text: `${dPct.toFixed(0)}%`,
      barClass: barColorClass(dPct, 85, 95),
      textClass: textColorClass(dPct, 85, 95),
    });
  }

  if (m.temperature != null) {
    const temp = m.temperature;
    list.push({
      key: 'temp',
      label: 'TEMP',
      percent: Math.min(100, Math.max(0, temp)),
      text: `${temp.toFixed(0)}°C`,
      barClass: barColorClass(temp, 70, 85),
      textClass: textColorClass(temp, 70, 85),
    });
  }

  return list;
});
</script>

<template>
  <div
    v-if="meterItems.length > 0"
    class="sh-subcard p-2.5 grid gap-2.5"
    :class="meterItems.length >= 4 ? 'grid-cols-4' : meterItems.length === 3 ? 'grid-cols-3' : 'grid-cols-2'"
  >
    <div v-for="item in meterItems" :key="item.key" class="flex flex-col gap-1 min-w-0">
      <div class="flex items-center justify-between text-[10px] leading-none">
        <span class="font-semibold tracking-wider text-zinc-500 uppercase">{{ item.label }}</span>
        <span :class="['font-mono font-bold', item.textClass]">{{ item.text }}</span>
      </div>
      <div class="h-1.5 w-full rounded-full bg-zinc-900/90 overflow-hidden">
        <div
          :class="['h-full rounded-full transition-all duration-300', item.barClass]"
          :style="{ width: `${Math.max(4, item.percent)}%` }"
        />
      </div>
    </div>
  </div>
</template>
