<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  Activity,
  Box,
  Check,
  Copy,
  Cpu,
  HardDrive,
  Layers,
  Monitor,
  MoreHorizontal,
  RefreshCw,
  Router,
  Server,
  Shield,
  Smartphone,
  Star,
  Wifi,
} from 'lucide-vue-next';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import RelativeTime from '@/components/8starlabs-ui/RelativeTime.vue';
import DeviceMetricsBar from '@/components/dashboard/DeviceMetricsBar.vue';
import NetworkChips from '@/components/dashboard/NetworkChips.vue';
import ServiceBadge from '@/components/dashboard/ServiceBadge.vue';
import type { Device, Subnet } from '@/types';

const props = defineProps<{
  device: Device;
  allDevices: Device[];
  subnets: Subnet[];
  editMode?: boolean;
  selected?: boolean;
  compact?: boolean;
}>();

const emit = defineEmits<{
  (e: 'open', device: Device): void;
  (e: 'togglePin', device: Device): void;
  (e: 'toggleSelect', deviceId: number): void;
  (e: 'rescan', device: Device): void;
  (e: 'adoptAgent', device: Device): void;
}>();

const copiedIp = ref(false);
const rescanning = ref(false);
const adopting = ref(false);

const deviceIconComponent = computed(() => {
  switch ((props.device.icon || 'server').toLowerCase()) {
    case 'router':
      return Router;
    case 'monitor':
    case 'pc':
    case 'desktop':
      return Monitor;
    case 'nas':
    case 'storage':
    case 'hard-drive':
      return HardDrive;
    case 'cpu':
    case 'iot':
    case 'raspberry':
      return Cpu;
    case 'shield':
    case 'firewall':
      return Shield;
    case 'phone':
    case 'mobile':
      return Smartphone;
    case 'wifi':
    case 'ap':
      return Wifi;
    case 'docker':
    case 'container':
      return Box;
    default:
      return Server;
  }
});

const parentHost = computed(() => {
  if (!props.device.parent_id) return null;
  return props.allDevices.find((d) => d.id === props.device.parent_id) || null;
});

