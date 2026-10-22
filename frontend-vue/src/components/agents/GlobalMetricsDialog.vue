<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { api } from '@/api/client';
import type { GlobalMetricPoint } from '@/types';
import Dialog from '@/components/ui/Dialog.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import TimeSeriesChart from '@/components/charts/TimeSeriesChart.vue';
import { t } from '@/i18n';

/** Fleet averages over time: mean CPU and RAM of all agents. */
const open = defineModel<boolean>('open', { default: false });
const history = ref<GlobalMetricPoint[]>([]);
const loading = ref(false);

watch(open, async (isOpen) => {
  if (!isOpen) return;
  loading.value = true;
  try {
    const res = await api.getGlobalMetrics();
    history.value = Array.isArray(res.history) ? res.history : [];
  } catch {
    history.value = [];
  } finally {
    loading.value = false;
  }
});

const avg = (key: 'avg_cpu' | 'avg_ram') => (history.value.length ? history.value.reduce((s, p) => s + p[key], 0) / history.value.length : 0);
const series = computed(() => [
  { label: t('agent.cpu'), color: 'var(--line-3)', values: history.value.map((p) => p.avg_cpu), suffix: ' %' },
  { label: t('agent.ram'), color: 'var(--line-1)', values: history.value.map((p) => p.avg_ram), suffix: ' %' },
]);
</script>

<template>
  <Dialog v-model:open="open" :title="t('global_metrics.title')" :description="t('global_metrics.subtitle')" size="xl">
    <Skeleton v-if="loading" class="h-56" />
    <p v-else-if="history.length === 0" class="py-10 text-center text-sm text-fg-subtle">{{ t('global_metrics.no_data') }}</p>
    <template v-else>
      <div class="mb-4 grid grid-cols-2 gap-3">
        <div class="rounded-md border border-line bg-raised p-3">
          <p class="gl-eyebrow">Ø {{ t('agent.cpu') }}</p>
          <p class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ avg('avg_cpu').toFixed(1) }} %</p>
        </div>
        <div class="rounded-md border border-line bg-raised p-3">
          <p class="gl-eyebrow">Ø {{ t('agent.ram') }}</p>
          <p class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ avg('avg_ram').toFixed(1) }} %</p>
        </div>
      </div>
      <TimeSeriesChart :timestamps="history.map((p) => p.timestamp)" :series="series" :max="100" :height="220" :label="t('global_metrics.title')" />
    </template>
  </Dialog>
</template>
