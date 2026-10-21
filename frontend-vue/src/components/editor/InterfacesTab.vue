<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { GitMerge, Plus, Unlink } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, DeviceInterface, MergeSuggestion } from '@/types';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import Input from '@/components/ui/Input.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { chipName, deviceLabel, deviceNetworks, networkColor, type NetworkChip } from '@/lib/networks';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { formatDateTime, t } from '@/i18n';

/** Addresses of a multi-homed device (router with VLAN gateways) and merge suggestions. */
const props = defineProps<{ device: Device }>();
const emit = defineEmits<{ changed: []; mergedAway: []; interfaces: [list: DeviceInterface[]] }>();
const { showToast } = useToast();
const { confirm } = useConfirm();

const interfaces = ref<DeviceInterface[]>(props.device.interfaces ?? []);
const suggestions = ref<MergeSuggestion[]>([]);
const labels = ref<Record<number, string>>({});
const busy = ref(false);
const newIp = ref('');
const newLabel = ref('');

async function reload() {
  const [ifaces, merge] = await Promise.all([
    api.getDeviceInterfaces(props.device.id),
    api.getMergeSuggestions().catch(() => [] as MergeSuggestion[]),
  ]);
  interfaces.value = ifaces;
  suggestions.value = merge;
  labels.value = Object.fromEntries(ifaces.map((i) => [i.id, i.label ?? '']));
  emit('interfaces', ifaces);
}
watch(() => props.device.id, () => void reload().catch(() => {}), { immediate: true });

const name = computed(() => deviceLabel(props.device));
const chips = computed(() => deviceNetworks({ ...props.device, interfaces: interfaces.value }));
const forThis = computed(() => suggestions.value.filter((s) => s.target_id === props.device.id));
const mergeMe = computed(() => suggestions.value.filter((s) => s.candidate.kind === 'device' && s.candidate.id === props.device.id));

async function run(action: () => Promise<unknown>, success: string) {
  busy.value = true;
  try {
    await action();
    showToast('success', t('common.success'), success);
    await reload();
    emit('changed');
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message || t('common.unknown'));
  } finally {
    busy.value = false;
  }
}

const ifaceOf = (chip: NetworkChip) => interfaces.value.find((i) => i.id === chip.interfaceId) ?? null;
const netMeta = (chip: NetworkChip) => [chipName(chip) !== chip.ip ? chipName(chip) : t('interfaces.no_subnet'), chip.vlanId != null ? `VLAN ${chip.vlanId}` : null].filter(Boolean).join(' · ');

function saveLabel(iface: DeviceInterface) {
  const label = (labels.value[iface.id] ?? '').trim();
  if (label === (iface.label ?? '')) return;
  void run(() => api.updateDeviceInterface(props.device.id, iface.id, { label: label || null }), t('interfaces.saved'));
}

async function removeIface(iface: DeviceInterface) {
  const ok = await confirm({ title: t('interfaces.remove', { ip: iface.ip }), message: t('interfaces.remove_confirm', { ip: iface.ip }), danger: true });
  if (ok) void run(() => api.removeDeviceInterface(props.device.id, iface.id), t('interfaces.removed', { ip: iface.ip }));
}

async function addIface() {
  const ip = newIp.value.trim();
  if (!ip) return;
  await run(() => api.addDeviceInterface(props.device.id, { ip, label: newLabel.value.trim() || null }), t('interfaces.added', { ip }));
  newIp.value = '';
  newLabel.value = '';
}

async function mergeSuggestion(s: MergeSuggestion) {
  const c = s.candidate;
  if (c.kind === 'device') {
    const ok = await confirm({ title: t('interfaces.merge_as_interface', { target: name.value }), message: t('interfaces.merge_confirm', { name: c.name || c.ip, ip: c.ip, target: name.value }) });
    if (!ok) return;
  }
  void run(
    () => api.mergeIntoDevice(props.device.id, c.kind === 'device' ? { source_device_id: c.id } : { ip: c.ip }),
    t('interfaces.merged', { ip: c.ip, target: name.value }),
  );
}

async function mergeAway(s: MergeSuggestion) {
  const ok = await confirm({ title: t('interfaces.merge_as_interface', { target: s.target_name }), message: t('interfaces.merge_confirm', { name: name.value, ip: props.device.ip, target: s.target_name }) });
  if (!ok) return;
  busy.value = true;
  try {
    await api.mergeIntoDevice(s.target_id, { source_device_id: props.device.id });
    showToast('success', t('common.success'), t('interfaces.merged', { ip: props.device.ip, target: s.target_name }));
    emit('changed');
    emit('mergedAway');
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
    busy.value = false;
  }
}
</script>

