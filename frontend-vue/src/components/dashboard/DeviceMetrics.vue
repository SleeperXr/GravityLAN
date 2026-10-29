<script setup lang="ts">
import { computed, toRef } from 'vue';
import { Activity, Cpu, HardDrive, MemoryStick, Thermometer } from 'lucide-vue-next';
import { useLiveMetrics } from '@/composables/useLiveMetrics';
import { formatBps, fullestDisk, meterTone, type MeterTone } from '@/lib/metrics';
import { t } from '@/i18n';

/**
 * Live agent metrics. Compact: up to four meters for a device card. Expanded: every disk,
 * temperature and per-interface traffic (agent tab of the device editor).
 */
const props = withDefaults(defineProps<{ deviceId: number; compact?: boolean; enabled?: boolean }>(), { compact: true, enabled: true });
const { metrics } = useLiveMetrics(toRef(props, 'deviceId'), toRef(props, 'enabled'));

const fills: Record<MeterTone, string> = { ok: 'bg-accent', warn: 'bg-warn', danger: 'bg-danger' };
const texts: Record<MeterTone, string> = { ok: 'text-fg', warn: 'text-warn-text', danger: 'text-danger-text' };

interface Meter {
  key: string;
  label: string;
  percent: number;
  text: string;
  tone: MeterTone;
}

const compactMeters = computed<Meter[]>(() => {
  const m = metrics.value;
  if (!m) return [];
  const cpu = m.cpu_percent ?? 0;
  const ram = m.ram?.percent ?? 0;
  const items: Meter[] = [
    { key: 'cpu', label: t('agent.cpu'), percent: cpu, text: `${cpu.toFixed(0)} %`, tone: meterTone(cpu, 80, 95) },
    { key: 'ram', label: t('agent.ram'), percent: ram, text: `${ram.toFixed(0)} %`, tone: meterTone(ram, 85, 95) },
  ];
  const disk = fullestDisk(m.disk);
  if (disk) {
    const pct = disk.percent ?? 0;
    items.push({ key: 'disk', label: t('agent.disk'), percent: pct, text: `${pct.toFixed(0)} %`, tone: meterTone(pct, 85, 95) });
  }
  if (m.temperature != null) {
    items.push({
      key: 'temp',
      label: t('agent.temp_short'),
      percent: Math.min(m.temperature, 100),
      text: `${m.temperature.toFixed(0)} °C`,
      tone: meterTone(m.temperature, 70, 85),
    });
  }
  return items;
});

const expandedRows = computed(() => {
  const m = metrics.value;
  if (!m) return [];
  return [
    { key: 'cpu', icon: Cpu, label: t('agent.cpu'), percent: m.cpu_percent ?? 0, value: `${(m.cpu_percent ?? 0).toFixed(1)} %` },
    {
      key: 'ram',
      icon: MemoryStick,
      label: t('agent.ram'),
      percent: m.ram?.percent ?? 0,
      value: `${((m.ram?.used_mb || 0) / 1024).toFixed(1)} / ${((m.ram?.total_mb || 0) / 1024).toFixed(1)} GB`,
    },
    ...(m.disk || []).map((d) => ({ key: `disk-${d.path}`, icon: HardDrive, label: d.path, percent: d.percent ?? 0, value: `${d.used_gb ?? 0} / ${d.total_gb ?? 0} GB` })),
  ];
});
</script>

<template>
  <template v-if="metrics">
    <div v-if="compact" class="grid grid-cols-2 gap-x-3 gap-y-2">
      <div v-for="m in compactMeters" :key="m.key" class="min-w-0">
        <div class="mb-1 flex items-baseline justify-between gap-2 text-xs">
          <span class="text-fg-subtle">{{ m.label }}</span>
          <span class="font-mono font-medium tabular" :class="texts[m.tone]">{{ m.text }}</span>
        </div>
        <div
          class="h-1 overflow-hidden rounded-full bg-sunken"
          role="meter"
          :aria-label="m.label"
          :aria-valuenow="Math.round(m.percent)"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuetext="m.text"
        >
          <div class="h-full rounded-full transition-[width] duration-500" :class="fills[m.tone]" :style="{ width: `${Math.min(m.percent, 100)}%` }" />
        </div>
      </div>
    </div>

    <div v-else class="space-y-3 rounded-md border border-line bg-sunken p-3">
      <div v-for="row in expandedRows" :key="row.key">
        <div class="mb-1 flex items-center justify-between gap-2 text-xs">
          <span class="flex min-w-0 items-center gap-1.5 text-fg-muted"><component :is="row.icon" class="size-3.5 shrink-0" aria-hidden="true" /><span class="truncate">{{ row.label }}</span></span>
          <span class="font-mono text-fg tabular">{{ row.value }}</span>
        </div>
        <div class="h-1.5 overflow-hidden rounded-full bg-raised" role="meter" :aria-label="row.label" :aria-valuenow="Math.round(row.percent)" aria-valuemin="0" aria-valuemax="100">
          <div class="h-full rounded-full transition-[width] duration-500" :class="fills[meterTone(row.percent, 70, 90)]" :style="{ width: `${Math.min(row.percent, 100)}%` }" />
        </div>
      </div>

      <div v-if="metrics.temperature != null" class="flex items-center justify-between text-xs">
        <span class="flex items-center gap-1.5 text-fg-muted"><Thermometer class="size-3.5" aria-hidden="true" />{{ t('agent.temperature') }}</span>
        <span class="font-mono font-semibold tabular" :class="texts[meterTone(metrics.temperature, 60, 80)]">{{ metrics.temperature.toFixed(1) }} °C</span>
      </div>

      <div v-if="metrics.network && Object.keys(metrics.network).length > 0" class="text-xs">
        <span class="mb-1 flex items-center gap-1.5 text-fg-muted"><Activity class="size-3.5" aria-hidden="true" />{{ t('agent.network') }}</span>
        <div v-for="(data, iface) in metrics.network" :key="iface" class="flex justify-between font-mono text-xs text-fg-subtle">
          <span>{{ iface }}</span>
          <span>↓ {{ formatBps(data?.rx_bytes_sec ?? 0) }} · ↑ {{ formatBps(data?.tx_bytes_sec ?? 0) }}</span>
        </div>
      </div>
    </div>
  </template>
</template>
