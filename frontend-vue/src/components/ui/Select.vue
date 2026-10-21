<script setup lang="ts" generic="T extends string | number | null">
import { ChevronDown } from 'lucide-vue-next';
import { cn } from '@/lib/utils';

/** Native select: best keyboard, screen reader and phone picker support, styled to match. */
defineOptions({ inheritAttrs: false });

const model = defineModel<T>();
const props = defineProps<{
  options: { value: T; label: string; disabled?: boolean }[];
  class?: string;
  invalid?: boolean;
}>();
</script>

<template>
  <div :class="cn('relative min-w-0', props.class)">
    <select
      v-model="model"
      v-bind="$attrs"
      :aria-invalid="props.invalid || undefined"
      class="h-9 w-full appearance-none rounded-md border border-line bg-sunken pr-8 pl-3 text-sm text-fg transition-colors hover:border-line-strong focus:border-info focus:ring-2 focus:ring-info/25 focus:outline-none focus-visible:outline-none disabled:opacity-60"
    >
      <option v-for="opt in props.options" :key="String(opt.value)" :value="opt.value" :disabled="opt.disabled">
        {{ opt.label }}
      </option>
    </select>
    <ChevronDown class="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
  </div>
</template>
