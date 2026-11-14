<script setup lang="ts">
import type { ThemePreview } from '@/lib/themes';

/**
 * A design in miniature: its ground, a card with a text line and a network line, its primary and
 * state colours. `small` is the 36 x 24 px chip in the sidebar's design button: ground, card and
 * the two action/state dots only.
 */
defineProps<{ preview: ThemePreview; small?: boolean }>();
</script>

<template>
  <span v-if="small" class="relative block h-6 w-9 shrink-0 overflow-hidden rounded-[4px] border border-line" :style="{ background: preview.canvas }" aria-hidden="true">
    <span class="absolute inset-1 rounded-[3px] border" :style="{ background: preview.surface, borderColor: preview.line }" />
    <span class="absolute right-[15px] bottom-[7px] h-[6px] w-2.5 rounded-full" :style="{ background: preview.primary }" />
    <span class="absolute right-[7px] bottom-[7px] size-[6px] rounded-full" :style="{ background: preview.accent }" />
  </span>
  <span v-else class="relative block h-9 w-14 shrink-0 overflow-hidden rounded-[5px] border border-line" :style="{ background: preview.canvas }" aria-hidden="true">
    <span class="absolute inset-1.5 rounded-[3px] border" :style="{ background: preview.surface, borderColor: preview.line }" />
    <span class="absolute top-3 left-3 h-[3px] w-5 rounded-full" :style="{ background: preview.text }" />
    <span class="absolute top-[19px] left-3 h-[3px] w-3 rounded-full" :style="{ background: preview.network }" />
    <span class="absolute right-[18px] bottom-2.5 h-[7px] w-3 rounded-full" :style="{ background: preview.primary }" />
    <span class="absolute right-2.5 bottom-2.5 size-[7px] rounded-full" :style="{ background: preview.accent }" />
  </span>
</template>
