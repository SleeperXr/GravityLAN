<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { canonicalCidr } from '@shared/components/Network/subnet/model';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';

/** Add a subnet: "192.168.20", "192.168.20.0/24" or a single address; shows the network it becomes. */
const open = defineModel<boolean>('open', { default: false });
defineProps<{ busy?: boolean }>();
const emit = defineEmits<{ add: [cidr: string, name: string] }>();

const input = ref('');
const name = ref('');
const touched = ref(false);
watch(open, (isOpen) => {
  if (isOpen) {
    input.value = '';
    name.value = '';
    touched.value = false;
  }
});

const cidr = computed(() => canonicalCidr(input.value));
const error = computed(() => (touched.value && input.value.trim() && !cidr.value ? t('network.invalid_format') : null));

function submit() {
  touched.value = true;
  if (!cidr.value) return;
  emit('add', cidr.value, name.value.trim() || `Network ${cidr.value}`);
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('network.add_subnet')" size="sm">
    <form id="add-subnet-form" class="space-y-4" @submit.prevent="submit">
      <Field v-slot="{ id, describedBy, invalid }" :label="t('network.subnets')" :hint="cidr ? `→ ${cidr}` : t('network.new_subnet_prompt')" :error="error">
        <Input :id="id" v-model="input" mono inputmode="decimal" placeholder="192.168.20.0/24" :aria-describedby="describedBy" :invalid="invalid" autofocus @blur="touched = true" />
      </Field>
      <Field v-slot="{ id }" :label="t('network.name')">
        <Input :id="id" v-model="name" :placeholder="cidr ? `Network ${cidr}` : ''" />
      </Field>
    </form>
    <template #footer>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button type="submit" form="add-subnet-form" variant="primary" :loading="busy" :disabled="!cidr">{{ t('network.add_subnet') }}</Button>
    </template>
  </Dialog>
</template>
