<script setup lang="ts">
import { computed } from 'vue';
import { useNetworkStore } from '@/stores/network';
import Card from '@/components/ui/card/Card.vue';
import Badge from '@/components/ui/badge/Badge.vue';
import Button from '@/components/ui/button/Button.vue';
import { api } from '@/api/client';

const store = useNetworkStore();

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
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-base font-semibold text-[#E6EAF0]">Konfigurierte Scan-Subnetze & VLANs</h2>
      <p class="text-xs text-[#9AA5B4]">L2 Direct, L3 Routed und L2 Agent-Probes im Überblick</p>
    </div>

    <Card class="overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-xs">
          <thead>
            <tr class="border-b border-[#1F2732] bg-[#12161C] text-[11px] font-medium uppercase tracking-wider text-[#8390A0]">
              <th class="px-4 py-3">Name</th>
              <th class="px-4 py-3">CIDR</th>
              <th class="px-4 py-3">VLAN</th>
              <th class="px-4 py-3">Erkennung</th>
              <th class="px-4 py-3">Gateway</th>
              <th class="px-4 py-3">Geräte</th>
              <th class="px-4 py-3 text-right">Scan-Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[#1F2732]">
            <tr v-for="sub in store.subnets" :key="sub.id" class="hover:bg-[#1F2732]/40">
              <td class="px-4 py-3 font-medium text-[#E6EAF0]">{{ sub.name || sub.cidr }}</td>
              <td class="px-4 py-3 font-mono text-[#3DB8F5]">{{ sub.cidr }}</td>
              <td class="px-4 py-3 font-mono text-[#9AA5B4]">{{ sub.vlan_id ?? '—' }}</td>
              <td class="px-4 py-3">
                <Badge v-if="sub.is_direct_l2" variant="success">L2 Direct ({{ sub.interface_name }})</Badge>
                <Badge v-else-if="sub.is_agent_probe" variant="default">L2 Probe ({{ sub.probe_device_name }})</Badge>
                <Badge v-else variant="secondary">L3 Routed</Badge>
              </td>
              <td class="px-4 py-3 font-mono text-[#9AA5B4]">
                {{ sub.gateway_ip || sub.gateway_suggestion || '—' }}
              </td>
              <td class="px-4 py-3 font-mono text-[#E6EAF0]">
                {{ devicesBySubnet.get(sub.id) ?? 0 }}
              </td>
              <td class="px-4 py-3 text-right">
                <Button
                  :variant="sub.is_enabled ? 'secondary' : 'outline'"
                  size="sm"
                  @click="toggleSubnet(sub.id, sub.is_enabled)"
                >
                  {{ sub.is_enabled ? 'Aktiv' : 'Pausiert' }}
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
