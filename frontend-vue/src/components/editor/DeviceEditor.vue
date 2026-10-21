<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { History, Network, Save, Server, Settings2, Trash2, Waypoints } from 'lucide-vue-next';
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
} from '@shared/components/Dashboard/editor/deviceForm';
import Sheet from '@/components/ui/Sheet.vue';
import Tabs from '@/components/ui/Tabs.vue';
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

function onInterfaces(list: DeviceInterface[]) {
  current.value = { ...current.value, interfaces: list };
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

    <div class="-mx-5 -mt-4 flex min-h-full flex-col">
      <Tabs v-model="tab" :tabs="tabs" :label="t('editor.title_edit')" list-class="px-4 sticky top-0 z-10 bg-surface">
        <template #settings>
          <div class="px-5 py-5">
            <SettingsTab v-model:form="form" :device="current" :devices="store.devices" :groups="groups" :racks="racks" :refreshing="refreshing" @refresh-info="refreshInfo" @submit="save" />
          </div>
        </template>
        <template #services>
          <div class="px-5 py-5"><ServicesTab v-model:device="current" :scanning="scanningServices" @changed="emit('saved')" @scan="scanServices" /></div>
        </template>
        <template #interfaces>
          <div class="px-5 py-5"><InterfacesTab :device="current" @changed="emit('saved')" @merged-away="open = false" @interfaces="onInterfaces" /></div>
        </template>
        <template #history>
          <div class="px-5 py-5"><HistoryTab :device-id="current.id" :active="tab === 'history'" /></div>
        </template>
        <template #agent>
          <div class="px-5 py-5"><AgentTab :device-id="current.id" :panel="agentPanel" /></div>
        </template>
      </Tabs>
    </div>

    <template #footer>
      <Button variant="danger-ghost" class="mr-auto" @click="remove"><Trash2 aria-hidden="true" />{{ t('common.delete') }}</Button>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :loading="saving" @click="save"><Save v-if="!saving" aria-hidden="true" />{{ t('common.save') }}</Button>
    </template>
  </Sheet>
</template>
