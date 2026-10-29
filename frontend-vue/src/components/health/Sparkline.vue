<script setup lang="ts">
import { computed } from 'vue';

/** Latency trend in a table cell; gaps (no answer) break the line instead of being bridged. */
const props = withDefaults(defineProps<{ values: (number | null)[]; width?: number; height?: number }>(), { width: 88, height: 24 });

const path = computed(() => {
  const vals = props.values;
  const valid = vals.filter((v): v is number => v !== null);
  if (vals.length < 2 || valid.length < 2) return '';
  const min = Math.min(...valid);
  const range = Math.max(...valid) - min || 1;
  let d = '';
  let pen = false;
  vals.forEach((v, i) => {
    if (v === null) {
      pen = false;
      return;
    }
    const x = (i / (vals.length - 1)) * props.width;
    const y = props.height - 2 - ((v - min) / range) * (props.height - 4);
    d += `${pen ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} `;
    pen = true;
  });
  return d.trim();
});
</script>

<template>
  <svg v-if="path" :width="width" :height="height" class="shrink-0 overflow-visible" aria-hidden="true">
    <path :d="path" fill="none" stroke="var(--gl-info)" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
  <span v-else class="font-mono text-xs text-fg-subtle">–</span>
</template>
