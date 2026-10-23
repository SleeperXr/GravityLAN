<script setup lang="ts">
import { computed } from 'vue';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Radio } from 'lucide-vue-next';
import type { HealthIncident } from '@/types';
import EmptyState from '@/components/ui/EmptyState.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import Timeline from '@/components/common/Timeline.vue';
import { incidentEntry, statusWord } from './healthModel';
import { t } from '@/i18n';

/**
 * Recent outages, flapping, SSL and patch notices as a timeline; a click opens the device.
 * `strip`: horizontal, oldest left and newest right (health page). `list`: vertical, newest first.
 */
const props = withDefaults(defineProps<{ incidents: HealthIncident[]; layout?: 'strip' | 'list'; interactive?: boolean }>(), {
  layout: 'strip',
  interactive: true,
});
const emit = defineEmits<{ select: [deviceId: number] }>();

const entries = computed(() => {
  const list = props.incidents.map(incidentEntry);
  return props.layout === 'strip' ? list.reverse() : list;
});

function iconOf(incident: HealthIncident) {
  if (incident.status === 'flapping') return { icon: Radio, cls: 'text-warn-text' };
  if (incident.status === 'online' || incident.status === 'service_up') return { icon: CheckCircle2, cls: 'text-accent-text' };
  if (incident.severity === 'critical') return { icon: AlertCircle, cls: 'text-danger-text' };
  if (incident.severity === 'warn') return { icon: AlertTriangle, cls: 'text-warn-text' };
  return { icon: Info, cls: 'text-info-text' };
}
</script>

<template>
  <EmptyState v-if="incidents.length === 0" compact :icon="CheckCircle2" :title="t('health_page.no_incidents')" />
  <Timeline
    v-else
    :items="entries"
    :label="t('gv.timeline.incidents')"
    :orientation="layout === 'strip' ? 'horizontal' : 'vertical'"
    :interactive="interactive"
    @select="(incident) => emit('select', incident.device_id)"
  >
    <template #default="{ item: incident }">
      <span class="flex items-start gap-2.5">
        <component :is="iconOf(incident).icon" class="mt-0.5 size-4 shrink-0" :class="iconOf(incident).cls" aria-hidden="true" />
        <span class="min-w-0 flex-1">
          <span class="flex items-baseline justify-between gap-2">
            <span class="truncate text-sm font-bold text-fg">{{ incident.device_name }}</span>
            <span class="shrink-0 text-[11px] text-fg-subtle"><RelativeTime :date="incident.timestamp" /></span>
          </span>
          <span class="mt-0.5 line-clamp-2 block text-xs text-fg-muted">{{ incident.message || incident.status }}</span>
          <span class="mt-2 flex items-center justify-between gap-2 border-t border-line pt-1.5 font-mono text-[11px] text-fg-subtle">
            <span class="truncate">{{ incident.device_ip }}</span>
            <span class="shrink-0 font-semibold">{{ statusWord(incident.status) }}</span>
          </span>
        </span>
      </span>
    </template>
  </Timeline>
</template>
