<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ArrowRight, Check, GripVertical, RefreshCw, Settings, ShieldAlert, SquareTerminal, Trash2, X } from 'lucide-vue-next';
import type { Device } from '@/types';
import { api } from '@/api/client';
import StatusDot from '@/components/common/StatusDot.vue';
import Badge from '@/components/ui/Badge.vue';
import DeviceMetrics from './DeviceMetrics.vue';
import NetworkChips from './NetworkChips.vue';
import ServiceBadge from './ServiceBadge.vue';
import { isAgentOutdated, patchState } from '@/lib/agent';
import { deviceLabel } from '@/lib/networks';
import { useConfirm } from '@/composables/useConfirm';
import { t } from '@/i18n';

const props = defineProps<{ device: Device; editMode?: boolean; selected?: boolean }>();
const emit = defineEmits<{ edit: []; refresh: []; select: [selected: boolean] }>();

const router = useRouter();
const { confirm } = useConfirm();
const refreshing = ref(false);

const name = computed(() => deviceLabel(props.device));
const services = computed(() => [...props.device.services].sort((a, b) => a.sort_order - b.sort_order));
const hasSsh = computed(() => services.value.some((s) => s.protocol.toLowerCase() === 'ssh' || s.port === 22));
const role = computed(() => {
  const d = props.device;
  if (d.virtual_type === 'docker') return 'Docker';
  if (d.virtual_type === 'vm') return 'VM';
  if (d.virtual_type) return d.virtual_type.toUpperCase();
  if (d.is_host) return 'Host';
  return null;
});
const agentUpdate = computed(
  () => !props.editMode && isAgentOutdated(props.device.agent_info?.agent_version, props.device.agent_info?.latest_version),
);
const pendingKey = computed(() => !props.editMode && !!props.device.has_pending_token);
// Security updates the agent reports for this host
const securityUpdates = computed(() => (props.editMode ? 0 : patchState(props.device)?.security ?? 0));

async function refreshInfo() {
  refreshing.value = true;
  try {
    await api.refreshDeviceInfo(props.device.id);
    emit('refresh');
  } catch {
    // the card simply stays as it was
  } finally {
    window.setTimeout(() => (refreshing.value = false), 600);
  }
}

async function adoptKey() {
  const ok = await confirm({ title: t('dashboard.security_alert'), message: t('agent.adopt_confirm'), confirmLabel: t('dashboard.adopt') });
  if (!ok) return;
  await api.adoptAgent(props.device.id).catch(() => {});
  emit('refresh');
}

async function clearIpChange() {
  await api.updateDevice(props.device.id, { old_ip: null, ip_changed_at: null }).catch(() => {});
  emit('refresh');
}
</script>

