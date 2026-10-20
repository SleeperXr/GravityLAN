<script setup lang="ts">
import { computed, ref } from 'vue';
import { Network, Plus, Radar, Trash2 } from 'lucide-vue-next';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import { api } from '@/api/client';
import { useNetworkStore } from '@/stores/network';

const store = useNetworkStore();

const newCidr = ref('');
const newName = ref('');
const newVlan = ref<number | ''>('');
const newGateway = ref('');
const adding = ref(false);

const devicesBySubnet = computed(() => {
  const counts = new Map<number, number>();
  for (const d of store.devices) {
    if (d.subnet_id) {
      counts.set(d.subnet_id, (counts.get(d.subnet_id) ?? 0) + 1);
    }
  }
  return counts;
});

async function toggleSubnet(id: number, current: boolean) {
  await api.updateSubnet(id, { is_enabled: !current });
  await store.fetchInventory(false);
}

async function handleCreateSubnet() {
  if (!newCidr.value.trim()) return;
  adding.value = true;
  try {
    await api.createSubnet({
      cidr: newCidr.value.trim(),
      name: newName.value.trim() || undefined,
      vlan_id: newVlan.value !== '' ? Number(newVlan.value) : null,
      gateway_ip: newGateway.value.trim() || null,
      is_enabled: true,
    });
    newCidr.value = '';
    newName.value = '';
    newVlan.value = '';
    newGateway.value = '';
    await store.fetchInventory(false);
  } finally {
    adding.value = false;
  }
}

async function handleDeleteSubnet(id: number) {
  if (!confirm('Remove this subnet configuration?')) return;
  await api.deleteSubnet(id);
  await store.fetchInventory(false);
}

async function scanSingleSubnet(cidr: string) {
  await api.startDashboardScan({ subnets: [cidr] });
}
</script>

<template>
  <div class="p-6 max-w-[1640px] mx-auto space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h2 class="text-lg font-bold text-zinc-100 tracking-tight">Subnets, VLANs & L2/L3 Probes</h2>
        <p class="text-xs text-zinc-400">
          Configure local L2 interfaces, routed VLANs, and remote agent discovery relays
        </p>
      </div>
    </div>

    <!-- Add Subnet Card -->
    <div class="sh-card p-5 space-y-4">
      <div class="flex items-center gap-2 text-xs font-semibold text-zinc-200">
        <Network class="w-4 h-4 text-emerald-400" />
        <span>Add Subnet or VLAN Range</span>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <input
          v-model="newCidr"
          placeholder="CIDR (e.g. 192.168.20.0/24)"
          class="h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs font-mono text-zinc-100"
        />
        <input
          v-model="newName"
          placeholder="Name (e.g. Homelab Core)"
          class="h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-100"
        />
        <input
          v-model="newVlan"
          type="number"
          placeholder="VLAN ID (e.g. 20)"
          class="h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs font-mono text-zinc-100"
        />
        <input
          v-model="newGateway"
          placeholder="Gateway IP (optional)"
          class="h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs font-mono text-zinc-100"
        />
        <button
          type="button"
          class="h-9 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs inline-flex items-center justify-center gap-1.5 cursor-pointer"
          :disabled="adding"
          @click="handleCreateSubnet"
        >
          <Plus class="w-3.5 h-3.5" />
          {{ adding ? 'Adding...' : 'Add Subnet' }}
        </button>
      </div>
    </div>

    <!-- Subnets Table Card -->
    <div class="sh-card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-xs">
          <thead>
            <tr class="border-b border-zinc-800/80 bg-[#16161a] text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              <th class="px-4 py-3">Status</th>
              <th class="px-4 py-3">Name</th>
              <th class="px-4 py-3">CIDR</th>
              <th class="px-4 py-3">VLAN</th>
              <th class="px-4 py-3">Discovery Mode</th>
              <th class="px-4 py-3">Gateway</th>
              <th class="px-4 py-3">Hosts</th>
              <th class="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-800/60">
            <tr v-for="sub in store.subnets" :key="sub.id" class="hover:bg-[#19191f] transition-colors">
              <td class="px-4 py-3">
                <StatusIndicator
                  :state="sub.is_enabled ? 'active' : 'idle'"
                  :label="sub.is_enabled ? 'Enabled' : 'Paused'"
                  size="sm"
                />
              </td>
              <td class="px-4 py-3 font-semibold text-zinc-100">{{ sub.name || sub.cidr }}</td>
              <td class="px-4 py-3 font-mono text-emerald-400">{{ sub.cidr }}</td>
              <td class="px-4 py-3 font-mono text-zinc-300">
                <span v-if="sub.vlan_id != null" class="px-2 py-0.5 rounded-md bg-[#1b1b20] border border-zinc-800">
                  VLAN {{ sub.vlan_id }}
                </span>
                <span v-else class="text-zinc-500">—</span>
              </td>
              <td class="px-4 py-3">
                <span
                  v-if="sub.is_direct_l2"
                  class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-emerald-500/12 text-emerald-400 border border-emerald-500/25"
                >
                  L2 Direct ({{ sub.interface_name }})
                </span>
                <span
                  v-else-if="sub.is_agent_probe"
                  class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-sky-500/12 text-sky-400 border border-sky-500/25"
                >
                  L2 Agent Relay ({{ sub.probe_device_name }})
                </span>
                <span
                  v-else
                  class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-[#1b1b20] text-zinc-300 border border-zinc-800"
                >
                  L3 Routed
                </span>
              </td>
              <td class="px-4 py-3 font-mono text-zinc-300">
                {{ sub.gateway_ip || sub.gateway_suggestion || '—' }}
              </td>
              <td class="px-4 py-3 font-mono font-bold text-zinc-100">
                {{ devicesBySubnet.get(sub.id) ?? 0 }}
              </td>
              <td class="px-4 py-3 text-right">
                <div class="inline-flex items-center gap-1.5">
                  <button
                    type="button"
                    class="sh-pill-btn px-2.5 py-1 text-[11px] font-medium inline-flex items-center gap-1 cursor-pointer"
                    @click="scanSingleSubnet(sub.cidr)"
                  >
                    <Radar class="w-3 h-3 text-emerald-400" />
                    Sweep
                  </button>
                  <button
                    type="button"
                    class="sh-pill-btn px-2.5 py-1 text-[11px] font-medium cursor-pointer"
                    @click="toggleSubnet(sub.id, sub.is_enabled)"
                  >
                    {{ sub.is_enabled ? 'Pause' : 'Enable' }}
                  </button>
                  <button
                    type="button"
                    class="p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 cursor-pointer"
                    @click="handleDeleteSubnet(sub.id)"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
