<script setup lang="ts">
import { ref, watch } from 'vue';
import { Save } from 'lucide-vue-next';
import { ApiError, api } from '@/api/client';
import type { Device } from '@/types';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Manual MAC correction dialog for a single device. Sends PUT /api/devices/{id}/mac,
 * displays 422 validation errors inline and reassures that the device keeps its identity.
 */
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ device: Device }>();
const emit = defineEmits<{ changed: [newMac: string] }>();

const { showToast } = useToast();
const macInput = ref('');
const fieldError = ref<string | null>(null);
const submitting = ref(false);

watch(
  () => [open.value, props.device.mac] as const,
  ([isOpen, currentMac]) => {
    if (!isOpen) return;
    macInput.value = currentMac ?? '';
    fieldError.value = null;
  },
  { immediate: true },
);

async function submit() {
  if (submitting.value) return;
  const trimmed = macInput.value.trim();
  fieldError.value = null;
  submitting.value = true;
  try {
    const result = await api.setDeviceMac(props.device.id, { mac: trimmed, apply_to_shared: false });
    if (result.changed_device_ids.length > 0) {
      showToast('success', t('gv.mac_conflicts.manual_save'), t('gv.mac_conflicts.manual_success'));
    } else {
      showToast('info', t('gv.mac_conflicts.manual_save'), t('gv.mac_conflicts.manual_unchanged'));
    }
    open.value = false;
    emit('changed', trimmed.toLowerCase().replaceAll('-', ':'));
  } catch (err) {
    if (err instanceof ApiError && err.status === 422) {
      fieldError.value = err.message;
    } else {
      showToast('error', t('notifications.save_failed'), (err as Error).message);
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog
    v-model:open="open"
    :title="t('gv.mac_conflicts.manual_title')"
    :description="t('gv.mac_conflicts.manual_desc')"
    size="sm"
    top
  >
    <form id="mac-manual-form" class="space-y-4" @submit.prevent="submit">
      <div class="flex items-center justify-between gap-2 rounded-md border border-line bg-raised px-3.5 py-2.5 text-xs">
        <span class="text-fg-subtle">{{ t('gv.mac_conflicts.manual_current') }}</span>
        <span class="font-mono text-fg tabular">{{ device.mac || t('gv.mac_conflicts.none') }}</span>
      </div>

      <Field
        v-slot="{ id, describedBy, invalid }"
        :label="t('gv.mac_conflicts.manual_label')"
        :hint="t('gv.mac_conflicts.manual_hint')"
        :error="fieldError"
        required
      >
        <Input
          :id="id"
          v-model="macInput"
          :placeholder="t('gv.mac_conflicts.manual_placeholder')"
          :aria-describedby="describedBy"
          :invalid="invalid"
          mono
          autofocus
          autocomplete="off"
          spellcheck="false"
          @update:model-value="fieldError = null"
        />
      </Field>
    </form>

    <template #footer>
      <Button variant="ghost" :disabled="submitting" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button type="submit" form="mac-manual-form" variant="primary" :loading="submitting" :disabled="!macInput.trim()">
        <Save v-if="!submitting" aria-hidden="true" />
        {{ t('gv.mac_conflicts.manual_save') }}
      </Button>
    </template>
  </Dialog>
</template>
