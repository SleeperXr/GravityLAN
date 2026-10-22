<script setup lang="ts">
import { computed } from 'vue';
import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from '@vue-flow/core';
import { octilinearPath } from './netzplan';

/**
 * A line segment between two stations, drawn centre to centre on the 45° grid of a transit
 * map. When an end station is down the segment turns dotted ("service interrupted"), so state
 * never rides on colour alone. A selected segment shows its link type at the middle.
 */
const props = defineProps<EdgeProps<{ color: string; interrupted: boolean; linkType: string; editable: boolean }>>();

function centre(node: EdgeProps['sourceNode'], fallbackX: number, fallbackY: number) {
  if (!node?.dimensions?.width) return { x: fallbackX, y: fallbackY };
  return { x: node.computedPosition.x + node.dimensions.width / 2, y: node.computedPosition.y + node.dimensions.height / 2 };
}

const geometry = computed(() => {
  const a = centre(props.sourceNode, props.sourceX, props.sourceY);
  const b = centre(props.targetNode, props.targetX, props.targetY);
  return { d: octilinearPath(a.x, a.y, b.x, b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
});
</script>

<template>
  <BaseEdge
    :id="id"
    :path="geometry.d"
    :interaction-width="26"
    :style="{
      stroke: data?.color,
      strokeWidth: selected ? 11 : 8,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      strokeDasharray: data?.interrupted ? '1 13' : undefined,
      transition: 'stroke-width 150ms ease',
    }"
  />
  <EdgeLabelRenderer v-if="selected && data?.editable">
    <div
      class="nodrag nopan pointer-events-none absolute rounded-full border border-line-strong bg-surface px-2 py-0.5 font-mono text-[10px] text-fg shadow-pop"
      :style="{ transform: `translate(-50%, -50%) translate(${geometry.mx}px, ${geometry.my}px)` }"
    >
      {{ data?.linkType }}
    </div>
  </EdgeLabelRenderer>
</template>
