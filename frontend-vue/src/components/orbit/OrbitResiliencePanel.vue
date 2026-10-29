<script setup lang="ts">
import { computed, ref } from 'vue';
import { ChevronRight, ShieldAlert, ShieldCheck, X } from 'lucide-vue-next';
import { t } from '@/i18n';

/**
 * Resilience view of the orbit map: the devices whose failure would cut others off, biggest impact first,
 * plus backup links carrying traffic right now and devices nothing reaches any more. Those unreachable
 * devices open into a list; a device whose only problem is a missing link on the map is told apart from
 * one cut off by a device that is down.
 */
const props = defineProps<{
  points: { id: number; label: string; cutOff: number }[];
  activeBackups: number;
  /** Online devices without a path to the core right now; `unlinked` when no link on the map leads to them */
  cutOff: { id: number; label: string; unlinked: boolean }[];
}>();
const emit = defineEmits<{ select: [id: number]; close: [] }>();

type GroupKind = 'cut_off' | 'unlinked';
const groups = computed(() =>
  [
    { kind: 'cut_off' as GroupKind, devices: props.cutOff.filter((d) => !d.unlinked), tone: 'text-danger-text', key: 'gv.orbit.devices_cut_off', hint: 'gv.orbit.devices_cut_off_hint' },
    { kind: 'unlinked' as GroupKind, devices: props.cutOff.filter((d) => d.unlinked), tone: 'text-fg-muted', key: 'gv.orbit.devices_unlinked', hint: 'gv.orbit.devices_unlinked_hint' },
  ].filter((g) => g.devices.length),
);
const expanded = ref<GroupKind | null>(null);
const toggle = (kind: GroupKind) => (expanded.value = expanded.value === kind ? null : kind);
</script>

<template>
  <div
    class="absolute top-14 left-3 z-10 flex max-h-[calc(100%-7.5rem)] w-[min(19rem,calc(100%-4.5rem))] flex-col rounded-lg border border-line-strong bg-surface/95 shadow-pop backdrop-blur"
    role="dialog"
    :aria-label="t('gv.orbit.resilience_title')"
    @pointerdown.stop
  >
    <div class="flex items-start gap-2 border-b border-line p-3">
      <ShieldAlert class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">{{ t('gv.orbit.resilience_title') }}</p>
        <p class="text-[11px] leading-snug text-fg-subtle">{{ t('gv.orbit.resilience_hint') }}</p>
        <p class="mt-1 text-[11px] leading-snug text-fg-subtle">{{ t('gv.orbit.core_hint') }}</p>
      </div>
      <button type="button" class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>

    <div v-if="activeBackups || groups.length" class="shrink-0 border-b border-line py-1 text-xs" aria-live="polite">
      <p v-if="activeBackups" class="px-3 py-1 text-warn-text">{{ t('gv.orbit.backups_active', { count: activeBackups }) }}</p>
      <div v-for="g in groups" :key="g.kind">
        <button
          type="button"
          class="flex w-full items-start gap-1.5 px-3 py-1 text-left hover:bg-control-hover focus-visible:bg-control-hover"
          :class="g.tone"
          :aria-expanded="expanded === g.kind"
          @click="toggle(g.kind)"
        >
          <ChevronRight class="mt-px size-3.5 shrink-0 transition-transform" :class="expanded === g.kind && 'rotate-90'" aria-hidden="true" />
          <span class="min-w-0 flex-1">{{ t(g.key, { count: g.devices.length }) }}</span>
        </button>
        <div v-if="expanded === g.kind" class="pb-1 pl-8">
          <p class="pr-3 pb-1 text-[11px] leading-snug text-fg-subtle">{{ t(g.hint) }}</p>
          <ul class="max-h-36 overflow-y-auto pr-1.5">
            <li v-for="d in g.devices" :key="d.id">
              <button
                type="button"
                class="w-full truncate rounded-md px-2 py-1 text-left text-fg hover:bg-control-hover focus-visible:bg-control-hover"
                @click="emit('select', d.id)"
              >
                {{ d.label }}
              </button>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <ol v-if="points.length" class="min-h-0 overflow-y-auto p-1.5">
      <li v-for="p in points" :key="p.id">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-control-hover focus-visible:bg-control-hover"
          :title="t('gv.orbit.spof_cuts', { count: p.cutOff })"
          @click="emit('select', p.id)"
        >
          <span class="min-w-0 flex-1 truncate text-fg">{{ p.label }}</span>
          <span class="shrink-0 font-mono text-xs text-warn-text tabular">{{ t('gv.orbit.spof_cuts_short', { count: p.cutOff }) }}</span>
        </button>
      </li>
    </ol>
    <p v-else class="flex items-center gap-2 p-3 text-xs text-fg-muted">
      <ShieldCheck class="size-4 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.orbit.no_spof') }}
    </p>
  </div>
</template>
