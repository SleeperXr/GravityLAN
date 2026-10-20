<script setup lang="ts">
import { computed } from 'vue';
import { cn } from '@/lib/utils';

export interface RelativeTimeProps {
  date?: Date | string | number | null;
  locale?: string;
  class?: string;
}

const props = withDefaults(defineProps<RelativeTimeProps>(), {
  locale: 'de',
});

const TIME_UNITS: Array<{ unit: Intl.RelativeTimeFormatUnit; ms: number }> = [
  { unit: 'year', ms: 365.25 * 24 * 60 * 60 * 1000 },
  { unit: 'month', ms: 30.44 * 24 * 60 * 60 * 1000 },
  { unit: 'week', ms: 7 * 24 * 60 * 60 * 1000 },
  { unit: 'day', ms: 24 * 60 * 60 * 1000 },
  { unit: 'hour', ms: 60 * 60 * 1000 },
  { unit: 'minute', ms: 60 * 1000 },
  { unit: 'second', ms: 1000 },
];

const parsedDate = computed(() => {
  if (!props.date) return null;
  const d = props.date instanceof Date ? props.date : new Date(props.date);
  return Number.isNaN(d.getTime()) ? null : d;
});

const relativeLabel = computed(() => {
  const d = parsedDate.value;
  if (!d) return '—';
  const diff = d.getTime() - Date.now();
  const found = TIME_UNITS.find(({ ms }) => Math.abs(diff) >= ms);
  const unit = found ? found.unit : 'second';
  const val = found ? Math.round(diff / found.ms) : 0;
  try {
    return new Intl.RelativeTimeFormat(props.locale, { numeric: 'auto' }).format(val, unit);
  } catch {
    return d.toLocaleTimeString();
  }
});

const utcTooltip = computed(() => {
  return parsedDate.value ? parsedDate.value.toUTCString() : '';
});
</script>

<template>
  <time
    v-if="parsedDate"
    :datetime="parsedDate.toISOString()"
    :title="utcTooltip"
    :class="cn('text-zinc-400 font-mono text-[11px] cursor-help decoration-dotted hover:underline', props.class)"
  >
    {{ relativeLabel }}
  </time>
  <span v-else :class="cn('text-zinc-500 text-[11px]', props.class)">—</span>
</template>
