<script setup lang="ts">
import { computed } from 'vue';
import { cn } from '@/lib/utils';

export interface PartitionSegmentItem {
  key: string;
  label: string;
  sublabel?: string;
  value: number;
  colorClass?: string;
  textClass?: string;
}

export interface PartitionBarProps {
  segments: PartitionSegmentItem[];
  size?: 'sm' | 'md' | 'lg';
  showLabels?: boolean;
  class?: string;
}

const props = withDefaults(defineProps<PartitionBarProps>(), {
  size: 'md',
  showLabels: true,
});

const total = computed(() =>
  Math.max(
    1,
    props.segments.reduce((sum, s) => sum + Math.max(0, s.value), 0)
  )
);

const normalizedSegments = computed(() =>
  props.segments
    .filter((s) => s.value > 0)
    .map((s) => ({
      ...s,
      percent: Math.max(4, Math.round((s.value / total.value) * 100)),
    }))
);

const barHeightClass = computed(() => {
  if (props.size === 'sm') return 'h-2';
  if (props.size === 'lg') return 'h-3.5';
  return 'h-2.5';
});
</script>

<template>
  <div :class="cn('w-full', props.class)">
    <!-- Proportional Segmented Bar -->
    <ul class="flex flex-row w-full gap-1.5 list-none p-0 m-0">
      <li
        v-for="seg in normalizedSegments"
        :key="seg.key"
        class="flex flex-col min-w-0 transition-all duration-300"
        :style="{ flexBasis: `${seg.percent}%`, flexGrow: 1 }"
      >
        <div
          :class="cn('rounded-full w-full shrink-0 transition-opacity hover:opacity-85', barHeightClass, seg.colorClass || 'bg-emerald-500')"
          :title="`${seg.label}: ${seg.value}`"
        />
      </li>
    </ul>

    <!-- Segment Legend -->
    <div v-if="showLabels" class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 mt-2.5">
      <div
        v-for="seg in segments"
        :key="seg.key"
        class="inline-flex items-center gap-1.5 text-xs"
      >
        <span :class="cn('w-2 h-2 rounded-full shrink-0', seg.colorClass || 'bg-emerald-500')" />
        <span class="font-medium text-zinc-300">{{ seg.label }}</span>
        <span class="font-mono text-[11px] text-zinc-400">{{ seg.sublabel ?? seg.value }}</span>
      </div>
    </div>
  </div>
</template>
