<script setup lang="ts">
import { cn } from '@/lib/utils';

defineOptions({ inheritAttrs: false });

const model = defineModel<string | null>();
const props = defineProps<{ class?: string; mono?: boolean; invalid?: boolean }>();
</script>

<template>
  <textarea
    v-model="model"
    v-bind="$attrs"
    :aria-invalid="props.invalid || undefined"
    :class="
      cn(
        'min-h-20 w-full rounded-md border border-line bg-sunken px-3 py-2 text-sm text-fg placeholder:text-fg-subtle transition-colors',
        'hover:border-line-strong focus:border-info focus:outline-none focus-visible:outline-none focus:ring-2 focus:ring-info/25',
        'disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger',
        props.mono && 'font-mono text-xs',
        props.class,
      )
    "
  />
</template>
