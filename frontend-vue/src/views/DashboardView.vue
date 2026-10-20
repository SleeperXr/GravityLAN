<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  Server,
  Wifi,
  Cpu,
  Network,
  Search,
  LayoutList,
  LayoutGrid,
  ExternalLink,
  SlidersHorizontal,
} from 'lucide-vue-next';
import { useNetworkStore } from '@/stores/network';
import { useI18n } from '@/composables/useI18n';
import type { Device } from '@/types';
import Card from '@/components/ui/card/Card.vue';
import Badge from '@/components/ui/badge/Badge.vue';
import Button from '@/components/ui/button/Button.vue';
import Input from '@/components/ui/input/Input.vue';
import DeviceSheet from '@/components/dashboard/DeviceSheet.vue';

const store = useNetworkStore();
const { t } = useI18n();

const searchQuery = ref('');
const selectedGroup = ref<number | 'all'>('all');
const statusFilter = ref<'all' | 'online' | 'offline'>('all');
const viewMode = ref<'table' | 'cards'>('table');
const activeDevice = ref<Device | null>(null);
const sheetOpen = ref(false);

const groupNameMap = computed(() => {
  const map = new Map<number, string>();
  for (const g of store.groups) {
    map.set(g.id, g.name);
  }
  return map;
});

const filteredDevices = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  return store.devices.filter((d) => {
    if (d.is_hidden) return false;
    if (selectedGroup.value !== 'all' && d.group_id !== selectedGroup.value) return false;
    if (statusFilter.value === 'online' && !d.is_online) return false;
    if (statusFilter.value === 'offline' && d.is_online) return false;
    if (!q) return true;
    const grp = d.group_id ? (groupNameMap.value.get(d.group_id) ?? '') : '';
    return (
      d.display_name.toLowerCase().includes(q) ||
      d.ip.toLowerCase().includes(q) ||
      (d.mac && d.mac.toLowerCase().includes(q)) ||
      (d.hostname && d.hostname.toLowerCase().includes(q)) ||
      (d.vendor && d.vendor.toLowerCase().includes(q)) ||
      grp.toLowerCase().includes(q)
    );
  });
});

function openDeviceDetail(device: Device) {
  activeDevice.value = device;
  sheetOpen.value = true;
}
</script>

