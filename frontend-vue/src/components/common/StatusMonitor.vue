<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { AlertTriangle, CheckCircle2, CircleOff, XCircle } from 'lucide-vue-next';
import { buildSlots, fitSlots, type SlotStatus } from './statusMonitor';
import { formatDateTime, formatNumber, t } from '@/i18n';

/**
 * Availability over a time window, one bar per slot, with a tooltip per slot (hover, or the
 * arrow keys once focused). Compact mode drops header and footer for table cells.
 *
 * Adapted from the Status Monitor block of 8starlabs-ui (https://github.com/8starlabs/ui),
 * MIT License, Copyright (c) 2025 Tham Kei Lok. See THIRD_PARTY_NOTICES.md.
 */
const props = withDefaults(
  defineProps<{
    bars: (number | null)[];
    /** Length of the window the bars cover, ending now */
    spanHours: number;
    uptime?: number | null;
    title?: string;
    compact?: boolean;
    size?: 'sm' | 'md';
    /** Percentage from which a slot counts as fully up */
    upAt?: number;
    /** False inside another control (a button card), where only hover shows details */
    focusable?: boolean;
  }>(),
  { uptime: null, title: undefined, compact: false, size: 'md', upAt: 99, focusable: true },
);

// Narrow cells show only the newest slots that fit, as the original does, instead of overflowing.
const root = ref<HTMLElement | null>(null);
const width = ref(0);
let observer: ResizeObserver | null = null;
onMounted(() => {
  if (!root.value) return;
  observer = new ResizeObserver(([entry]) => (width.value = entry.contentRect.width));
  observer.observe(root.value);
});
onBeforeUnmount(() => observer?.disconnect());

const allSlots = computed(() => buildSlots(props.bars, props.spanHours, new Date(), props.upAt));
const slots = computed(() => allSlots.value.slice(-fitSlots(allSlots.value.length, width.value)));
const shownHours = computed(() => (props.spanHours * slots.value.length) / Math.max(1, allSlots.value.length));
const active = ref<number | null>(null);
const barsEl = ref<HTMLElement | null>(null);
const tip = ref<{ x: number; y: number; below: boolean } | null>(null);

const look: Record<SlotStatus, { bar: string; text: string; icon: typeof CheckCircle2 }> = {
  normal: { bar: 'bg-accent', text: 'text-accent-text', icon: CheckCircle2 },
  warning: { bar: 'bg-warn', text: 'text-warn-text', icon: AlertTriangle },
  error: { bar: 'bg-danger', text: 'text-danger-text', icon: XCircle },
  empty: { bar: 'bg-line', text: 'text-fg-subtle', icon: CircleOff },
};

const short = computed(() => props.spanHours <= 48);
function when(d: Date) {
  return short.value ? formatDateTime(d, { timeStyle: 'short' }) : formatDateTime(d, { dateStyle: 'short', timeStyle: 'short' });
}
const pct = (v: number) => formatNumber(v, { maximumFractionDigits: v >= 99.95 || v === 0 ? 0 : 1 });

const spanLabel = computed(() =>
  shownHours.value > 48 && Number.isInteger(shownHours.value / 24)
    ? t('gv.status_monitor.ago_days', { count: shownHours.value / 24 })
    : t('gv.status_monitor.ago_hours', { count: Math.round(shownHours.value) }),
);

const summary = computed(() => {
  const down = slots.value.filter((s) => s.status === 'error').length;
  const partial = slots.value.filter((s) => s.status === 'warning').length;
  return t('gv.status_monitor.summary', {
    title: props.title ?? t('health_page.table_uptime'),
    uptime: props.uptime === null ? '–' : pct(props.uptime),
    down,
    partial,
    count: slots.value.length,
  });
});

