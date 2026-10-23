<script setup lang="ts">
import { Route, X } from 'lucide-vue-next';
import type { TracedPath } from './orbitFocus';
import { t } from '@/i18n';

/** Path tracing: first asks for the destination, then lists the hops of the found route. */
defineProps<{
  startLabel: string;
  hasTarget: boolean;
  path: TracedPath | null;
  hops: { id: number; label: string; linkType: string | null; interrupted: boolean }[];
}>();
const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <div
    class="absolute bottom-3 left-3 z-10 w-[min(24rem,calc(100%-4.5rem))] space-y-2.5 rounded-lg border border-accent bg-surface/95 p-3.5 shadow-pop backdrop-blur"
    role="dialog"
    :aria-label="t('gv.orbit.trace')"
    @pointerdown.stop
  >
    <div class="flex items-center gap-2">
      <Route class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
      <p class="min-w-0 flex-1 truncate text-sm font-semibold text-fg" aria-live="polite">
        <template v-if="!hasTarget">{{ t('gv.orbit.trace_pick', { name: startLabel }) }}</template>
        <template v-else-if="path">{{ t('gv.orbit.trace_hops', { count: path.bodyIds.length - 1 }) }}</template>
        <template v-else>{{ t('gv.orbit.trace_none') }}</template>
      </p>
      <button type="button" class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>

    <p v-if="hasTarget && !path" class="text-xs text-fg-muted">{{ t('gv.orbit.trace_none_hint') }}</p>
    <p v-if="path?.broken" class="text-xs font-medium text-danger-text">{{ t('gv.orbit.trace_broken') }}</p>

    <ol v-if="hops.length" class="max-h-44 space-y-1 overflow-y-auto text-xs">
      <li v-for="(hop, i) in hops" :key="hop.id" class="flex items-center gap-2">
        <span class="flex size-4 shrink-0 items-center justify-center rounded-full bg-accent font-mono text-[10px] font-bold text-sign-ink">{{ i + 1 }}</span>
        <span class="min-w-0 flex-1 truncate text-fg">{{ hop.label }}</span>
        <span v-if="hop.linkType" class="font-mono text-[10px]" :class="hop.interrupted ? 'text-danger-text' : 'text-fg-subtle'">{{ hop.linkType }}</span>
      </li>
    </ol>
  </div>
</template>
