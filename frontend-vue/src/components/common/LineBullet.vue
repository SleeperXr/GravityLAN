<script setup lang="ts">
/** Round line sign in the line's colour, like a transit line bullet ("30", "L"). */
withDefaults(defineProps<{ color: string; label: string; size?: 'sm' | 'md' | 'lg' }>(), { size: 'md' });
</script>

<template>
  <span
    class="inline-grid shrink-0 place-items-center rounded-full font-extrabold tracking-tight text-[#0c0f14] tabular"
    :class="{ 'h-5 min-w-5 px-1 text-micro': size === 'sm', 'h-7 min-w-7 px-1.5 text-xs': size === 'md', 'h-10 min-w-10 px-2 text-sm': size === 'lg' }"
    :style="{ backgroundColor: color }"
    aria-hidden="true"
  >
    {{ label }}
  </span>
</template>
