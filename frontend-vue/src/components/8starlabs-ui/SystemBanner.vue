<script setup lang="ts">
export interface SystemBannerProps {
  text?: string;
  colorClass?: string;
  show?: boolean;
}

withDefaults(defineProps<SystemBannerProps>(), {
  text: 'Active Radar Scan',
  colorClass: 'bg-emerald-500',
  show: false,
});
</script>

<template>
  <div
    v-if="show"
    :class="['fixed top-0 left-0 w-full h-0.5 z-50 flex justify-center pointer-events-none', colorClass]"
  >
    <span
      :class="[
        'absolute -bottom-4 text-zinc-950 font-bold text-[10px] uppercase tracking-wider px-2.5 py-0.5 rounded-b-md shadow-md',
        colorClass,
      ]"
    >
      {{ text }}
    </span>
  </div>
</template>
