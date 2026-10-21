<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { Subnet } from '@/types';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';

/**
 * Gateway address and VLAN tag of one subnet. Empty gateway means "automatic" (the detected
 * default route, else .1), shown as placeholder. Each field saves on blur when it changed.
 */
const props = defineProps<{ subnet: Subnet }>();
const emit = defineEmits<{ save: [patch: { gateway_ip?: string | null; vlan_id?: number | null }] }>();

const gateway = ref(props.subnet.gateway_ip ?? '');
const vlan = ref<string | number | null>(props.subnet.vlan_id ?? '');
watch(
  () => props.subnet,
  (s) => {
    gateway.value = s.gateway_ip ?? '';
    vlan.value = s.vlan_id ?? '';
  },
);

const autoHint = computed(() =>
  props.subnet.gateway_suggestion
    ? t(props.subnet.gateway_source === 'detected' ? 'subnet_gateway.auto_detected' : 'subnet_gateway.auto_suggested', { ip: props.subnet.gateway_suggestion })
    : t('subnet_gateway.gateway'),
);

function saveGateway() {
  const value = String(gateway.value ?? '').trim();
  if (value !== (props.subnet.gateway_ip ?? '')) emit('save', { gateway_ip: value || null });
}
function saveVlan() {
  const value = String(vlan.value ?? '').trim();
  const current = props.subnet.vlan_id != null ? String(props.subnet.vlan_id) : '';
  if (value !== current) emit('save', { vlan_id: value ? Number(value) : null });
}
</script>

<template>
  <div class="grid grid-cols-[1fr_6rem] gap-3">
    <label class="flex min-w-0 flex-col gap-1.5">
      <span class="text-xs font-medium text-fg">{{ t('subnet_gateway.gateway') }}</span>
      <Input v-model="gateway" mono inputmode="decimal" :placeholder="autoHint" :aria-label="t('subnet_gateway.gateway_for', { cidr: subnet.cidr })" @blur="saveGateway" />
    </label>
    <label class="flex min-w-0 flex-col gap-1.5">
      <span class="text-xs font-medium text-fg">{{ t('subnet_gateway.vlan') }}</span>
      <Input v-model="vlan" mono type="number" min="1" max="4094" placeholder="—" :aria-label="t('subnet_gateway.vlan_for', { cidr: subnet.cidr })" @blur="saveVlan" />
    </label>
  </div>
</template>
