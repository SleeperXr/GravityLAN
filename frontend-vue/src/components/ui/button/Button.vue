<script setup lang="ts">
import { computed } from 'vue';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#3DB8F5] disabled:pointer-events-none disabled:opacity-50 cursor-pointer',
  {
    variants: {
      variant: {
        default: 'bg-[#3DB8F5] text-[#07121A] font-semibold hover:bg-[#7CCFF8] shadow-xs',
        destructive: 'bg-[#F47067]/15 text-[#F47067] border border-[#F47067]/30 hover:bg-[#F47067]/25',
        outline: 'border border-[#2A3340] bg-[#151A21] text-[#E6EAF0] hover:bg-[#1F2732] hover:border-[#3A434F]',
        secondary: 'bg-[#1F2732] text-[#E6EAF0] hover:bg-[#2A3340]',
        ghost: 'text-[#9AA5B4] hover:bg-[#1F2732] hover:text-[#E6EAF0]',
      },
      size: {
        default: 'h-8 px-3 py-1.5',
        sm: 'h-7 rounded-md px-2.5 text-[11px]',
        lg: 'h-9 rounded-md px-4 text-sm',
        icon: 'h-8 w-8',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

type ButtonVariants = VariantProps<typeof buttonVariants>;

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariants['variant'];
    size?: ButtonVariants['size'];
    class?: string;
    disabled?: boolean;
    type?: 'button' | 'submit' | 'reset';
  }>(),
  {
    variant: 'default',
    size: 'default',
    type: 'button',
    disabled: false,
  }
);

const classes = computed(() => cn(buttonVariants({ variant: props.variant, size: props.size }), props.class));
</script>

<template>
  <button :type="props.type" :disabled="props.disabled" :class="classes">
    <slot />
  </button>
</template>
