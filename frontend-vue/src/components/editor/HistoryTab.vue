<script setup lang="ts">
import { ref, watch } from 'vue';
import { History } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { DeviceHistoryResponse } from '@/types';
import EmptyState from '@/components/ui/EmptyState.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { t } from '@/i18n';

/** Status history, (re)loaded each time the tab is opened. */
const props = defineProps<{ deviceId: number; active: boolean }>();
const history = ref<DeviceHistoryResponse[]>([]);
const loading = ref(false);

watch(
  () => props.active,
  async (on) => {
    if (!on) return;
    loading.value = true;
    try {
      history.value = await api.getDeviceHistory(props.deviceId);
    } catch {
      history.value = [];
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

const isUp = (item: DeviceHistoryResponse) => item.status === 'online' || item.status === 'up';
</script>

<template>
  <div v-if="loading" class="space-y-2" aria-busy="true">
    <Skeleton v-for="i in 4" :key="i" class="h-14" />
  </div>
  <EmptyState v-else-if="history.length === 0" compact :icon="History" :title="t('notifications.no_events')" />
  <ol v-else class="relative space-y-0 border-l border-line pl-5">
    <li v-for="item in history" :key="item.id" class="relative pb-4 last:pb-0">
      <span
        class="absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-surface"
        :class="isUp(item) ? 'bg-accent' : 'bg-danger'"
        aria-hidden="true"
      />
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[11px] font-semibold uppercase tracking-wide" :class="isUp(item) ? 'text-accent-text' : 'text-danger-text'">{{ item.status }}</span>
        <span v-if="item.service_id" class="rounded-sm bg-raised px-1.5 text-[10px] font-medium text-fg-muted">SERVICE</span>
        <span class="ml-auto text-xs text-fg-subtle"><RelativeTime :date="item.timestamp" /></span>
      </div>
      <p class="mt-0.5 text-sm text-fg">{{ item.message }}</p>
    </li>
  </ol>
</template>
