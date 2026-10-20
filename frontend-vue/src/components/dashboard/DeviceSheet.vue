<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  Activity,
  Check,
  Copy,
  Globe,
  Layers,
  Plus,
  RefreshCw,
  Server,
  Settings2,
  Star,
  Terminal,
  Trash2,
  X,
} from 'lucide-vue-next';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import RelativeTime from '@/components/8starlabs-ui/RelativeTime.vue';
import DeviceMetricsBar from '@/components/dashboard/DeviceMetricsBar.vue';
import ServiceBadge from '@/components/dashboard/ServiceBadge.vue';
import { useNetworkStore } from '@/stores/network';
import { api } from '@/api/client';
import type { Device } from '@/types';

const props = defineProps<{
  device: Device | null;
  open: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'updated'): void;
}>();

const store = useNetworkStore();
const activeTab = ref<'general' | 'services' | 'agent' | 'interfaces'>('general');

// Form fields
const editName = ref('');
const editGroupId = ref<number | null>(null);
const editIcon = ref('server');
const editRole = ref<'standalone' | 'host' | 'vm' | 'lxc' | 'docker'>('standalone');
const editParentId = ref<number | null>(null);
const editNotes = ref('');
const isPinned = ref(false);
const saving = ref(false);
const refreshing = ref(false);

// Services form
const newSvcName = ref('');
const newSvcPort = ref<number | ''>('');
const newSvcProtocol = ref<'tcp' | 'udp'>('tcp');
const newSvcUrl = ref('');
const addingService = ref(false);

// Interfaces form
const newIfaceIp = ref('');
const newIfaceLabel = ref('');
const newIfaceVlan = ref<number | ''>('');

// Agent enrollment
const enrollCode = ref<string | null>(null);
const enrolling = ref(false);
const copiedCmd = ref(false);

const ICON_OPTIONS = [
  { id: 'server', label: 'Server' },
  { id: 'router', label: 'Router / Switch' },
  { id: 'monitor', label: 'Workstation / PC' },
  { id: 'nas', label: 'NAS / Storage' },
  { id: 'docker', label: 'Container / Docker' },
  { id: 'shield', label: 'Firewall / Security' },
  { id: 'cpu', label: 'Raspberry / IoT' },
  { id: 'wifi', label: 'Access Point' },
  { id: 'phone', label: 'Mobile' },
];

watch(
  () => props.device,
  (d) => {
    if (d) {
      editName.value = d.display_name || d.name || '';
      editGroupId.value = d.group_id ?? null;
      editIcon.value = d.icon || 'server';
      editRole.value = d.virtual_type || d.device_role || (d.is_host ? 'host' : 'standalone');
      editParentId.value = d.parent_id ?? null;
      editNotes.value = d.notes || '';
      isPinned.value = Boolean(d.is_pinned);
      enrollCode.value = null;
    }
  },
  { immediate: true }
);

const potentialParents = computed(() =>
  store.devices.filter((d) => d.id !== props.device?.id && (d.device_role === 'host' || !d.parent_id))
);

const agentInstallCommand = computed(() => {
  if (!enrollCode.value) return '';
  const origin = window.location.origin;
  return `curl -fsSL ${origin}/api/agent/install.sh | sudo bash -s -- --url ${origin} --code ${enrollCode.value}`;
});

async function saveGeneral() {
  if (!props.device) return;
  saving.value = true;
  try {
    await store.updateDevice(props.device.id, {
      display_name: editName.value,
      group_id: editGroupId.value,
      icon: editIcon.value,
      virtual_type: editRole.value === 'docker' || editRole.value === 'vm' || editRole.value === 'lxc' ? editRole.value : null,
      is_host: editRole.value === 'host',
      parent_id: editParentId.value,
      notes: editNotes.value,
      is_pinned: isPinned.value,
    });
    emit('updated');
    emit('close');
  } finally {
    saving.value = false;
  }
}

async function handleRefreshHost() {
  if (!props.device) return;
  refreshing.value = true;
  try {
    await api.refreshDeviceInfo(props.device.id);
    await api.refreshServices(props.device.id);
    await store.fetchDashboardData();
    emit('updated');
  } finally {
    refreshing.value = false;
  }
}

