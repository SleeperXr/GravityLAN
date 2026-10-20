<script setup lang="ts">
import { computed } from 'vue';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-[#3DB8F5]/30 bg-[#3DB8F5]/10 text-[#3DB8F5]',
        secondary: 'border-[#2A3340] bg-[#1F2732] text-[#9AA5B4]',
        success: 'border-[#2EA043]/35 bg-[#2EA043]/15 text-[#4AC26B]',
        warning: 'border-[#E3B341]/35 bg-[#E3B341]/15 text-[#E3B341]',
        destructive: 'border-[#F47067]/35 bg-[#F47067]/15 text-[#F47067]',
        outline: 'border-[#2A3340] text-[#E6EAF0]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

type BadgeVariants = VariantProps<typeof badgeVariants>;

const props = defineProps<{
  variant?: BadgeVariants['variant'];
  class?: string;
}>();

const classes = computed(() => cn(badgeVariants({ variant: props.variant }), props.class));
</script>

<template>
  <span :class="classes">
    <slot />
  </span>
</template>
