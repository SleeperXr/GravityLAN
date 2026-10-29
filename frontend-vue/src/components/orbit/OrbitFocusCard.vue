<script setup lang="ts">
import { Route, X } from 'lucide-vue-next';
import { roleOf, type OrbitBody } from './orbitModel';
import Button from '@/components/ui/Button.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/** Details of the focused body in view mode, with the ways to move on from it. */
defineProps<{
  body: OrbitBody;
  parent: OrbitBody | null;
  moons: number;
  beams: number;
  badge: string | null;
  /** Labels of the devices it hangs on alone, how many fail with it, and whether anything reaches it */
  resilience: { dependsOn: string[]; cutOff: number; unconnected: boolean; cutOffNow: boolean } | null;
}>();
const emit = defineEmits<{ close: []; open: []; toHub: []; centre: []; trace: [] }>();
</script>

<template>
  <div
    class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-2.5 rounded-lg border border-line-strong bg-surface/95 p-3.5 shadow-pop backdrop-blur"
    role="dialog"
    :aria-label="deviceLabel(body.device)"
    @pointerdown.stop
  >
    <div class="flex items-start gap-2">
      <span class="mt-1.5 size-2.5 shrink-0 rounded-full" :style="{ backgroundColor: body.color }" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-semibold text-fg">{{ deviceLabel(body.device) }}</p>
        <p class="font-mono text-xs text-fg-subtle">{{ body.device.ip }}</p>
      </div>
      <button type="button" class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>

    <dl class="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
      <dt class="text-fg-subtle">{{ t('gv.orbit.kind') }}</dt>
      <dd class="text-fg">
        {{ t(`gv.orbit.role_${roleOf(body)}`) }}<span v-if="badge" class="font-mono text-[10px] text-fg-muted"> · {{ badge }}</span>
      </dd>
      <dt class="text-fg-subtle">{{ t('gv.orbit.status') }}</dt>
      <dd class="text-fg">{{ t(`gv.orbit.state_${body.state}`) }}</dd>
      <dt class="text-fg-subtle">{{ t('gv.orbit.orbits') }}</dt>
      <dd class="truncate text-fg">{{ parent ? deviceLabel(parent.device) : '–' }}</dd>
      <dt class="text-fg-subtle">{{ t('gv.orbit.moons_beams') }}</dt>
      <dd class="font-mono text-fg">{{ moons }} / {{ beams }}</dd>
      <template v-if="resilience">
        <dt class="text-fg-subtle">{{ t('gv.orbit.uplink') }}</dt>
        <dd v-if="resilience.cutOffNow" class="text-danger-text">{{ t('gv.orbit.cut_off_now') }}</dd>
        <dd v-else-if="resilience.unconnected" class="text-fg-muted">{{ t('gv.orbit.unconnected') }}</dd>
        <dd v-else-if="resilience.dependsOn.length" class="text-warn-text" :title="resilience.dependsOn.join(', ')">
          {{ t('gv.orbit.depends_on', { names: resilience.dependsOn.slice(0, 2).join(', ') }) }}<span v-if="resilience.dependsOn.length > 2"> +{{ resilience.dependsOn.length - 2 }}</span>
        </dd>
        <dd v-else class="text-accent-text">{{ t('gv.orbit.redundant') }}</dd>
        <template v-if="resilience.cutOff">
          <dt class="text-fg-subtle">{{ t('gv.orbit.if_fails') }}</dt>
          <dd class="text-warn-text">{{ t('gv.orbit.spof_cuts', { count: resilience.cutOff }) }}</dd>
        </template>
      </template>
    </dl>

    <div class="flex flex-wrap items-center gap-1.5">
      <Button size="sm" @click="emit('open')">{{ t('gv.orbit.open_details') }}</Button>
      <Button v-if="parent" size="sm" @click="emit('toHub')">{{ t('gv.orbit.to_hub') }}</Button>
      <Button size="sm" @click="emit('centre')">{{ t('gv.orbit.centre') }}</Button>
      <Button size="sm" @click="emit('trace')"><Route aria-hidden="true" />{{ t('gv.orbit.trace') }}</Button>
    </div>
  </div>
</template>
