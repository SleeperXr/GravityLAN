<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Bell, BellOff, Cpu, Layers, Lock, RotateCcw, Server, ShieldAlert, ShieldCheck, ShieldOff, Thermometer } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { DeviceHealthDetailResponse, DeviceHealthItem } from '@/types';
import Sheet from '@/components/ui/Sheet.vue';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import HealthStatusBadge from './HealthStatusBadge.vue';
import LatencyChart from './LatencyChart.vue';
import IncidentList from './IncidentList.vue';
import UptimeBars from './UptimeBars.vue';
import { ms, scoreText } from './healthModel';
import { formatDateTime, t } from '@/i18n';

/** Telemetry of one device: uptime, latency chart, service probes with SSL, agent health, incidents. */
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ device: DeviceHealthItem | null; period: '24h' | '7d' | '30d' }>();
const emit = defineEmits<{ updated: []; openEditor: [deviceId: number] }>();

const detail = ref<DeviceHealthDetailResponse | null>(null);
const loading = ref(false);
const togglingAlert = ref(false);
const togglingSvc = ref<number | null>(null);

async function load() {
  if (!props.device) return;
  loading.value = true;
  try {
    detail.value = await api.getDeviceHealthDetail(props.device.id, props.period);
  } catch {
    detail.value = null;
  } finally {
    loading.value = false;
  }
}
watch(() => [props.device?.id, props.period, open.value] as const, ([id, , isOpen]) => {
  if (id && isOpen) void load();
});

const dev = computed(() => (detail.value && detail.value.device.id === props.device?.id ? detail.value.device : props.device));
const alertOn = computed(() => dev.value?.alert_offline ?? true);

async function toggleAlert() {
  if (!dev.value) return;
  togglingAlert.value = true;
  try {
    await api.updateDevice(dev.value.id, { alert_offline: !alertOn.value });
    await load();
    emit('updated');
  } finally {
    togglingAlert.value = false;
  }
}

async function toggleSsl(serviceId: number, ignored: boolean) {
  togglingSvc.value = serviceId;
  try {
    await api.updateService(serviceId, { ignore_ssl: !ignored });
    await load();
    emit('updated');
  } finally {
    togglingSvc.value = null;
  }
}

const isSslCandidate = (s: DeviceHealthItem['services'][number]) =>
  s.protocol?.toLowerCase() === 'https' || [443, 8443, 5001].includes(s.port) || s.ssl_expiry_days !== null || !!s.ignore_ssl;
</script>

