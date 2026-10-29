<script setup lang="ts">
import type { Component } from 'vue';
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui';
import { cn } from '@/lib/utils';

/** Underlined tabs with arrow-key navigation. Each tab's panel is the slot named after its value. */
const model = defineModel<string>({ required: true });
const props = defineProps<{
  tabs: { value: string; label: string; icon?: Component; badge?: string | number; disabled?: boolean }[];
  label: string;
  listClass?: string;
}>();
</script>

<template>
  <TabsRoot v-model="model" class="flex min-h-0 flex-1 flex-col">
    <TabsList
      :aria-label="props.label"
      :class="cn('flex shrink-0 gap-1 overflow-x-auto border-b border-line px-3 [scrollbar-width:none]', props.listClass)"
    >
      <TabsTrigger
        v-for="tab in props.tabs"
        :key="tab.value"
        :value="tab.value"
        :disabled="tab.disabled"
        class="relative inline-flex h-10 shrink-0 items-center gap-1.5 px-2.5 text-sm font-medium text-fg-muted transition-colors hover:text-fg disabled:opacity-40 data-[state=active]:text-fg after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent data-[state=active]:after:bg-accent [&_svg]:size-4"
      >
        <component :is="tab.icon" v-if="tab.icon" aria-hidden="true" />
        {{ tab.label }}
        <span v-if="tab.badge !== undefined" class="rounded-sm bg-raised px-1 font-mono text-micro text-fg-subtle">{{ tab.badge }}</span>
      </TabsTrigger>
    </TabsList>
    <TabsContent v-for="tab in props.tabs" :key="tab.value" :value="tab.value" class="min-h-0 flex-1 focus-visible:outline-none">
      <slot :name="tab.value" />
    </TabsContent>
  </TabsRoot>
</template>
