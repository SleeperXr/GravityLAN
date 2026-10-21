<script setup lang="ts">
import { Trash2 } from 'lucide-vue-next';
import type { Subnet } from '@/types';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Switch from '@/components/ui/Switch.vue';
import GatewayFields from './GatewayFields.vue';
import SubnetModeBadge from './SubnetModeBadge.vue';
import { t } from '@/i18n';

type SubnetPatch = { name?: string; dns_server?: string | null; is_enabled?: boolean; gateway_ip?: string | null; vlan_id?: number | null };

/** Name, DNS, scan on/off, gateway and VLAN of every subnet; fields save on blur. */
const open = defineModel<boolean>('open', { default: false });
defineProps<{ subnets: Subnet[] }>();
const emit = defineEmits<{ update: [id: number, patch: SubnetPatch]; delete: [subnet: Subnet] }>();

function onBlur(sub: Subnet, key: 'name' | 'dns_server', event: FocusEvent) {
  const value = (event.target as HTMLInputElement).value.trim();
  if (key === 'name' && value && value !== sub.name) emit('update', sub.id, { name: value });
  if (key === 'dns_server' && value !== (sub.dns_server ?? '')) emit('update', sub.id, { dns_server: value || null });
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('network.subnet_config')" size="lg">
    <ul class="space-y-3">
      <li v-for="sub in subnets" :key="sub.id" class="space-y-3 rounded-md border border-line bg-raised p-4">
        <div class="flex flex-wrap items-center gap-2">
          <strong class="font-mono text-sm text-fg">{{ sub.cidr }}</strong>
          <SubnetModeBadge :subnet="sub" long />
          <label class="ml-auto flex items-center gap-2 text-xs text-fg-muted">
            {{ t('network.subnet_scan') }}
            <Switch :model-value="sub.is_enabled !== false" :aria-label="t('network.subnet_scan_label', { cidr: sub.cidr })" @update:model-value="(v) => emit('update', sub.id, { is_enabled: v })" />
          </label>
          <Button size="icon-sm" variant="danger-ghost" :aria-label="`${t('common.delete')} ${sub.cidr}`" @click="emit('delete', sub)"><Trash2 aria-hidden="true" /></Button>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="flex flex-col gap-1.5">
            <span class="text-xs font-medium text-fg">{{ t('network.area_name') }}</span>
            <Input :model-value="sub.name" @blur="(e: FocusEvent) => onBlur(sub, 'name', e)" />
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="text-xs font-medium text-fg">{{ t('network.dns_gateway') }}</span>
            <Input :model-value="sub.dns_server ?? ''" mono :placeholder="t('network.dns_gateway')" @blur="(e: FocusEvent) => onBlur(sub, 'dns_server', e)" />
          </label>
        </div>
        <GatewayFields :subnet="sub" @save="(patch) => emit('update', sub.id, patch)" />
      </li>
    </ul>
    <template #footer>
      <Button variant="primary" @click="open = false">{{ t('common.finish') }}</Button>
    </template>
  </Dialog>
</template>
