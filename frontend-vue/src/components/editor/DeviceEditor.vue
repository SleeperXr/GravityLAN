<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowRight, History, Network, Save, Server, Settings2, Trash2, Waypoints } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, DeviceGroup, DeviceInterface, Rack } from '@/types';
import {
  computeGroupPlacement,
  deviceRoleOf,
  initialFormData,
  networkPathOf,
  syncModifiedServices,
  type DeviceFormData,
  type EditorTab,
} from '@/lib/deviceForm';
import Sheet from '@/components/ui/Sheet.vue';
import Button from '@/components/ui/Button.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import SettingsTab from './SettingsTab.vue';
import ServicesTab from './ServicesTab.vue';
import InterfacesTab from './InterfacesTab.vue';
import HistoryTab from './HistoryTab.vue';
import AgentTab from './AgentTab.vue';
import { useAgentPanel } from '@/composables/useAgentPanel';
import { useNetworkStore } from '@/stores/network';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/** Device inspector (port of React DeviceEditor): five tabs in a side sheet. */
const open = defineModel<boolean>('open', { default: false });
const props = withDefaults(defineProps<{ device: Device; initialTab?: EditorTab }>(), { initialTab: 'settings' });
const emit = defineEmits<{ saved: []; afterLeave: [] }>();

const store = useNetworkStore();
const { showToast } = useToast();
const { confirm } = useConfirm();

const original = ref<Device>(props.device);
const current = ref<Device>(props.device);
const form = ref<DeviceFormData>(initialFormData(props.device));
const tab = ref<EditorTab>(props.initialTab);
const saving = ref(false);
const refreshing = ref(false);
const scanningServices = ref(false);
const groups = ref<DeviceGroup[]>([]);
const racks = ref<Rack[]>([]);

watch(
  () => [props.device, props.initialTab] as const,
  ([device, initialTab]) => {
    original.value = device;
    current.value = device;
    form.value = initialFormData(device);
    tab.value = initialTab;
  },
);

watch(
  open,
  (isOpen) => {
    if (!isOpen) {
      // Sheet leave animation is ~160 ms
      window.setTimeout(() => emit('afterLeave'), 200);
      return;
    }
    api.getGroups().then((g) => (groups.value = g)).catch(() => (groups.value = []));
    api.getRacks().then((r) => (racks.value = Array.isArray(r) ? r : [])).catch(() => (racks.value = []));
  },
  { immediate: true },
);

const agentPanel = useAgentPanel(current, computed(() => open.value && tab.value === 'agent'));
const networkPath = computed(() => networkPathOf(current.value.parent_id, store.devices));
const name = computed(() => deviceLabel(current.value));
const role = computed(() => deviceRoleOf(current.value));

const tabs = computed(() => {
  const ifaceCount = current.value.interfaces?.length ?? 0;
  return [
    { value: 'settings', label: t('editor.tabs.general'), icon: Settings2 },
    { value: 'services', label: t('editor.tabs.services'), icon: Waypoints, badge: current.value.services.length || undefined },
    { value: 'interfaces', label: t('editor.tabs.interfaces'), icon: Network, badge: ifaceCount ? ifaceCount + 1 : undefined },
    { value: 'history', label: t('editor.tabs.history'), icon: History },
    { value: 'agent', label: t('editor.tabs.agent'), icon: Server },
  ];
});

function onTabKeydown(e: KeyboardEvent) {
  if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
  e.preventDefault();
  const idx = tabs.value.findIndex((t) => t.value === tab.value);
  const next = e.key === 'ArrowRight' ? (idx + 1) % tabs.value.length : (idx - 1 + tabs.value.length) % tabs.value.length;
  tab.value = tabs.value[next].value as EditorTab;
}

function onInterfaces(list: DeviceInterface[]) {
  current.value = { ...current.value, interfaces: list };
}

async function ackIpChange() {
  await api.updateDevice(current.value.id, { old_ip: null, ip_changed_at: null }).catch(() => {});
  current.value = { ...current.value, old_ip: null, ip_changed_at: null };
  emit('saved');
}

async function refreshInfo() {
  refreshing.value = true;
  showToast('info', t('dashboard.refreshing'), t('notifications.refreshing_details', { ip: current.value.ip }));
  try {
    const updated = await api.refreshDeviceInfo(current.value.id);
    const previousIp = current.value.ip;
    current.value = updated;
    form.value = {
      ...form.value,
      vendor: updated.vendor || '',
      display_name: form.value.display_name === previousIp && updated.hostname ? updated.hostname.split('.')[0] : form.value.display_name,
    };
    showToast('success', t('notifications.info_updated'), t('notifications.info_updated_text', { ip: previousIp }));
    emit('saved');
  } catch (err) {
    showToast('error', t('common.error'), t('notifications.refresh_failed', { error: (err as Error).message || t('common.unknown') }));
  } finally {
    refreshing.value = false;
  }
}