const roleBadge = computed(() => {
  const role = props.device.virtual_type || props.device.device_role || (props.device.is_host ? 'host' : null);
  if (!role || role === 'standalone') return null;
  const map: Record<string, { label: string; cls: string }> = {
    docker: { label: 'Docker', cls: 'bg-sky-500/12 text-sky-400 border-sky-500/25' },
    vm: { label: 'VM', cls: 'bg-amber-500/12 text-amber-400 border-amber-500/25' },
    lxc: { label: 'LXC', cls: 'bg-teal-500/12 text-teal-400 border-teal-500/25' },
    host: { label: 'Hypervisor', cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25' },
  };
  return map[role] || { label: role.toUpperCase(), cls: 'bg-zinc-800 text-zinc-300 border-zinc-700' };
});

function copyIp(e: MouseEvent) {
  e.stopPropagation();
  navigator.clipboard?.writeText(props.device.ip).then(() => {
    copiedIp.value = true;
    setTimeout(() => {
      copiedIp.value = false;
    }, 1800);
  });
}

async function handleRescan(e: MouseEvent) {
  e.stopPropagation();
  if (rescanning.value) return;
  rescanning.value = true;
  emit('rescan', props.device);
  setTimeout(() => {
    rescanning.value = false;
  }, 1500);
}

async function handleAdopt(e: MouseEvent) {
  e.stopPropagation();
  if (adopting.value) return;
  adopting.value = true;
  emit('adoptAgent', props.device);
  setTimeout(() => {
    adopting.value = false;
  }, 1500);
}

function handleCardClick() {
  if (props.editMode) {
    emit('toggleSelect', props.device.id);
  } else {
    emit('open', props.device);
  }
}
</script>

<template>
  <article
    :class="[
      'sh-card-interactive p-4 flex flex-col gap-3 cursor-pointer relative group select-none',
      !device.is_online && 'opacity-75 hover:opacity-100',
      selected && 'ring-2 ring-emerald-500 border-emerald-500/60 bg-emerald-950/10',
    ]"
    @click="handleCardClick"
  >
    <!-- Top Row: Icon + Name + Role/Host Badges + Quick Actions -->
    <div class="flex items-start justify-between gap-2.5">
      <div class="flex items-center gap-3 min-w-0">
        <!-- Selection Checkbox in Edit Mode OR Device Icon Box -->
        <div
          v-if="editMode"
          :class="[
            'w-10 h-10 rounded-xl border flex items-center justify-center shrink-0 transition-colors',
            selected
              ? 'bg-emerald-500 border-emerald-400 text-zinc-950'
              : 'bg-[#1b1b20] border-zinc-700 text-zinc-400',
          ]"
        >
          <Check v-if="selected" class="w-5 h-5 stroke-[2.5]" />
          <div v-else class="w-4 h-4 rounded border border-zinc-600" />
        </div>

        <div
          v-else
          :class="[
            'w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border transition-colors relative',
            device.is_online
              ? 'bg-[#1b1b20] border-zinc-800 text-emerald-400 group-hover:border-emerald-500/40'
              : 'bg-[#16161a] border-zinc-800/70 text-zinc-500',
          ]"
        >
          <component :is="deviceIconComponent" class="w-4.5 h-4.5" />
          <div class="absolute -bottom-1 -right-1 bg-[#131316] p-0.5 rounded-full">
            <StatusIndicator :state="device.is_online ? 'active' : 'down'" size="sm" />
          </div>
        </div>

        <div class="min-w-0">
          <div class="flex items-center gap-1.5 flex-wrap">
            <h3 class="text-sm font-semibold text-zinc-100 truncate max-w-[165px] group-hover:text-white transition-colors">
              {{ device.display_name || device.name || device.hostname || device.ip }}
            </h3>
            <span
              v-if="roleBadge"
              :class="['px-1.5 py-0.2 rounded-md text-[10px] font-semibold border leading-tight', roleBadge.cls]"
            >
              {{ roleBadge.label }}
            </span>
            <span
              v-if="device.has_agent"
              title="Live Agent Connected"
              class="inline-flex items-center gap-1 px-1.5 py-0.2 rounded-md text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
            >
              <Activity class="w-2.5 h-2.5" />
              Agent
            </span>
          </div>

          <!-- IP + Copy + Network Chips Row -->
          <div class="flex items-center gap-1.5 mt-1 flex-wrap">
            <button
              type="button"
              title="Click to copy IP address"
              class="inline-flex items-center gap-1 font-mono text-xs text-zinc-400 hover:text-zinc-100 transition-colors cursor-pointer"
              @click="copyIp"
            >
              <span>{{ device.ip }}</span>
              <Check v-if="copiedIp" class="w-3 h-3 text-emerald-400" />
              <Copy v-else class="w-2.5 h-2.5 opacity-0 group-hover:opacity-70 transition-opacity" />
            </button>

            <span v-if="parentHost" class="inline-flex items-center gap-1 text-[10px] text-zinc-500">
              <Layers class="w-2.5 h-2.5 text-zinc-500" />
              on {{ parentHost.display_name || parentHost.name || parentHost.ip }}
            </span>
          </div>
        </div>
      </div>

      <!-- Right Action Buttons -->
      <div class="flex items-center gap-1 shrink-0">
        <button
          type="button"
          :title="device.is_pinned ? 'Unpin device' : 'Pin to top'"
          :class="[
            'p-1.5 rounded-lg transition-all cursor-pointer',
            device.is_pinned
              ? 'text-amber-400 bg-amber-500/10 border border-amber-500/20'
              : 'text-zinc-500 opacity-0 group-hover:opacity-100 hover:text-zinc-200 hover:bg-zinc-800/70',
          ]"
          @click.stop="emit('togglePin', device)"
        >
          <Star class="w-3.5 h-3.5" :fill="device.is_pinned ? 'currentColor' : 'none'" />
        </button>

        <button
          type="button"
          title="Rescan device info & ports"
          class="p-1.5 rounded-lg text-zinc-500 opacity-0 group-hover:opacity-100 hover:text-zinc-200 hover:bg-zinc-800/70 transition-all cursor-pointer"
          @click="handleRescan"
        >
          <RefreshCw :class="['w-3.5 h-3.5', rescanning && 'animate-spin text-emerald-400']" />
        </button>

        <button
          type="button"
          title="Device settings & details"
          class="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800/70 transition-all cursor-pointer"
          @click.stop="emit('open', device)"
        >
          <MoreHorizontal class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Pending Agent Adoption Banner -->
    <div
      v-if="device.has_pending_token || device.agent_status === 'pending'"
      class="sh-subcard px-3 py-2 flex items-center justify-between gap-2 border-amber-500/30 bg-amber-500/10"
      @click.stop
    >
      <div class="flex items-center gap-2 text-xs text-amber-300 font-medium">
        <StatusIndicator state="fixing" size="sm" />
        <span>New Agent awaiting adoption</span>
      </div>
      <button
        type="button"
        class="px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs transition-colors cursor-pointer"
        @click="handleAdopt"
      >
        {{ adopting ? 'Adopting...' : 'Adopt' }}
      </button>
    </div>

    <!-- Live Agent Telemetry Sub-Card (Just like React DeviceMetrics + Shadcn Subcard) -->
    <DeviceMetricsBar v-if="device.has_agent && !compact" :device-id="device.id" />

    <!-- Multi-VLAN Network Chips & Vendor Info -->
    <div v-if="!compact" class="flex items-center justify-between gap-2 text-[11px] text-zinc-500">
      <div class="flex items-center gap-1.5 min-w-0 truncate">
        <NetworkChips :device="device" :subnets="subnets" />
        <span v-if="device.vendor || device.os_info" class="truncate text-zinc-500">
          {{ device.vendor || device.os_info }}
        </span>
        <span v-else-if="device.mac" class="font-mono text-[10px] text-zinc-600">
          {{ device.mac }}
        </span>
      </div>
      <RelativeTime v-if="device.last_seen" :date="device.last_seen" />
    </div>

    <!-- Interactive Service Badges Strip -->
    <div
      v-if="device.services && device.services.length > 0"
      class="flex flex-wrap items-center gap-1.5 pt-2 border-t border-zinc-800/70"
    >
      <ServiceBadge
        v-for="svc in device.services.slice(0, compact ? 3 : 6)"
        :key="svc.id || svc.port"
        :service="svc"
        :ip="device.ip"
      />
      <span
        v-if="device.services.length > (compact ? 3 : 6)"
        class="px-2 py-0.5 rounded-lg text-[10px] font-mono bg-[#1b1b20] border border-zinc-800 text-zinc-400"
      >
        +{{ device.services.length - (compact ? 3 : 6) }} more
      </span>
    </div>
  </article>
</template>
