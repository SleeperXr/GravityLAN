<script setup lang="ts">
import { computed, ref } from 'vue';
import type { HealthSamplePoint } from '@/types';
import { formatDateTime, t } from '@/i18n';

/**
 * Latency over the chosen period with a crosshair tooltip (mouse, touch, arrow keys).
 * Offline samples sit on the baseline as red marks, so outages stay visible.
 */
const props = defineProps<{ samples: HealthSamplePoint[]; loading?: boolean }>();

const W = 600;
const H = 160;
const PAD = { top: 12, right: 8, bottom: 22, left: 40 };
const plotW = W - PAD.left - PAD.right;
const plotH = H - PAD.top - PAD.bottom;

const container = ref<HTMLElement | null>(null);
const active = ref<number | null>(null);

const stats = computed(() => {
  const vals = props.samples.map((s) => s.latency_ms).filter((v): v is number => v !== null);
  const min = vals.length ? Math.min(...vals) : 0;
  const max = vals.length ? Math.max(...vals) : 10;
  return { min, max, top: max === min ? max + 1 : max, bottom: Math.max(0, min - (max - min) * 0.1) };
});

const points = computed(() => {
  const n = props.samples.length;
  const { top, bottom } = stats.value;
  return props.samples.map((s, i) => {
    const x = PAD.left + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
    const y = s.latency_ms !== null ? PAD.top + plotH - ((s.latency_ms - bottom) / (top - bottom || 1)) * plotH : PAD.top + plotH;
    return { x, y, s };
  });
});

const linePath = computed(() => {
  let d = '';
  let pen = false;
  for (const p of points.value) {
    if (p.s.latency_ms === null) {
      pen = false;
      continue;
    }
    d += `${pen ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)} `;
    pen = true;
  }
  return d.trim();
});

const areaPath = computed(() => {
  const valid = points.value.filter((p) => p.s.latency_ms !== null);
  if (valid.length < 2) return '';
  const base = (PAD.top + plotH).toFixed(1);
  return `${valid.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')} L${valid[valid.length - 1].x.toFixed(1)} ${base} L${valid[0].x.toFixed(1)} ${base} Z`;
});

const yTicks = computed(() => {
  const { top, bottom } = stats.value;
  return [0, 0.5, 1].map((f) => ({ y: PAD.top + plotH - f * plotH, label: `${(bottom + f * (top - bottom)).toFixed(top - bottom < 10 ? 1 : 0)}` }));
});

const xTicks = computed(() => {
  const n = props.samples.length;
  if (n < 2) return [];
  return [0, Math.floor((n - 1) / 2), n - 1].map((i) => ({ x: points.value[i].x, label: formatDateTime(props.samples[i].timestamp, { hour: '2-digit', minute: '2-digit' }) }));
});

const offlineCount = computed(() => props.samples.filter((s) => !s.is_online).length);
const summary = computed(() => `${t('health_page.drawer_telemetry')}: Min ${stats.value.min.toFixed(1)} ms, Max ${stats.value.max.toFixed(1)} ms, ${props.samples.length} samples, ${offlineCount.value} offline`);

function pick(clientX: number) {
  const el = container.value;
  if (!el || points.value.length === 0) return;
  const rect = el.getBoundingClientRect();
  const svgX = ((clientX - rect.left) / rect.width) * W;
  let best = 0;
  points.value.forEach((p, i) => {
    if (Math.abs(p.x - svgX) < Math.abs(points.value[best].x - svgX)) best = i;
  });
  active.value = best;
}

function onKey(event: KeyboardEvent) {
  const n = points.value.length;
  if (!n) return;
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    event.preventDefault();
    const step = event.key === 'ArrowRight' ? 1 : -1;
    active.value = Math.max(0, Math.min(n - 1, (active.value ?? (step > 0 ? -1 : n)) + step));
  } else if (event.key === 'Escape') {
    active.value = null;
  }
}

const hovered = computed(() => (active.value !== null ? points.value[active.value] : null));
</script>

