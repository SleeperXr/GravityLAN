<script setup lang="ts">
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Radio } from 'lucide-vue-next';
import type { HealthIncident } from '@/types';
import EmptyState from '@/components/ui/EmptyState.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { statusWord } from './healthModel';
import { t } from '@/i18n';

/** Recent outages, flapping, SSL and patch notices; a click opens the device. */
withDefaults(defineProps<{ incidents: HealthIncident[]; layout?: 'grid' | 'list' }>(), { layout: 'grid' });
const emit = defineEmits<{ select: [deviceId: number] }>();

function iconOf(incident: HealthIncident) {
  if (incident.status === 'flapping') return { icon: Radio, cls: 'text-warn-text animate-pulse' };
  if (incident.severity === 'critical') return { icon: AlertCircle, cls: 'text-danger-text' };
  if (incident.severity === 'warn') return { icon: AlertTriangle, cls: 'text-warn-text' };
  if (incident.status === 'online' || incident.status === 'service_up') return { icon: CheckCircle2, cls: 'text-accent-text' };
  return { icon: Info, cls: 'text-info-text' };
}

const frame = (incident: HealthIncident) =>
  incident.severity === 'critical' ? 'border-danger/30 bg-danger/[0.05]' : incident.severity === 'warn' ? 'border-warn/30 bg-warn/[0.05]' : 'border-line bg-raised';
</script>

<template>
  <EmptyState v-if="incidents.length === 0" compact :icon="CheckCircle2" :title="t('health_page.no_incidents')" />
  <ul v-else class="max-h-[30rem] overflow-y-auto pr-1" :class="layout === 'grid' ? 'grid gap-2.5 md:grid-cols-2 xl:grid-cols-3' : 'space-y-2'">
    <li v-for="incident in incidents" :key="incident.id">
      <button type="button" class="flex w-full items-start gap-3 rounded-md border p-3 text-left transition-colors hover:border-accent/50" :class="frame(incident)" @click="emit('select', incident.device_id)">
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
      </button>
    </li>
  </ul>
</template>
