<script setup lang="ts">
import { ref } from 'vue';
import { AlertTriangle, Check, X } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { MacConflictDevice, MacConflictGroup } from '@/types';
import { hasSharedDevices, macConflictGroupKey, sourceLabel, type DeviceMacConflict } from '@/lib/macConflicts';
import Badge from '@/components/ui/Badge.vue';
import Button from '@/components/ui/Button.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import MacAdoptDialog from './MacAdoptDialog.vue';
import { useConfirm } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Calm, clearly visible notice inside DeviceEditor when another MAC answered at this device's IP.
 * Offers adopting (with shared-group choice when applicable) or dismissing the observation.
 */
defineProps<{ conflicts: DeviceMacConflict[] }>();
const emit = defineEmits<{ resolved: [] }>();

const { confirm } = useConfirm();
const { showToast } = useToast();

const adoptOpen = ref(false);
const adoptGroup = ref<MacConflictGroup | null>(null);
const adoptDevice = ref<MacConflictDevice | null>(null);
const dismissingKey = ref<string | null>(null);

function openAdopt(entry: DeviceMacConflict) {
  adoptGroup.value = entry.group;
  adoptDevice.value = entry.device;
  adoptOpen.value = true;
}

async function dismiss(entry: DeviceMacConflict) {
  const key = macConflictGroupKey(entry.group);
  if (dismissingKey.value) return;
  const ok = await confirm({
    title: t('gv.mac_conflicts.dismiss_title'),
    message: t('gv.mac_conflicts.dismiss_message', { mac: entry.group.observed_mac }),
    confirmLabel: t('gv.mac_conflicts.dismiss_confirm'),
  });
  if (!ok) return;
  dismissingKey.value = key;
  try {
    await api.dismissMacObservation(entry.device.id, entry.group.observed_mac);
    showToast('success', t('gv.mac_conflicts.dismiss_title'), t('gv.mac_conflicts.dismiss_success'));
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    dismissingKey.value = null;
    emit('resolved');
  }
}
</script>

<template>
  <div v-if="conflicts.length > 0" class="mb-4 space-y-2.5" role="region" :aria-label="t('gv.mac_conflicts.title')">
    <section
      v-for="entry in conflicts"
      :key="macConflictGroupKey(entry.group)"
      class="rounded-md border border-warn/35 bg-warn/10 px-3.5 py-3 text-xs text-fg"
    >
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="flex min-w-0 items-center gap-2">
          <AlertTriangle class="size-4 shrink-0 text-warn-text" aria-hidden="true" />
          <p class="font-semibold text-warn-text">{{ t('gv.mac_conflicts.device_heading') }}</p>
        </div>
        <Badge tone="warn">{{ sourceLabel(entry.device.source) }}</Badge>
      </div>

      <dl class="mt-2.5 grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
        <div>
          <dt class="text-fg-subtle">{{ t('gv.mac_conflicts.documented_mac') }}</dt>
          <dd class="font-mono text-fg tabular">{{ entry.group.documented_mac || t('gv.mac_conflicts.none') }}</dd>
        </div>
        <div>
          <dt class="text-fg-subtle">{{ t('gv.mac_conflicts.observed_mac') }}</dt>
          <dd class="font-mono font-semibold text-fg tabular">{{ entry.group.observed_mac }}</dd>
        </div>
        <div>
          <dt class="text-fg-subtle">{{ t('gv.mac_conflicts.first_seen') }}</dt>
          <dd class="text-fg-muted"><RelativeTime :date="entry.group.first_seen" /></dd>
        </div>
        <div>
          <dt class="text-fg-subtle">{{ t('gv.mac_conflicts.last_seen') }}</dt>
          <dd class="text-fg-muted"><RelativeTime :date="entry.group.last_seen" /></dd>
        </div>
      </dl>

      <p v-if="hasSharedDevices(entry.group)" class="mt-2 text-fg-muted">
        {{ t('gv.mac_conflicts.shared_hint', { count: entry.group.devices.length }) }}
      </p>

      <div class="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" @click="openAdopt(entry)">
          <Check aria-hidden="true" />
          {{ t('gv.mac_conflicts.adopt') }}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          :loading="dismissingKey === macConflictGroupKey(entry.group)"
          @click="dismiss(entry)"
        >
          <X v-if="dismissingKey !== macConflictGroupKey(entry.group)" aria-hidden="true" />
          {{ t('gv.mac_conflicts.dismiss') }}
        </Button>
      </div>
    </section>

    <MacAdoptDialog
      v-model:open="adoptOpen"
      :group="adoptGroup"
      :device="adoptDevice"
      default-scope="single"
      @refresh="emit('resolved')"
    />
  </div>
</template>
