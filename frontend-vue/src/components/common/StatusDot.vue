<script setup lang="ts">
import { computed } from 'vue';

/**
 * Status as a dot that never relies on colour alone: online is filled, offline is a hollow
 * ring, unknown is dashed grey. `label` names the state for screen readers and the tooltip.
 */
const props = withDefaults(
  defineProps<{ state: 'online' | 'offline' | 'unknown' | 'warn'; label?: string; size?: 'sm' | 'md'; pulse?: boolean }>(),
  { size: 'md', pulse: false },
);

const sizeClass = computed(() => (props.size === 'sm' ? 'size-2' : 'size-2.5'));
const stateClass = computed(
  () =>
    ({
      online: 'bg-accent',
      offline: 'bg-transparent ring-2 ring-inset ring-danger',
      warn: 'bg-warn',
      unknown: 'bg-transparent ring-1 ring-inset ring-fg-subtle [outline:1px_dashed_transparent]',
    })[props.state],
);
</script>

<template>
  <span
    class="relative inline-flex shrink-0 rounded-full"
    :class="[sizeClass, stateClass]"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    :title="label"
  >
    <span v-if="pulse && state === 'online'" class="absolute inset-0 animate-ping rounded-full bg-accent opacity-40 [animation-duration:2.4s]" />
  </span>
</template>
