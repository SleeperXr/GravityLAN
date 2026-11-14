<script setup lang="ts">
import { computed } from 'vue';
import { AlertTriangle, ChevronRight } from 'lucide-vue-next';
import type { ProxmoxReport } from '@/api/client';
import Badge, { type BadgeTone } from '@/components/ui/Badge.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { t } from '@/i18n';

/** Settings > Proxmox VE > Last sync: per guest what happened to each address, conflicts, skipped guests. */
const props = defineProps<{ report: ProxmoxReport }>();

type Status = ProxmoxReport['guests'][number]['addresses'][number]['status'];
const TONES: Record<Status, BadgeTone> = {
  renamed: 'accent',
  device: 'info',
  host: 'neutral',
  new_host: 'neutral',
  conflict: 'danger',
  outside: 'neutral',
};

const empty = computed(() => props.report.guests.length === 0 && props.report.skipped.length === 0);
const outsideCount = computed(() => props.report.guests.reduce((n, g) => n + g.addresses.filter((a) => a.status === 'outside').length, 0));
// Open by default when something needs a look
const needsLook = computed(() => empty.value || props.report.conflicts.length > 0);
</script>

<template>
  <details class="group border-t border-line pt-4" :open="needsLook" data-test="proxmox-report">
    <summary class="flex cursor-pointer list-none flex-wrap items-center gap-2 text-sm font-medium text-fg [&::-webkit-details-marker]:hidden">
      <ChevronRight class="size-4 text-fg-subtle transition-transform group-open:rotate-90" aria-hidden="true" />
      {{ t('gv.proxmox.report.title') }}
      <span class="text-xs font-normal text-fg-subtle"><RelativeTime :date="report.synced_at" /></span>
      <Badge>{{ t('gv.proxmox.report.guests', { count: report.guests.length }) }}</Badge>
      <Badge v-if="report.conflicts.length" tone="danger">{{ t('gv.proxmox.report.conflicts', { count: report.conflicts.length }) }}</Badge>
      <Badge v-if="report.skipped.length" tone="warn">{{ t('gv.proxmox.report.skipped', { count: report.skipped.length }) }}</Badge>
    </summary>

    <div class="mt-3 space-y-4">
      <p v-if="empty" class="flex items-start gap-2 rounded-md border border-warn/30 bg-warn/10 p-3 text-sm text-warn-text" data-test="proxmox-no-guests">
        <AlertTriangle class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ t('gv.proxmox.no_guests') }}
      </p>

      <div v-if="report.conflicts.length" class="space-y-1.5">
        <p class="gl-eyebrow text-danger-text">{{ t('gv.proxmox.report.conflicts_title') }}</p>
        <p class="text-xs text-fg-subtle">{{ t('gv.proxmox.report.conflicts_hint') }}</p>
        <ul class="divide-y divide-line border-y border-line">
          <li v-for="c in report.conflicts" :key="c.ip" class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
            <code class="font-mono text-danger-text">{{ c.ip }}</code>
            <span class="text-fg-muted">{{ c.guests.join(', ') }}</span>
          </li>
        </ul>
      </div>

      <div v-if="report.guests.length" class="space-y-1.5">
        <p class="gl-eyebrow">{{ t('gv.proxmox.report.guests_title') }}</p>
        <ul class="divide-y divide-line border-y border-line">
          <li v-for="g in report.guests" :key="g.guest" class="flex flex-col gap-1.5 py-2.5 sm:flex-row sm:items-start sm:gap-4">
            <div class="flex min-w-0 items-center gap-2 sm:w-48 sm:shrink-0">
              <span class="truncate text-sm font-medium text-fg" :title="g.name">{{ g.name }}</span>
              <code class="font-mono text-xs text-fg-subtle">{{ g.guest }}</code>
            </div>
            <ul class="flex min-w-0 flex-wrap gap-1.5">
              <li v-for="a in g.addresses" :key="a.ip">
                <Badge mono :tone="TONES[a.status]" :class="a.status === 'outside' ? 'opacity-60' : undefined" :title="t(`gv.proxmox.status.${a.status}`)">
                  {{ a.ip }}<span class="font-sans opacity-80">· {{ t(`gv.proxmox.status.${a.status}`) }}</span>
                </Badge>
              </li>
            </ul>
          </li>
        </ul>
      </div>

      <div v-if="report.skipped.length" class="space-y-1.5">
        <p class="gl-eyebrow">{{ t('gv.proxmox.report.skipped_title') }}</p>
        <ul class="divide-y divide-line border-y border-line">
          <li v-for="s in report.skipped" :key="s.guest" class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 text-sm">
            <span class="font-medium text-fg">{{ s.name || '–' }}</span>
            <code class="font-mono text-xs text-fg-subtle">{{ s.guest }}</code>
            <span class="text-xs text-fg-muted">{{ t(`gv.proxmox.reason.${s.reason}`) }}</span>
          </li>
        </ul>
      </div>

      <p v-if="outsideCount" class="text-xs leading-relaxed text-fg-subtle">
        {{ t('gv.proxmox.report.outside_hint', { count: outsideCount, subnets: (report.subnets ?? []).join(', ') }) }}
      </p>
    </div>
  </details>
</template>
