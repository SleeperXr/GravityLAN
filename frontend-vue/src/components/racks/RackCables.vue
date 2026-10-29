<script setup lang="ts">
/**
 * The cables of the rack as one SVG layer over the faceplates. Each cable is a coloured line on a dark casing,
 * so it stays visible on any faceplate; a wide invisible stroke makes it easy to point at. A cable whose other
 * end is elsewhere is dashed and ends at a label that takes you there. Selected cables carry a travelling pulse
 * while ambient motion is on.
 */
export interface CableDraw {
  id: number;
  d: string;
  colour: string;
  /** The other end is not drawn here */
  dashed: boolean;
  state: 'normal' | 'active' | 'dim';
}

export interface StubLabel {
  key: string;
  x: number;
  y: number;
  text: string;
}

defineProps<{
  width: number;
  height: number;
  cables: CableDraw[];
  labels: StubLabel[];
  /** The cable being plugged in right now */
  live: { d: string; colour: string; snapped: boolean } | null;
  ambient: boolean;
}>();
const emit = defineEmits<{
  hover: [id: number | null, event: PointerEvent];
  pick: [id: number];
  stub: [key: string];
}>();

const widthOf = (c: CableDraw) => (c.state === 'active' ? 3.5 : 2.5);
/** Mono at the micro size (11 px) is about 6.7 px per character */
const labelWidth = (text: string) => Math.ceil(text.length * 6.7) + 10;
</script>

<template>
  <!-- Above the faceplates (z 2, a selected one z 3), below a lifted one (z 20) -->
  <svg class="pointer-events-none absolute top-0 left-0 z-[4] overflow-visible" :width="width" :height="height" aria-hidden="true">
    <g v-for="c in cables" :key="c.id" class="transition-opacity duration-200" :opacity="c.state === 'dim' ? 0.16 : 1">
      <path :d="c.d" class="rack-casing" :stroke-width="widthOf(c) + 3" />
      <path :d="c.d" fill="none" :stroke="c.colour" :stroke-width="widthOf(c)" :stroke-dasharray="c.dashed ? '5 4' : undefined" stroke-linecap="round" stroke-linejoin="round" />
      <path v-if="ambient && c.state === 'active' && !c.dashed" :d="c.d" class="rack-pulse" />
      <path
        :d="c.d"
        class="rack-hit"
        @pointerenter="emit('hover', c.id, $event)"
        @pointermove="emit('hover', c.id, $event)"
        @pointerleave="emit('hover', null, $event)"
        @click.stop="emit('pick', c.id)"
      />
    </g>

    <g v-for="l in labels" :key="l.key" class="rack-stub" @click.stop="emit('stub', l.key)" @pointerdown.stop>
      <rect :x="l.x - labelWidth(l.text)" :y="l.y - 8" :width="labelWidth(l.text)" height="15" rx="4" />
      <text :x="l.x - 5" :y="l.y + 3" text-anchor="end">{{ l.text }}</text>
    </g>

    <g v-if="live">
      <path :d="live.d" class="rack-casing" stroke-width="6.5" />
      <path :d="live.d" fill="none" :stroke="live.colour" stroke-width="3.5" stroke-linecap="round" :stroke-dasharray="live.snapped ? undefined : '6 4'" />
    </g>
  </svg>
</template>

<style scoped>
.rack-casing {
  fill: none;
  stroke: var(--gl-sunken);
  stroke-linecap: round;
  stroke-linejoin: round;
}
.rack-hit {
  fill: none;
  stroke: transparent;
  stroke-width: 12;
  pointer-events: stroke;
  cursor: pointer;
}
.rack-pulse {
  fill: none;
  stroke: color-mix(in oklab, #fff 75%, transparent);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-dasharray: 2 34;
  animation: rack-pulse 1.6s linear infinite;
}
:root[data-theme='light'] .rack-pulse {
  stroke: color-mix(in oklab, var(--gl-fg) 55%, transparent);
}
@keyframes rack-pulse {
  to {
    stroke-dashoffset: -36;
  }
}
.rack-stub {
  pointer-events: auto;
  cursor: pointer;
}
.rack-stub rect {
  fill: var(--gl-surface);
  stroke: var(--gl-line-strong);
  transition: stroke 120ms ease-out;
}
.rack-stub:hover rect {
  stroke: var(--gl-accent);
}
.rack-stub text {
  fill: var(--gl-fg-muted);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: var(--text-micro);
}
</style>
