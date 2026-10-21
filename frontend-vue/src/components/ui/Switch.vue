<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from 'reka-ui';

const model = defineModel<boolean>({ default: false });
defineProps<{ id?: string; disabled?: boolean; ariaLabel?: string; ariaDescribedby?: string }>();
</script>

<template>
  <SwitchRoot
    :id="id"
    v-model="model"
    :disabled="disabled"
    :aria-label="ariaLabel"
    :aria-describedby="ariaDescribedby"
    class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-line-strong bg-sunken transition-colors data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:opacity-50"
  >
    <SwitchThumb
      class="block size-3.5 translate-x-0.5 rounded-full bg-fg-subtle shadow-sm transition-transform duration-150 ease-out data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-accent-fg"
    />
  </SwitchRoot>
</template>
