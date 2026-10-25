<script setup lang="ts">
import { computed } from 'vue';
import { ArrowRight, CircleAlert, CircleCheck, CloudOff } from 'lucide-vue-next';
import type { Device } from '@/types';
import Button from '@/components/ui/Button.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { deviceLabel } from '@/lib/networks';
import { attentionDevices, nameList, networkPulse } from './pulse';
import { t } from '@/i18n';

/**
 * One line above the status board: is the network fine, which devices are not, and how fresh
 * that answer is. Counts follow the status board and the notices (offline only for devices
 * watched 24/7); the button opens the first device that needs attention, offline before degraded.
 */
const props = defineProps<{ devices: Device[]; updated: Date | null; failed: boolean }>();
const emit = defineEmits<{ open: [device: Device] }>();

const pulse = computed(() => networkPulse(props.devices));
const attention = computed(() => attentionDevices(props.devices));
const problems = computed(() => pulse.value.offline + pulse.value.degraded);
const first = computed(() => attention.value.offline[0] ?? attention.value.degraded[0] ?? null);

function named(text: string, devices: Device[]) {
  return t('gv.pulse.named', { text, names: nameList(devices.map(deviceLabel)) });
}
const summary = computed(() => {
  const p = pulse.value;
  if (!problems.value) return t('gv.pulse.all_clear', { online: p.online, total: p.total });
  const { offline, degraded } = attention.value;
  return [
    offline.length ? named(t('gv.lines.dropped', { count: offline.length }), offline) : '',
    degraded.length ? named(t('gv.lines.degraded', { count: degraded.length }), degraded) : '',
  ]
    .filter(Boolean)
    .join(' · ');
});
</script>

<template>
  <!-- Only the summary and a failed refresh are live regions; the ticking "updated" time would be read out every minute -->
  <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
    <p class="flex min-w-0 items-center gap-2 text-sm font-semibold" :class="problems ? (pulse.offline ? 'text-danger-text' : 'text-warn-text') : 'text-accent-text'" role="status">
      <component :is="problems ? CircleAlert : CircleCheck" class="size-4 shrink-0" aria-hidden="true" />
      <span>{{ summary }}</span>
    </p>
    <p class="flex items-center gap-1.5 text-xs" :class="failed ? 'text-warn-text' : 'text-fg-subtle'">
      <span role="status" class="contents">
        <template v-if="failed">
          <CloudOff class="size-3.5 shrink-0" aria-hidden="true" /><span>{{ t('gv.pulse.failed') }}</span><span aria-hidden="true">·</span>
        </template>
      </span>
      <span>{{ t('gv.pulse.updated') }} <RelativeTime :date="updated" /></span>
    </p>
    <Button v-if="first" size="sm" class="sm:ml-auto" :aria-label="t('gv.pulse.jump_label', { name: deviceLabel(first) })" @click="emit('open', first)">
      {{ t('gv.pulse.jump') }}<ArrowRight aria-hidden="true" />
    </Button>
  </div>
</template>