<template>
  <article
    class="relative flex h-full w-full flex-col gap-2.5 overflow-hidden rounded-lg border bg-surface p-3.5 shadow-card transition-[border-color,box-shadow]"
    :class="[
      selected ? 'border-danger ring-1 ring-danger/50' : editMode ? 'border-accent/40' : 'border-line hover:border-line-strong',
      !device.is_online && !editMode && 'bg-surface/70',
    ]"
  >
    <header class="flex items-start gap-2.5">
      <button
        v-if="editMode"
        type="button"
        class="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-md border transition-colors"
        :class="selected ? 'border-danger bg-danger text-danger-fg' : 'border-line-strong text-fg-subtle hover:border-danger hover:text-danger-text'"
        :aria-pressed="selected"
        :aria-label="t('dashboard.delete_selected', { count: 1 })"
        @click.stop="emit('select', !selected)"
      >
        <Check v-if="selected" class="size-3.5" aria-hidden="true" />
        <Trash2 v-else class="size-3" aria-hidden="true" />
      </button>
      <StatusDot
        v-else
        class="mt-1.5"
        :state="device.is_online ? 'online' : 'offline'"
        :label="device.is_online ? t('network.online') : t('network.offline')"
      />

      <div class="min-w-0 flex-1">
        <h3 class="truncate text-sm font-semibold text-fg" :class="!device.is_online && 'text-fg-muted'" :title="name">{{ name }}</h3>
        <div class="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-subtle">
          <span class="font-mono">{{ device.ip }}</span>
          <Badge v-if="role" class="text-[10px]">{{ role }}</Badge>
          <span v-if="device.parent_id" class="truncate">{{ t('dashboard.on_host', { host: device.parent_name || 'Host' }) }}</span>
        </div>
      </div>

      <div v-if="editMode" class="gs-drag-handle -mt-1 -mr-1 inline-flex size-7 cursor-grab items-center justify-center rounded-md text-fg-subtle" aria-hidden="true">
        <GripVertical class="size-4" />
      </div>
      <div v-else class="-mt-1 -mr-1.5 flex shrink-0 items-center opacity-70 transition-opacity group-hover/tile:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        <button
          v-if="hasSsh"
          type="button"
          class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg"
          :aria-label="`${t('ssh.open_terminal')}: ${name}`"
          :title="t('ssh.open_terminal')"
          @click.stop="router.push({ path: '/ssh', query: { device: device.id } })"
        >
          <SquareTerminal class="size-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg"
          :aria-label="t('dashboard.refresh_info')"
          :title="t('dashboard.refresh_info')"
          @click.stop="refreshInfo"
        >
          <RefreshCw class="size-3.5" :class="refreshing && 'animate-spin'" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg"
          :aria-label="`${t('dashboard.edit_device')}: ${name}`"
          :title="t('dashboard.edit_device')"
          @click.stop="emit('edit')"
        >
          <Settings class="size-4" aria-hidden="true" />
        </button>
      </div>
    </header>

    <NetworkChips :device="device" />

    <div v-if="agentUpdate || pendingKey || securityUpdates || device.old_ip" class="flex flex-wrap gap-1.5">
      <Badge v-if="securityUpdates" tone="warn" :title="t('gv.dashboard.security_updates_title', { count: securityUpdates, total: patchState(device)?.available ?? securityUpdates })">
        <ShieldAlert aria-hidden="true" />{{ t('gv.dashboard.security_updates', { count: securityUpdates }) }}
      </Badge>
      <Badge v-if="agentUpdate" tone="warn" :title="t('common.update_available', { version: device.agent_info?.latest_version })">
        <RefreshCw aria-hidden="true" />{{ t('dashboard.agent_update') }}
      </Badge>
      <span v-if="pendingKey" class="inline-flex items-center gap-1 rounded-sm border border-danger/30 bg-danger/10 py-0.5 pr-0.5 pl-1.5 text-[11px] font-medium text-danger-text">
        <ShieldAlert class="size-3" aria-hidden="true" />{{ t('dashboard.security_alert') }}
        <button type="button" class="ml-1 rounded-[4px] bg-danger px-1.5 text-[10px] font-semibold text-danger-fg hover:opacity-90" @click.stop="adoptKey">
          {{ t('dashboard.adopt') }}
        </button>
      </span>
      <button
        v-if="device.old_ip"
        type="button"
        class="inline-flex items-center gap-1 rounded-sm border border-info/25 bg-info/10 px-1.5 py-0.5 font-mono text-[11px] text-info-text hover:border-info/50"
        :title="t('dashboard.ip_changed_hint')"
        @click.stop="clearIpChange"
      >
        {{ device.old_ip }} <ArrowRight class="size-3" aria-hidden="true" /> {{ device.ip }} <X class="size-3" aria-hidden="true" />
      </button>
    </div>

    <DeviceMetrics v-if="device.has_agent && !editMode" :device-id="device.id" />

    <div v-if="services.length > 0" class="mt-auto flex min-h-0 flex-wrap content-start gap-1.5 overflow-y-auto border-t border-line pt-2.5 [scrollbar-width:thin]">
      <ServiceBadge v-for="service in services" :key="service.id" :service="service" :ip="device.ip" :disabled="editMode" />
    </div>
  </article>
</template>
