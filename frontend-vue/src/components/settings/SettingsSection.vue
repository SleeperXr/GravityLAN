<script setup lang="ts">
/** One settings block: title and explanation, then the controls. `danger` marks the reset zone. */
defineProps<{ id: string; title: string; description?: string; danger?: boolean }>();
</script>

<template>
  <section
    :id="id"
    :aria-labelledby="`${id}-title`"
    class="gl-card scroll-mt-6 p-5 md:p-6"
    :class="danger && 'border-danger/30'"
  >
    <header class="mb-5">
      <h2 :id="`${id}-title`" class="text-base font-semibold" :class="danger ? 'text-danger-text' : 'text-fg'">{{ title }}</h2>
      <p v-if="description" class="mt-1 max-w-prose text-sm leading-relaxed text-fg-muted">{{ description }}</p>
    </header>
    <div class="space-y-5"><slot /></div>
  </section>
</template>
