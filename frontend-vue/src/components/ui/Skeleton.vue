<script setup lang="ts">
import { cn } from '@/lib/utils';

defineProps<{ class?: string }>();
</script>

<template>
  <div aria-hidden="true" :class="cn('gl-skeleton rounded-md bg-raised', $props.class)" />
</template>

<style>
.gl-skeleton {
  background-image: linear-gradient(90deg, transparent, var(--gl-line), transparent);
  background-size: 200% 100%;
  animation: gl-shimmer 1.4s ease-in-out infinite;
}
@keyframes gl-shimmer {
  from { background-position: 150% 0; }
  to { background-position: -50% 0; }
}
</style>
