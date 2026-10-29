<script setup lang="ts">
import { computed } from 'vue';
import type { LightBeam, Point } from './orbitModel';
import { beamPath } from './orbitLayout';
import { t } from '@/i18n';

/**
 * Light beams (topology links) between bodies. Beams between bodies on rings around the same
 * star bend along the orbit; offline ends turn the beam red and dotted, WLAN beams are dashed.
 * Also draws the beam being dragged out in edit mode and a traced path.
 */
const props = defineProps<{
  beams: LightBeam[];
  /** Where each body sits */
  pos: (id: number) => Point;
  /** Centre a beam bends around (the shared star), or null for a straight beam */
  centreOf: (beam: LightBeam) => Point | null;
  dim: (id: number) => number;
  selectedId: number | null;
  animated: boolean;
  connecting: { from: Point; to: Point } | null;
  trace: { segments: { key: number; from: number; to: number; interrupted: boolean }[]; hops: number[] };
}>();
const emit = defineEmits<{ select: [id: number, e: MouseEvent] }>();

const paths = computed(() =>
  props.beams.map((beam) => ({ beam, ...beamPath(props.pos(beam.sourceId), props.pos(beam.targetId), props.centreOf(beam)) })),
);
const traceById = computed(() => new Map(paths.value.map((p) => [p.beam.id, p.d])));
const traceD = (seg: { key: number; from: number; to: number }) => traceById.value.get(seg.key) ?? `M${props.pos(seg.from).x},${props.pos(seg.from).y} L${props.pos(seg.to).x},${props.pos(seg.to).y}`;
const colourOf = (beam: LightBeam) => (beam.interrupted ? 'var(--gl-danger)' : beam.failover ? 'var(--gl-warn)' : beam.color);
/** A backup that took over is drawn as a live beam, an idle one thin and dashed */
const idleBackup = (beam: LightBeam) => beam.isBackup && !beam.failover;
</script>

<template>
  <g class="constellation-beams">
    <g
      v-for="{ beam, d, mid } in paths"
      :key="beam.id"
      class="cursor-pointer transition-opacity duration-300"
      :style="{ opacity: dim(beam.id) }"
      @click="emit('select', beam.id, $event)"
    >
      <!-- Wide hit target -->
      <path :d="d" fill="none" stroke="transparent" stroke-width="20" />
      <!-- Glow -->
      <path
        :d="d"
        fill="none"
        :stroke="colourOf(beam)"
        :stroke-width="selectedId === beam.id ? 9 : beam.isPrimaryBridge ? 6 : 4"
        :stroke-opacity="selectedId === beam.id ? 0.38 : beam.failover ? 0.32 : beam.interrupted || beam.isBackup ? 0.08 : 0.2"
        stroke-linecap="round"
      />
      <!-- Core line -->
      <path
        :d="d"
        fill="none"
        :stroke="colourOf(beam)"
        :stroke-width="selectedId === beam.id ? 3.2 : beam.failover ? 2.4 : beam.isBackup ? 1.3 : beam.isPrimaryBridge ? 2.2 : 1.4"
        :stroke-dasharray="beam.interrupted ? '2 9' : idleBackup(beam) ? '3 7' : beam.isWireless ? '6 6' : undefined"
        :stroke-opacity="beam.interrupted ? 0.65 : idleBackup(beam) ? 0.6 : 0.9"
        stroke-linecap="round"
      />
      <!-- Photon travelling along live beams -->
      <path
        v-if="!beam.interrupted && !idleBackup(beam) && animated"
        :d="d"
        fill="none"
        stroke="var(--gl-fg)"
        :stroke-width="beam.isPrimaryBridge ? 2.2 : 1.6"
        stroke-dasharray="8 120"
        stroke-linecap="round"
        class="photon-pulse"
      />
      <!-- Link type at the middle of the beam -->
      <g v-if="beam.linkType && (beam.isPrimaryBridge || beam.isBackup || selectedId === beam.id)" :transform="`translate(${mid.x}, ${mid.y})`">
        <rect
          :x="beam.failover ? -52 : beam.isBackup ? -40 : -22"
          y="-9"
          :width="beam.failover ? 104 : beam.isBackup ? 80 : 44"
          height="18"
          rx="9"
          fill="var(--gl-surface)"
          :stroke="selectedId === beam.id ? 'var(--gl-fg)' : beam.failover ? 'var(--gl-warn)' : 'var(--gl-line-strong)'"
          stroke-width="1"
          :stroke-dasharray="idleBackup(beam) ? '3 3' : undefined"
        />
        <text x="0" y="3.5" text-anchor="middle" :fill="beam.failover ? 'var(--gl-warn-text)' : 'var(--gl-fg-muted)'" class="pointer-events-none font-mono text-[10px] font-medium">{{ beam.failover ? `${t('gv.plan.backup_active')} · ${beam.linkType}` : beam.isBackup ? `${t('gv.plan.backup')} · ${beam.linkType}` : beam.linkType }}</text>
      </g>
    </g>

    <!-- Beam being drawn in edit mode -->
    <line
      v-if="connecting"
      :x1="connecting.from.x"
      :y1="connecting.from.y"
      :x2="connecting.to.x"
      :y2="connecting.to.y"
      stroke="var(--gl-accent)"
      stroke-width="2.5"
      stroke-dasharray="6 4"
      stroke-linecap="round"
    />
  </g>

  <!-- Traced path between two bodies, numbered hop by hop -->
  <g v-if="trace.segments.length" class="trace-path pointer-events-none" aria-hidden="true">
    <template v-for="seg in trace.segments" :key="`trace-${seg.key}`">
      <path :d="traceD(seg)" fill="none" :stroke="seg.interrupted ? 'var(--gl-danger)' : 'var(--gl-accent)'" stroke-width="9" stroke-opacity="0.22" stroke-linecap="round" />
      <path :d="traceD(seg)" fill="none" :stroke="seg.interrupted ? 'var(--gl-danger)' : 'var(--gl-accent)'" stroke-width="3" stroke-dasharray="10 8" stroke-linecap="round" class="trace-flow" />
    </template>
    <g v-for="(id, i) in trace.hops" :key="`trace-hop-${id}`" :transform="`translate(${pos(id).x + 20}, ${pos(id).y - 24})`">
      <circle r="9" fill="var(--gl-accent)" />
      <text y="3.5" text-anchor="middle" fill="var(--gl-sign-ink)" class="font-mono text-[10px] font-bold">{{ i + 1 }}</text>
    </g>
  </g>
</template>
