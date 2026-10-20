<script setup lang="ts">
import { computed } from 'vue';
import { cn } from '@/lib/utils';

export interface StatusIndicatorProps {
  state?: 'active' | 'down' | 'fixing' | 'idle';
  label?: string;
  size?: 'sm' | 'md' | 'lg';
  class?: string;
  labelClass?: string;
}

const props = withDefaults(defineProps<StatusIndicatorProps>(), {
  state: 'idle',
  size: 'md',
});

const shouldAnimate = computed(
  () => props.state === 'active' || props.state === 'fixing' || props.state === 'down'
);

const colors = computed(() => {
  switch (props.state) {
    case 'active':
      return { dot: 'bg-emerald-500', ping: 'bg-emerald-400' };
    case 'down':
      return { dot: 'bg-rose-500', ping: 'bg-rose-400' };
    case 'fixing':
      return { dot: 'bg-amber-500', ping: 'bg-amber-300' };
    case 'idle':
    default:
      return { dot: 'bg-zinc-600', ping: 'bg-zinc-400' };
  }
});

const sizeClasses = computed(() => {
  switch (props.size) {
    case 'sm':
      return { dot: 'h-2 w-2', ping: 'h-2 w-2' };
    case 'lg':
      return { dot: 'h-3.5 w-3.5', ping: 'h-3.5 w-3.5' };
    case 'md':
    default:
      return { dot: 'h-2.5 w-2.5', ping: 'h-2.5 w-2.5' };
  }
});
</script>

<template>
  <div :class="cn('inline-flex items-center gap-2', props.class)">
    <div class="relative flex items-center justify-center">
      <span
        v-if="shouldAnimate"
        :class="cn('absolute inline-flex rounded-full opacity-75 animate-ping', sizeClasses.ping, colors.ping)"
      />
      <span :class="cn('relative inline-flex rounded-full', sizeClasses.dot, colors.dot)" />
    </div>
    <p
      v-if="label"
      :class="cn('text-xs font-medium text-zinc-300 leading-none', props.labelClass)"
    >
      {{ label }}
    </p>
  </div>
</template>