async function handleAddService() {
  if (!props.device || !newSvcName.value || !newSvcPort.value) return;
  addingService.value = true;
  try {
    await api.addService(props.device.id, {
      name: newSvcName.value,
      port: Number(newSvcPort.value),
      protocol: newSvcProtocol.value,
      url: newSvcUrl.value || undefined,
    });
    newSvcName.value = '';
    newSvcPort.value = '';
    newSvcUrl.value = '';
    await store.fetchDashboardData();
    emit('updated');
  } finally {
    addingService.value = false;
  }
}

async function handleDeleteService(serviceId: number) {
  await api.deleteService(serviceId);
  await store.fetchDashboardData();
  emit('updated');
}

async function handleAddInterface() {
  if (!props.device || !newIfaceIp.value.trim()) return;
  await api.addDeviceInterface(props.device.id, {
    ip: newIfaceIp.value.trim(),
    label: newIfaceLabel.value.trim() || null,
    vlan_id: newIfaceVlan.value !== '' ? Number(newIfaceVlan.value) : null,
  });
  newIfaceIp.value = '';
  newIfaceLabel.value = '';
  newIfaceVlan.value = '';
  await store.fetchDashboardData();
  emit('updated');
}

async function handleRemoveInterface(ifaceId: number) {
  if (!props.device) return;
  await api.removeDeviceInterface(props.device.id, ifaceId);
  await store.fetchDashboardData();
  emit('updated');
}

async function generateEnrollmentCode() {
  if (!props.device) return;
  enrolling.value = true;
  try {
    const res = await api.createAgentEnrollment(props.device.id);
    enrollCode.value = res.code;
  } finally {
    enrolling.value = false;
  }
}

function copyInstallCommand() {
  if (!agentInstallCommand.value) return;
  navigator.clipboard?.writeText(agentInstallCommand.value).then(() => {
    copiedCmd.value = true;
    setTimeout(() => {
      copiedCmd.value = false;
    }, 2000);
  });
}

