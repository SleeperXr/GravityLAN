<script setup lang="ts">
import { cn } from '@/lib/utils';

const props = defineProps<{
  modelValue?: string | number;
  placeholder?: string;
  type?: string;
  class?: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void;
}>();
</script>

<template>
  <input
    :type="props.type ?? 'text'"
    :value="props.modelValue"
    :placeholder="props.placeholder"
    :disabled="props.disabled"
    :class="
      cn(
        'flex h-8 w-full rounded-md border border-[#2A3340] bg-[#0B0E13] px-3 py-1 text-xs text-[#E6EAF0] placeholder:text-[#8390A0] focus-visible:outline-none focus-visible:border-[#3DB8F5] focus-visible:ring-1 focus-visible:ring-[#3DB8F5] disabled:cursor-not-allowed disabled:opacity-50',
        props.class
      )
    "
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>
