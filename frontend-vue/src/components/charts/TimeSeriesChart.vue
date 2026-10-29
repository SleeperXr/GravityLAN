<script setup lang="ts">
import { computed, ref } from 'vue';
import { formatDateTime } from '@/i18n';

/**
 * Line chart for one or more series over time (agent CPU/RAM/temperature, fleet averages).
 * Crosshair with values by pointer or arrow keys; the latest value of each series sits in the
 * legend, so the chart reads without hovering.
 */
export interface ChartSeries {
  label: string;
  color: string;
  values: number[];
  suffix?: string;
}

const props = withDefaults(defineProps<{ timestamps: string[]; series: ChartSeries[]; max?: number; height?: number; label: string }>(), { height: 160 });

const W = 600;
const PAD = { top: 10, right: 6, bottom: 20, left: 34 };
const H = computed(() => props.height);
const plotW = W - PAD.left - PAD.right;
const plotH = computed(() => H.value - PAD.top - PAD.bottom);
const active = ref<number | null>(null);
const box = ref<HTMLElement | null>(null);

const top = computed(() => {
  if (props.max) return props.max;
  const all = props.series.flatMap((s) => s.values);
  const peak = all.length ? Math.max(...all) : 1;
  return Math.max(1, Math.ceil(peak * 1.15));
});

const n = computed(() => props.timestamps.length);
const xOf = (i: number) => PAD.left + (n.value > 1 ? (i / (n.value - 1)) * plotW : plotW / 2);
const yOf = (v: number) => PAD.top + plotH.value - (Math.min(v, top.value) / top.value) * plotH.value;

const paths = computed(() => props.series.map((s) => s.values.map((v, i) => `${i ? 'L' : 'M'}${xOf(i).toFixed(1)} ${yOf(v).toFixed(1)}`).join(' ')));
const ticks = computed(() => [0, 0.5, 1].map((f) => ({ y: PAD.top + plotH.value - f * plotH.value, label: Math.round(top.value * f) })));
const xTicks = computed(() => (n.value < 2 ? [] : [0, Math.floor((n.value - 1) / 2), n.value - 1].map((i) => ({ x: xOf(i), label: formatDateTime(props.timestamps[i], { hour: '2-digit', minute: '2-digit' }) }))));

function pick(clientX: number) {
  const el = box.value;
  if (!el || n.value === 0) return;
  const rect = el.getBoundingClientRect();
  const svgX = ((clientX - rect.left) / rect.width) * W;
  active.value = Math.max(0, Math.min(n.value - 1, Math.round(((svgX - PAD.left) / plotW) * (n.value - 1))));
}

function onKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  e.preventDefault();
  const step = e.key === 'ArrowRight' ? 1 : -1;
  active.value = Math.max(0, Math.min(n.value - 1, (active.value ?? (step > 0 ? -1 : n.value)) + step));
}

const at = computed(() => (active.value !== null ? active.value : n.value - 1));
const summary = computed(() => `${props.label}: ${props.series.map((s) => `${s.label} ${s.values[n.value - 1]?.toFixed(1) ?? '–'}${s.suffix ?? ''}`).join(', ')}`);
</script>

<template>
  <div>
    <ul class="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
      <li v-for="s in series" :key="s.label" class="flex items-center gap-1.5">
        <span class="h-0.5 w-3 rounded-full" :style="{ backgroundColor: s.color }" aria-hidden="true" />
        <span class="text-fg-subtle">{{ s.label }}</span>
        <span class="font-mono font-semibold text-fg tabular">{{ s.values[at]?.toFixed(1) ?? '–' }}{{ s.suffix }}</span>
      </li>
      <li v-if="active !== null" class="ml-auto font-mono text-fg-subtle">{{ formatDateTime(timestamps[active], { dateStyle: 'short', timeStyle: 'short' }) }}</li>
    </ul>
    <div
      ref="box"
      class="relative cursor-crosshair touch-pan-y select-none"
      :style="{ height: `${height}px` }"
      tabindex="0"
      role="img"
      :aria-label="summary"
      @pointermove="pick($event.clientX)"
      @pointerleave="active = null"
      @keydown="onKey"
      @blur="active = null"
    >
      <svg :viewBox="`0 0 ${W} ${height}`" preserveAspectRatio="none" class="h-full w-full overflow-visible" aria-hidden="true">
        <line v-for="tk in ticks" :key="tk.y" :x1="PAD.left" :x2="W - PAD.right" :y1="tk.y" :y2="tk.y" stroke="var(--gl-line)" :stroke-dasharray="tk.label === 0 ? undefined : '3 4'" vector-effect="non-scaling-stroke" />
        <path v-for="(d, i) in paths" :key="i" :d="d" fill="none" :stroke="series[i].color" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
        <line v-if="active !== null" :x1="xOf(active)" :x2="xOf(active)" :y1="PAD.top" :y2="PAD.top + plotH" stroke="var(--gl-fg-subtle)" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" />
      </svg>
      <span v-for="tk in ticks" :key="`t${tk.y}`" class="absolute left-0 -translate-y-1/2 font-mono text-micro text-fg-subtle" :style="{ top: `${(tk.y / height) * 100}%` }">{{ tk.label }}</span>
      <span v-for="tk in xTicks" :key="`x${tk.x}`" class="absolute bottom-0 -translate-x-1/2 font-mono text-micro whitespace-nowrap text-fg-subtle" :style="{ left: `${(tk.x / W) * 100}%` }">{{ tk.label }}</span>
      <template v-if="active !== null">
        <span
          v-for="s in series"
          :key="`dot-${s.label}`"
          class="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
          :style="{ backgroundColor: s.color, left: `${(xOf(active) / W) * 100}%`, top: `${(yOf(s.values[active] ?? 0) / height) * 100}%` }"
        />
      </template>
    </div>
  </div>
</template>
