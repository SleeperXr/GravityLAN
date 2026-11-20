<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowRight, Check } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { MacConflictDevice, MacConflictGroup } from '@/types';
import { buildAdoptPayload, hasSharedDevices } from '@/lib/macConflicts';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Confirm adopting an observed MAC. When the group has multiple devices sharing the same
 * documented MAC (e.g. ipvlan host), lists all affected devices and offers "only this device"
 * vs "all N devices".
 */
const open = defineModel<boolean>('open', { default: false });
const props = withDefaults(
  defineProps<{
    group: MacConflictGroup | null;
    /** Target device; defaults to the first device in the group when opened from a group row. */
    device?: MacConflictDevice | null;
    /** Initial choice when the group has multiple devices ('single' in device editor, 'all' in overview). */
    defaultScope?: 'single' | 'all';
  }>(),
  { device: null, defaultScope: 'single' },
);
const emit = defineEmits<{ adopted: [changedIds: number[]] }>();

const { showToast } = useToast();
const scope = ref<'single' | 'all'>('single');
const submitting = ref(false);

const targetDevice = computed<MacConflictDevice | null>(() => props.device ?? props.group?.devices[0] ?? null);
const isSharedGroup = computed(() => (props.group ? hasSharedDevices(props.group) : false));

watch(
  () => [open.value, props.group, props.defaultScope] as const,
  ([isOpen, group, defScope]) => {
    if (!isOpen || !group) return;
    scope.value = hasSharedDevices(group) ? defScope : 'single';
  },
  { immediate: true },
);

async function submit() {
  if (!props.group || !targetDevice.value || submitting.value) return;
  submitting.value = true;
  try {
    const payload = buildAdoptPayload(props.group, scope.value === 'all');
    const result = await api.setDeviceMac(targetDevice.value.id, payload);
    const count = result.changed_device_ids.length;
    showToast('success', t('gv.mac_conflicts.adopt_confirm'), t('gv.mac_conflicts.adopt_success', { count: Math.max(count, 1) }));
    open.value = false;
    emit('adopted', result.changed_device_ids);
  } catch (err) {
    showToast('error', t('notifications.save_failed'), (err as Error).message);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog
    v-model:open="open"
    :title="t('gv.mac_conflicts.adopt_title')"
    :description="t('gv.mac_conflicts.adopt_desc')"
    size="md"
    top
  >
    <div v-if="group && targetDevice" class="space-y-4">
      <div class="flex flex-wrap items-center gap-2 rounded-md border border-line bg-raised px-3.5 py-3 font-mono text-xs tabular">
        <div class="min-w-0">
          <span class="block font-sans text-micro text-fg-subtle">{{ t('gv.mac_conflicts.documented_mac') }}</span>
          <span class="text-fg-muted">{{ group.documented_mac || t('gv.mac_conflicts.none') }}</span>
        </div>
        <ArrowRight class="size-4 shrink-0 text-fg-subtle" aria-hidden="true" />
        <div class="min-w-0">
          <span class="block font-sans text-micro text-fg-subtle">{{ t('gv.mac_conflicts.observed_mac') }}</span>
          <span class="font-semibold text-fg">{{ group.observed_mac }}</span>
        </div>
      </div>

      <template v-if="isSharedGroup">
        <fieldset class="space-y-2">
          <legend class="text-xs font-medium text-fg">{{ t('gv.mac_conflicts.adopt_scope_label') }}</legend>
          <label
            class="flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 text-sm transition-colors"
            :class="scope === 'single' ? 'border-accent/50 bg-accent/10 text-fg' : 'border-line bg-raised text-fg-muted hover:border-line-strong'"
          >
            <input v-model="scope" type="radio" name="mac-adopt-scope" value="single" class="mt-0.5 accent-accent" />
            <span class="min-w-0 flex-1">{{ t('gv.mac_conflicts.adopt_only_this', { name: targetDevice.name, ip: targetDevice.ip }) }}</span>
          </label>
          <label
            class="flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2.5 text-sm transition-colors"
            :class="scope === 'all' ? 'border-accent/50 bg-accent/10 text-fg' : 'border-line bg-raised text-fg-muted hover:border-line-strong'"
          >
            <input v-model="scope" type="radio" name="mac-adopt-scope" value="all" class="mt-0.5 accent-accent" />
            <span class="min-w-0 flex-1">{{ t('gv.mac_conflicts.adopt_all_shared', { count: group.devices.length }) }}</span>
          </label>
        </fieldset>

        <div>
          <p class="gl-eyebrow mb-1.5">{{ t('gv.mac_conflicts.adopt_affected_devices') }}</p>
          <ul class="max-h-44 divide-y divide-line overflow-y-auto rounded-md border border-line bg-raised">
            <li v-for="dev in group.devices" :key="dev.id" class="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs">
              <span class="font-medium text-fg">{{ dev.name }}</span>
              <span class="font-mono text-fg-subtle tabular">{{ dev.ip }}</span>
            </li>
          </ul>
        </div>
      </template>

      <div v-else class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-raised px-3.5 py-2.5 text-xs">
        <span class="font-medium text-fg">{{ targetDevice.name }}</span>
        <span class="font-mono text-fg-subtle tabular">{{ targetDevice.ip }}</span>
      </div>
    </div>

    <template #footer>
      <Button variant="ghost" :disabled="submitting" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :loading="submitting" @click="submit">
        <Check v-if="!submitting" aria-hidden="true" />
        {{ t('gv.mac_conflicts.adopt_confirm') }}
      </Button>
    </template>
  </Dialog>
</template>
