<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';
import { Activity, Clock, AlertTriangle, ShieldAlert } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { HealthOverviewResponse } from '@/types';
import { useI18n } from '@/composables/useI18n';
import Card from '@/components/ui/card/Card.vue';
import Badge from '@/components/ui/badge/Badge.vue';
import Button from '@/components/ui/button/Button.vue';

const { t } = useI18n();
const period = ref<'24h' | '7d' | '30d'>('24h');
const overview = ref<HealthOverviewResponse | null>(null);
const loading = ref(true);

async function loadHealth() {
  loading.value = true;
  try {
    overview.value = await api.getHealthOverview(period.value);
  } finally {
    loading.value = false;
  }
}

onMounted(loadHealth);
watch(period, loadHealth);
</script>

<template>
  <div class="space-y-6">
    <!-- Period Switcher -->
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-base font-semibold text-[#E6EAF0]">Health & SLA Radar</h2>
        <p class="text-xs text-[#9AA5B4]">Verfügbarkeit, Latenz-Telemetrie, Flapping-Erkennung und Zertifikatsstatus</p>
      </div>
      <div class="inline-flex rounded-md border border-[#2A3340] bg-[#0B0E13] p-0.5">
        <Button
          v-for="p in (['24h', '7d', '30d'] as const)"
          :key="p"
          :variant="period === p ? 'secondary' : 'ghost'"
          size="sm"
          class="font-mono"
          @click="period = p"
        >
          {{ p }}
        </Button>
      </div>
    </div>

    <!-- KPI Row -->
    <div v-if="overview" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>{{ t('kpi.health_score') }}</span>
          <Activity class="h-4 w-4 text-[#3DB8F5]" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-2xl font-bold text-[#3DB8F5]">
            {{ overview.kpis.network_health_score }}%
          </span>
          <span class="text-[11px] text-[#8390A0]">
            {{ overview.kpis.online_devices }}/{{ overview.kpis.total_devices }} Online
          </span>
        </div>
      </Card>

      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>{{ t('kpi.avg_latency') }}</span>
          <Clock class="h-4 w-4 text-[#4AC26B]" />
        </div>
        <div class="flex items-baseline justify-between font-mono">
          <span class="text-2xl font-bold text-[#E6EAF0]">
            {{ overview.kpis.avg_latency_ms !== null ? `${overview.kpis.avg_latency_ms.toFixed(1)} ms` : '—' }}
          </span>
          <span class="text-[11px] text-[#8390A0]">
            Jitter {{ overview.kpis.avg_jitter_ms !== null ? `${overview.kpis.avg_jitter_ms.toFixed(1)} ms` : '—' }}
          </span>
        </div>
      </Card>

      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>Flapping / Instabil</span>
          <AlertTriangle class="h-4 w-4 text-[#E3B341]" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-2xl font-bold text-[#E3B341]">
            {{ overview.kpis.flapping_devices }}
          </span>
          <span class="text-[11px] text-[#8390A0]">{{ overview.kpis.active_issues_count }} offene Vorfälle</span>
        </div>
      </Card>

      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>SSL & Security Patches</span>
          <ShieldAlert class="h-4 w-4 text-[#F47067]" />
        </div>
        <div class="flex items-baseline justify-between font-mono">
          <span class="text-2xl font-bold text-[#E6EAF0]">
            {{ overview.kpis.patch_warning_count + overview.kpis.ssl_warning_count }}
          </span>
          <span class="text-[11px] text-[#8390A0]">
            {{ overview.kpis.ssl_warning_count }} SSL · {{ overview.kpis.patch_warning_count }} Patches
          </span>
        </div>
      </Card>
    </div>

    <!-- Health Table -->
    <Card v-if="overview" class="overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-xs">
          <thead>
            <tr class="border-b border-[#1F2732] bg-[#12161C] text-[11px] font-medium uppercase tracking-wider text-[#8390A0]">
              <th class="px-4 py-3">Host</th>
              <th class="px-4 py-3">Health Status</th>
              <th class="px-4 py-3">Score</th>
              <th class="px-4 py-3">Uptime ({{ period }})</th>
              <th class="px-4 py-3">Latenz (Ø / Max)</th>
              <th class="px-4 py-3">Services</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[#1F2732]">
            <tr v-for="item in overview.devices" :key="item.id" class="hover:bg-[#1F2732]/40">
              <td class="px-4 py-3">
                <div class="font-medium text-[#E6EAF0]">{{ item.display_name }}</div>
                <div class="font-mono text-[11px] text-[#8390A0]">{{ item.ip }}</div>
              </td>
              <td class="px-4 py-3">
                <Badge
                  :variant="
                    item.health_status === 'healthy'
                      ? 'success'
                      : item.health_status === 'flapping' || item.health_status === 'degraded'
                        ? 'warning'
                        : 'destructive'
                  "
                >
                  {{ item.health_status }}
                </Badge>
              </td>
              <td class="px-4 py-3 font-mono font-semibold text-[#E6EAF0]">{{ item.health_score }}%</td>
              <td class="px-4 py-3 font-mono text-[#E6EAF0]">{{ item.uptime.uptime_pct.toFixed(2) }}%</td>
              <td class="px-4 py-3 font-mono text-[#9AA5B4]">
                {{ item.latency.avg_ms !== null ? `${item.latency.avg_ms.toFixed(1)} ms` : '—' }}
                <span v-if="item.latency.max_ms !== null" class="text-[#8390A0]">
                  / {{ item.latency.max_ms.toFixed(1) }} ms
                </span>
              </td>
              <td class="px-4 py-3 font-mono text-[11px] text-[#9AA5B4]">
                {{ item.services.filter((s) => s.is_up).length }}/{{ item.services.length }} aktiv
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
