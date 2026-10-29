<script setup lang="ts">
import { ShieldAlert, ShieldCheck, X } from 'lucide-vue-next';
import { t } from '@/i18n';

/**
 * Resilience view of the orbit map: the devices whose failure would cut others off, biggest impact first,
 * plus backup links carrying traffic right now and devices nothing reaches any more.
 */
defineProps<{
  points: { id: number; label: string; cutOff: number }[];
  activeBackups: number;
  cutOff: number;
}>();
const emit = defineEmits<{ select: [id: number]; close: [] }>();
</script>

<template>
  <div
    class="absolute top-14 left-3 z-10 flex max-h-[calc(100%-7.5rem)] w-[min(19rem,calc(100%-4.5rem))] flex-col rounded-lg border border-line-strong bg-surface/95 shadow-pop backdrop-blur"
    role="dialog"
    :aria-label="t('gv.orbit.resilience_title')"
    @pointerdown.stop
  >
    <div class="flex items-start gap-2 border-b border-line p-3">
      <ShieldAlert class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">{{ t('gv.orbit.resilience_title') }}</p>
        <p class="text-[11px] leading-snug text-fg-subtle">{{ t('gv.orbit.resilience_hint') }}</p>
      </div>
      <button type="button" class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>

    <p v-if="activeBackups || cutOff" class="border-b border-line px-3 py-2 text-xs" aria-live="polite">
      <span v-if="activeBackups" class="block text-warn-text">{{ t('gv.orbit.backups_active', { count: activeBackups }) }}</span>
      <span v-if="cutOff" class="block text-danger-text">{{ t('gv.orbit.devices_cut_off', { count: cutOff }) }}</span>
    </p>

    <ol v-if="points.length" class="min-h-0 overflow-y-auto p-1.5">
      <li v-for="p in points" :key="p.id">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-control-hover focus-visible:bg-control-hover"
          @click="emit('select', p.id)"
        >
          <span class="min-w-0 flex-1 truncate text-fg">{{ p.label }}</span>
          <span class="shrink-0 font-mono text-xs text-warn-text tabular" :title="t('gv.orbit.spof_cuts', { count: p.cutOff })">−{{ p.cutOff }}</span>
        </button>
      </li>
    </ol>
    <p v-else class="flex items-center gap-2 p-3 text-xs text-fg-muted">
      <ShieldCheck class="size-4 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.orbit.no_spof') }}
    </p>
  </div>
</template>