<template>
  <div class="space-y-6">
    <!-- Top Standard KPI Cards -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>{{ t('kpi.total_devices') }}</span>
          <Server class="h-4 w-4 text-[#3DB8F5]" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-2xl font-bold text-[#E6EAF0]">{{ store.devices.length }}</span>
          <span class="text-[11px] text-[#8390A0]">{{ store.groups.length }} Gruppen</span>
        </div>
      </Card>

      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>{{ t('kpi.online_status') }}</span>
          <Wifi class="h-4 w-4 text-[#4AC26B]" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-2xl font-bold text-[#4AC26B]">{{ store.onlineDevicesCount }}</span>
          <Badge :variant="store.offlineDevicesCount > 0 ? 'destructive' : 'secondary'" class="font-mono">
            {{ store.offlineDevicesCount }} Offline
          </Badge>
        </div>
      </Card>

      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>{{ t('kpi.active_agents') }}</span>
          <Cpu class="h-4 w-4 text-[#3DB8F5]" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-2xl font-bold text-[#E6EAF0]">{{ store.activeAgentsCount }}</span>
          <span class="text-[11px] text-[#8390A0]">Live-Telemetrie</span>
        </div>
      </Card>

      <Card class="p-4 space-y-2">
        <div class="flex items-center justify-between text-xs text-[#9AA5B4]">
          <span>{{ t('kpi.subnets_active') }}</span>
          <Network class="h-4 w-4 text-[#3DB8F5]" />
        </div>
        <div class="flex items-baseline justify-between">
          <span class="font-mono text-2xl font-bold text-[#E6EAF0]">{{ store.enabledSubnetsCount }}</span>
          <span class="text-[11px] text-[#8390A0]">von {{ store.subnets.length }} konfiguriert</span>
        </div>
      </Card>
    </div>

    <!-- Filter & View Toolbar -->
    <Card class="p-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="relative flex-1 min-w-[240px]">
          <Search class="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-[#8390A0]" />
          <Input
            v-model="searchQuery"
            :placeholder="t('dashboard.search')"
            class="pl-8"
          />
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <!-- Group Filter -->
          <select
            v-model="selectedGroup"
            class="h-8 rounded-md border border-[#2A3340] bg-[#0B0E13] px-2.5 text-xs text-[#E6EAF0] focus:border-[#3DB8F5] focus:outline-none"
          >
            <option value="all">{{ t('dashboard.all_groups') }}</option>
            <option v-for="grp in store.groups" :key="grp.id" :value="grp.id">
              {{ grp.name }} ({{ grp.device_count }})
            </option>
          </select>

          <!-- Status Filter -->
          <select
            v-model="statusFilter"
            class="h-8 rounded-md border border-[#2A3340] bg-[#0B0E13] px-2.5 text-xs text-[#E6EAF0] focus:border-[#3DB8F5] focus:outline-none"
          >
            <option value="all">{{ t('dashboard.status_all') }}</option>
            <option value="online">{{ t('dashboard.status_online') }}</option>
            <option value="offline">{{ t('dashboard.status_offline') }}</option>
          </select>

          <!-- View Switcher (Standard Table vs. Structured Cards) -->
          <div class="inline-flex rounded-md border border-[#2A3340] bg-[#0B0E13] p-0.5">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-xs px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer"
              :class="viewMode === 'table' ? 'bg-[#1F2732] text-[#E6EAF0]' : 'text-[#8390A0] hover:text-[#E6EAF0]'"
              @click="viewMode = 'table'"
            >
              <LayoutList class="h-3.5 w-3.5" />
              {{ t('dashboard.view_table') }}
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-xs px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer"
              :class="viewMode === 'cards' ? 'bg-[#1F2732] text-[#E6EAF0]' : 'text-[#8390A0] hover:text-[#E6EAF0]'"
              @click="viewMode = 'cards'"
            >
              <LayoutGrid class="h-3.5 w-3.5" />
              {{ t('dashboard.view_cards') }}
            </button>
          </div>
        </div>
      </div>
    </Card>

    <!-- Standard shadcn-vue Data Table View -->
    <Card v-if="viewMode === 'table'" class="overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-xs">
          <thead>
            <tr class="border-b border-[#1F2732] bg-[#12161C] text-[11px] font-medium uppercase tracking-wider text-[#8390A0]">
              <th class="px-4 py-3">{{ t('table.device') }}</th>
              <th class="px-4 py-3">{{ t('table.ip_mac') }}</th>
              <th class="px-4 py-3">{{ t('table.group') }}</th>
              <th class="px-4 py-3">{{ t('table.status') }}</th>
              <th class="px-4 py-3">{{ t('table.services') }}</th>
              <th class="px-4 py-3">{{ t('table.agent') }}</th>
              <th class="px-4 py-3 text-right">{{ t('table.actions') }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[#1F2732]">
            <tr
              v-for="device in filteredDevices"
              :key="device.id"
              class="hover:bg-[#1F2732]/45 transition-colors cursor-pointer"
              @click="openDeviceDetail(device)"
            >
              <td class="px-4 py-3">
                <div class="font-medium text-[#E6EAF0]">{{ device.display_name }}</div>
                <div class="text-[11px] text-[#8390A0]">
                  {{ device.vendor || device.hostname || device.device_type }}
                </div>
              </td>

              <td class="px-4 py-3 font-mono">
                <div class="text-[#E6EAF0]">{{ device.ip }}</div>
                <div v-if="device.mac" class="text-[11px] text-[#8390A0]">{{ device.mac }}</div>
              </td>

              <td class="px-4 py-3">
                <Badge variant="secondary">
                  {{ device.group_id ? (groupNameMap.get(device.group_id) ?? 'Standard') : 'Ungruppiert' }}
                </Badge>
              </td>

              <td class="px-4 py-3">
                <Badge :variant="device.is_online ? 'success' : 'destructive'">
                  <span
                    class="h-1.5 w-1.5 rounded-full"
                    :class="device.is_online ? 'bg-[#4AC26B]' : 'bg-[#F47067]'"
                  />
                  {{ device.is_online ? 'Online' : 'Offline' }}
                </Badge>
              </td>

              <td class="px-4 py-3" @click.stop>
                <div class="flex flex-wrap gap-1">
                  <template v-for="svc in device.services.slice(0, 4)" :key="svc.id">
                    <a
                      v-if="svc.protocol === 'http' || svc.protocol === 'https'"
                      :href="`${svc.protocol}://${device.ip}:${svc.port}`"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="inline-flex items-center gap-1 rounded border border-[#2A3340] bg-[#0E1116] px-1.5 py-0.5 font-mono text-[10px] text-[#3DB8F5] hover:border-[#3DB8F5]"
                    >
                      {{ svc.name || svc.port }}
                      <ExternalLink class="h-2.5 w-2.5" />
                    </a>
                    <span
                      v-else
                      class="inline-flex items-center rounded border border-[#1F2732] bg-[#0E1116] px-1.5 py-0.5 font-mono text-[10px] text-[#9AA5B4]"
                    >
                      {{ svc.name || svc.port }}
                    </span>
                  </template>
                  <span
                    v-if="device.services.length > 4"
                    class="text-[10px] font-mono text-[#8390A0] self-center"
                  >
                    +{{ device.services.length - 4 }}
                  </span>
                </div>
              </td>

              <td class="px-4 py-3">
                <div v-if="device.has_agent && device.agent_info?.metrics" class="flex items-center gap-3 font-mono text-[11px]">
                  <span class="text-[#3DB8F5]">
                    CPU {{ device.agent_info.metrics.cpu_usage.toFixed(0) }}%
                  </span>
                  <span class="text-[#9AA5B4]">
                    RAM {{ device.agent_info.metrics.memory_usage.toFixed(0) }}%
                  </span>
                </div>
                <span v-else class="text-[11px] text-[#8390A0]">—</span>
              </td>

              <td class="px-4 py-3 text-right">
                <Button variant="ghost" size="sm" @click.stop="openDeviceDetail(device)">
                  <SlidersHorizontal class="h-3.5 w-3.5" />
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <!-- Structured Standard Cards View -->
    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      <Card
        v-for="device in filteredDevices"
        :key="device.id"
        class="p-4 space-y-3 hover:border-[#3DB8F5]/50 transition-colors cursor-pointer"
        @click="openDeviceDetail(device)"
      >
        <div class="flex items-start justify-between gap-2">
          <div>
            <h3 class="text-sm font-semibold text-[#E6EAF0]">{{ device.display_name }}</h3>
            <p class="font-mono text-xs text-[#9AA5B4]">{{ device.ip }}</p>
          </div>
          <Badge :variant="device.is_online ? 'success' : 'destructive'">
            {{ device.is_online ? 'Online' : 'Offline' }}
          </Badge>
        </div>

        <div class="flex items-center justify-between text-[11px] text-[#8390A0]">
          <span>{{ device.vendor || device.device_type }}</span>
          <span>{{ device.group_id ? groupNameMap.get(device.group_id) : 'Ungruppiert' }}</span>
        </div>

        <div v-if="device.has_agent && device.agent_info?.metrics" class="grid grid-cols-3 gap-1.5 pt-1 border-t border-[#1F2732] font-mono text-[11px]">
          <div>
            <span class="text-[#8390A0] block text-[10px]">CPU</span>
            <span class="text-[#3DB8F5]">{{ device.agent_info.metrics.cpu_usage.toFixed(0) }}%</span>
          </div>
          <div>
            <span class="text-[#8390A0] block text-[10px]">RAM</span>
            <span class="text-[#E6EAF0]">{{ device.agent_info.metrics.memory_usage.toFixed(0) }}%</span>
          </div>
          <div>
            <span class="text-[#8390A0] block text-[10px]">DISK</span>
            <span class="text-[#E6EAF0]">{{ device.agent_info.metrics.disk_usage.toFixed(0) }}%</span>
          </div>
        </div>
      </Card>
    </div>

    <DeviceSheet
      v-model:open="sheetOpen"
      :device="activeDevice"
      :groups="store.groups"
      @saved="store.fetchInventory(false)"
    />
  </div>
</template>
