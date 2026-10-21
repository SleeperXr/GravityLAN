<script setup lang="ts">
/** Page title row: title + one-line description on the left, actions on the right (wrap on phones). */
defineProps<{ title: string; description?: string }>();
</script>

<template>
  <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
    <div class="min-w-0">
      <!-- On phones the app bar already shows the page title -->
      <h1 class="text-xl font-semibold tracking-tight text-fg text-balance max-md:sr-only">{{ title }}</h1>
      <p v-if="description" class="max-w-2xl text-sm text-fg-muted text-pretty md:mt-1">{{ description }}</p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.default" class="flex flex-wrap items-center gap-2">
      <slot />
    </div>
  </div>
</template>
