<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { api } from '@/api/client';
import type { AgentSummary } from '@/types';
import Card from '@/components/ui/card/Card.vue';
import Badge from '@/components/ui/badge/Badge.vue';

const agents = ref<AgentSummary[]>([]);
const avgCpu = ref(0);
const avgRam = ref(0);
const activeCount = ref(0);

async function loadAgents() {
  const res = await api.getAgentsOverview();
  agents.value = res.agents;
  avgCpu.value = res.avg_cpu;
  avgRam.value = res.avg_ram;
  activeCount.value = res.active_agents;
}

onMounted(loadAgents);
</script>

<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Card class="p-4 space-y-1">
        <span class="text-xs text-[#9AA5B4]">Aktive Linux-Agents</span>
        <div class="font-mono text-2xl font-bold text-[#E6EAF0]">{{ activeCount }} / {{ agents.length }}</div>
      </Card>
      <Card class="p-4 space-y-1">
        <span class="text-xs text-[#9AA5B4]">Flotten Ø CPU-Auslastung</span>
        <div class="font-mono text-2xl font-bold text-[#3DB8F5]">{{ avgCpu.toFixed(1) }}%</div>
      </Card>
      <Card class="p-4 space-y-1">
        <span class="text-xs text-[#9AA5B4]">Flotten Ø RAM-Auslastung</span>
        <div class="font-mono text-2xl font-bold text-[#E6EAF0]">{{ avgRam.toFixed(1) }}%</div>
      </Card>
    </div>

    <Card class="overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-xs">
          <thead>
            <tr class="border-b border-[#1F2732] bg-[#12161C] text-[11px] font-medium uppercase tracking-wider text-[#8390A0]">
              <th class="px-4 py-3">Host</th>
              <th class="px-4 py-3">Version</th>
              <th class="px-4 py-3">CPU</th>
              <th class="px-4 py-3">RAM</th>
              <th class="px-4 py-3">Temp</th>
              <th class="px-4 py-3">Offene Updates</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[#1F2732]">
            <tr v-for="ag in agents" :key="ag.device_id" class="hover:bg-[#1F2732]/40">
              <td class="px-4 py-3">
                <div class="font-medium text-[#E6EAF0]">{{ ag.hostname }}</div>
                <div class="font-mono text-[11px] text-[#8390A0]">{{ ag.ip }}</div>
              </td>
              <td class="px-4 py-3 font-mono text-[#9AA5B4]">v{{ ag.agent_version || '—' }}</td>
              <td class="px-4 py-3 font-mono text-[#3DB8F5]">{{ ag.cpu_usage.toFixed(1) }}%</td>
              <td class="px-4 py-3 font-mono text-[#E6EAF0]">{{ ag.ram_usage.toFixed(1) }}%</td>
              <td class="px-4 py-3 font-mono text-[#9AA5B4]">
                {{ ag.temp !== null ? `${ag.temp.toFixed(0)} °C` : '—' }}
              </td>
              <td class="px-4 py-3">
                <Badge v-if="ag.patch_security > 0" variant="destructive">
                  {{ ag.patch_available }} ({{ ag.patch_security }} Security)
                </Badge>
                <Badge v-else-if="ag.patch_available > 0" variant="warning">
                  {{ ag.patch_available }} Updates
                </Badge>
                <Badge v-else variant="success">Aktuell</Badge>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
