<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowRight, CheckCircle2, ChevronDown } from 'lucide-vue-next';
import type { Device } from '@/types';
import LineBullet from '@/components/common/LineBullet.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { isAgentOutdated, patchState } from '@/lib/agent';
import { isClientStandby } from '@/lib/standby';
import { deviceLabel, lineLabelFor, networkColor } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * Service notices: everything that needs the operator, most urgent first. Offline devices
 * watched 24/7, new agent keys, services down (not for clients in standby), security updates and
 * pending reboots reported by agents, IP changes, agent updates.
 */
const props = defineProps<{
  devices: Device[];
  /** Show only the most urgent notices and a button for the rest (stacked layout, no inner scrolling) */
  limit?: number;
}>();
const emit = defineEmits<{ openDevice: [device: Device]; openUpdates: []; openPatches: [device: Device] }>();

interface Notice {
  key: string;
  rank: number;
  device?: Device;
  tone: 'danger' | 'warn' | 'info';
  title: string;
  detail: string;
  since?: string | null;
  action?: 'device' | 'updates' | 'patches';
}

const notices = computed<Notice[]>(() => {
  const list: Notice[] = [];
  for (const d of props.devices) {
    const name = deviceLabel(d);
    if (!d.is_online && d.alert_offline !== false) {
      list.push({ key: `off-${d.id}`, rank: 0, device: d, tone: 'danger', title: t('gv.notices.dropped', { name }), detail: d.ip, since: d.status_changed_at, action: 'device' });
    }
    if (d.has_pending_token) {
      list.push({ key: `key-${d.id}`, rank: 1, device: d, tone: 'danger', title: t('gv.notices.new_key', { name }), detail: t('dashboard.security_alert'), action: 'device' });
    }
    // A client with every port closed is asleep (standby), not disrupted
    const down = d.is_online && !isClientStandby(d) ? d.services.filter((s) => !s.is_up) : [];
    if (down.length) {
      const title = down.length === d.services.length ? t('gv.notices.services_none', { name }) : t('gv.notices.services_down', { name, count: down.length });
      list.push({ key: `svc-${d.id}`, rank: 2, device: d, tone: 'warn', title, detail: down.map((s) => `${s.name} :${s.port}`).join(', '), action: 'device' });
    }
    // Security updates the agent reports, or a pending reboot: the Agents page installs them
    const patches = patchState(d);
    if (patches && (patches.security > 0 || patches.reboot)) {
      const parts = [t('gv.notices.updates_total', { count: patches.available }), patches.reboot ? t('gv.notices.reboot') : ''].filter(Boolean);
      const title = patches.security > 0 ? t('gv.notices.security_updates', { name, count: patches.security }) : t('gv.notices.reboot_only', { name });
      list.push({ key: `sec-${d.id}`, rank: 2, device: d, tone: patches.security > 0 ? 'warn' : 'info', title, detail: parts.join(' · '), action: 'patches' });
    }
    if (d.old_ip) {
      list.push({ key: `ip-${d.id}`, rank: 3, device: d, tone: 'info', title: t('gv.notices.ip_changed', { name }), detail: `${d.old_ip} → ${d.ip}`, since: d.ip_changed_at, action: 'device' });
    }
  }
  const outdated = props.devices.filter((d) => d.has_agent && isAgentOutdated(d.agent_info?.agent_version, d.agent_info?.latest_version));
  if (outdated.length) {
    const target = outdated[0].agent_info?.latest_version;
    list.push({ key: 'updates', rank: 4, tone: 'info', title: t('gv.notices.updates', { count: outdated.length }), detail: target ? `→ v${target}` : '', action: 'updates' });
  }
  return list.sort((a, b) => a.rank - b.rank);
});

const expanded = ref(false);
const shown = computed(() => (props.limit && !expanded.value ? notices.value.slice(0, props.limit) : notices.value));
const hidden = computed(() => notices.value.length - shown.value.length);
/** More notices than the limit, so the list can fold; the toggle stays in place, keeping keyboard focus */
const foldable = computed(() => !!props.limit && notices.value.length > props.limit);
watch(foldable, (can) => {
  if (!can) expanded.value = false;
});

function open(n: Notice) {
  if (n.action === 'updates') emit('openUpdates');
  else if (n.action === 'patches' && n.device) emit('openPatches', n.device);
  else if (n.device) emit('openDevice', n.device);
}
</script>

<template>
  <section class="gl-card flex min-h-0 flex-col" aria-labelledby="notices-title">
    <header class="flex items-baseline justify-between border-b border-line px-4 py-3">
      <h2 id="notices-title" class="text-sm font-bold text-fg">{{ t('gv.notices.title') }}</h2>
      <span class="font-mono text-xs text-fg-subtle tabular">{{ notices.length }}</span>
    </header>
    <div v-if="notices.length === 0" class="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <CheckCircle2 class="size-6 text-accent-text" aria-hidden="true" />
      <p class="text-sm font-semibold text-fg">{{ t('gv.notices.all_clear') }}</p>
      <p class="text-xs text-fg-subtle">{{ t('gv.notices.all_clear_hint') }}</p>
    </div>
    <ul v-else class="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
      <li v-for="n in shown" :key="n.key">
        <button type="button" class="group flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-raised" @click="open(n)">
          <!-- The badge of the network orbit the device belongs to; fleet-wide notices get a neutral sign -->
          <LineBullet
            v-if="n.device"
            :color="networkColor(n.device.subnet_id, n.device.ip)"
            :label="lineLabelFor(n.device.subnet_id)"
            size="sm"
            class="mt-0.5"
          />
          <LineBullet v-else color="var(--gl-fg-muted)" label="A" size="sm" class="mt-0.5" />
          <span class="min-w-0 flex-1">
            <span class="block text-sm leading-5 font-bold" :class="n.tone === 'danger' ? 'text-danger-text' : n.tone === 'warn' ? 'text-warn-text' : 'text-fg'">
              {{ n.title }}
            </span>
            <span class="mt-0.5 block truncate font-mono text-xs text-fg-subtle">{{ n.detail }}</span>
            <span v-if="n.since" class="mt-0.5 block text-xs text-fg-subtle"><RelativeTime :date="n.since" /></span>
          </span>
          <ArrowRight class="mt-1 size-4 shrink-0 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
        </button>
      </li>
    </ul>
    <button
      v-if="foldable"
      type="button"
      class="flex min-h-11 items-center justify-center gap-1.5 border-t border-line px-4 text-xs font-semibold text-fg-muted transition-colors hover:bg-raised hover:text-fg"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <ChevronDown class="size-4 transition-transform" :class="expanded && 'rotate-180'" aria-hidden="true" />
      {{ expanded ? t('gv.notices.show_less') : t('gv.notices.show_all', { count: hidden }) }}
    </button>
  </section>
</template>
