<script setup lang="ts">
import { computed, useId } from 'vue';

/**
 * Label + control + hint/error, wired for screen readers. The default slot receives
 * `{ id, describedBy, invalid }` to spread onto the control.
 */
const props = defineProps<{
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  /** Visually hide the label (it stays for screen readers) */
  srOnlyLabel?: boolean;
}>();

const id = useId();
const hintId = `${id}-hint`;
const errorId = `${id}-error`;
const describedBy = computed(() => [props.error ? errorId : null, props.hint ? hintId : null].filter(Boolean).join(' ') || undefined);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1.5">
    <label :for="id" class="text-xs font-medium text-fg" :class="props.srOnlyLabel && 'sr-only'">
      {{ props.label }}<span v-if="props.required" class="text-danger-text" aria-hidden="true"> *</span>
    </label>
    <slot :id="id" :described-by="describedBy" :invalid="Boolean(props.error)" />
    <p v-if="props.error" :id="errorId" class="text-xs text-danger-text" role="alert">{{ props.error }}</p>
    <p v-else-if="props.hint" :id="hintId" class="text-xs leading-relaxed text-fg-subtle">{{ props.hint }}</p>
  </div>
</template>
