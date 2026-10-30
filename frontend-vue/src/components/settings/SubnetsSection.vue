<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { Plus, Router, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Subnet, SubnetInfo } from '@/types';
import { normalizeCidr } from '@/lib/subnetModel';
import SettingsSection from './SettingsSection.vue';
import ActionRow from './ActionRow.vue';
import RouterImportPanel from './RouterImportPanel.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Switch from '@/components/ui/Switch.vue';
import GatewayFields from '@/components/network/GatewayFields.vue';
import SubnetModeBadge from '@/components/network/SubnetModeBadge.vue';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { useNetworkStore } from '@/stores/network';
import { t } from '@/i18n';

/** The scan subnets, the same list as the tabs of the IP overview. */
const { showToast } = useToast();
const { confirm } = useConfirm();
const store = useNetworkStore();

const subnets = ref<Subnet[]>([]);
const detected = ref<SubnetInfo[]>([]);
const loaded = ref(false);
const editing = ref<number | null>(null);
const importing = ref(false);
const cidr = ref('');
const name = ref('');
const adding = ref(false);

async function load() {
  try {
    const list = await api.getSubnetsList();
    subnets.value = Array.isArray(list) ? list : [];
  } catch {
    // keep the list
  } finally {
    loaded.value = true;
  }
  void store.loadData(true);
}

onMounted(() => {
  void load();
  api
    .getSubnets()
    .then((list) => (detected.value = Array.isArray(list) ? list.filter((s) => !s.is_virtual) : []))
    .catch(() => (detected.value = []));
});

const failed = (err: unknown) => showToast('error', t('common.error'), `${t('settings.subnet_failed')} ${(err as Error).message}`);

async function add(value: string, label = ''): Promise<boolean> {
  try {
    const created = await api.createSubnet({ cidr: value.trim(), name: label.trim() });
    showToast('success', t('notifications.saved'), t('settings.subnet_added', { cidr: created.cidr }));
    await load();
    return true;
  } catch (err) {
    failed(err);
    return false;
  }
}

async function submit() {
  if (!cidr.value.trim()) return;
  adding.value = true;
  if (await add(cidr.value, name.value)) {
    cidr.value = '';
    name.value = '';
  }
  adding.value = false;
}

async function setEnabled(sub: Subnet, isEnabled: boolean) {
  subnets.value = subnets.value.map((s) => (s.id === sub.id ? { ...s, is_enabled: isEnabled } : s));
  try {
    await api.updateSubnet(sub.id, { is_enabled: isEnabled });
    void store.loadData(true);
  } catch (err) {
    failed(err);
    await load();
  }
}

async function updateGateway(sub: Subnet, patch: { gateway_ip?: string | null; vlan_id?: number | null }) {
  try {
    const updated = await api.updateSubnet(sub.id, patch);
    subnets.value = subnets.value.map((s) => (s.id === sub.id ? updated : s));
    showToast('success', t('notifications.saved'), t('subnet_gateway.saved', { cidr: sub.cidr }));
  } catch (err) {
    failed(err);
  }
}

async function remove(sub: Subnet) {
  const ok = await confirm({ title: t('settings.subnet_delete', { cidr: sub.cidr }), message: t('settings.subnet_delete_confirm', { cidr: sub.cidr }), danger: true, confirmLabel: t('common.delete') });
  if (!ok) return;
  try {
    await api.deleteSubnet(sub.id);
    await load();
  } catch (err) {
    failed(err);
  }
}

const suggestions = computed(() => {
  const configured = new Set(subnets.value.map((s) => normalizeCidr(s.cidr)));
  return detected.value.filter((s) => !configured.has(normalizeCidr(s.subnet)));
});

function gatewayLabel(sub: Subnet): string {
  const ip = sub.gateway_ip || sub.gateway_suggestion;
  const parts = ip ? [`${t('subnet_gateway.gateway')} ${ip}${sub.gateway_ip ? '' : ` (${t('subnet_gateway.auto')})`}`] : [];
  if (sub.vlan_id != null) parts.push(`VLAN ${sub.vlan_id}`);
  return parts.join(' · ');
}
</script>

