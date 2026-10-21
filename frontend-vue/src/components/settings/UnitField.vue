<script setup lang="ts">
import Field from '@/components/ui/Field.vue';

/** Number field with its unit inside the box (minutes, seconds, days ...). */
const model = defineModel<string>({ required: true });
defineProps<{ label: string; hint?: string; unit: string; step?: number; min?: number; max?: number }>();
</script>

<template>
  <Field v-slot="{ id, describedBy }" :label="label" :hint="hint">
    <div class="flex h-9 items-center rounded-md border border-line bg-sunken transition-colors focus-within:border-info focus-within:ring-2 focus-within:ring-info/25 hover:border-line-strong">
      <input
        :id="id"
        v-model="model"
        type="number"
        :inputmode="step && step < 1 ? 'decimal' : 'numeric'"
        :min="min ?? 0"
        :max="max"
        :step="step"
        :aria-describedby="`${id}-unit ${describedBy ?? ''}`"
        class="h-full min-w-0 flex-1 bg-transparent px-3 font-mono text-sm text-fg focus:outline-none"
      />
      <span :id="`${id}-unit`" class="shrink-0 pr-3 text-xs text-fg-subtle">{{ unit }}</span>
    </div>
  </Field>
</template>
