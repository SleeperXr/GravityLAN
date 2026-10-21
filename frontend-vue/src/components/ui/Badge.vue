<script setup lang="ts">
import { computed } from 'vue';
import { cn } from '@/lib/utils';

export type BadgeTone = 'neutral' | 'accent' | 'info' | 'warn' | 'danger';

const props = withDefaults(defineProps<{ tone?: BadgeTone; mono?: boolean; class?: string }>(), {
  tone: 'neutral',
  mono: false,
});

const tones: Record<BadgeTone, string> = {
  neutral: 'bg-raised text-fg-muted border-line',
  accent: 'bg-accent/10 text-accent-text border-accent/25',
  info: 'bg-info/10 text-info-text border-info/25',
  warn: 'bg-warn/10 text-warn-text border-warn/30',
  danger: 'bg-danger/10 text-danger-text border-danger/30',
};

const classes = computed(() =>
  cn(
    'inline-flex max-w-full items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0',
    tones[props.tone],
    props.mono && 'font-mono',
    props.class,
  ),
);
</script>

<template>
  <span :class="classes"><slot /></span>
</template>
