<script setup lang="ts">
import { computed } from 'vue';
import type { Device, Subnet } from '@/types';

const props = defineProps<{
  device: Device;
  subnets: Subnet[];
}>();

const PALETTE = [
  '#10b981', // emerald
  '#38bdf8', // sky
  '#f59e0b', // amber
  '#14b8a6', // teal
  '#3b82f6', // blue
  '#f43f5e', // rose
  '#84cc16', // lime
  '#06b6d4', // cyan
];

function ipToInt(ip: string): number | null {
  const parts = ip.trim().split('.');
  if (parts.length !== 4) return null;
  let num = 0;
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isInteger(n) || n < 0 || n > 255) return null;
    num = (num << 8) + n;
  }
  return num >>> 0;
}

function ipInCidr(ip: string, cidr: string): boolean {
  const [net, bitsStr] = cidr.split('/');
  const bits = Number(bitsStr);
  if (!net || !Number.isInteger(bits) || bits < 0 || bits > 32) return false;
  const ipNum = ipToInt(ip);
  const netNum = ipToInt(net);
  if (ipNum === null || netNum === null) return false;
  if (bits === 0) return true;
  const mask = (0xffffffff << (32 - bits)) >>> 0;
  return (ipNum & mask) === (netNum & mask);
}

const matchedNetworks = computed(() => {
  const ips = [props.device.ip, ...(props.device.interfaces || []).map((i) => i.ip)].filter(Boolean);
  const matches: Array<{ id: string; label: string; color: string; cidr: string }> = [];

  for (const s of props.subnets) {
    if (ips.some((ip) => ipInCidr(ip, s.cidr))) {
      const color = s.color && !s.color.toLowerCase().includes('8b5cf6') && !s.color.toLowerCase().includes('a855f7')
        ? s.color
        : PALETTE[s.id % PALETTE.length];
      const label = s.name || (s.vlan_id != null ? `VLAN ${s.vlan_id}` : s.cidr);
      matches.push({
        id: String(s.id),
        label,
        color,
        cidr: s.cidr,
      });
    }
  }
  return matches;
});

const extraIpsCount = computed(() => (props.device.interfaces || []).length);
</script>

<template>
  <div v-if="matchedNetworks.length > 0 || extraIpsCount > 0" class="inline-flex flex-wrap items-center gap-1">
    <span
      v-for="net in matchedNetworks.slice(0, 2)"
      :key="net.id"
      :title="`${net.label} · ${net.cidr}`"
      class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-[#1b1b20] border border-zinc-800 text-zinc-300"
    >
      <span class="w-1.5 h-1.5 rounded-full shrink-0" :style="{ backgroundColor: net.color }" />
      <span class="truncate max-w-[85px]">{{ net.label }}</span>
    </span>
    <span
      v-if="matchedNetworks.length > 2"
      class="px-1.5 py-0.5 rounded-md text-[10px] font-mono bg-[#1b1b20] border border-zinc-800 text-zinc-400"
    >
      +{{ matchedNetworks.length - 2 }} VLAN
    </span>
    <span
      v-if="extraIpsCount > 0"
      :title="(device.interfaces || []).map((i) => i.ip).join(', ')"
      class="px-1.5 py-0.5 rounded-md text-[10px] font-mono bg-sky-500/10 border border-sky-500/20 text-sky-300"
    >
      +{{ extraIpsCount }} IP
    </span>
  </div>
</template>
