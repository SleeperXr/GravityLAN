<script setup lang="ts">
import { ref } from 'vue';
import { AlertTriangle, ArrowRight, Check, X } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { MacConflictGroup } from '@/types';
import { groupSources, hasSharedDevices, macConflictGroupKey, sourceLabel } from '@/lib/macConflicts';
import Badge from '@/components/ui/Badge.vue';
import Button from '@/components/ui/Button.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import MacAdoptDialog from './MacAdoptDialog.vue';
import { useConfirm } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Compact overview card for all open MAC conflicts: one row per (documented, observed) MAC group,
 * with direct Adopt / Dismiss actions and links to the affected devices.
 */
defineProps<{ groups: MacConflictGroup[] }>();
const emit = defineEmits<{ resolved: []; openDevice: [deviceId: number] }>();

const { confirm } = useConfirm();
const { showToast } = useToast();

const adoptOpen = ref(false);
const adoptGroup = ref<MacConflictGroup | null>(null);
const dismissingKey = ref<string | null>(null);

function openAdopt(group: MacConflictGroup) {
  adoptGroup.value = group;
  adoptOpen.value = true;
}

async function dismissGroup(group: MacConflictGroup) {
  const key = macConflictGroupKey(group);
  if (dismissingKey.value) return;
  const multi = hasSharedDevices(group);
  const ok = await confirm({
    title: t('gv.mac_conflicts.dismiss_title'),
    message: multi
      ? t('gv.mac_conflicts.dismiss_group_message', { mac: group.observed_mac, count: group.devices.length })
      : t('gv.mac_conflicts.dismiss_message', { mac: group.observed_mac }),
    confirmLabel: t('gv.mac_conflicts.dismiss_confirm'),
  });
  if (!ok) return;
  dismissingKey.value = key;
  try {
    for (const dev of group.devices) {
      await api.dismissMacObservation(dev.id, group.observed_mac);
    }
    showToast('success', t('gv.mac_conflicts.dismiss_title'), t('gv.mac_conflicts.dismiss_success'));
    emit('resolved');
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    dismissingKey.value = null;
  }
}
</script>

<template>
  <section v-if="groups.length > 0" class="gl-card overflow-hidden" aria-labelledby="mac-conflicts-title">
    <header class="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
      <div class="flex min-w-0 items-center gap-2">
        <AlertTriangle class="size-4 shrink-0 text-warn-text" aria-hidden="true" />
        <div class="min-w-0">
          <h2 id="mac-conflicts-title" class="text-sm font-semibold text-fg">{{ t('gv.mac_conflicts.title') }}</h2>
          <p class="text-xs text-fg-subtle">{{ t('gv.mac_conflicts.subtitle') }}</p>
        </div>
      </div>
      <Badge tone="warn" mono>{{ groups.length }}</Badge>
    </header>

    <ul class="divide-y divide-line">
      <li
        v-for="group in groups"
        :key="macConflictGroupKey(group)"
        class="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="min-w-0 flex-1 space-y-1.5">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-mono text-xs text-fg-muted tabular">{{ group.documented_mac || t('gv.mac_conflicts.none') }}</span>
            <ArrowRight class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
            <span class="font-mono text-xs font-semibold text-fg tabular">{{ group.observed_mac }}</span>
            <Badge v-for="src in groupSources(group)" :key="src" tone="warn">{{ sourceLabel(src) }}</Badge>
            <Badge v-if="hasSharedDevices(group)" tone="neutral" mono>
              {{ t('gv.mac_conflicts.devices_count', { count: group.devices.length }) }}
            </Badge>
          </div>

          <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <button
              v-for="dev in group.devices"
              :key="dev.id"
              type="button"
              class="inline-flex items-center gap-1.5 rounded-sm bg-raised px-2 py-0.5 text-fg transition-colors hover:bg-control-hover"
              @click="emit('openDevice', dev.id)"
            >
              <span class="font-medium">{{ dev.name }}</span>
              <span class="font-mono text-fg-subtle tabular">{{ dev.ip }}</span>
            </button>
          </div>

          <p class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-fg-subtle">
            <span>{{ t('gv.mac_conflicts.first_seen') }}: <RelativeTime :date="group.first_seen" /></span>
            <span>{{ t('gv.mac_conflicts.last_seen') }}: <RelativeTime :date="group.last_seen" /></span>
          </p>
        </div>

        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" @click="openAdopt(group)">
            <Check aria-hidden="true" />
            {{ t('gv.mac_conflicts.adopt') }}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            :loading="dismissingKey === macConflictGroupKey(group)"
            @click="dismissGroup(group)"
          >
            <X v-if="dismissingKey !== macConflictGroupKey(group)" aria-hidden="true" />
            {{ t('gv.mac_conflicts.dismiss') }}
          </Button>
        </div>
      </li>
    </ul>

    <MacAdoptDialog
      v-model:open="adoptOpen"
      :group="adoptGroup"
      :default-scope="adoptGroup && hasSharedDevices(adoptGroup) ? 'all' : 'single'"
      @adopted="emit('resolved')"
    />
  </section>
</template>
