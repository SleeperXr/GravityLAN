<script setup lang="ts">
import { X } from 'lucide-vue-next';
import type { Device } from '@/types';
import type { OrbitBody } from './orbitModel';
import Button from '@/components/ui/Button.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/** Edit mode: the selected body, with the hub it orbits (choosable) and a link to its editor. */
defineProps<{ device: Device; body: OrbitBody; parents: OrbitBody[] }>();
const emit = defineEmits<{ open: []; close: []; assign: [targetId: number] }>();
</script>

<template>
  <div class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-2.5 rounded-lg border border-line-strong bg-surface p-3.5 shadow-pop" @pointerdown.stop>
    <div class="flex items-center justify-between gap-2">
      <div class="min-w-0">
        <p class="truncate text-sm font-semibold text-fg">{{ deviceLabel(device) }}</p>
        <p class="font-mono text-xs text-fg-subtle">{{ device.ip }}</p>
      </div>
      <div class="flex items-center gap-1.5">
        <Button size="sm" @click="emit('open')">{{ t('dashboard.edit_device') }}</Button>
        <button type="button" class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="emit('close')">
          <X class="size-4" />
        </button>
      </div>
    </div>
    <label v-if="body.kind !== 'star' && parents.length > 0" class="flex flex-col gap-1 text-xs font-medium text-fg">
      <span>{{ t('gv.orbit.hub') }}</span>
      <select
        :value="body.parentId ?? ''"
        class="h-8 rounded-md border border-line bg-sunken px-2 text-xs text-fg focus:border-accent focus:outline-none"
        @change="emit('assign', Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="p in parents" :key="p.id" :value="p.id">{{ deviceLabel(p.device) }} ({{ t(`gv.orbit.role_${p.kind}`) }})</option>
      </select>
    </label>
  </div>
</template>
