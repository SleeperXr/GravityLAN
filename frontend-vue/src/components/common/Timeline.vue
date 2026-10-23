<script setup lang="ts" generic="T">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import type { TimelineEntry, TimelineTone } from './timeline';

/**
 * Events on a line with a dot and a short branch to each card. Vertical for narrow panels
 * (one side), horizontal as a scrollable strip with cards alternating above and below.
 * Filled dots mark problems, hollow dots recoveries, so meaning never rides on colour alone.
 *
 * Adapted from the Timeline block of 8starlabs-ui (https://github.com/8starlabs/ui),
 * MIT License, Copyright (c) 2025 Tham Kei Lok. See THIRD_PARTY_NOTICES.md.
 */
const props = withDefaults(
  defineProps<{
    items: TimelineEntry<T>[];
    label: string;
    orientation?: 'vertical' | 'horizontal';
    /** Cards become buttons and emit `select` */
    interactive?: boolean;
    /** Plain text next to the line instead of cards (dense history lists) */
    noCards?: boolean;
    /** Horizontal only: width of a card and distance between two dots, in px */
    itemWidth?: number;
    itemSpacing?: number;
  }>(),
  { orientation: 'vertical', interactive: false, noCards: false, itemWidth: 240, itemSpacing: 150 },
);
const emit = defineEmits<{ select: [item: T] }>();
defineSlots<{ default(props: { item: T; index: number }): unknown }>();

const horizontal = computed(() => props.orientation === 'horizontal');
const ring: Record<TimelineTone, string> = {
  accent: 'border-accent',
  danger: 'border-danger',
  warn: 'border-warn',
  info: 'border-info',
  neutral: 'border-line-strong',
};
const fill: Record<TimelineTone, string> = {
  accent: 'bg-accent',
  danger: 'bg-danger',
  warn: 'bg-warn',
  info: 'bg-info',
  neutral: 'bg-line-strong',
};
const card: Record<TimelineTone, string> = {
  accent: 'border-line bg-raised',
  danger: 'border-danger/30 bg-danger/[0.05]',
  warn: 'border-warn/30 bg-warn/[0.05]',
  info: 'border-line bg-raised',
  neutral: 'border-line bg-raised',
};
const dotClass = (item: TimelineEntry<T>) => [ring[item.tone], item.hollow ? 'bg-surface' : fill[item.tone]];
const hover = 'transition-colors hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-accent';

// The line starts and stops at the outer dots instead of running past them.
const first = (i: number) => i === 0;
const last = (i: number) => i === props.items.length - 1;

// Horizontal: alternate above/below, pad so the outer cards are not cut off, open at the newest end.
const above = (i: number) => i % 2 === 0;
const pad = computed(() => Math.max(0, (props.itemWidth - props.itemSpacing) / 2));
const scroller = ref<HTMLElement | null>(null);
async function toEnd() {
  if (!horizontal.value) return;
  await nextTick();
  scroller.value?.scrollTo({ left: scroller.value.scrollWidth });
}
onMounted(toEnd);
watch(() => props.items.length, toEnd);
</script>

<template>
  <!-- Vertical: [line] [card] per row; the line runs through every row -->
  <ol v-if="!horizontal" class="grid grid-cols-[1.5rem_minmax(0,1fr)]" :aria-label="label">
    <li v-for="(item, i) in items" :key="item.key" class="contents" role="listitem">
      <span class="relative flex justify-center" aria-hidden="true">
        <span class="absolute w-0.5 bg-line" :style="{ top: first(i) ? '0.75rem' : '0', bottom: last(i) ? 'calc(100% - 0.75rem)' : '0' }" />
        <span class="absolute top-3 left-1/2 h-px w-3" :class="fill[item.tone]" />
        <span class="relative z-10 mt-1.5 size-3 rounded-full border-2" :class="dotClass(item)" />
      </span>
      <div class="min-w-0 pl-2" :class="last(i) ? 'pb-0' : 'pb-3'">
        <component
          :is="interactive ? 'button' : 'div'"
          :type="interactive ? 'button' : undefined"
          class="block w-full min-w-0 text-left"
          :class="[noCards ? 'py-0.5' : ['rounded-md border p-3', card[item.tone]], interactive && hover]"
          @click="interactive && emit('select', item.data)"
        >
          <slot :item="item.data" :index="i" />
        </component>
      </div>
    </li>
  </ol>

  <!-- Horizontal: three rows (cards above, line, cards below), one column per event -->
  <div v-else ref="scroller" class="gl-timeline-scroll overflow-x-auto pb-2">
    <ol
      class="grid w-max grid-rows-[auto_2rem_auto]"
      :style="{ gridAutoColumns: `${itemSpacing}px`, paddingLeft: `${pad}px`, paddingRight: `${pad}px` }"
      :aria-label="label"
    >
      <li v-for="(item, i) in items" :key="item.key" class="contents" role="listitem">
        <div
          class="flex justify-center"
          :class="above(i) ? 'items-end' : 'items-start'"
          :style="{ gridColumn: i + 1, gridRow: above(i) ? 1 : 3, scrollSnapAlign: 'center' }"
        >
          <component
            :is="interactive ? 'button' : 'div'"
            :type="interactive ? 'button' : undefined"
            class="shrink-0 rounded-md border p-3 text-left"
            :class="[card[item.tone], interactive && hover]"
            :style="{ width: `${itemWidth}px` }"
            @click="interactive && emit('select', item.data)"
          >
            <slot :item="item.data" :index="i" />
          </component>
        </div>
        <span class="relative flex items-center justify-center" :style="{ gridColumn: i + 1, gridRow: 2 }" aria-hidden="true">
          <span class="absolute h-0.5 bg-line" :style="{ left: first(i) ? '50%' : '0', right: last(i) ? '50%' : '0' }" />
          <span class="absolute left-1/2 h-4 w-px" :class="[fill[item.tone], above(i) ? 'top-0' : 'bottom-0']" />
          <span class="relative z-10 size-3.5 rounded-full border-2" :class="dotClass(item)" />
        </span>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.gl-timeline-scroll {
  scroll-snap-type: x proximity;
  scrollbar-width: thin;
  scrollbar-color: var(--gl-line) transparent;
}
</style>
