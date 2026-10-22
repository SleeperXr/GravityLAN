<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { Activity, ArrowUpCircle, ChevronRight, Package, RefreshCw, RotateCcw, Search, Server, ShieldAlert, ShieldCheck } from 'lucide-vue-next';
import { api } from '@/api/client';
import PageHeader from '@/components/ui/PageHeader.vue';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import ErrorState from '@/components/ui/ErrorState.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import AgentDetail from '@/components/agents/AgentDetail.vue';
import GlobalMetricsDialog from '@/components/agents/GlobalMetricsDialog.vue';
import { hourState, loadTone, matchesAgent, osLabelOf, type AgentRow } from '@/components/agents/agentRow';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { formatDateTime, formatNumber, t } from '@/i18n';

/** Every installed agent: load, uptime, pending updates; a row opens telemetry and patching. */
interface Overview {
  agents: AgentRow[];
  total_agents: number;
  active_agents: number;
  total_data_points: number;
  avg_cpu: number;
  avg_ram: number;
}

const { showToast } = useToast();
const data = ref<Overview | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref<string | null>(null);
const search = ref('');
const expandedId = ref<number | null>(null);
const showGlobal = ref(false);
let timer: number | undefined;

async function load(silent = true) {
  if (!silent) refreshing.value = true;
  try {
    data.value = (await api.getAgentsOverview()) as Overview;
    error.value = null;
  } catch (err) {
    if (!data.value) error.value = (err as Error).message;
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

onMounted(() => {
  void load();
  timer = window.setInterval(() => void load(), 30000);
});
onBeforeUnmount(() => window.clearInterval(timer));

const agents = computed(() => (data.value?.agents ?? []).filter((a) => matchesAgent(a, search.value)));

async function adopt(agent: AgentRow) {
  const ok = await confirmAction({ title: t('dashboard.adopt'), message: t('agent.adopt_confirm'), confirmLabel: t('dashboard.adopt') });
  if (!ok) return;
  try {
    await api.adoptAgent(agent.device_id);
    showToast('success', t('gv.agents.adopted'), agent.hostname);
    await load();
  } catch (err) {
    showToast('error', t('gv.agents.adopt_failed'), (err as Error).message);
  }
}

const toneText = { ok: 'text-fg-muted', warn: 'text-warn-text', danger: 'text-danger-text' } as const;
const toneBar = { ok: 'bg-accent', warn: 'bg-warn', danger: 'bg-danger' } as const;
const hourBar = { up: 'bg-accent', partial: 'bg-warn', down: 'bg-danger', none: 'bg-line' } as const;
const uptimeText = (pct: number) => (pct < 80 ? 'text-danger-text' : pct < 95 ? 'text-warn-text' : 'text-accent-text');
const hours = (a: AgentRow): (number | null)[] => (a.uptime_history?.length ? a.uptime_history : Array<number | null>(24).fill(null));
</script>

<template>
  <div class="mx-auto max-w-[1800px] space-y-5 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('agents_page.title')" :description="t('agents_page.subtitle', { count: data?.total_agents ?? 0 })">
      <Button :disabled="refreshing" @click="load(false)">
        <RefreshCw :class="refreshing && 'animate-spin'" aria-hidden="true" />{{ t('agents_page.sync') }}
      </Button>
    </PageHeader>

    <div class="flex flex-wrap items-center gap-3">
      <label class="relative min-w-0 flex-1 sm:max-w-xs">
        <span class="sr-only">{{ t('agents_page.search_placeholder') }}</span>
        <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
        <input v-model="search" type="search" :placeholder="t('agents_page.search_placeholder')" class="h-9 w-full rounded-md border border-line bg-surface pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:outline-none" />
      </label>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-line bg-surface px-3.5 py-2 text-xs" :aria-label="t('agents_page.title')">
        <span class="flex items-baseline gap-1.5">
          <span class="text-fg-subtle">{{ t('agents_page.nodes') }}:</span>
          <span class="font-mono font-semibold text-accent-text tabular">{{ data?.active_agents ?? 0 }}</span>
          <span class="font-mono text-fg-subtle">/ {{ data?.total_agents ?? 0 }}</span>
        </span>
        <span class="h-3.5 w-px bg-line" aria-hidden="true" />
        <span class="flex items-baseline gap-1.5">
          <span class="text-fg-subtle">{{ t('agents_page.avg_cpu') }}:</span>
          <span class="font-mono font-semibold tabular" :class="(data?.avg_cpu ?? 0) >= 80 ? 'text-warn-text' : 'text-fg'">{{ (data?.avg_cpu ?? 0).toFixed(1) }}%</span>
        </span>
        <span class="h-3.5 w-px bg-line" aria-hidden="true" />
        <span class="flex items-baseline gap-1.5">
          <span class="text-fg-subtle">{{ t('agents_page.avg_ram') }}:</span>
          <span class="font-mono font-semibold text-fg tabular">{{ (data?.avg_ram ?? 0).toFixed(1) }}%</span>
        </span>
        <span class="hidden h-3.5 w-px bg-line sm:inline-block" aria-hidden="true" />
        <span class="hidden items-baseline gap-1.5 sm:flex">
          <span class="text-fg-subtle">{{ t('agents_page.snapshots') }}:</span>
          <span class="font-mono font-semibold text-fg tabular">{{ formatNumber(data?.total_data_points ?? 0) }}</span>
        </span>
      </div>
      <Button class="ml-auto" @click="showGlobal = true"><Activity aria-hidden="true" />{{ t('agents_page.global_analytics') }}</Button>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 4" :key="i" class="h-20" />
    </div>
    <ErrorState v-else-if="error" :title="t('gv.agents.load_failed')" :message="error" :retrying="refreshing" @retry="load(false)" />
    <EmptyState v-else-if="agents.length === 0" :icon="Server" :title="t('agent_detail.no_agents')" />

    <section v-else class="gl-card overflow-hidden">
      <div class="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.3fr)_minmax(0,0.8fr)] gap-4 border-b border-line px-4 py-2 text-xs font-medium text-fg-subtle lg:grid" aria-hidden="true">
        <span class="pl-7">{{ t('agents_page.col_agent') }}</span>
        <span>{{ t('agents_page.col_connection') }}</span>
        <span>{{ t('agents_page.col_performance') }}</span>
        <span>{{ t('agents_page.col_uptime') }}</span>
        <span class="text-right">{{ t('agents_page.col_activity') }}</span>
      </div>
      <ul class="divide-y divide-line">
        <li v-for="agent in agents" :key="agent.device_id" :class="expandedId === agent.device_id && 'bg-raised/40'">
          <button
            type="button"
            class="grid w-full grid-cols-1 gap-3 px-4 py-3 text-left transition-colors hover:bg-raised/60 lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.3fr)_minmax(0,0.8fr)] lg:items-center lg:gap-4"
            :aria-expanded="expandedId === agent.device_id"
            :aria-controls="`agent-detail-${agent.device_id}`"
            @click="expandedId = expandedId === agent.device_id ? null : agent.device_id"
          >
            <span class="flex min-w-0 items-start gap-2.5">
              <ChevronRight class="mt-1 size-4 shrink-0 text-fg-subtle transition-transform" :class="expandedId === agent.device_id && 'rotate-90'" aria-hidden="true" />
              <span class="grid size-9 shrink-0 place-items-center rounded-md border" :class="agent.is_online ? 'border-accent/40 bg-accent/10 text-accent-text' : 'border-line bg-sunken text-fg-subtle'" aria-hidden="true">
                <Server class="size-4" />
              </span>
              <span class="min-w-0">
                <span class="block truncate text-sm font-semibold text-fg">{{ agent.hostname }}</span>
                <span class="block font-mono text-xs text-fg-subtle">{{ agent.ip }} · v{{ agent.agent_version || '0.0.0' }}</span>
                <span class="mt-1 flex flex-wrap gap-1">
                  <Badge v-if="osLabelOf(agent)" class="max-w-48 truncate" :title="osLabelOf(agent) ?? undefined">{{ osLabelOf(agent) }}</Badge>
                  <Badge v-if="agent.patch_available > 0" :tone="agent.patch_security > 0 ? 'danger' : 'warn'" mono :title="t('agent_detail.updates_badge', { count: agent.patch_available, security: agent.patch_security })">
                    <component :is="agent.patch_security > 0 ? ShieldAlert : Package" aria-hidden="true" />{{ agent.patch_available }}
                  </Badge>
                  <Badge v-if="agent.reboot_required" tone="danger"><RotateCcw aria-hidden="true" />{{ t('agent_detail.reboot_badge') }}</Badge>
                  <Badge v-if="agent.major_upgrade_available" tone="info" :title="t('agent_detail.major_upgrade', { target: agent.major_upgrade_available })"><ArrowUpCircle aria-hidden="true" />{{ agent.major_upgrade_available }}</Badge>
                </span>
              </span>
            </span>

            <span class="flex items-center gap-2 text-xs font-medium" :class="agent.is_online ? 'text-accent-text' : 'text-danger-text'">
              <StatusDot :state="agent.is_online ? 'online' : 'offline'" size="sm" />
              {{ agent.is_online ? t('agents_page.connected') : t('agents_page.disconnected') }}
            </span>

            <span class="grid grid-cols-2 gap-3">
              <span v-for="m in [{ label: 'CPU', value: agent.cpu_usage }, { label: 'RAM', value: agent.ram_usage }]" :key="m.label" class="space-y-1">
                <span class="flex justify-between font-mono text-[11px]">
                  <span class="text-fg-subtle">{{ m.label }}</span>
                  <span class="font-semibold tabular" :class="toneText[loadTone(m.value)]">{{ m.value.toFixed(1) }} %</span>
                </span>
                <span class="block h-1.5 overflow-hidden rounded-full bg-sunken">
                  <span class="block h-full rounded-full" :class="toneBar[loadTone(m.value)]" :style="{ width: `${Math.min(100, Math.max(0, m.value))}%` }" />
                </span>
              </span>
            </span>

            <span class="flex items-center gap-2.5">
              <span class="w-14 shrink-0 font-mono text-xs font-semibold tabular" :class="uptimeText(agent.uptime_pct)">{{ agent.uptime_pct.toFixed(1) }} %</span>
              <span class="flex h-5 min-w-0 flex-1 items-end gap-px" aria-hidden="true">
                <span
                  v-for="(val, i) in hours(agent)"
                  :key="i"
                  class="h-full min-w-0 flex-1 rounded-[1px]"
                  :class="hourBar[hourState(val)]"
                  :title="val === null || val < 0 ? undefined : t('agent_detail.uptime_hour', { hours: hours(agent).length - 1 - i, pct: val.toFixed(1) })"
                />
              </span>
            </span>

            <span class="font-mono text-xs text-fg-muted lg:text-right">
              <template v-if="agent.last_seen">
                {{ formatDateTime(agent.last_seen, { timeStyle: 'medium' }) }}
                <span class="text-fg-subtle lg:block">{{ formatDateTime(agent.last_seen, { dateStyle: 'short' }) }}</span>
              </template>
              <template v-else>{{ t('agent_detail.never') }}</template>
            </span>
          </button>

          <div v-if="agent.has_pending_token" class="mx-4 mb-3 flex flex-wrap items-center gap-3 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger-text">
            <ShieldCheck class="size-4 shrink-0" aria-hidden="true" />
            <p class="min-w-0 flex-1">{{ t('agent_detail.token_mismatch') }}</p>
            <Button size="sm" @click="adopt(agent)">{{ t('dashboard.adopt') }}</Button>
          </div>

          <div v-if="expandedId === agent.device_id" :id="`agent-detail-${agent.device_id}`" class="border-t border-line px-4 pb-4">
            <AgentDetail :agent="agent" @refresh="load()" />
          </div>
        </li>
      </ul>
    </section>

    <GlobalMetricsDialog v-model:open="showGlobal" />
  </div>
</template>