async function handleDeleteDevice() {
  if (!props.device) return;
  if (!confirm(`Delete device "${props.device.name || props.device.ip}"?`)) return;
  await store.deleteDevice(props.device.id);
  emit('close');
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open && device" class="fixed inset-0 z-50 flex justify-end">
      <div class="fixed inset-0 bg-black/75 backdrop-blur-xs transition-opacity" @click="emit('close')" />

      <aside class="relative z-10 w-full max-w-xl bg-[#111114] border-l border-zinc-800/90 h-full flex flex-col shadow-2xl">
        <!-- Header -->
        <div class="p-5 border-b border-zinc-800/80 flex items-center justify-between gap-3">
          <div class="flex items-center gap-3.5 min-w-0">
            <div class="w-11 h-11 rounded-xl bg-[#1b1b20] border border-zinc-800 flex items-center justify-center relative shrink-0">
              <Server class="w-5 h-5 text-emerald-400" />
              <div class="absolute -bottom-1 -right-1 bg-[#111114] p-0.5 rounded-full">
                <StatusIndicator :state="device.is_online ? 'active' : 'down'" size="sm" />
              </div>
            </div>
            <div class="min-w-0">
              <h3 class="text-base font-bold text-zinc-100 truncate">
                {{ device.display_name || device.name || device.hostname || device.ip }}
              </h3>
              <div class="flex items-center gap-2 text-xs text-zinc-400 font-mono mt-0.5">
                <span>{{ device.ip }}</span>
                <span v-if="device.mac" class="text-zinc-600">· {{ device.mac }}</span>
                <RelativeTime v-if="device.last_seen" :date="device.last_seen" />
              </div>
            </div>
          </div>

          <div class="flex items-center gap-1.5">
            <button
              type="button"
              title="Rescan device & services"
              class="sh-pill-btn px-2.5 py-1.5 text-xs inline-flex items-center gap-1.5 cursor-pointer"
              :disabled="refreshing"
              @click="handleRefreshHost"
            >
              <RefreshCw :class="['w-3.5 h-3.5', refreshing && 'animate-spin text-emerald-400']" />
              <span>Rescan</span>
            </button>
            <button
              type="button"
              class="p-2 rounded-xl text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/70 transition-colors cursor-pointer"
              @click="emit('close')"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>

        <!-- Segmented Tab Bar (Shadcn Style) -->
        <div class="px-5 pt-3 border-b border-zinc-800/80 flex items-center gap-1 bg-[#131316]">
          <button
            v-for="tab in [
              { id: 'general', label: 'Settings', icon: Settings2 },
              { id: 'services', label: `Services (${device.services?.length || 0})`, icon: Globe },
              { id: 'agent', label: 'Agent & Telemetry', icon: Activity },
              { id: 'interfaces', label: `Interfaces (${(device.interfaces?.length || 0) + 1})`, icon: Layers },
            ] as const"
            :key="tab.id"
            type="button"
            :class="[
              'flex items-center gap-1.5 px-3 py-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer -mb-px',
              activeTab === tab.id
                ? 'border-emerald-500 text-zinc-100'
                : 'border-transparent text-zinc-500 hover:text-zinc-300',
            ]"
            @click="activeTab = tab.id"
          >
            <component :is="tab.icon" class="w-3.5 h-3.5" />
            <span>{{ tab.label }}</span>
          </button>
        </div>

        <!-- Tab Body -->
        <div class="p-5 flex-1 overflow-y-auto space-y-5">
          <!-- TAB 1: GENERAL SETTINGS -->
          <template v-if="activeTab === 'general'">
            <!-- Hardware Summary Nested Subcards -->
            <div class="grid grid-cols-2 gap-3">
              <div class="sh-subcard p-3">
                <div class="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Vendor / Hardware</div>
                <div class="text-xs font-medium text-zinc-200 mt-1 truncate">
                  {{ device.vendor || 'Unknown Vendor' }}
                </div>
              </div>
              <div class="sh-subcard p-3">
                <div class="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">OS / Fingerprint</div>
                <div class="text-xs font-medium text-zinc-200 mt-1 truncate">
                  {{ device.os_info || device.hostname || 'Generic Host' }}
                </div>
              </div>
            </div>

            <div class="space-y-4">
              <div>
                <label class="block text-xs font-medium text-zinc-400 mb-1.5">Display Name</label>
                <input
                  v-model="editName"
                  type="text"
                  placeholder="e.g. proxmox-ve-01"
                  class="w-full h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-sm text-zinc-100 focus:outline-none focus:border-emerald-500/60"
                />
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs font-medium text-zinc-400 mb-1.5">Group Assignment</label>
                  <select
                    v-model="editGroupId"
                    class="w-full h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-100 focus:outline-none focus:border-emerald-500/60"
                  >
                    <option :value="null">Unassigned</option>
                    <option v-for="g in store.groups" :key="g.id" :value="g.id">{{ g.name }}</option>
                  </select>
                </div>

                <div>
                  <label class="block text-xs font-medium text-zinc-400 mb-1.5">Device Icon</label>
                  <select
                    v-model="editIcon"
                    class="w-full h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-100 focus:outline-none focus:border-emerald-500/60"
                  >
                    <option v-for="ico in ICON_OPTIONS" :key="ico.id" :value="ico.id">{{ ico.label }}</option>
                  </select>
                </div>
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs font-medium text-zinc-400 mb-1.5">Architecture Role</label>
                  <select
                    v-model="editRole"
                    class="w-full h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-100 focus:outline-none focus:border-emerald-500/60"
                  >
                    <option value="standalone">Standalone Hardware</option>
                    <option value="host">Hypervisor / Docker Host</option>
                    <option value="vm">Virtual Machine (VM)</option>
                    <option value="lxc">LXC Container</option>
                    <option value="docker">Docker Container</option>
                  </select>
                </div>

                <div>
                  <label class="block text-xs font-medium text-zinc-400 mb-1.5">Parent Host</label>
                  <select
                    v-model="editParentId"
                    class="w-full h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-100 focus:outline-none focus:border-emerald-500/60"
                  >
                    <option :value="null">None (Top-Level)</option>
                    <option v-for="p in potentialParents" :key="p.id" :value="p.id">
                      {{ p.name || p.ip }} ({{ p.ip }})
                    </option>
                  </select>
                </div>
              </div>

              <label class="sh-subcard p-3 flex items-center justify-between cursor-pointer">
                <div class="flex items-center gap-2.5">
                  <Star class="w-4 h-4 text-amber-400" :fill="isPinned ? 'currentColor' : 'none'" />
                  <div>
                    <div class="text-xs font-semibold text-zinc-200">Pin to Priority Bar</div>
                    <div class="text-[11px] text-zinc-500">Always keep this device highlighted at the top of its group</div>
                  </div>
                </div>
                <input v-model="isPinned" type="checkbox" class="accent-emerald-500 w-4 h-4" />
              </label>

              <div>
                <label class="block text-xs font-medium text-zinc-400 mb-1.5">Operator Notes</label>
                <textarea
                  v-model="editNotes"
                  rows="3"
                  placeholder="Rack slot, credentials hint, VLAN notes..."
                  class="w-full rounded-xl bg-[#1b1b20] border border-zinc-800 p-3 text-xs text-zinc-100 focus:outline-none focus:border-emerald-500/60"
                />
              </div>
            </div>
          </template>

          <!-- TAB 2: SERVICES -->
          <template v-else-if="activeTab === 'services'">
            <div class="sh-subcard p-3.5 space-y-3">
              <div class="text-xs font-semibold text-zinc-200">Add Custom Service / Port</div>
              <div class="grid grid-cols-3 gap-2">
                <input
                  v-model="newSvcName"
                  placeholder="Name (e.g. WebUI)"
                  class="h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs text-zinc-100"
                />
                <input
                  v-model="newSvcPort"
                  type="number"
                  placeholder="Port (e.g. 8080)"
                  class="h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs font-mono text-zinc-100"
                />
                <select
                  v-model="newSvcProtocol"
                  class="h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs text-zinc-100"
                >
                  <option value="tcp">TCP</option>
                  <option value="udp">UDP</option>
                </select>
              </div>
              <div class="flex gap-2">
                <input
                  v-model="newSvcUrl"
                  placeholder="Optional custom URL (e.g. https://proxmox.local:8006)"
                  class="flex-1 h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs text-zinc-100"
                />
                <button
                  type="button"
                  class="px-3 h-8 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs inline-flex items-center gap-1 cursor-pointer"
                  :disabled="addingService"
                  @click="handleAddService"
                >
                  <Plus class="w-3.5 h-3.5" />
                  Add
                </button>
              </div>
            </div>

            <div class="space-y-2">
              <div class="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                Discovered & Configured Services ({{ device.services?.length || 0 }})
              </div>
              <div v-if="!device.services?.length" class="sh-subcard p-6 text-center text-xs text-zinc-500">
                No open ports detected yet. Click "Rescan" above or add a port manually.
              </div>
              <div
                v-for="svc in device.services"
                :key="svc.id"
                class="sh-subcard p-3 flex items-center justify-between gap-3"
              >
                <div class="flex items-center gap-2.5 min-w-0">
                  <ServiceBadge :service="svc" :ip="device.ip" />
                  <span class="text-[11px] font-mono text-zinc-500 uppercase">{{ svc.protocol }}</span>
                </div>
                <button
                  type="button"
                  class="p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer"
                  @click="handleDeleteService(svc.id)"
                >
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </template>

          <!-- TAB 3: AGENT & TELEMETRY -->
          <template v-else-if="activeTab === 'agent'">
            <div v-if="device.has_agent" class="space-y-4">
              <div class="sh-subcard p-3.5 flex items-center justify-between">
                <div class="flex items-center gap-2.5">
                  <StatusIndicator state="active" size="md" />
                  <div>
                    <div class="text-xs font-semibold text-zinc-100">GravityLAN Telemetry Agent Connected</div>
                    <div class="text-[11px] text-zinc-400">Streaming live WebSocket metrics</div>
                  </div>
                </div>
                <span class="px-2 py-0.5 rounded-md text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  ACTIVE
                </span>
              </div>

              <DeviceMetricsBar :device-id="device.id" />
            </div>

            <div class="sh-subcard p-4 space-y-3">
              <div class="flex items-center justify-between">
                <div>
                  <h4 class="text-xs font-semibold text-zinc-100">One-Liner Linux Agent Enrollment</h4>
                  <p class="text-[11px] text-zinc-400 mt-0.5">
                    Generate a temporary enrollment code to install or re-enroll the telemetry agent on this Linux host.
                  </p>
                </div>
                <button
                  type="button"
                  class="sh-pill-btn px-3 py-1.5 text-xs font-semibold cursor-pointer shrink-0"
                  :disabled="enrolling"
                  @click="generateEnrollmentCode"
                >
                  <Terminal class="w-3.5 h-3.5 inline mr-1" />
                  {{ enrolling ? 'Generating...' : 'Generate Code' }}
                </button>
              </div>

              <div v-if="enrollCode" class="space-y-2 pt-2 border-t border-zinc-800">
                <div class="flex items-center justify-between text-[11px] text-zinc-400">
                  <span>Run this on <strong class="text-zinc-200">{{ device.ip }}</strong>:</span>
                  <button
                    type="button"
                    class="inline-flex items-center gap-1 text-emerald-400 hover:underline cursor-pointer"
                    @click="copyInstallCommand"
                  >
                    <Check v-if="copiedCmd" class="w-3 h-3" />
                    <Copy v-else class="w-3 h-3" />
                    {{ copiedCmd ? 'Copied!' : 'Copy command' }}
                  </button>
                </div>
                <pre class="p-3 rounded-xl bg-[#0d0d10] border border-zinc-800 text-[11px] font-mono text-emerald-300 overflow-x-auto whitespace-pre-wrap break-all">{{ agentInstallCommand }}</pre>
              </div>
            </div>
          </template>

          <!-- TAB 4: NETWORK INTERFACES -->
          <template v-else-if="activeTab === 'interfaces'">
            <div class="space-y-2">
              <div class="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Primary Address</div>
              <div class="sh-subcard p-3 flex items-center justify-between">
                <div>
                  <div class="font-mono text-xs font-semibold text-zinc-100">{{ device.ip }}</div>
                  <div class="text-[11px] text-zinc-500 font-mono">{{ device.mac || 'No MAC recorded' }}</div>
                </div>
                <span class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  Primary
                </span>
              </div>
            </div>

            <div class="space-y-2">
              <div class="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                Additional VLAN / Multi-Homed Interfaces ({{ device.interfaces?.length || 0 }})
              </div>
              <div
                v-for="iface in device.interfaces || []"
                :key="iface.id"
                class="sh-subcard p-3 flex items-center justify-between"
              >
                <div>
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-xs font-semibold text-zinc-100">{{ iface.ip }}</span>
                    <span v-if="iface.label" class="text-xs text-zinc-400">({{ iface.label }})</span>
                    <span
                      v-if="iface.vlan_id != null"
                      class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-sky-500/10 text-sky-400 border border-sky-500/20"
                    >
                      VLAN {{ iface.vlan_id }}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  class="p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 cursor-pointer"
                  @click="handleRemoveInterface(iface.id)"
                >
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <div class="sh-subcard p-3.5 space-y-2.5">
              <div class="text-xs font-semibold text-zinc-200">Attach Secondary IP / VLAN Interface</div>
              <div class="grid grid-cols-3 gap-2">
                <input
                  v-model="newIfaceIp"
                  placeholder="IP (e.g. 10.0.20.5)"
                  class="h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs font-mono text-zinc-100"
                />
                <input
                  v-model="newIfaceLabel"
                  placeholder="Label (e.g. eth1)"
                  class="h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs text-zinc-100"
                />
                <input
                  v-model="newIfaceVlan"
                  type="number"
                  placeholder="VLAN ID"
                  class="h-8 rounded-lg bg-[#131316] border border-zinc-800 px-2.5 text-xs font-mono text-zinc-100"
                />
              </div>
              <button
                type="button"
                class="w-full h-8 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-zinc-100 cursor-pointer"
                @click="handleAddInterface"
              >
                + Attach Interface
              </button>
            </div>
          </template>
        </div>

        <!-- Footer -->
        <div class="p-4 border-t border-zinc-800/80 bg-[#131316] flex items-center justify-between gap-2">
          <button
            type="button"
            class="px-3 py-2 rounded-xl text-xs font-semibold text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 inline-flex items-center gap-1.5 cursor-pointer"
            @click="handleDeleteDevice"
          >
            <Trash2 class="w-3.5 h-3.5" />
            Delete Host
          </button>

          <div class="flex items-center gap-2">
            <button
              type="button"
              class="sh-pill-btn px-3.5 py-2 text-xs font-semibold cursor-pointer"
              @click="emit('close')"
            >
              Cancel
            </button>
            <button
              v-if="activeTab === 'general'"
              type="button"
              class="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs transition-colors cursor-pointer"
              :disabled="saving"
              @click="saveGeneral"
            >
              {{ saving ? 'Saving...' : 'Save Changes' }}
            </button>
          </div>
        </div>
      </aside>
    </div>
  </Teleport>
</template>
