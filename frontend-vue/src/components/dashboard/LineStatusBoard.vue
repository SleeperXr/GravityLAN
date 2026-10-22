<script setup lang="ts">
import { computed } from 'vue';
import type { Device, Subnet } from '@/types';
import LineBullet from '@/components/common/LineBullet.vue';
import { lineLabel, networkColor } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * Network orbit status board: one cell per subnet with its VLAN/subnet badge, its health state
 * in words and how many devices are online. Selecting a cell filters the overview to that orbit.
 */
const props = defineProps<{ subnets: Subnet[]; devices: Device[]; active: number | null }>();
const emit = defineEmits<{ select: [subnetId: number | null] }>();

interface LineRow {
  id: number;
  name: string;
  cidr: string;
  bullet: string;
  color: string;
  total: number;
  online: number;
  dropped: number;
  degraded: number;
  paused: boolean;
}

const rows = computed<LineRow[]>(() =>
  props.subnets.map((s) => {
    const members = props.devices.filter((d) => d.subnet_id === s.id || d.interfaces?.some((i) => i.subnet_id === s.id));
    return {
      id: s.id,
      name: s.name,
      cidr: s.cidr,
      bullet: lineLabel(s),
      color: networkColor(s.id, s.cidr),
      total: members.length,
      online: members.filter((d) => d.is_online).length,
      dropped: members.filter((d) => !d.is_online && d.alert_offline !== false).length,
      degraded: members.filter((d) => d.is_online && d.services.some((x) => !x.is_up)).length,
      paused: s.is_enabled === false,
    };
  }),
);

function statusText(row: LineRow) {
  if (row.paused) return { text: t('gv.lines.paused'), tone: 'text-fg-subtle' };
  if (row.dropped > 0) return { text: t('gv.lines.dropped', { count: row.dropped }), tone: 'text-danger-text' };
  if (row.degraded > 0) return { text: t('gv.lines.degraded', { count: row.degraded }), tone: 'text-warn-text' };
  return { text: t('gv.lines.normal'), tone: 'text-accent-text' };
}
</script>

<template>
  <section :aria-label="t('gv.lines.title')" class="gl-card overflow-hidden">
    <ul class="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-[repeat(auto-fit,minmax(16rem,1fr))]">
      <li v-for="row in rows" :key="row.id" class="sm:border-r sm:border-b sm:border-line">
        <button
          type="button"
          class="flex h-full w-full items-center gap-3.5 px-4 py-3.5 text-left transition-colors hover:bg-raised"
          :class="active === row.id && 'bg-raised shadow-[inset_0_-2px_0_0_var(--gl-accent)]'"
          :aria-pressed="active === row.id"
          @click="emit('select', active === row.id ? null : row.id)"
        >
          <LineBullet :color="row.color" :label="row.bullet" size="lg" />
          <span class="min-w-0 flex-1">
            <span class="flex items-baseline gap-2">
              <span class="truncate text-sm font-bold text-fg">{{ row.name }}</span>
              <span class="hidden truncate font-mono text-[11px] text-fg-subtle 2xl:inline">{{ row.cidr }}</span>
            </span>
            <span class="mt-0.5 block truncate text-[13px] font-semibold" :class="statusText(row).tone">{{ statusText(row).text }}</span>
          </span>
          <span class="shrink-0 text-right font-mono text-xs text-fg-muted tabular">
            <span class="block text-base font-semibold text-fg">{{ row.online }}<span class="text-fg-subtle">/{{ row.total }}</span></span>
            {{ t('network.online') }}
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>
