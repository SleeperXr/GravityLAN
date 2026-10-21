<script setup lang="ts">
import { ref, watch } from 'vue';
import { Radar } from 'lucide-vue-next';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import type { ScanTarget } from '@/composables/useDashboardScan';
import { t } from '@/i18n';

/** Choose what the dashboard scan sweeps: every scan subnet, or one of them. */
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ targets: ScanTarget[]; starting?: boolean }>();
const emit = defineEmits<{ start: [subnet: string | null] }>();

const ALL = '__all__';
const selected = ref<string>(ALL);
watch(open, (isOpen) => {
  if (isOpen) selected.value = props.targets.length > 1 ? ALL : (props.targets[0]?.subnet ?? ALL);
});
</script>

<template>
  <Dialog v-model:open="open" :title="t('dashboard.select_network')" :description="t('dashboard.select_subnet_prompt')" size="sm">
    <fieldset class="space-y-1.5">
      <legend class="sr-only">{{ t('dashboard.select_network') }}</legend>
      <label
        v-for="option in [
          ...(targets.length > 1 ? [{ subnet: ALL, label: t('gv.scan.all_targets', { count: targets.length }) }] : []),
          ...targets,
        ]"
        :key="option.subnet"
        class="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2.5 transition-colors"
        :class="selected === option.subnet ? 'border-accent/60 bg-accent/[0.06]' : 'border-line bg-raised hover:border-line-strong'"
      >
        <input v-model="selected" type="radio" name="scan-target" :value="option.subnet" class="size-4 accent-[var(--gl-accent)]" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium" :class="option.subnet === ALL ? 'text-fg' : 'font-mono text-fg'">
            {{ option.subnet === ALL ? t('gv.scan.all') : option.subnet }}
          </span>
          <span class="block truncate text-xs text-fg-subtle">{{ option.label }}</span>
        </span>
      </label>
    </fieldset>
    <template #footer>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :loading="starting" @click="emit('start', selected === ALL ? null : selected)">
        <Radar v-if="!starting" aria-hidden="true" />
        {{ t('dashboard.start_scan') }}
      </Button>
    </template>
  </Dialog>
</template>
