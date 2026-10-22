<script setup lang="ts">
import { computed } from 'vue';
import { Handle, Position, type NodeProps } from '@vue-flow/core';
import type { StationData } from './netzplan';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * A station on the network map. Online: white ring. Degraded (a service down): amber ring.
 * Offline: red ring struck through, the stop "is dropped". Interchanges (gateways, multi-homed
 * devices) are capsules carrying the colours of the lines that meet there.
 */
const props = defineProps<NodeProps<StationData>>();

const name = computed(() => deviceLabel(props.data.device));
const latency = computed(() => {
  const ms = (props.data.device as { latency_ms?: number | null }).latency_ms;
  return typeof ms === 'number' ? `${ms.toFixed(1).replace('.', ',')} ms` : props.data.device.ip;
});
const stateLabel = computed(
  () => ({ online: t('network.online'), degraded: t('gv.plan.degraded'), offline: t('gv.plan.dropped') })[props.data.state],
);
const handles = [Position.Top, Position.Right, Position.Bottom, Position.Left];
</script>

<template>
  <!-- Every station has the same 28×28 anchor box with the marker centred in it, so stations
       placed on one axis line up exactly, whatever the marker or name width -->
  <div
    class="group relative flex size-7 items-center justify-center"
    :class="data.editable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'"
    :title="`${name} · ${data.device.ip} · ${stateLabel}`"
  >
    <div
      class="station relative flex shrink-0 items-center justify-center rounded-full border-[3.5px] bg-station transition-[transform,box-shadow] duration-200 group-hover:scale-110"
      :class="[
        data.interchange ? 'h-7 min-w-12 px-1.5 gap-1' : 'size-[18px]',
        data.state === 'offline' ? 'border-danger' : data.state === 'degraded' ? 'border-warn' : 'border-fg',
        selected && 'ring-4 ring-accent/40',
      ]"
    >
      <template v-if="data.interchange">
        <span v-for="(c, i) in data.lines.slice(0, 4)" :key="i" class="size-2.5 rounded-full" :style="{ backgroundColor: c }" />
      </template>
      <span v-if="data.state === 'offline'" class="absolute h-[3px] w-[140%] rotate-45 rounded-full bg-danger" aria-hidden="true" />
      <span v-if="data.state === 'degraded'" class="station-blink absolute inset-0 rounded-full bg-warn/60" aria-hidden="true" />
    </div>
    <div class="pointer-events-none absolute top-full mt-1.5 text-center whitespace-nowrap">
      <p class="text-[13px] leading-4 font-bold" :class="data.state === 'offline' ? 'text-danger-text' : 'text-fg'">{{ name }}</p>
      <p class="font-mono text-[10.5px] leading-4" :class="data.state === 'offline' ? 'text-danger-text' : 'text-fg-subtle'">
        {{ data.state === 'offline' ? stateLabel : latency }}
      </p>
    </div>
    <template v-for="pos in handles" :key="pos">
      <Handle
        :id="pos"
        type="source"
        :position="pos"
        :connectable="data.editable"
        class="plan-handle"
        :class="data.editable ? 'opacity-0 group-hover:opacity-100' : 'pointer-events-none !opacity-0'"
      />
    </template>
  </div>
</template>

<style>
.plan-handle {
  width: 10px !important;
  height: 10px !important;
  min-width: 0 !important;
  border: 2px solid var(--gl-canvas) !important;
  background: var(--gl-accent) !important;
  transition: opacity 150ms ease;
}
.station-blink {
  animation: station-blink 1.2s steps(2, jump-none) infinite;
}
@keyframes station-blink {
  50% {
    opacity: 0;
  }
}
</style>
