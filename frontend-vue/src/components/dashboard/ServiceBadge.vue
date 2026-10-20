<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  Check,
  Database,
  ExternalLink,
  Folder,
  Globe,
  Lock,
  Monitor,
  Server,
  Shield,
  Terminal,
} from 'lucide-vue-next';
import type { Service } from '@/types';

const props = defineProps<{
  service: Service;
  ip: string;
}>();

const copied = ref(false);

const serviceKey = computed(() => {
  const n = (props.service.name || '').toLowerCase();
  const p = props.service.port;
  if (n.includes('https') || p === 443 || p === 8443 || p === 8006 || p === 9443) return 'https';
  if (n.includes('http') || p === 80 || p === 8080 || p === 3000 || p === 5000 || p === 9000) return 'http';
  if (n.includes('ssh') || p === 22) return 'ssh';
  if (n.includes('rdp') || p === 3389) return 'rdp';
  if (n.includes('vnc') || p === 5900) return 'vnc';
  if (n.includes('smb') || n.includes('samba') || n.includes('microsoft-ds') || p === 445 || p === 139) return 'smb';
  if (n.includes('ftp') || p === 21) return 'ftp';
  if (
    n.includes('sql') ||
    n.includes('postgres') ||
    n.includes('mariadb') ||
    n.includes('redis') ||
    n.includes('mongo') ||
    [3306, 5432, 6379, 27017].includes(p)
  )
    return 'db';
  if (n.includes('dns') || n.includes('wireguard') || p === 53 || p === 51820) return 'shield';
  return 'generic';
});

const iconComponent = computed(() => {
  switch (serviceKey.value) {
    case 'ssh':
      return Terminal;
    case 'https':
      return Lock;
    case 'http':
      return Globe;
    case 'rdp':
    case 'vnc':
      return Monitor;
    case 'smb':
      return Folder;
    case 'ftp':
      return Server;
    case 'db':
      return Database;
    case 'shield':
      return Shield;
    default:
      return ExternalLink;
  }
});

const href = computed(() => {
  if (props.service.url) return props.service.url;
  const k = serviceKey.value;
  const p = props.service.port;
  if (k === 'https') return `https://${props.ip}${p === 443 ? '' : `:${p}`}`;
  if (k === 'http') return `http://${props.ip}${p === 80 ? '' : `:${p}`}`;
  if (k === 'ssh') return `ssh://${props.ip}${p === 22 ? '' : `:${p}`}`;
  if (k === 'vnc') return `vnc://${props.ip}:${p}`;
  if (k === 'ftp') return `ftp://${props.ip}${p === 21 ? '' : `:${p}`}`;
  return null;
});

function handleClick(e: MouseEvent) {
  e.stopPropagation();

  if (serviceKey.value === 'smb') {
    e.preventDefault();
    const uncPath = `\\\\${props.ip}`;
    navigator.clipboard?.writeText(uncPath).then(() => {
      copied.value = true;
      setTimeout(() => {
        copied.value = false;
      }, 2000);
    });
    return;
  }

  if (serviceKey.value === 'rdp') {
    e.preventDefault();
    const portSuffix = props.service.port && props.service.port !== 3389 ? `:${props.service.port}` : '';
    const rdpContent = [
      `full address:s:${props.ip}${portSuffix}`,
      'prompt for credentials:i:1',
      'administrative session:i:1',
    ].join('\r\n');
    const blob = new Blob([rdpContent], { type: 'application/x-rdp' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${props.ip}.rdp`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
}
</script>

<template>
  <component
    :is="href && serviceKey !== 'smb' && serviceKey !== 'rdp' ? 'a' : 'button'"
    :href="href && serviceKey !== 'smb' && serviceKey !== 'rdp' ? href : undefined"
    :target="href?.startsWith('http') ? '_blank' : undefined"
    :rel="href?.startsWith('http') ? 'noopener noreferrer' : undefined"
    type="button"
    :title="
      serviceKey === 'smb'
        ? `Copy UNC path \\\\${ip}`
        : serviceKey === 'rdp'
          ? `Download ${ip}.rdp`
          : `${service.name} (${ip}:${service.port})`
    "
    class="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-medium bg-[#1b1b20] hover:bg-[#25252c] text-zinc-200 border border-zinc-800/90 hover:border-zinc-700 transition-all cursor-pointer select-none group/badge"
    @click="handleClick"
  >
    <span
      :class="[
        'w-1.5 h-1.5 rounded-full shrink-0',
        service.is_up === false ? 'bg-rose-500' : 'bg-emerald-500',
      ]"
    />
    <Check v-if="copied" class="w-3 h-3 text-emerald-400 shrink-0" />
    <component :is="iconComponent" v-else class="w-3 h-3 text-zinc-400 group-hover/badge:text-zinc-200 shrink-0" />
    <span class="truncate max-w-[105px]">{{ copied ? 'Copied UNC' : service.name || service.port }}</span>
    <span class="font-mono text-[10px] text-zinc-500 group-hover/badge:text-zinc-400">:{{ service.port }}</span>
  </component>
</template>
