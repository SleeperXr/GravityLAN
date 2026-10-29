<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ShieldAlert, ShieldCheck } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { TopologyLink } from '@/types';
import { useNetworkStore } from '@/stores/network';
import { analyseResilience } from '@/components/orbit/orbitResilience';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * The single points of failure of the network, as the health view shows them: the devices whose loss would
 * cut others off from the core, biggest impact first. Same analysis as the orbit map's resilience view.
 */
const store = useNetworkStore();
const links = ref<TopologyLink[]>([]);

onMounted(async () => {
  links.value = await api.getTopologyLinks().catch(() => []);
});

// The core is what the orbit map calls a star: routers and firewalls
const coreIds = computed(() => store.devices.filter((d) => d.device_type === 'firewall' || d.device_type === 'router').map((d) => d.id));
const analysis = computed(() => analyseResilience(store.devices, links.value, coreIds.value));
const top = computed(() => analysis.value.singlePoints.slice(0, 5));
const byId = computed(() => new Map(store.devices.map((d) => [d.id, d])));
</script>

<template>
  <section class="gl-card space-y-3 p-4" :aria-label="t('gv.orbit.resilience_title')">
    <header class="flex items-start gap-2.5">
      <ShieldAlert v-if="top.length" class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
      <ShieldCheck v-else class="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden="true" />
      <div class="min-w-0">
        <h2 class="text-sm font-bold text-fg">{{ t('gv.orbit.resilience_title') }}</h2>
        <p class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.orbit.resilience_hint') }}</p>
      </div>
    </header>
    <p v-if="!top.length" class="text-xs text-fg-muted">{{ t('gv.orbit.no_spof') }}</p>
    <ol v-else class="divide-y divide-line">
      <li v-for="p in top" :key="p.id" class="flex items-center gap-3 py-2 text-sm">
        <span class="min-w-0 flex-1 truncate text-fg">{{ byId.get(p.id) ? deviceLabel(byId.get(p.id)!) : p.id }}</span>
        <span class="shrink-0 font-mono text-xs text-warn-text tabular">{{ t('gv.orbit.spof_cuts', { count: p.cutOff.length }) }}</span>
      </li>
    </ol>
  </section>
</template>
