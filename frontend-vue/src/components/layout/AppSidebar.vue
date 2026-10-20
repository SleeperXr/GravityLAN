<script setup lang="ts">
import { useRoute } from 'vue-router';
import {
  Activity,
  ArrowLeftRight,
  ExternalLink,
  Grid3x3,
  LayoutDashboard,
  Network,
  ScrollText,
  Server,
  Settings,
  SquareTerminal,
} from 'lucide-vue-next';
import StatusIndicator from '@/components/8starlabs-ui/StatusIndicator.vue';
import { useI18n } from '@/composables/useI18n';
import { useNetworkStore } from '@/stores/network';

const props = defineProps<{
  version?: string;
}>();

const route = useRoute();
const store = useNetworkStore();
const { t } = useI18n();

const navItems = [
  { name: 'dashboard', to: '/', icon: LayoutDashboard, labelKey: 'nav.dashboard' },
  { name: 'health', to: '/health', icon: Activity, labelKey: 'nav.health' },
  { name: 'network', to: '/network', icon: Grid3x3, labelKey: 'nav.network' },
  { name: 'agents', to: '/agents', icon: Server, labelKey: 'nav.agents' },
  { name: 'settings', to: '/settings', icon: Settings, labelKey: 'nav.settings' },
];

const legacyDeepLinks = [
  { href: '/topology', icon: Network, label: 'Topology & Rack' },
  { href: '/ssh', icon: SquareTerminal, label: 'SSH Terminal' },
  { href: '/logs', icon: ScrollText, label: 'Live Logs' },
];
</script>

<template>
  <aside class="flex h-screen w-64 shrink-0 flex-col border-r border-zinc-800/80 bg-[#0e0e11] select-none">
    <!-- Brand Header -->
    <div class="flex h-15 items-center justify-between border-b border-zinc-800/80 px-4">
      <div class="flex items-center gap-3">
        <div class="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500 text-zinc-950 font-extrabold text-xs shadow-sm">
          GL
        </div>
        <div>
          <div class="flex items-center gap-2">
            <span class="text-sm font-bold tracking-tight text-zinc-100">GravityUI</span>
            <span class="px-1.5 py-0.5 rounded-md text-[10px] font-mono font-semibold bg-emerald-500/12 text-emerald-400 border border-emerald-500/25">
              Vue 3
            </span>
          </div>
          <p class="text-[10px] text-zinc-500 font-mono">
            {{ props.version ? `v${props.version} · 8starlabs` : 'shadcn-vue · 8starlabs' }}
          </p>
        </div>
      </div>
    </div>

    <!-- Live Fleet Mini Summary Card inside Sidebar -->
    <div class="px-3 pt-4">
      <div class="sh-subcard p-3 space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Radar Status</span>
          <StatusIndicator
            :state="store.isScanning ? 'fixing' : store.onlineCount > 0 ? 'active' : 'idle'"
            :label="store.isScanning ? 'Scanning' : 'Online'"
            size="sm"
          />
        </div>
        <div class="grid grid-cols-3 gap-1.5 pt-1 text-center">
          <div class="rounded-lg bg-[#131316] border border-zinc-800/80 py-1.5">
            <div class="font-mono text-xs font-bold text-emerald-400">{{ store.onlineCount }}</div>
            <div class="text-[9px] text-zinc-500 uppercase">Online</div>
          </div>
          <div class="rounded-lg bg-[#131316] border border-zinc-800/80 py-1.5">
            <div class="font-mono text-xs font-bold text-zinc-300">{{ store.totalCount }}</div>
            <div class="text-[9px] text-zinc-500 uppercase">Total</div>
          </div>
          <div class="rounded-lg bg-[#131316] border border-zinc-800/80 py-1.5">
            <div class="font-mono text-xs font-bold text-sky-400">{{ store.agentCount }}</div>
            <div class="text-[9px] text-zinc-500 uppercase">Agents</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Primary Standard Dashboard Navigation -->
    <div class="flex-1 overflow-y-auto px-3 py-4 space-y-6">
      <div class="space-y-1">
        <p class="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Standard Dashboards
        </p>
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          :to="item.to"
          class="flex items-center justify-between rounded-xl px-3 py-2 text-xs font-medium transition-all"
          :class="
            route.path === item.to
              ? 'bg-[#1b1b20] text-zinc-100 border border-zinc-700/80 shadow-xs'
              : 'text-zinc-400 hover:bg-[#151519] hover:text-zinc-200 border border-transparent'
          "
        >
          <span class="flex items-center gap-2.5">
            <component
              :is="item.icon"
              class="h-4 w-4 shrink-0"
              :class="route.path === item.to ? 'text-emerald-400' : 'text-zinc-500'"
            />
            <span>{{ t(item.labelKey) }}</span>
          </span>
          <span
            v-if="item.name === 'dashboard' && store.totalCount > 0"
            class="font-mono text-[10px] px-1.5 py-0.5 rounded-md bg-zinc-900 text-zinc-400"
          >
            {{ store.totalCount }}
          </span>
          <span
            v-else-if="item.name === 'agents' && store.agentCount > 0"
            class="font-mono text-[10px] px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400"
          >
            {{ store.agentCount }}
          </span>
        </RouterLink>
      </div>

      <!-- Direct Deep-Links for specialized canvases in Legacy UI -->
      <div class="space-y-1">
        <p class="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Spezial-Werkzeuge (Legacy)
        </p>
        <a
          v-for="link in legacyDeepLinks"
          :key="link.href"
          :href="link.href"
          class="flex items-center justify-between rounded-xl px-3 py-2 text-xs text-zinc-400 hover:bg-[#151519] hover:text-zinc-200 transition-colors"
        >
          <span class="flex items-center gap-2.5">
            <component :is="link.icon" class="h-3.5 w-3.5 text-zinc-500" />
            <span>{{ link.label }}</span>
          </span>
          <ExternalLink class="h-3 w-3 text-zinc-600" />
        </a>
      </div>
    </div>

    <!-- 1-Click Switcher Footer back to Legacy UI -->
    <div class="border-t border-zinc-800/80 p-3">
      <a
        href="/"
        class="sh-subcard flex w-full items-center justify-between px-3 py-2.5 text-xs font-medium text-zinc-200 hover:border-emerald-500/40 hover:bg-[#222228] transition-all"
      >
        <span class="flex items-center gap-2">
          <ArrowLeftRight class="h-3.5 w-3.5 text-emerald-400" />
          <span>{{ t('nav.legacy_switch') }}</span>
        </span>
        <span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-900 text-zinc-400 border border-zinc-800">
          {{ t('nav.legacy_badge') }}
        </span>
      </a>
    </div>
  </aside>
</template>
