<script setup lang="ts">
import type { Component } from 'vue';

defineProps<{ icon?: Component; title: string; description?: string; compact?: boolean }>();
</script>

<template>
  <div class="flex flex-col items-center justify-center text-center" :class="compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-16'">
    <div v-if="icon" class="flex size-11 items-center justify-center rounded-lg border border-line bg-raised text-fg-subtle">
      <component :is="icon" class="size-5" aria-hidden="true" />
    </div>
    <div class="max-w-sm space-y-1">
      <p class="text-sm font-semibold text-fg">{{ title }}</p>
      <p v-if="description" class="text-sm leading-relaxed text-fg-muted">{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="mt-1 flex flex-wrap justify-center gap-2">
      <slot />
    </div>
  </div>
</template>
