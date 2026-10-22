<script setup lang="ts">
import { t } from '@/i18n';

/** Availability per time slice: full green, partial amber, down red, no data grey. */
defineProps<{ bars: (number | null)[]; uptime: number; height?: 'sm' | 'md' }>();

function barClass(pct: number | null) {
  if (pct === null) return 'bg-raised';
  if (pct >= 99) return 'bg-accent';
  if (pct > 0) return 'bg-warn';
  return 'bg-danger';
}
</script>

<template>
  <div
    v-if="bars.length > 0"
    class="flex w-full items-end gap-[2px]"
    :class="height === 'sm' ? 'h-2.5' : 'h-4'"
    role="img"
    :aria-label="`${t('health_page.table_uptime')}: ${uptime.toFixed(1)} %`"
  >
    <span v-for="(pct, idx) in bars" :key="idx" class="h-full min-w-[2px] flex-1 rounded-[1px]" :class="barClass(pct)" :title="pct !== null ? `${pct}%` : '–'" />
  </div>
  <span v-else class="font-mono text-xs text-fg-subtle">100%</span>
</template>
