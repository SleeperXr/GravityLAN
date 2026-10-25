<script setup lang="ts">
import { computed } from 'vue';
import { CircleAlert, CircleCheck, CloudOff } from 'lucide-vue-next';
import type { Device } from '@/types';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { networkPulse } from './pulse';
import { t } from '@/i18n';

/**
 * One line above the status board: is the network fine, and how fresh is that answer.
 * Counts follow the status board and the notices (offline only for devices watched 24/7).
 */
const props = defineProps<{ devices: Device[]; updated: Date | null; failed: boolean }>();

const pulse = computed(() => networkPulse(props.devices));
const problems = computed(() => pulse.value.offline + pulse.value.degraded);
const summary = computed(() => {
  const p = pulse.value;
  if (!problems.value) return t('gv.pulse.all_clear', { online: p.online, total: p.total });
  return [p.offline ? t('gv.lines.dropped', { count: p.offline }) : '', p.degraded ? t('gv.lines.degraded', { count: p.degraded }) : ''].filter(Boolean).join(' · ');
});
</script>

<template>
  <div class="flex flex-wrap items-center gap-x-4 gap-y-1" role="status">
    <p class="flex min-w-0 items-center gap-2 text-sm font-semibold" :class="problems ? (pulse.offline ? 'text-danger-text' : 'text-warn-text') : 'text-accent-text'">
      <component :is="problems ? CircleAlert : CircleCheck" class="size-4 shrink-0" aria-hidden="true" />
      <span>{{ summary }}</span>
    </p>
    <p class="flex items-center gap-1.5 text-xs" :class="failed ? 'text-warn-text' : 'text-fg-subtle'">
      <CloudOff v-if="failed" class="size-3.5 shrink-0" aria-hidden="true" />
      <span v-if="failed">{{ t('gv.pulse.failed') }}</span>
      <span>{{ t('gv.pulse.updated') }} <RelativeTime :date="updated" /></span>
    </p>
  </div>
</template>
