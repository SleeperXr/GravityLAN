<script setup lang="ts">
import { Cpu, MemoryStick, Pencil } from 'lucide-vue-next';
import type { Device } from '@/types';
import StatusDot from '@/components/common/StatusDot.vue';
import ServiceBadge from './ServiceBadge.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/** Compact rows: the phone layout, and the list view on desktop. A row opens the editor. */
defineProps<{ devices: Device[] }>();
const emit = defineEmits<{ edit: [device: Device] }>();
</script>

<template>
  <ul class="gl-card divide-y divide-line overflow-hidden">
    <li
      v-for="device in devices"
      :key="device.id"
      class="group flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-raised md:flex-nowrap"
      @click="emit('edit', device)"
    >
      <StatusDot :state="device.is_online ? 'online' : 'offline'" :label="device.is_online ? t('network.online') : t('network.offline')" />
      <div class="min-w-0 flex-1">
        <button
          type="button"
          class="block max-w-full truncate text-left text-sm font-semibold text-fg hover:underline"
          :class="!device.is_online && 'text-fg-muted'"
          @click.stop="emit('edit', device)"
        >
          {{ deviceLabel(device) }}
        </button>
        <p class="font-mono text-xs text-fg-subtle">{{ device.ip }}</p>
      </div>

      <div v-if="device.has_agent && device.agent_info?.metrics" class="hidden shrink-0 gap-2 lg:flex">
        <span class="inline-flex items-center gap-1 rounded-sm bg-raised px-1.5 py-0.5 font-mono text-[11px] text-fg-muted" title="CPU">
          <Cpu class="size-3" aria-hidden="true" />{{ device.agent_info.metrics.cpu_usage }}%
        </span>
        <span class="inline-flex items-center gap-1 rounded-sm bg-raised px-1.5 py-0.5 font-mono text-[11px] text-fg-muted" title="RAM">
          <MemoryStick class="size-3" aria-hidden="true" />{{ device.agent_info.metrics.memory_usage }}%
        </span>
      </div>

      <div class="order-last flex w-full flex-wrap gap-1.5 pl-6 md:order-none md:w-auto md:max-w-md md:justify-end md:pl-0">
        <ServiceBadge v-for="service in device.services" :key="service.id" :service="service" :ip="device.ip" />
      </div>

      <button
        type="button"
        class="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg"
        :aria-label="`${t('dashboard.edit_device')}: ${deviceLabel(device)}`"
        @click.stop="emit('edit', device)"
      >
        <Pencil class="size-4" aria-hidden="true" />
      </button>
    </li>
  </ul>
</template>