<template>
  <div class="space-y-6">
    <div v-for="s in mergeMe" :key="s.target_id" role="note" class="flex gap-3 rounded-md border border-warn/30 bg-warn/[0.07] p-3">
      <GitMerge class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
      <div class="min-w-0 flex-1 space-y-2">
        <p class="text-sm text-fg">{{ t('interfaces.looks_like_interface', { name, target: s.target_name, ip: s.target_ip }) }}</p>
        <div class="flex flex-wrap gap-1"><Badge v-for="r in s.reasons" :key="r">{{ t(`interfaces.reason_${r}`) }}</Badge></div>
        <div class="flex flex-wrap gap-2">
          <Button size="sm" variant="primary" :disabled="busy" @click="mergeAway(s)">{{ t('interfaces.merge_as_interface', { target: s.target_name }) }}</Button>
          <Button size="sm" :disabled="busy" @click="run(() => api.dismissMergeSuggestion({ target_id: s.target_id, kind: 'device', candidate_ip: device.ip }), t('interfaces.dismissed'))">
            {{ t('interfaces.dismiss') }}
          </Button>
        </div>
      </div>
    </div>

    <section aria-labelledby="iface-list-title" class="space-y-3">
      <div>
        <h3 id="iface-list-title" class="text-sm font-semibold text-fg">{{ t('interfaces.addresses') }}</h3>
        <p class="mt-1 text-xs leading-relaxed text-fg-subtle">{{ t('interfaces.addresses_hint') }}</p>
      </div>
      <ul class="divide-y divide-line rounded-md border border-line">
        <li v-for="chip in chips" :key="chip.ip" class="flex items-start gap-3 p-3" :class="chip.isPrimary && 'bg-raised'">
          <StatusDot class="mt-1.5" :state="chip.isOnline ? 'online' : 'offline'" :label="chip.isOnline ? t('network.online') : t('network.offline')" />
          <div class="min-w-0 flex-1 space-y-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-mono text-sm text-fg">{{ chip.ip }}</span>
              <Badge v-if="chip.isPrimary" tone="accent">{{ t('interfaces.primary') }}</Badge>
              <input
                v-if="ifaceOf(chip)"
                v-model="labels[ifaceOf(chip)!.id]"
                maxlength="100"
                :placeholder="t('interfaces.label_placeholder')"
                :aria-label="t('interfaces.label_for', { ip: chip.ip })"
                class="h-7 min-w-0 flex-1 rounded-sm border border-transparent bg-transparent px-1.5 text-sm text-fg-muted hover:border-line focus:border-info focus:bg-sunken focus:outline-none"
                @blur="saveLabel(ifaceOf(chip)!)"
                @keydown.enter="($event.target as HTMLInputElement).blur()"
              />
            </div>
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-subtle">
              <span class="inline-flex items-center gap-1.5"><span class="size-2 rounded-[3px]" :style="{ backgroundColor: chip.color }" aria-hidden="true" />{{ netMeta(chip) }}</span>
              <span v-if="ifaceOf(chip) ? ifaceOf(chip)!.mac : chip.isPrimary ? device.mac : null" class="font-mono">{{ ifaceOf(chip) ? ifaceOf(chip)!.mac : device.mac }}</span>
              <span v-if="ifaceOf(chip)?.last_seen">{{ t('interfaces.last_seen', { when: formatDateTime(ifaceOf(chip)!.last_seen!) }) }}</span>
            </div>
          </div>
          <Button v-if="ifaceOf(chip)" size="icon-sm" variant="danger-ghost" :disabled="busy" :aria-label="t('interfaces.remove', { ip: chip.ip })" :title="t('interfaces.remove', { ip: chip.ip })" @click="removeIface(ifaceOf(chip)!)">
            <Unlink aria-hidden="true" />
          </Button>
        </li>
      </ul>
      <form class="flex flex-wrap gap-2" @submit.prevent="addIface">
        <Input v-model="newIp" class="w-40" mono placeholder="192.168.110.1" inputmode="decimal" :aria-label="t('interfaces.add_ip')" />
        <Input v-model="newLabel" class="min-w-40 flex-1" maxlength="100" :placeholder="t('interfaces.label_placeholder')" :aria-label="t('interfaces.add_label')" />
        <Button type="submit" :disabled="busy || !newIp.trim()"><Plus aria-hidden="true" />{{ t('interfaces.add') }}</Button>
      </form>
    </section>

    <section v-if="forThis.length > 0" aria-labelledby="iface-suggestions-title" class="space-y-3">
      <div>
        <h3 id="iface-suggestions-title" class="text-sm font-semibold text-fg">{{ t('interfaces.suggestions') }}</h3>
        <p class="mt-1 text-xs text-fg-subtle">{{ t('interfaces.suggestions_hint', { name }) }}</p>
      </div>
      <ul class="space-y-2">
        <li v-for="s in forThis" :key="`${s.candidate.kind}:${s.candidate.id}`" class="rounded-md border border-dashed border-line-strong p-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="h-4 w-1 rounded-full" :style="{ backgroundColor: networkColor(s.candidate.subnet_id, s.candidate.ip) }" aria-hidden="true" />
            <StatusDot size="sm" :state="s.candidate.is_online ? 'online' : 'offline'" />
            <span class="font-mono text-sm text-fg">{{ s.candidate.ip }}</span>
            <span v-if="s.candidate.name" class="text-sm text-fg-muted">{{ s.candidate.name }}</span>
            <Badge>{{ t(s.candidate.kind === 'device' ? 'interfaces.kind_device' : 'interfaces.kind_discovered') }}</Badge>
          </div>
          <div class="mt-1.5 flex flex-wrap items-center gap-1 text-xs text-fg-subtle">
            <span v-if="s.candidate.subnet_name" class="mr-1">{{ s.candidate.subnet_name }}</span>
            <Badge v-for="r in s.reasons" :key="r">{{ t(`interfaces.reason_${r}`) }}</Badge>
          </div>
          <div class="mt-2.5 flex flex-wrap gap-2">
            <Button size="sm" variant="primary" :disabled="busy" @click="mergeSuggestion(s)"><GitMerge aria-hidden="true" />{{ t('interfaces.merge_as_interface', { target: s.target_name }) }}</Button>
            <Button size="sm" :disabled="busy" @click="run(() => api.dismissMergeSuggestion({ target_id: device.id, kind: s.candidate.kind, candidate_ip: s.candidate.ip }), t('interfaces.dismissed'))">
              {{ t('interfaces.dismiss') }}
            </Button>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
