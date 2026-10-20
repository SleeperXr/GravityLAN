<script setup lang="ts">
import { Languages, Radar, RefreshCw } from 'lucide-vue-next';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import { useI18n } from '@/composables/useI18n';
import { useNetworkStore } from '@/stores/network';

const store = useNetworkStore();
const { locale, toggleLocale, t } = useI18n();
</script>

<template>
  <header class="flex h-15 shrink-0 items-center justify-between border-b border-zinc-800/80 bg-[#0e0e11]/90 px-6 backdrop-blur-md">
    <div class="flex items-center gap-3">
      <h1 class="text-sm font-bold text-zinc-100 tracking-tight">
        {{ t('dashboard.title') }}
      </h1>

      <div
        v-if="store.isScanning"
        class="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-xs font-mono text-emerald-400"
      >
        <StatusIndicator state="active" size="sm" />
        <span>
          {{ store.scanProgress?.current_subnet || t('dashboard.scanning') }}
          ({{ store.scanProgress?.hosts_scanned ?? 0 }}/{{ store.scanProgress?.hosts_total ?? 0 }})
        </span>
      </div>
      <div
        v-else
        class="hidden sm:inline-flex items-center gap-2 px-2.5 py-1 rounded-lg bg-[#1b1b20] border border-zinc-800 text-[11px] font-mono text-zinc-400"
      >
        <StatusIndicator :state="store.onlineCount > 0 ? 'active' : 'idle'" size="sm" />
        <span>{{ store.onlineCount }}/{{ store.totalCount }} Hosts Online</span>
      </div>
    </div>

    <div class="flex items-center gap-2">
      <button
        type="button"
        class="sh-pill-btn px-3 py-1.5 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
        @click="toggleLocale"
      >
        <Languages class="h-3.5 w-3.5 text-emerald-400" />
        <span class="font-mono uppercase">{{ locale }}</span>
      </button>

      <button
        type="button"
        class="sh-pill-btn px-3 py-1.5 text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer"
        :disabled="store.loading"
        @click="store.fetchInventory(true)"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="store.loading ? 'animate-spin text-emerald-400' : ''" />
        <span class="hidden sm:inline">{{ t('dashboard.refresh') }}</span>
      </button>

      <button
        type="button"
        class="px-3.5 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs inline-flex items-center gap-1.5 transition-colors cursor-pointer"
        :disabled="store.isScanning"
        @click="store.triggerQuickScan()"
      >
        <Radar class="h-3.5 w-3.5" :class="store.isScanning && 'animate-spin'" />
        <span>{{ store.isScanning ? t('dashboard.scanning') : t('dashboard.scan_now') }}</span>
      </button>
    </div>
  </header>
</template>
