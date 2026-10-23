<script setup lang="ts">
import { X } from 'lucide-vue-next';
import type { Device } from '@/types';
import { roleOf, type OrbitBody, type OrbitRole } from './orbitModel';
import Button from '@/components/ui/Button.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * Edit mode: the selected body with its role (automatic or chosen), the hub it orbits and a link
 * to its editor. A body that others orbit cannot become a moon.
 */
const props = defineProps<{ device: Device; body: OrbitBody; parents: OrbitBody[]; chosenRole: OrbitRole | null; hasOrbiters: boolean }>();
const emit = defineEmits<{ open: []; close: []; assign: [targetId: number]; role: [role: OrbitRole | null] }>();

const roles: OrbitRole[] = ['star', 'planet', 'dwarf', 'moon'];
const field = 'h-8 rounded-md border border-line bg-sunken px-2 text-xs text-fg focus:border-accent focus:outline-none';

function onRole(e: Event) {
  const value = (e.target as HTMLSelectElement).value;
  emit('role', value === 'auto' ? null : (value as OrbitRole));
}
const autoLabel = () => t('gv.orbit.role_auto_is', { role: t(`gv.orbit.role_${roleOf(props.body)}`) });
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
    <label class="flex flex-col gap-1 text-xs font-medium text-fg">
      <span>{{ t('gv.orbit.role') }}</span>
      <select :value="chosenRole ?? 'auto'" :class="field" @change="onRole">
        <option value="auto">{{ chosenRole ? t('gv.orbit.role_auto') : autoLabel() }}</option>
        <option v-for="r in roles" :key="r" :value="r" :disabled="r === 'moon' && hasOrbiters">{{ t(`gv.orbit.role_${r}`) }}</option>
      </select>
      <span v-if="hasOrbiters" class="font-normal text-fg-subtle">{{ t('gv.orbit.role_moon_blocked') }}</span>
    </label>
    <label v-if="body.kind !== 'star' && parents.length > 0" class="flex flex-col gap-1 text-xs font-medium text-fg">
      <span>{{ t('gv.orbit.hub') }}</span>
      <select :value="body.parentId ?? ''" :class="field" @change="emit('assign', Number(($event.target as HTMLSelectElement).value))">
        <option v-for="p in parents" :key="p.id" :value="p.id">{{ deviceLabel(p.device) }} ({{ t(`gv.orbit.role_${roleOf(p)}`) }})</option>
      </select>
    </label>
  </div>
</template>