function show(i: number) {
  active.value = i;
  const bar = barsEl.value?.children[i] as HTMLElement | undefined;
  if (!bar) return;
  const r = bar.getBoundingClientRect();
  const below = r.top < 120;
  tip.value = { x: r.left + r.width / 2, y: below ? r.bottom + 8 : r.top - 8, below };
}
function hide() {
  active.value = null;
  tip.value = null;
}
// The tooltip is fixed to the viewport, so anything that moves the bars closes it.
watch(tip, (open, was) => {
  if (open && !was) window.addEventListener('scroll', hide, { capture: true, passive: true });
  if (!open && was) window.removeEventListener('scroll', hide, { capture: true });
});
onBeforeUnmount(() => window.removeEventListener('scroll', hide, { capture: true }));
function onKey(e: KeyboardEvent) {
  const last = slots.value.length - 1;
  const cur = active.value ?? last + 1;
  const next = { ArrowLeft: cur - 1, ArrowRight: cur + 1, Home: 0, End: last }[e.key];
  if (next === undefined) {
    if (e.key === 'Escape') hide();
    return;
  }
  e.preventDefault();
  show(Math.min(last, Math.max(0, next)));
}

const activeSlot = computed(() => (active.value === null ? null : slots.value[active.value]));
</script>

<template>
  <div ref="root" class="w-full min-w-0">
    <div v-if="!compact && (title || uptime !== null)" class="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
      <span v-if="title" class="truncate font-semibold text-fg">{{ title }}</span>
      <span v-if="uptime !== null" class="ml-auto shrink-0 font-mono font-semibold text-fg-muted tabular">{{ t('gv.status_monitor.uptime', { pct: pct(uptime) }) }}</span>
    </div>

    <div
      v-if="slots.length"
      ref="barsEl"
      class="gl-status-monitor flex w-full items-stretch gap-[2px] rounded-[2px]"
      :class="size === 'sm' ? 'h-2.5' : 'h-5'"
      :role="focusable ? 'group' : 'img'"
      :tabindex="focusable ? 0 : undefined"
      :aria-label="summary"
      :aria-describedby="focusable && activeSlot ? 'gl-status-tip' : undefined"
      @keydown="onKey"
      @blur="hide"
      @pointerleave="hide"
      @pointerdown="hide"
    >
      <span
        v-for="(slot, i) in slots"
        :key="i"
        class="min-w-[3px] flex-1 transition-opacity first:rounded-l-[2px] last:rounded-r-[2px]"
        :class="[look[slot.status].bar, active !== null && active !== i && 'opacity-45']"
        @pointerenter="show(i)"
      />
    </div>
    <span v-else class="font-mono text-xs text-fg-subtle">–</span>

    <div v-if="!compact && slots.length" class="mt-1 flex justify-between text-micro text-fg-subtle">
      <span>{{ spanLabel }}</span>
      <span>{{ t('gv.status_monitor.now') }}</span>
    </div>

    <Teleport to="body">
      <div
        v-if="tip && activeSlot"
        id="gl-status-tip"
        role="tooltip"
        class="pointer-events-none fixed z-[60] w-max max-w-56 -translate-x-1/2 rounded-md border border-line bg-surface px-2.5 py-2 text-xs shadow-pop"
        :class="tip.below ? '' : '-translate-y-full'"
        :style="{ left: `${tip.x}px`, top: `${tip.y}px` }"
      >
        <p class="flex items-center gap-1.5 font-semibold" :class="look[activeSlot.status].text">
          <component :is="look[activeSlot.status].icon" class="size-3.5 shrink-0" aria-hidden="true" />
          {{ t(`gv.status_monitor.${activeSlot.status}`) }}
          <span v-if="activeSlot.pct !== null" class="ml-auto pl-2 font-mono tabular">{{ pct(activeSlot.pct) }} %</span>
        </p>
        <p class="mt-0.5 font-mono text-xs text-fg-muted">{{ when(activeSlot.start) }} – {{ when(activeSlot.end) }}</p>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.gl-status-monitor:focus-visible {
  outline: 2px solid var(--gl-accent);
  outline-offset: 3px;
}
</style>
