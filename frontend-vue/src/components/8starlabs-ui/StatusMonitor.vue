<script setup lang="ts">
import { computed, ref } from 'vue';
import { AlertTriangle, CheckCircle2, CircleOff, XCircle } from 'lucide-vue-next';
import { cn } from '@/lib/utils';

export type AppStatus = 'normal' | 'warning' | 'error' | 'empty';

export interface AppStatusData {
  status: AppStatus;
  timestamp?: string | Date;
  info?: string;
}

export interface StatusMonitorProps {
  statuses: AppStatusData[];
  unit?: 'days' | 'hours' | 'slots';
  title?: string;
  showUptime?: boolean;
  slots?: number;
  compact?: boolean;
  class?: string;
}

const props = withDefaults(defineProps<StatusMonitorProps>(), {
  unit: 'hours',
  showUptime: true,
  slots: 36,
  compact: false,
});

const hoveredIndex = ref<number | null>(null);

const statusConfig = {
  normal: {
    label: 'Operational',
    defaultInfo: 'All network checks responded normally.',
    barClassName: 'bg-emerald-500 hover:bg-emerald-400',
    textClassName: 'text-emerald-400',
    icon: CheckCircle2,
  },
  warning: {
    label: 'Degraded',
    defaultInfo: 'Elevated latency or partial service degradation.',
    barClassName: 'bg-amber-500 hover:bg-amber-400',
    textClassName: 'text-amber-400',
    icon: AlertTriangle,
  },
  error: {
    label: 'Offline / Incident',
    defaultInfo: 'Host or monitored service was unreachable.',
    barClassName: 'bg-rose-500 hover:bg-rose-400',
    textClassName: 'text-rose-400',
    icon: XCircle,
  },
  empty: {
    label: 'No telemetry',
    defaultInfo: 'No probe data recorded for this window.',
    barClassName: 'bg-zinc-800/80 hover:bg-zinc-700',
    textClassName: 'text-zinc-400',
    icon: CircleOff,
  },
} as const;

const uptimePercentage = computed(() => {
  const valid = props.statuses.filter((s) => s.status !== 'empty');
  if (valid.length === 0) return 100;
  const normalCount = valid.filter((s) => s.status === 'normal').length;
  return parseFloat(((normalCount / valid.length) * 100).toFixed(1));
});

const visibleStatuses = computed<AppStatusData[]>(() => {
  const count = props.slots;
  const padCount = Math.max(0, count - props.statuses.length);
  const padding: AppStatusData[] = Array.from({ length: padCount }, () => ({ status: 'empty' as const }));
  return [...padding, ...props.statuses].slice(-count);
});

const activeTooltip = computed(() => {
  if (hoveredIndex.value === null) return null;
  const item = visibleStatuses.value[hoveredIndex.value];
  if (!item) return null;
  return {
    item,
    config: statusConfig[item.status],
  };
});

function formatTimestamp(ts?: string | Date): string {
  if (!ts) return '';
  if (ts instanceof Date) {
    return ts.toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
  return ts;
}
</script>

<template>
  <div :class="cn('w-full font-sans select-none relative', props.class)">
    <!-- Header -->
    <div v-if="title || showUptime" class="flex justify-between items-center text-xs mb-2">
      <span v-if="title" class="font-medium text-zinc-200 tracking-tight">{{ title }}</span>
      <span
        v-if="showUptime"
        :class="[
          'font-mono font-semibold text-[11px] px-1.5 py-0.5 rounded-md border',
          uptimePercentage >= 98
            ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
            : uptimePercentage >= 90
              ? 'text-amber-400 bg-amber-500/10 border-amber-500/20'
              : 'text-rose-400 bg-rose-500/10 border-rose-500/20',
        ]"
      >
        {{ uptimePercentage }}% uptime
      </span>
    </div>

    <!-- Status Bars -->
    <div
      :class="cn('grid w-full gap-[3px]', compact ? 'h-5' : 'h-7')"
      :style="{ gridTemplateColumns: `repeat(${visibleStatuses.length}, minmax(0, 1fr))` }"
      @mouseleave="hoveredIndex = null"
    >
      <div
        v-for="(item, idx) in visibleStatuses"
        :key="idx"
        :class="
          cn(
            'h-full w-full rounded-[2px] transition-all duration-150 cursor-pointer',
            idx === 0 && 'rounded-l-sm',
            idx === visibleStatuses.length - 1 && 'rounded-r-sm',
            statusConfig[item.status].barClassName,
            hoveredIndex === idx && 'scale-y-110 ring-1 ring-white/30'
          )
        "
        @mouseenter="hoveredIndex = idx"
      />
    </div>

    <!-- Floating Popover Tooltip -->
    <div
      v-if="activeTooltip"
      class="mt-2 flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg bg-[#1b1b20] border border-zinc-700/80 text-[11px] text-zinc-200 shadow-lg animate-in fade-in duration-150"
    >
      <div class="flex items-center gap-1.5 min-w-0">
        <component :is="activeTooltip.config.icon" :class="cn('w-3.5 h-3.5 shrink-0', activeTooltip.config.textClassName)" />
        <span :class="cn('font-semibold shrink-0', activeTooltip.config.textClassName)">
          {{ activeTooltip.config.label }}
        </span>
        <span class="text-zinc-400 truncate">{{ activeTooltip.item.info || activeTooltip.config.defaultInfo }}</span>
      </div>
      <span v-if="activeTooltip.item.timestamp" class="font-mono text-[10px] text-zinc-400 shrink-0">
        {{ formatTimestamp(activeTooltip.item.timestamp) }}
      </span>
    </div>

    <!-- Footer Legend -->
    <div v-else-if="!compact" class="flex justify-between text-[11px] text-zinc-500 mt-1.5">
      <span>{{ visibleStatuses.length }} {{ unit }} window</span>
      <span>Live</span>
    </div>
  </div>
</template>
