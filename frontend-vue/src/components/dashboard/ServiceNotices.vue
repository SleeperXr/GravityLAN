<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowRight, Check, CheckCircle2, ChevronDown } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device } from '@/types';
import LineBullet from '@/components/common/LineBullet.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { lineLabelFor, networkColor } from '@/lib/networks';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';
import { buildNotices, type Notice } from './serviceNotices';

/**
 * Service notices: everything that needs the operator, most urgent first. Offline devices
 * watched 24/7, new agent keys, agents that stopped reporting, services down (not for clients in standby), security updates and
 * pending reboots reported by agents, IP changes, agent updates.
 */
const props = defineProps<{
  devices: Device[];
  /** Show only the most urgent notices and a button for the rest (stacked layout, no inner scrolling) */
  limit?: number;
}>();
const emit = defineEmits<{ openDevice: [device: Device]; openUpdates: []; openPatches: [device: Device] }>();

const notices = computed<Notice[]>(() => buildNotices(props.devices));

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

const { showToast } = useToast();
const acking = ref<string | null>(null);

/** Confirm an IP change; the notice only goes away once the server stored that. */
async function ackNotice(n: Notice) {
  if (!n.device || acking.value) return;
  const dev = n.device;
  acking.value = n.key;
  try {
    await api.updateDevice(dev.id, { old_ip: null, ip_changed_at: null });
    dev.old_ip = null;
    dev.ip_changed_at = null;
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    acking.value = null;
  }
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
      <!-- The confirm button sits next to the row button, not inside it: buttons must not nest -->
      <li v-for="n in shown" :key="n.key" class="group flex items-start transition-colors hover:bg-raised">
        <button type="button" class="flex min-w-0 flex-1 items-start gap-3 py-3 pl-4 text-left" :class="n.key.startsWith('ip-') && n.device ? 'pr-2' : 'pr-4'" @click="open(n)">
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
          <ArrowRight
            v-if="!(n.key.startsWith('ip-') && n.device)"
            class="mt-1 size-4 shrink-0 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100"
            aria-hidden="true"
          />
        </button>
        <button
          v-if="n.key.startsWith('ip-') && n.device"
          type="button"
          class="my-3 mr-4 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fg-subtle opacity-70 transition-opacity hover:bg-control-hover hover:text-fg hover:opacity-100 disabled:opacity-40 [@media(hover:none)]:opacity-100"
          :title="t('dashboard.ip_changed_ack')"
          :aria-label="t('dashboard.ip_changed_ack')"
          :disabled="acking === n.key"
          data-test="ack-ip-change"
          @click="ackNotice(n)"
        >
          <Check class="size-4" aria-hidden="true" />
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
