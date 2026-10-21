<script setup lang="ts">
/** "Title + explanation | action" row inside a settings section. */
defineProps<{ title: string; description?: string }>();
</script>

<template>
  <div class="flex flex-col gap-3 border-t border-line pt-5 first:border-t-0 first:pt-0 sm:flex-row sm:items-center sm:justify-between">
    <div class="min-w-0">
      <p class="text-sm font-medium text-fg">{{ title }}</p>
      <p v-if="description" class="mt-0.5 max-w-xl text-xs leading-relaxed text-fg-subtle">{{ description }}</p>
    </div>
    <div class="flex shrink-0 flex-wrap items-end gap-2"><slot /></div>
  </div>
</template>
