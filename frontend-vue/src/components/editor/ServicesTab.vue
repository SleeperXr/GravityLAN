<script setup lang="ts">
import { computed, ref, type Component } from 'vue';
import { Activity, ExternalLink, Globe, Lock, Monitor, Plus, Radar, Terminal, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, Service } from '@/types';
import Button from '@/components/ui/Button.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { t } from '@/i18n';

/** Services of a device. Edits are saved on blur (and once more with the device). */
const device = defineModel<Device>('device', { required: true });
defineProps<{ scanning: boolean }>();
const emit = defineEmits<{ changed: []; scan: [] }>();
const { showToast } = useToast();
const { confirm } = useConfirm();

const ICONS: Record<string, Component> = { ssh: Terminal, http: Globe, https: Lock, rdp: Monitor, tcp: Activity };
const PROTOCOLS = ['http', 'https', 'ssh', 'tcp', 'udp'].map((p) => ({ value: p, label: p.toUpperCase() }));

const services = computed(() => [...device.value.services].sort((a, b) => a.port - b.port));
const adding = ref(false);
const draft = ref({ name: 'Web Interface', port: 80 as number | null, protocol: 'http' });

async function reload() {
  device.value = await api.getDevice(device.value.id);
  emit('changed');
}

function editLocally(id: number, patch: Partial<Service>) {
  device.value = { ...device.value, services: device.value.services.map((s) => (s.id === id ? { ...s, ...patch, is_auto_detected: false } : s)) };
}

async function save(svc: Service, patch: Partial<Service>) {
  try {
    await api.updateService(svc.id, patch);
    emit('changed');
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  }
}

async function changeProtocol(svc: Service, protocol: string) {
  editLocally(svc.id, { protocol });
  try {
    await api.updateService(svc.id, { protocol });
    await reload();
    showToast('success', t('notifications.info_updated'), `${svc.name}: ${protocol.toUpperCase()}`);
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  }
}

async function remove(svc: Service) {
  const ok = await confirm({ title: t('editor.delete_service_confirm'), message: `${svc.name} · ${svc.port}`, danger: true, confirmLabel: t('common.delete') });
  if (!ok) return;
  await api.deleteService(svc.id).catch(() => {});
  await reload();
}

async function addService() {
  const name = draft.value.name.trim();
  const port = Number(draft.value.port);
  if (!name || !(port > 0)) return;
  try {
    await api.addService(device.value.id, { name, port, protocol: draft.value.protocol });
    adding.value = false;
    draft.value = { name: 'Web Interface', port: 80, protocol: 'http' };
    await reload();
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  }
}

const showsSsl = (svc: Service) => svc.protocol?.toLowerCase() === 'https' || [443, 8443, 5001].includes(svc.port) || svc.ignore_ssl;
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 class="text-sm font-semibold text-fg">{{ t('editor.active_services') }}</h3>
      <div class="flex gap-2">
        <Button size="sm" :loading="scanning" @click="emit('scan')">
          <Radar v-if="!scanning" aria-hidden="true" />{{ scanning ? t('dashboard.scanning') : t('network.nmap_scan') }}
        </Button>
        <Button size="sm" :aria-expanded="adding" @click="adding = !adding"><Plus aria-hidden="true" />{{ t('editor.add_service') }}</Button>
      </div>
    </div>

    <form v-if="adding" class="grid gap-2 rounded-md border border-line bg-raised p-3 sm:grid-cols-[1fr_6rem_7rem_auto]" @submit.prevent="addService">
      <Input v-model="draft.name" :aria-label="t('network.name')" :placeholder="t('network.name')" />
      <Input v-model="draft.port" type="number" min="1" max="65535" mono aria-label="Port" placeholder="Port" />
      <Select v-model="draft.protocol" :options="PROTOCOLS" aria-label="Protocol" />
      <Button type="submit" variant="primary">{{ t('interfaces.add') }}</Button>
    </form>

    <EmptyState v-if="services.length === 0" compact :icon="Globe" :title="t('editor.no_services')" />
    <ul v-else class="space-y-2">
      <li v-for="svc in services" :key="svc.id" class="flex items-center gap-3 rounded-md border border-line bg-raised p-3">
        <span
          class="flex size-9 shrink-0 items-center justify-center rounded-md"
          :class="svc.is_up ? 'bg-accent/10 text-accent-text' : 'bg-danger/10 text-danger-text'"
          :title="svc.is_up ? t('network.online') : t('network.offline')"
        >
          <component :is="ICONS[svc.protocol.toLowerCase()] ?? ExternalLink" class="size-4" aria-hidden="true" />
        </span>
        <div class="min-w-0 flex-1 space-y-1.5">
          <div class="flex items-center gap-2">
            <input
              :value="svc.name"
              :aria-label="t('network.name')"
              class="min-w-0 flex-1 rounded-sm bg-transparent px-1 -mx-1 text-sm font-medium text-fg hover:bg-sunken focus:bg-sunken focus:outline-none"
              @input="editLocally(svc.id, { name: ($event.target as HTMLInputElement).value })"
              @blur="save(svc, { name: ($event.target as HTMLInputElement).value })"
            />
            <span v-if="!svc.is_auto_detected" class="rounded-sm bg-info/15 px-1.5 text-micro font-semibold text-info-text">{{ t('editor.manual') }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-3 text-xs text-fg-subtle">
            <label class="flex items-center gap-1.5">
              <span>Prot.</span>
              <select
                :value="svc.protocol"
                class="rounded-sm border border-line bg-sunken px-1 py-0.5 font-mono text-xs text-fg focus:border-info focus:outline-none"
                @change="changeProtocol(svc, ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="p in PROTOCOLS" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </label>
            <label class="flex items-center gap-1.5">
              <span>Port</span>
              <input
                type="number"
                :value="svc.port"
                class="w-20 rounded-sm border border-line bg-sunken px-1 py-0.5 font-mono text-xs text-fg focus:border-info focus:outline-none"
                @input="(e) => { const p = parseInt((e.target as HTMLInputElement).value, 10); if (!Number.isNaN(p)) editLocally(svc.id, { port: p }); }"
                @blur="(e) => { const p = parseInt((e.target as HTMLInputElement).value, 10); if (!Number.isNaN(p)) save(svc, { port: p }); }"
              />
            </label>
            <label v-if="showsSsl(svc)" class="flex cursor-pointer items-center gap-1.5" :title="t('health_page.ignore_ssl_hint')">
              <input
                type="checkbox"
                :checked="Boolean(svc.ignore_ssl)"
                class="size-3.5 accent-[var(--gl-accent)]"
                @change="(e) => { const v = (e.target as HTMLInputElement).checked; editLocally(svc.id, { ignore_ssl: v }); save(svc, { ignore_ssl: v }); }"
              />
              {{ t('health_page.ignore_ssl_btn') }}
            </label>
          </div>
        </div>
        <Button size="icon-sm" variant="danger-ghost" :aria-label="`${t('common.delete')}: ${svc.name}`" @click="remove(svc)">
          <Trash2 aria-hidden="true" />
        </Button>
      </li>
    </ul>

    <p class="rounded-md border border-dashed border-info/30 bg-info/[0.05] px-3 py-2 text-xs text-info-text">
      <strong>{{ t('common.warning') }}:</strong> {{ t('editor.service_note') }}
    </p>
  </div>
</template>