<template>
  <Sheet v-if="dev" v-model:open="open" :title="dev.display_name" :description="`${dev.ip}${dev.group_name ? ` · ${dev.group_name}` : ''}`" width="lg">
    <template #icon>
      <StatusDot class="mt-2" :state="dev.is_online ? 'online' : 'offline'" :label="dev.is_online ? t('network.online') : t('network.offline')" />
    </template>
    <template #meta>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <HealthStatusBadge :status="dev.health_status" />
        <span class="font-mono text-xs font-semibold" :class="scoreText(dev.health_score)">Score {{ dev.health_score }}</span>
      </div>
    </template>

    <div class="space-y-5">
      <button
        type="button"
        class="flex w-full items-center gap-3 rounded-md border p-3 text-left transition-colors"
        :class="alertOn ? 'border-accent/40 bg-accent/[0.06]' : 'border-line bg-raised'"
        :disabled="togglingAlert"
        :aria-pressed="alertOn"
        @click="toggleAlert"
      >
        <component :is="alertOn ? Bell : BellOff" class="size-4 shrink-0" :class="alertOn ? 'text-accent-text' : 'text-fg-subtle'" aria-hidden="true" />
        <span class="min-w-0 flex-1">
          <span class="block text-sm font-semibold text-fg">{{ alertOn ? t('health_page.alert_offline_24_7') : t('health_page.alert_offline_client') }}</span>
          <span class="block text-xs text-fg-subtle">{{ t('health_page.alert_offline_hint') }}</span>
        </span>
      </button>

      <div class="grid grid-cols-2 gap-3">
        <div class="rounded-md border border-line bg-raised p-3">
          <p class="gl-eyebrow">{{ t('health_page.table_uptime') }}</p>
          <p class="mt-1 font-mono text-xl font-semibold text-accent-text tabular">{{ dev.uptime.uptime_pct.toFixed(1) }}%</p>
          <p class="mt-0.5 font-mono text-[11px] text-fg-subtle">24h {{ dev.uptime.uptime_24h.toFixed(1) }}% · 7d {{ dev.uptime.uptime_7d.toFixed(1) }}%</p>
          <UptimeBars class="mt-2" height="sm" :bars="dev.uptime.history_bars" :uptime="dev.uptime.uptime_pct" />
        </div>
        <div class="rounded-md border border-line bg-raised p-3">
          <p class="gl-eyebrow">{{ t('health_page.avg_latency') }}</p>
          <p class="mt-1 font-mono text-xl font-semibold text-info-text tabular">{{ ms(dev.latency.avg_ms) }}</p>
          <p class="mt-0.5 font-mono text-[11px] text-fg-subtle">Jitter ±{{ ms(dev.latency.jitter_ms) }}</p>
        </div>
      </div>

      <LatencyChart :samples="detail?.device.id === dev.id ? detail.time_series : []" :loading="loading" />

      <section class="space-y-2">
        <h3 class="flex items-center gap-1.5 text-sm font-bold text-fg"><Layers class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('health_page.drawer_services') }} ({{ dev.services.length }})</h3>
        <p v-if="dev.services.length === 0" class="rounded-md border border-line bg-raised p-3 text-center text-xs text-fg-subtle">{{ t('health_page.no_services_discovered') }}</p>
        <ul v-else class="divide-y divide-line rounded-md border border-line">
          <li v-for="srv in dev.services" :key="srv.id" class="flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
            <StatusDot size="sm" :state="srv.is_up ? 'online' : 'offline'" :label="srv.is_up ? t('network.online') : t('network.offline')" />
            <span class="font-semibold text-fg">{{ srv.name }}</span>
            <span class="font-mono text-fg-subtle">:{{ srv.port }}</span>
            <span class="ml-auto flex flex-wrap items-center gap-2">
              <span v-if="srv.latency_ms !== null" class="font-mono text-fg-muted">{{ ms(srv.latency_ms) }}</span>
              <Badge v-if="srv.ignore_ssl"><ShieldOff aria-hidden="true" />{{ t('health_page.ssl_ignored') }}</Badge>
              <Badge v-else-if="srv.ssl_expiry_days !== null" :tone="srv.ssl_expiry_days <= 0 ? 'danger' : srv.ssl_expiry_days <= 14 ? 'warn' : 'neutral'">
                <Lock aria-hidden="true" />{{ srv.ssl_expiry_days <= 0 ? t('health_page.ssl_expired') : t('health_page.ssl_days_left', { days: srv.ssl_expiry_days }) }}
              </Badge>
              <Button v-if="isSslCandidate(srv)" size="sm" variant="ghost" class="h-6 px-1.5 text-[11px]" :loading="togglingSvc === srv.id" :title="t('health_page.ignore_ssl_hint')" @click="toggleSsl(srv.id, !!srv.ignore_ssl)">
                <component :is="srv.ignore_ssl ? ShieldCheck : ShieldOff" v-if="togglingSvc !== srv.id" aria-hidden="true" />
                {{ srv.ignore_ssl ? t('health_page.unignore_ssl_btn') : t('health_page.ignore_ssl_btn') }}
              </Button>
            </span>
          </li>
        </ul>
      </section>

      <section v-if="dev.agent?.has_agent" class="space-y-2">
        <h3 class="flex items-center gap-1.5 text-sm font-bold text-fg"><Server class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('health_page.drawer_agent_health') }}</h3>
        <div class="space-y-3 rounded-md border border-line bg-raised p-3">
          <p class="flex justify-between font-mono text-xs"><span class="text-fg-subtle">{{ t('health_page.agent_version_label') }}</span><span class="text-fg">{{ dev.agent.agent_version || '–' }}</span></p>
          <div class="grid grid-cols-3 gap-2 text-center font-mono text-xs">
            <div class="rounded-sm border border-line bg-surface p-2"><p class="flex items-center justify-center gap-1 text-[10px] text-fg-subtle"><Cpu class="size-3" />CPU</p><p class="mt-1 font-semibold text-fg">{{ dev.agent.cpu_percent !== null ? `${dev.agent.cpu_percent.toFixed(0)}%` : '–' }}</p></div>
            <div class="rounded-sm border border-line bg-surface p-2"><p class="text-[10px] text-fg-subtle">RAM</p><p class="mt-1 font-semibold text-fg">{{ dev.agent.ram_percent !== null ? `${dev.agent.ram_percent.toFixed(0)}%` : '–' }}</p></div>
            <div class="rounded-sm border border-line bg-surface p-2"><p class="flex items-center justify-center gap-1 text-[10px] text-fg-subtle"><Thermometer class="size-3" />Temp</p><p class="mt-1 font-semibold text-fg">{{ dev.agent.temperature !== null ? `${dev.agent.temperature.toFixed(0)}°C` : '–' }}</p></div>
          </div>
          <div v-if="dev.agent.patch_security > 0 || dev.agent.reboot_required" class="flex gap-2 rounded-sm border border-danger/30 bg-danger/10 p-2.5 text-xs text-danger-text">
            <ShieldAlert class="size-4 shrink-0" aria-hidden="true" />
            <div>
              <p v-if="dev.agent.patch_security > 0">{{ t('health_page.critical_patches_count', { count: dev.agent.patch_security }) }}</p>
              <p v-if="dev.agent.reboot_required" class="flex items-center gap-1 font-semibold"><RotateCcw class="size-3" />{{ t('health_page.reboot_required_desc') }}</p>
            </div>
          </div>
        </div>
      </section>

      <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-md border border-line bg-raised p-3 text-xs">
        <dt class="text-fg-subtle">{{ t('health_page.last_seen') }}</dt><dd class="text-right font-mono text-fg"><RelativeTime :date="dev.last_seen" /></dd>
        <dt class="text-fg-subtle">{{ t('health_page.status_changed') }}</dt><dd class="text-right font-mono text-fg">{{ dev.status_changed_at ? formatDateTime(dev.status_changed_at) : '–' }}</dd>
        <template v-if="dev.ip_changed_at"><dt class="text-fg-subtle">{{ t('health_page.ip_changed') }}</dt><dd class="text-right font-mono text-fg">{{ formatDateTime(dev.ip_changed_at) }}</dd></template>
      </dl>

      <section class="space-y-2">
        <h3 class="text-sm font-bold text-fg">{{ t('health_page.drawer_history') }}</h3>
        <IncidentList layout="list" :incidents="detail?.device.id === dev.id ? detail.incidents : []" />
      </section>
    </div>

    <template #footer>
      <Button @click="emit('openEditor', dev.id)">{{ t('dashboard.edit_device') }}</Button>
    </template>
  </Sheet>
</template>
