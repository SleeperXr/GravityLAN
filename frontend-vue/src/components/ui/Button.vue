<script setup lang="ts">
import { computed } from 'vue';
import { Loader2 } from 'lucide-vue-next';
import { cn } from '@/lib/utils';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost';
type Size = 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm';

const props = withDefaults(
  defineProps<{
    variant?: Variant;
    size?: Size;
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
    loading?: boolean;
    class?: string;
  }>(),
  { variant: 'secondary', size: 'md', type: 'button', disabled: false, loading: false },
);

const variants: Record<Variant, string> = {
  primary: 'bg-accent text-accent-fg hover:bg-accent-hover border border-transparent font-semibold',
  secondary: 'bg-control text-fg border border-line hover:bg-control-hover hover:border-line-strong',
  ghost: 'text-fg-muted hover:text-fg hover:bg-control-hover border border-transparent',
  danger: 'bg-danger text-danger-fg hover:opacity-90 border border-transparent font-semibold',
  'danger-ghost': 'text-danger-text hover:bg-danger/10 border border-transparent',
};

// Phones (below md, where the mobile tab bar shows) get 44 px targets in every size
const sizes: Record<Size, string> = {
  sm: 'h-8 px-2.5 text-xs gap-1.5 max-md:h-11',
  md: 'h-9 px-3.5 text-sm gap-2 max-md:h-11',
  lg: 'h-11 px-5 text-sm gap-2',
  icon: 'h-9 w-9 max-md:size-11',
  'icon-sm': 'h-8 w-8 max-md:size-11',
};

const classes = computed(() =>
  cn(
    'inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors duration-150 select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
    variants[props.variant],
    sizes[props.size],
    props.class,
  ),
);
</script>

<template>
  <button :type="props.type" :disabled="props.disabled || props.loading" :aria-busy="props.loading || undefined" :class="classes">
    <Loader2 v-if="props.loading" class="animate-spin" aria-hidden="true" />
    <slot />
  </button>
</template>