<template>
  <div class="rounded-md border border-line bg-sunken p-3">
    <div class="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
      <span class="font-semibold text-fg">{{ t('health_page.drawer_telemetry') }}</span>
      <span v-if="samples.length >= 2" class="font-mono text-fg-subtle">Min {{ stats.min.toFixed(1) }} ms · Max {{ stats.max.toFixed(1) }} ms</span>
    </div>
    <div v-if="samples.length < 2" class="flex h-36 items-center justify-center font-mono text-xs text-fg-subtle">
      {{ loading ? t('common.loading') : t('health_page.not_enough_samples') }}
    </div>
    <div
      v-else
      ref="container"
      class="relative h-40 cursor-crosshair touch-pan-y select-none"
      tabindex="0"
      role="img"
      :aria-label="summary"
      @pointermove="pick($event.clientX)"
      @pointerleave="active = null"
      @keydown="onKey"
      @blur="active = null"
    >
      <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="h-full w-full overflow-visible" aria-hidden="true">
        <line v-for="tick in yTicks" :key="tick.y" :x1="PAD.left" :x2="W - PAD.right" :y1="tick.y" :y2="tick.y" stroke="var(--gl-line)" :stroke-dasharray="tick.y === PAD.top + plotH ? undefined : '3 4'" vector-effect="non-scaling-stroke" />
        <path v-if="areaPath" :d="areaPath" fill="var(--gl-info)" fill-opacity="0.1" />
        <path :d="linePath" fill="none" stroke="var(--gl-info)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
        <template v-for="(p, i) in points" :key="i">
          <rect v-if="!p.s.is_online" :x="p.x - 1.5" :y="PAD.top + plotH - 6" width="3" height="6" fill="var(--gl-danger)" />
        </template>
        <line v-if="hovered" :x1="hovered.x" :x2="hovered.x" :y1="PAD.top" :y2="PAD.top + plotH" stroke="var(--gl-fg-subtle)" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" />
      </svg>
      <span v-for="tick in yTicks" :key="`y${tick.y}`" class="absolute left-0 -translate-y-1/2 font-mono text-micro text-fg-subtle" :style="{ top: `${(tick.y / H) * 100}%` }">{{ tick.label }}</span>
      <span v-for="tick in xTicks" :key="`x${tick.x}`" class="absolute bottom-0 -translate-x-1/2 font-mono text-micro whitespace-nowrap text-fg-subtle" :style="{ left: `${(tick.x / W) * 100}%` }">{{ tick.label }}</span>
      <span
        v-if="hovered"
        class="pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-sunken"
        :class="hovered.s.is_online ? 'bg-info' : 'bg-danger'"
        :style="{ left: `${(hovered.x / W) * 100}%`, top: `${(hovered.y / H) * 100}%` }"
      />
      <div
        v-if="hovered"
        role="status"
        class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs shadow-pop"
        :style="{ left: `${Math.min(Math.max((hovered.x / W) * 100, 15), 85)}%`, top: `${Math.max(14, (hovered.y / H) * 100 - 6)}%` }"
      >
        <p class="font-mono text-xs text-fg-subtle">{{ formatDateTime(hovered.s.timestamp, { dateStyle: 'short', timeStyle: 'medium' }) }}</p>
        <p class="mt-0.5 flex items-center gap-1.5 font-mono font-semibold" :class="hovered.s.is_online ? 'text-fg' : 'text-danger-text'">
          <span class="size-2 rounded-full" :class="hovered.s.is_online ? 'bg-info' : 'bg-danger'" />
          {{ hovered.s.latency_ms !== null ? `${hovered.s.latency_ms.toFixed(1)} ms` : t('common.offline') }}
          <span v-if="hovered.s.ports_total" class="font-normal text-fg-subtle">· {{ hovered.s.ports_up }}/{{ hovered.s.ports_total }} Ports</span>
        </p>
      </div>
    </div>
  </div>
</template>
