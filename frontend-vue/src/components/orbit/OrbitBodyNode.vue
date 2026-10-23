<script setup lang="ts">
import { computed } from 'vue';
import type { OrbitBody, Point } from './orbitModel';
import { BODY_RADIUS, type LabelPlacement } from './orbitLayout';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * One body on the orbit map. Star: filled core with diffraction spikes. Planet: ring with halo
 * and role pill (SW / AP / HOST). Moon: small ring. Offline is struck through and labelled,
 * degraded carries a "!" badge, so state never rides on colour alone.
 */
const props = defineProps<{
  body: OrbitBody;
  pos: Point;
  /** Where the label goes; null hides it (moon labels at overview zoom) */
  label: LabelPlacement | null;
  labelScale: number;
  index: number;
  editing: boolean;
  selected: boolean;
  dim: number;
  badge: string | null;
}>();
const emit = defineEmits<{
  down: [e: PointerEvent];
  click: [e: MouseEvent];
  dblclick: [e: MouseEvent];
  enter: [];
  leave: [];
  beamStart: [e: PointerEvent];
}>();

const r = computed(() => BODY_RADIUS[props.body.kind]);
const name = computed(() => deviceLabel(props.body.device));
const stroke = computed(() => (props.body.state === 'offline' ? 'var(--gl-danger)' : props.body.state === 'degraded' ? 'var(--gl-warn)' : props.body.color));
const halo = 'paint-order: stroke; stroke: var(--gl-canvas); stroke-linejoin: round';
</script>

<template>
  <g
    :transform="`translate(${pos.x}, ${pos.y})`"
    class="constellation-node cursor-pointer transition-opacity duration-300"
    :class="editing && 'cursor-grab active:cursor-grabbing'"
    :style="{ opacity: dim * (body.state === 'offline' ? 0.7 : 1) }"
    role="button"
    tabindex="0"
    :aria-label="`${name} (${body.device.ip})`"
    @pointerdown="emit('down', $event)"
    @click="emit('click', $event)"
    @dblclick="emit('dblclick', $event)"
    @pointerenter="emit('enter')"
    @pointerleave="emit('leave')"
    @keydown.enter.prevent="emit('click', $event as unknown as MouseEvent)"
  >
    <g class="orbit-float-node" :style="{ animationDelay: `${(index % 7) * -0.85}s` }">
      <!-- Star: diffraction spikes and corona -->
      <g v-if="body.kind === 'star'" class="star-diffraction pointer-events-none" :stroke="body.color">
        <line x1="-32" y1="0" x2="32" y2="0" stroke-width="1.2" stroke-opacity="0.8" />
        <line x1="0" y1="-32" x2="0" y2="32" stroke-width="1.2" stroke-opacity="0.8" />
        <line x1="-14" y1="-14" x2="14" y2="14" stroke-width="0.65" stroke-opacity="0.4" />
        <line x1="-14" y1="14" x2="14" y2="-14" stroke-width="0.65" stroke-opacity="0.4" />
        <circle :r="r + 12" :fill="body.color" fill-opacity="0.16" class="star-corona" />
      </g>
      <!-- Planet: atmosphere ring (dashed for access points) -->
      <template v-else-if="body.kind === 'planet'">
        <circle :r="r + 7" :fill="body.color" fill-opacity="0.1" class="planet-halo" />
        <circle :r="r + 4" fill="none" :stroke="body.color" stroke-width="1.2" :stroke-dasharray="body.device.is_ap ? '4 3' : undefined" stroke-opacity="0.65" />
      </template>
      <!-- WLAN moon: satellite beacon -->
      <circle v-else-if="body.device.is_wlan && body.state === 'online'" :r="r + 4" fill="none" :stroke="body.color" stroke-width="1" stroke-dasharray="3 3" stroke-opacity="0.45" />

      <circle v-if="selected" :r="r + 9" fill="none" stroke="var(--gl-fg)" stroke-width="2" />
      <circle :r="r" :fill="body.kind === 'star' ? body.color : 'var(--gl-station)'" :stroke="stroke" :stroke-width="body.kind === 'star' ? 3.2 : body.kind === 'planet' ? 3 : 2.5" />
      <!-- Second network of a multi-homed body -->
      <circle v-if="body.rings.length > 1 && body.kind !== 'star'" :r="Math.max(4, r - 4)" fill="none" :stroke="body.rings[1]" stroke-width="2" />
      <circle v-if="body.kind === 'star'" r="6.5" fill="var(--gl-sign-ink)" />
      <circle v-else-if="body.kind === 'planet' && body.state === 'online'" r="4" :fill="body.color" />

      <g v-if="body.kind === 'planet' && badge" :transform="`translate(${r + 1}, ${-r + 2})`">
        <rect x="-2" y="-8" width="26" height="13" rx="4" fill="var(--gl-surface)" :stroke="body.color" stroke-width="0.8" />
        <text x="11" y="1.5" text-anchor="middle" :fill="body.color" class="font-mono text-[10px] font-bold">{{ badge }}</text>
      </g>

      <line v-if="body.state === 'offline'" :x1="-r + 2" :y1="r - 2" :x2="r - 2" :y2="-r + 2" stroke="var(--gl-danger)" stroke-width="2.5" stroke-linecap="round" />
      <g v-if="body.state === 'degraded'" :transform="`translate(${r - 2}, ${-r + 2})`">
        <circle r="6" fill="var(--gl-warn)" />
        <text x="0" y="3.5" text-anchor="middle" fill="var(--gl-sign-ink)" class="font-sans text-[10px] font-extrabold">!</text>
      </g>

      <!-- Edit mode: drag from + to draw a light beam -->
      <g v-if="editing" :transform="`translate(${r + 7}, 0)`" class="opacity-80 hover:opacity-100" @pointerdown="emit('beamStart', $event)">
        <circle r="6.5" fill="var(--gl-surface)" stroke="var(--gl-accent)" stroke-width="1.5" />
        <line x1="-3" y1="0" x2="3" y2="0" stroke="var(--gl-accent)" stroke-width="1.5" />
        <line x1="0" y1="-3" x2="0" y2="3" stroke="var(--gl-accent)" stroke-width="1.5" />
      </g>

      <!-- Label on the free side chosen by placeLabels() -->
      <g v-if="label" :transform="`translate(${label.x}, ${label.y}) scale(${labelScale})`" class="pointer-events-none">
        <text :text-anchor="label.anchor" fill="var(--gl-fg)" class="text-[12px] font-bold tracking-tight" :class="body.state === 'offline' && 'line-through opacity-75'" :style="`${halo}; stroke-width: 4px`">
          {{ name }}
        </text>
        <text y="13" :text-anchor="label.anchor" fill="var(--gl-fg-muted)" class="font-mono text-[10px]" :style="`${halo}; stroke-width: 3.5px`">{{ body.device.ip }}</text>
        <text
          v-if="body.state !== 'online'"
          y="25"
          :text-anchor="label.anchor"
          :fill="body.state === 'offline' ? 'var(--gl-danger-text)' : 'var(--gl-warn-text)'"
          class="text-[10px] font-semibold"
          :style="`${halo}; stroke-width: 3.5px`"
        >
          {{ body.state === 'offline' ? t('gv.plan.dropped') : t('gv.plan.degraded') }}
        </text>
      </g>
    </g>
  </g>
</template>
