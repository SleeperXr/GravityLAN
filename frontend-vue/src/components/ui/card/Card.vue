<script setup lang="ts">
import { cn } from '@/lib/utils';

const props = defineProps<{ class?: string }>();
</script>

<template>
  <div :class="cn('rounded-lg border border-[#1F2732] bg-[#151A21] text-[#E6EAF0] shadow-xs', props.class)">
    <slot />
  </div>
</template>