<template>
  <SettingsSection id="subnets" :title="t('settings.subnets')" :description="t('settings.subnets_desc')">
    <form class="grid gap-2 sm:grid-cols-[12rem_1fr_auto]" @submit.prevent="submit">
      <Input v-model="cidr" mono placeholder="192.168.110.0/24" :aria-label="t('settings.subnet_cidr')" aria-describedby="set-subnets-hint" />
      <Input v-model="name" :placeholder="t('settings.subnet_name_placeholder')" :aria-label="t('settings.subnet_name')" />
      <Button type="submit" :loading="adding" :disabled="!cidr.trim()"><Plus v-if="!adding" aria-hidden="true" />{{ t('settings.subnet_add') }}</Button>
    </form>
    <p id="set-subnets-hint" class="-mt-3 max-w-prose text-xs text-fg-subtle">{{ t('settings.subnets_hint') }}</p>

    <p v-if="loaded && subnets.length === 0" class="rounded-md border border-dashed border-line-strong px-4 py-5 text-center text-sm text-fg-muted">
      {{ detected.length > 0 ? t('settings.subnets_empty_auto', { subnets: detected.map((s) => s.subnet).join(', ') }) : t('settings.subnets_empty') }}
    </p>

    <!-- Ruled rows, not boxes: the section card is the only frame -->
    <ul v-if="subnets.length > 0" class="divide-y divide-line border-y border-line" :aria-label="t('settings.subnets')">
      <li v-for="sub in subnets" :key="sub.id" class="py-2.5">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div class="min-w-0 flex-1" :class="!sub.is_enabled && 'opacity-60'">
            <p class="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
              {{ sub.name }} <code class="font-mono text-xs font-normal text-fg-muted">{{ sub.cidr }}</code>
              <SubnetModeBadge :subnet="sub" />
              <span v-if="!sub.is_enabled" class="text-xs font-normal text-warn-text">{{ t('settings.subnet_paused') }}</span>
            </p>
            <p v-if="gatewayLabel(sub)" class="mt-0.5 font-mono text-xs text-fg-subtle">{{ gatewayLabel(sub) }}</p>
          </div>
          <Button size="icon-sm" variant="ghost" :aria-expanded="editing === sub.id" :aria-label="t('subnet_gateway.edit', { cidr: sub.cidr })" :title="t('subnet_gateway.edit', { cidr: sub.cidr })" @click="editing = editing === sub.id ? null : sub.id">
            <Router aria-hidden="true" />
          </Button>
          <label class="flex items-center gap-2 text-xs text-fg-muted">
            {{ t('settings.subnet_scan') }}
            <Switch :model-value="sub.is_enabled" :aria-label="t('settings.subnet_scan_label', { cidr: sub.cidr })" @update:model-value="(v) => setEnabled(sub, v)" />
          </label>
          <Button size="icon-sm" variant="danger-ghost" :aria-label="t('settings.subnet_delete', { cidr: sub.cidr })" @click="remove(sub)"><Trash2 aria-hidden="true" /></Button>
        </div>
        <div v-if="editing === sub.id" class="mt-3"><GatewayFields :subnet="sub" @save="(patch) => updateGateway(sub, patch)" /></div>
      </li>
    </ul>

    <div v-if="subnets.length > 0 && suggestions.length > 0" class="space-y-2">
      <p class="text-xs font-medium text-fg">{{ t('settings.subnets_detected') }}</p>
      <ul class="divide-y divide-line border-y border-dashed border-line-strong" :aria-label="t('settings.subnets_detected')">
        <li v-for="s in suggestions" :key="s.subnet" class="flex items-center gap-3 py-2">
          <div class="min-w-0 flex-1">
            <code class="font-mono text-sm text-fg">{{ s.subnet }}</code>
            <p class="text-xs text-fg-subtle">{{ s.interface_name }} · {{ s.ip_address }}</p>
          </div>
          <Button size="sm" :aria-label="t('settings.subnet_add_detected', { cidr: s.subnet })" @click="add(s.subnet, s.interface_name)"><Plus aria-hidden="true" />{{ t('settings.subnet_add') }}</Button>
        </li>
      </ul>
    </div>

    <ActionRow :title="t('router_import.title')" :description="t('router_import.desc')">
      <Button size="sm" :aria-expanded="importing" aria-controls="router-import-panel" @click="importing = !importing">
        <Router aria-hidden="true" />{{ importing ? t('router_import.close') : t('router_import.open') }}
      </Button>
    </ActionRow>
    <div v-if="importing" id="router-import-panel"><RouterImportPanel @applied="load" /></div>

    <ActionRow :title="t('settings.subnets_overview')" :description="t('settings.subnets_overview_desc')">
      <RouterLink to="/network" class="inline-flex h-8 items-center rounded-md border border-line bg-control px-2.5 text-xs font-medium text-fg hover:border-line-strong hover:bg-control-hover">
        {{ t('settings.subnets_overview_open') }}
      </RouterLink>
    </ActionRow>
  </SettingsSection>
</template>
