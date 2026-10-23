<script setup lang="ts">
import { ref, watch } from 'vue';
import { History } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { DeviceHealthItem, DeviceHistoryResponse } from '@/types';
import EmptyState from '@/components/ui/EmptyState.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import StatusMonitor from '@/components/common/StatusMonitor.vue';
import { periodHours, statusWord } from '@/components/health/healthModel';
import { t } from '@/i18n';

type Period = '24h' | '7d' | '30d';

/** Availability over the chosen period plus the status history, (re)loaded each time the tab is opened. */
const props = defineProps<{ deviceId: number; active: boolean }>();
const history = ref<DeviceHistoryResponse[]>([]);
const uptime = ref<DeviceHealthItem['uptime'] | null>(null);
const period = ref<Period>('24h');
const periods: Period[] = ['24h', '7d', '30d'];
const loading = ref(false);

async function loadUptime() {
  try {
    uptime.value = (await api.getDeviceHealthDetail(props.deviceId, period.value)).device.uptime;
  } catch {
    uptime.value = null;
  }
}

watch(
  () => props.active,
  async (on) => {
    if (!on) return;
    loading.value = true;
    try {
      const [items] = await Promise.all([api.getDeviceHistory(props.deviceId).catch(() => []), loadUptime()]);
      history.value = items;
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);
watch(period, () => void loadUptime());

const isUp = (item: DeviceHistoryResponse) => item.status === 'online' || item.status === 'up';
</script>

<template>
  <div v-if="loading" class="space-y-2" aria-busy="true">
    <Skeleton class="h-20" />
    <Skeleton v-for="i in 3" :key="i" class="h-14" />
  </div>
  <div v-else class="space-y-5">
    <section v-if="uptime" class="rounded-md border border-line bg-raised p-3">
      <div class="mb-2 flex items-center justify-between gap-2">
        <p class="gl-eyebrow">{{ t('health_page.table_uptime') }}</p>
        <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.health.period')">
          <button
            v-for="p in periods"
            :key="p"
            type="button"
            class="rounded px-2 py-0.5 text-[11px] font-semibold"
            :class="period === p ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="period === p"
            @click="period = p"
          >
            {{ t(`health_page.period_${p}`) }}
          </button>
        </div>
      </div>
      <StatusMonitor :bars="uptime.history_bars" :span-hours="periodHours(period)" :uptime="uptime.uptime_pct" />
    </section>

    <EmptyState v-if="history.length === 0" compact :icon="History" :title="t('notifications.no_events')" />
    <ol v-else class="relative space-y-0 border-l border-line pl-5">
      <li v-for="item in history" :key="item.id" class="relative pb-4 last:pb-0">
        <span
          class="absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-surface"
          :class="isUp(item) ? 'bg-accent' : 'bg-danger'"
          aria-hidden="true"
        />
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[11px] font-semibold" :class="isUp(item) ? 'text-accent-text' : 'text-danger-text'">{{ statusWord(item.status) }}</span>
          <span v-if="item.service_id" class="rounded-sm bg-raised px-1.5 text-[10px] font-medium text-fg-muted">SERVICE</span>
          <span class="ml-auto text-xs text-fg-subtle"><RelativeTime :date="item.timestamp" /></span>
        </div>
        <p class="mt-0.5 text-sm text-fg">{{ item.message }}</p>
      </li>
    </ol>
  </div>
</template>