async function scanServices() {
  scanningServices.value = true;
  showToast('info', t('network.nmap_scan'), t('notifications.nmap_scan_started', { ip: current.value.ip }));
  try {
    current.value = await api.refreshServices(current.value.id);
    showToast('success', t('network.nmap_scan'), t('notifications.nmap_scan_finished', { ip: current.value.ip }));
    emit('saved');
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message || t('common.unknown'));
  } finally {
    scanningServices.value = false;
  }
}

async function save() {
  saving.value = true;
  const placement = computeGroupPlacement(form.value, current.value, store.devices);
  const data = placement ? { ...form.value, ...placement } : { ...form.value };
  if (current.value.old_ip) {
    (data as Record<string, unknown>).old_ip = null;
    (data as Record<string, unknown>).ip_changed_at = null;
  }
  try {
    // Services edited but not yet blurred are saved first
    await Promise.all(syncModifiedServices(original.value, current.value).filter(Boolean));
    await api.updateDevice(current.value.id, data);
    showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
    emit('saved');
    open.value = false;
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  const ok = await confirm({ title: t('common.delete'), message: t('editor.delete_device_confirm'), danger: true, confirmLabel: t('common.delete') });
  if (!ok) return;
  try {
    await api.deleteDevice(current.value.id);
    showToast('success', t('common.success'), t('notifications.deleted'));
    emit('saved');
    open.value = false;
  } catch {
    showToast('error', t('common.error'), t('notifications.delete_failed'));
  }
}
</script>

<template>
  <Sheet v-model:open="open" :title="name" :description="`${current.ip}${role ? ` · ${role}` : ''}`" :width="tab === 'agent' ? 'xl' : 'lg'">
    <template #icon>
      <StatusDot class="mt-2" :state="current.is_online ? 'online' : 'offline'" :label="current.is_online ? t('network.online') : t('network.offline')" />
    </template>
    <template #meta>
      <nav v-if="networkPath.length > 0" :aria-label="t('editor.network_path')" class="mt-1.5 flex flex-wrap items-center gap-1 text-xs text-fg-subtle">
        <template v-for="node in networkPath" :key="node.id">
          <span>{{ deviceLabel(node) }}</span><span aria-hidden="true">›</span>
        </template>
        <span class="text-fg-muted">{{ name }}</span>
      </nav>
    </template>

    <template #tabs>
      <nav
        class="flex shrink-0 gap-1 overflow-x-auto overflow-y-hidden border-b border-line bg-surface px-4 [scrollbar-width:none]"
        :aria-label="t('editor.title_edit')"
        @keydown="onTabKeydown"
      >
        <button
          v-for="item in tabs"
          :key="item.value"
          type="button"
          class="relative inline-flex h-10 shrink-0 items-center gap-1.5 px-2.5 text-sm font-medium transition-colors disabled:opacity-40 [&_svg]:size-4"
          :class="tab === item.value ? 'text-fg after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-accent' : 'text-fg-muted hover:text-fg'"
          @click="tab = item.value as EditorTab"
        >
          <component :is="item.icon" v-if="item.icon" aria-hidden="true" />
          {{ item.label }}
          <span v-if="item.badge !== undefined" class="rounded-sm bg-raised px-1 font-mono text-micro text-fg-subtle">{{ item.badge }}</span>
        </button>
      </nav>
    </template>

    <div v-if="current.old_ip" class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-info/40 bg-info/10 px-3.5 py-2.5 text-xs text-fg">
      <div class="flex items-center gap-2">
        <ArrowRight class="size-4 shrink-0 text-info-text" aria-hidden="true" />
        <span>{{ t('gv.notices.ip_changed', { name }) }}: <strong class="font-mono">{{ current.old_ip }}</strong> → <strong class="font-mono">{{ current.ip }}</strong></span>
      </div>
      <Button size="sm" variant="ghost" @click="ackIpChange">{{ t('dashboard.ip_changed_ack') }}</Button>
    </div>

    <div class="py-1">
      <SettingsTab v-if="tab === 'settings'" v-model:form="form" :device="current" :devices="store.devices" :groups="groups" :racks="racks" :refreshing="refreshing" @refresh-info="refreshInfo" @submit="save" />
      <ServicesTab v-else-if="tab === 'services'" v-model:device="current" :scanning="scanningServices" @changed="emit('saved')" @scan="scanServices" />
      <InterfacesTab v-else-if="tab === 'interfaces'" :device="current" @changed="emit('saved')" @merged-away="open = false" @interfaces="onInterfaces" />
      <HistoryTab v-else-if="tab === 'history'" :device-id="current.id" :active="tab === 'history'" />
      <AgentTab v-else-if="tab === 'agent'" :device-id="current.id" :panel="agentPanel" />
    </div>

    <template #footer>
      <Button variant="danger-ghost" class="mr-auto" @click="remove"><Trash2 aria-hidden="true" />{{ t('common.delete') }}</Button>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :loading="saving" @click="save"><Save v-if="!saving" aria-hidden="true" />{{ t('common.save') }}</Button>
    </template>
  </Sheet>
</template>
