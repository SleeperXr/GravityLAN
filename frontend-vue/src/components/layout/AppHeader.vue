<script setup lang="ts">
import { Radar, RefreshCw, Languages } from 'lucide-vue-next';
import { useNetworkStore } from '@/stores/network';
import { useI18n } from '@/composables/useI18n';
import Button from '@/components/ui/button/Button.vue';
import Badge from '@/components/ui/badge/Badge.vue';

const store = useNetworkStore();
const { locale, toggleLocale, t } = useI18n();
</script>

<template>
  <header class="flex h-14 shrink-0 items-center justify-between border-b border-[#1F2732] bg-[#12161C]/90 px-6 backdrop-blur-xs">
    <div class="flex items-center gap-3">
      <h1 class="text-sm font-semibold text-[#E6EAF0]">
        {{ t('dashboard.title') }}
      </h1>
      <Badge v-if="store.isScanning" variant="default" class="animate-pulse font-mono">
        <Radar class="h-3 w-3 animate-spin" />
        {{ store.scanProgress?.current_subnet || t('dashboard.scanning') }}
        ({{ store.scanProgress?.hosts_scanned ?? 0 }}/{{ store.scanProgress?.hosts_total ?? 0 }})
      </Badge>
    </div>

    <div class="flex items-center gap-2">
      <Button variant="outline" size="sm" @click="toggleLocale">
        <Languages class="h-3.5 w-3.5 text-[#3DB8F5]" />
        <span class="font-mono uppercase">{{ locale }}</span>
      </Button>

      <Button
        variant="outline"
        size="sm"
        :disabled="store.loading"
        @click="store.fetchInventory(true)"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="store.loading ? 'animate-spin' : ''" />
        <span>{{ t('dashboard.refresh') }}</span>
      </Button>

      <Button
        variant="default"
        size="sm"
        :disabled="store.isScanning"
        @click="store.triggerQuickScan()"
      >
        <Radar class="h-3.5 w-3.5" />
        <span>{{ store.isScanning ? t('dashboard.scanning') : t('dashboard.scan_now') }}</span>
      </Button>
    </div>
  </header>
</template>
