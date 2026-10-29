<script setup lang="ts">
import { ref, useId, watch } from 'vue';
import { api } from '@/api/client';
import type { RackItem } from '@/types';
import Button from '@/components/ui/Button.vue';
import Dialog from '@/components/ui/Dialog.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import Textarea from '@/components/ui/Textarea.vue';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';
import { apiErrorMessage } from '@/lib/apiErrors';
import { RACK_KINDS, kindOf } from './rackKinds';
import { PORT_KINDS } from './rackModel';

/**
 * Creates or edits a piece of rack equipment. A new item starts in the tray; drag it onto a free place.
 * Its ports are set in the ports panel once it exists, except the starting count given here.
 */
const open = defineModel<boolean>('open', { required: true });
const props = defineProps<{ rackId: number; item: RackItem | null }>();
const emit = defineEmits<{ saved: [item: RackItem] }>();

const id = useId();
const { showToast } = useToast();
const saving = ref(false);
const emptyForm = () => ({ name: '', kind: 'switch_unmanaged', height: 1, notes: '', ports: 8, portKind: 'RJ45' });
const form = ref(emptyForm());

const kindOptions = RACK_KINDS.map((k) => ({ value: k.value, label: t(`gv.rack.kind_${k.value}`) }));
const portKindOptions = PORT_KINDS.map((k) => ({ value: k, label: k }));

watch(open, (isOpen) => {
  if (!isOpen) return;
  const item = props.item;
  form.value = item
    ? { name: item.name, kind: item.kind, height: item.rack_height, notes: item.notes ?? '', ports: 0, portKind: 'RJ45' }
    : emptyForm();
});

// A new item takes the usual height and ports of its kind; the user can still change them
watch(
  () => form.value.kind,
  (kind) => {
    if (props.item || !open.value) return;
    const defaults = kindOf(kind);
    form.value.height = defaults.height;
    form.value.ports = defaults.ports;
    form.value.portKind = defaults.portKind;
  },
);

async function save() {
  const name = form.value.name.trim();
  if (!name) return;
  saving.value = true;
  const body = { name, kind: form.value.kind, rack_height: form.value.height, notes: form.value.notes.trim() || null };
  try {
    const saved = props.item
      ? await api.updateRackItem(props.item.id, body)
      : await api.createRackItem({ ...body, rack_id: props.rackId, port_count: form.value.ports, port_kind: form.value.portKind });
    open.value = false;
    emit('saved', saved);
  } catch (err) {
    showToast('error', t('gv.rack.item_save'), apiErrorMessage(err));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog v-model:open="open" :title="item ? t('gv.rack.edit_item') : t('gv.rack.add_item')" size="sm">
    <form :id="`${id}-form`" class="space-y-4" @submit.prevent="save">
      <div class="space-y-1.5">
        <label :for="`${id}-name`" class="text-xs font-medium text-fg">{{ t('gv.rack.item_name') }}</label>
        <Input :id="`${id}-name`" v-model="form.name" :placeholder="t('gv.rack.item_name_hint')" required autofocus />
      </div>
      <div class="grid grid-cols-[minmax(0,1fr)_7.5rem] gap-3">
        <div class="space-y-1.5">
          <label :for="`${id}-kind`" class="text-xs font-medium text-fg">{{ t('gv.rack.item_kind') }}</label>
          <Select :id="`${id}-kind`" v-model="form.kind" :options="kindOptions" />
        </div>
        <div class="space-y-1.5">
          <label :for="`${id}-height`" class="text-xs font-medium text-fg">{{ t('gv.rack.item_height') }}</label>
          <Input :id="`${id}-height`" :model-value="form.height" type="number" min="1" max="10" mono @update:model-value="(v) => (form.height = Math.min(10, Math.max(1, Number(v) || 1)))" />
        </div>
      </div>
      <fieldset v-if="!item" class="space-y-2">
        <legend class="gl-eyebrow mb-2">{{ t('gv.rack.ports_title') }}</legend>
        <div class="grid grid-cols-[minmax(0,1fr)_7.5rem] gap-3">
          <div class="space-y-1.5">
            <label :for="`${id}-port-kind`" class="text-xs font-medium text-fg">{{ t('gv.rack.ports_kind') }}</label>
            <Select :id="`${id}-port-kind`" v-model="form.portKind" :options="portKindOptions" />
          </div>
          <div class="space-y-1.5">
            <label :for="`${id}-ports`" class="text-xs font-medium text-fg">{{ t('gv.rack.ports_count') }}</label>
            <Input :id="`${id}-ports`" :model-value="form.ports" type="number" min="0" max="96" mono @update:model-value="(v) => (form.ports = Math.min(96, Math.max(0, Number(v) || 0)))" />
          </div>
        </div>
      </fieldset>
      <div class="space-y-1.5">
        <label :for="`${id}-notes`" class="text-xs font-medium text-fg">{{ t('gv.rack.item_notes') }}</label>
        <Textarea :id="`${id}-notes`" v-model="form.notes" rows="2" />
      </div>
    </form>
    <template #footer>
      <Button @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" :form="`${id}-form`" :loading="saving">{{ item ? t('gv.rack.item_save') : t('gv.rack.add_item') }}</Button>
    </template>
  </Dialog>
</template>
