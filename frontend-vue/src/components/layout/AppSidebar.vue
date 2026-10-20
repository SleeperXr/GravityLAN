<script setup lang="ts">
import { useRoute } from 'vue-router';
import {
  LayoutDashboard,
  Activity,
  Grid3x3,
  Server,
  Settings,
  ArrowLeftRight,
  Network,
  SquareTerminal,
  ScrollText,
  ExternalLink,
} from 'lucide-vue-next';
import { useI18n } from '@/composables/useI18n';
import Badge from '@/components/ui/badge/Badge.vue';

const props = defineProps<{
  version?: string;
}>();

const route = useRoute();
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
  <aside class="flex h-screen w-64 shrink-0 flex-col border-r border-[#1F2732] bg-[#12161C] select-none">
    <!-- Brand Header -->
    <div class="flex h-14 items-center justify-between border-b border-[#1F2732] px-4">
      <div class="flex items-center gap-2.5">
        <div class="flex h-7 w-7 items-center justify-center rounded-md bg-[#3DB8F5] text-[#07121A] font-bold text-xs shadow-xs">
          GL
        </div>
        <div>
          <div class="flex items-center gap-1.5">
            <span class="text-sm font-bold tracking-tight text-[#E6EAF0]">GravityUI</span>
            <Badge variant="default" class="px-1.5 py-0 text-[10px]">Vue</Badge>
          </div>
          <p class="text-[10px] text-[#8390A0] font-mono">
            {{ props.version ? `v${props.version}` : 'shadcn-vue' }}
          </p>
        </div>
      </div>
    </div>

    <!-- Primary Standard Dashboard Navigation -->
    <div class="flex-1 overflow-y-auto px-3 py-4 space-y-6">
      <div class="space-y-1">
        <p class="px-2.5 pb-1 text-[10px] font-mono uppercase tracking-wider text-[#8390A0]">
          Standard Dashboards
        </p>
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          :to="item.to"
          class="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-xs font-medium transition-colors"
          :class="
            route.path === item.to
              ? 'bg-[#1F2732] text-[#E6EAF0] border border-[#2A3340]'
              : 'text-[#9AA5B4] hover:bg-[#151A21] hover:text-[#E6EAF0]'
          "
        >
          <component
            :is="item.icon"
            class="h-4 w-4 shrink-0"
            :class="route.path === item.to ? 'text-[#3DB8F5]' : 'text-[#8390A0]'"
          />
          <span>{{ t(item.labelKey) }}</span>
        </RouterLink>
      </div>

      <!-- Direct Deep-Links for specialized canvases in Legacy UI -->
      <div class="space-y-1">
        <p class="px-2.5 pb-1 text-[10px] font-mono uppercase tracking-wider text-[#8390A0]">
          Spezial-Werkzeuge (Legacy)
        </p>
        <a
          v-for="link in legacyDeepLinks"
          :key="link.href"
          :href="link.href"
          class="flex items-center justify-between rounded-md px-2.5 py-1.5 text-xs text-[#9AA5B4] hover:bg-[#151A21] hover:text-[#E6EAF0] transition-colors"
        >
          <span class="flex items-center gap-2.5">
            <component :is="link.icon" class="h-3.5 w-3.5 text-[#8390A0]" />
            <span>{{ link.label }}</span>
          </span>
          <ExternalLink class="h-3 w-3 text-[#8390A0]" />
        </a>
      </div>
    </div>

    <!-- 1-Click Switcher Footer back to Legacy UI -->
    <div class="border-t border-[#1F2732] p-3">
      <a
        href="/"
        class="flex w-full items-center justify-between rounded-md border border-[#2A3340] bg-[#151A21] px-3 py-2 text-xs font-medium text-[#E6EAF0] hover:border-[#3DB8F5]/50 hover:bg-[#1F2732] transition-colors"
      >
        <span class="flex items-center gap-2">
          <ArrowLeftRight class="h-3.5 w-3.5 text-[#3DB8F5]" />
          <span>{{ t('nav.legacy_switch') }}</span>
        </span>
        <Badge variant="secondary" class="font-mono text-[10px]">
          {{ t('nav.legacy_badge') }}
        </Badge>
      </a>
    </div>
  </aside>
</template>
