<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { EyeOff, ShieldAlert, ShieldCheck } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { TopologyLink } from '@/types';
import { useNetworkStore } from '@/stores/network';
import { useToast } from '@/composables/useToast';
import { analyseResilience, showResilienceCard, type ResilienceCardMode } from '@/components/orbit/orbitResilience';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * The single points of failure of the network, as the health view shows them: the devices whose loss would
 * cut others off from the core, biggest impact first. Same analysis as the orbit map's resilience view.
 *
 * Optional (`ui.health_resilience`): automatic shows it only once the network has a backup link, since a
 * simple homelab without any fallback path learns nothing from it; "on" and "off" force it. Hiding it here
 * sets "off", with an undo; Settings → System turns it back on.
 */
const store = useNetworkStore();
const { showToast } = useToast();
const links = ref<TopologyLink[]>([]);
const mode = ref<ResilienceCardMode>('auto');
const ready = ref(false);

onMounted(async () => {
  const [linkList, settings] = await Promise.all([api.getTopologyLinks().catch(() => []), api.getSettings().catch(() => ({}) as Record<string, string>)]);
  links.value = linkList;
  const stored = settings['ui.health_resilience'];
  mode.value = stored === 'on' || stored === 'off' ? stored : 'auto';
  ready.value = true;
});

const visible = computed(() => ready.value && showResilienceCard(mode.value, links.value));

async function setMode(next: ResilienceCardMode) {
  const before = mode.value;
  mode.value = next;
  try {
    await api.updateSettings({ 'ui.health_resilience': next });
  } catch (err) {
    mode.value = before;
    showToast('error', t('gv.health.resilience_setting'), (err as Error).message);
  }
}

function hide() {
  const before = mode.value;
  void setMode('off');
  showToast('success', t('gv.health.resilience_hidden'), t('gv.health.resilience_hidden_hint'), { label: t('gv.toast.undo'), run: () => void setMode(before) });
}

// The core is what the orbit map calls a star: routers and firewalls
const coreIds = computed(() => store.devices.filter((d) => d.device_type === 'firewall' || d.device_type === 'router').map((d) => d.id));
const analysis = computed(() => analyseResilience(store.devices, links.value, coreIds.value));
const top = computed(() => analysis.value.singlePoints.slice(0, 5));
const byId = computed(() => new Map(store.devices.map((d) => [d.id, d])));
</script>

<template>
  <section v-if="visible" class="gl-card space-y-3 p-4" :aria-label="t('gv.orbit.resilience_title')">
    <header class="flex items-start gap-2.5">
      <ShieldAlert v-if="top.length" class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
      <ShieldCheck v-else class="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden="true" />
      <div class="min-w-0">
        <h2 class="text-sm font-bold text-fg">{{ t('gv.orbit.resilience_title') }}</h2>
        <p class="text-xs leading-relaxed text-fg-subtle">{{ t('gv.orbit.resilience_hint') }}</p>
      </div>
      <button
        type="button"
        class="ml-auto inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent max-md:size-11"
        :aria-label="t('gv.health.resilience_hide')"
        :title="t('gv.health.resilience_hide')"
        @click="hide"
      >
        <EyeOff class="size-4" aria-hidden="true" />
      </button>
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
