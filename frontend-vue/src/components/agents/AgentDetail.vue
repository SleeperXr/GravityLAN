<script lang="ts">
type AuthType = 'password' | 'key' | 'stored_key';
interface SshCreds {
  ssh_user: string;
  ssh_password: string;
  sudo_password?: string;
  ssh_key: string;
  key_id: number | null;
  key_passphrase: string;
  auth_type: AuthType;
  ssh_port: number;
}

// SSH secrets are kept in memory only (never in web storage), so they are gone on reload
const sshCredCache = new Map<number, SshCreds>();
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ArrowUpCircle, Cpu, HardDrive, Lock, MemoryStick, RotateCcw, Shield, Terminal, Thermometer } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { SshKey } from '@/types';
import type { AgentRow } from './agentRow';
import Tabs from '@/components/ui/Tabs.vue';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import Textarea from '@/components/ui/Textarea.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import TimeSeriesChart from '@/components/charts/TimeSeriesChart.vue';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Telemetry and updates of one agent. All state lives here, so the chosen range, the package
 * list and the output of a running update survive switching tabs.
 */
interface DiskSample { path: string; percent: number; used_gb: number; total_gb: number }
interface MetricSnapshot { cpu_percent: number; ram: { percent: number }; temperature?: number | null; timestamp: string; disk?: DiskSample[] }
interface PatchPackage { package: string; current_version: string; new_version: string; repo?: string }

const props = defineProps<{ agent: AgentRow }>();
const emit = defineEmits<{ refresh: [] }>();
const { showToast } = useToast();
const deviceId = computed(() => props.agent.device_id);
const tab = ref<'telemetry' | 'patching'>('telemetry');

// ── Telemetry ────────────────────────────────────────────────────────────────
const range = ref('24h');
const ranges = ref<string[]>(['6h', '24h', '7d', '30d']);
const retentionDays = ref<number | null>(null);
const history = ref<MetricSnapshot[]>([]);
const loadingHistory = ref(true);

async function loadHistory() {
  loadingHistory.value = true;
  try {
    const res = await api.getAgentMetrics(deviceId.value, undefined, range.value);
    // The client declares the stored-row shape (AgentSnapshot); the endpoint returns report payloads
    history.value = res.snapshots as unknown as MetricSnapshot[];
    if (res.available_ranges?.length) {
      ranges.value = res.available_ranges;
      if (!res.available_ranges.includes(range.value)) range.value = res.available_ranges[res.available_ranges.length - 1];
    }
    if (res.retention_days !== undefined) retentionDays.value = res.retention_days;
  } catch {
    history.value = [];
  } finally {
    loadingHistory.value = false;
  }
}
watch([range, tab], () => {
  if (tab.value === 'telemetry') void loadHistory();
}, { immediate: true });

const stamps = computed(() => history.value.map((h) => h.timestamp));
const cpuSeries = computed(() => [{ label: 'CPU', color: 'var(--line-3)', values: history.value.map((h) => h.cpu_percent), suffix: ' %' }]);
const ramSeries = computed(() => [{ label: 'RAM', color: 'var(--line-1)', values: history.value.map((h) => h.ram.percent), suffix: ' %' }]);
const tempSeries = computed(() => [{ label: 'Temp', color: 'var(--line-5)', values: history.value.map((h) => h.temperature ?? 0), suffix: ' °C' }]);
const disks = computed(() => history.value[history.value.length - 1]?.disk ?? []);
const diskTone = (pct: number) => (pct > 90 ? 'bg-danger' : pct > 75 ? 'bg-warn' : 'bg-accent');

// ── SSH credentials ──────────────────────────────────────────────────────────
const sshUser = ref('root');
const sshPassword = ref('');
const sudoPassword = ref('');
const sshKey = ref('');
const sshPort = ref(22);
const authType = ref<AuthType>('password');
const keyId = ref<number | null>(null);
const keyPassphrase = ref('');
const storedKeys = ref<SshKey[]>([]);
const saveCreds = ref(true);
const showForm = ref(true);
const hasStored = ref(false);

onMounted(async () => {
  const cached = sshCredCache.get(deviceId.value);
  if (cached) {
    sshUser.value = cached.ssh_user || 'root';
    sshPassword.value = cached.ssh_password;
    sudoPassword.value = cached.sudo_password || '';
    sshKey.value = cached.ssh_key;
    keyId.value = cached.key_id;
    keyPassphrase.value = cached.key_passphrase;
    sshPort.value = cached.ssh_port || 22;
    authType.value = cached.auth_type;
    showForm.value = false;
    hasStored.value = true;
  }
  try {
    storedKeys.value = await api.getSshKeys();
    if (!cached && storedKeys.value.length > 0) {
      authType.value = 'stored_key';
      keyId.value = storedKeys.value[0].id;
    }
  } catch {
    storedKeys.value = [];
  }
});

const authOptions = computed(() => [
  { value: 'password' as AuthType, label: t('agent_detail.auth_password') },
  ...(storedKeys.value.length ? [{ value: 'stored_key' as AuthType, label: t('agent_detail.auth_stored_key') }] : []),
  { value: 'key' as AuthType, label: t('agent_detail.auth_key') },
]);
const keyOptions = computed(() => [
  { value: null, label: t('agent_detail.choose_key') },
  ...storedKeys.value.map((k) => ({ value: k.id as number | null, label: `${k.name} (${k.key_type}) – ${k.fingerprint.slice(0, 16)}…` })),
]);
const selectedKeyNeedsPassphrase = computed(() => storedKeys.value.find((k) => k.id === keyId.value)?.has_passphrase ?? false);

/** The request body, remembering (or forgetting) the credentials as the checkbox says. */
function payload() {
  const auth = authType.value;
  if (saveCreds.value) {
    sshCredCache.set(deviceId.value, {
      ssh_user: sshUser.value,
      ssh_password: auth === 'password' ? sshPassword.value : '',
      sudo_password: sudoPassword.value,
      ssh_key: auth === 'key' ? sshKey.value : '',
      key_id: auth === 'stored_key' ? keyId.value : null,
      key_passphrase: auth === 'stored_key' ? keyPassphrase.value : '',
      auth_type: auth,
      ssh_port: sshPort.value,
    });
    hasStored.value = true;
  } else {
    sshCredCache.delete(deviceId.value);
    hasStored.value = false;
  }
  const body: {
    ssh_user: string;
    ssh_password?: string;
    sudo_password?: string;
    ssh_key?: string;
    key_id?: number;
    key_passphrase?: string;
    ssh_port: number;
  } = {
    ssh_user: sshUser.value,
    ssh_password: auth === 'password' ? (sshPassword.value || undefined) : (sudoPassword.value || undefined),
    ssh_key: auth === 'key' ? (sshKey.value || undefined) : undefined,
    key_id: auth === 'stored_key' ? (keyId.value ?? undefined) : undefined,
    key_passphrase: auth === 'stored_key' && keyPassphrase.value ? keyPassphrase.value : undefined,
    ssh_port: sshPort.value,
  };
  if (sudoPassword.value) {
    body.sudo_password = sudoPassword.value;
  }
  return body;
}

// ── Patching ─────────────────────────────────────────────────────────────────
const querying = ref(false);
const patching = ref(false);
const packages = ref<PatchPackage[]>([]);
const majorUpgrade = ref<string | null>(null);
const patchManager = ref<string | null>(null);
const output = ref<string[]>([]);
const outputBox = ref<HTMLElement | null>(null);
let socket: WebSocket | null = null;

// A fresh update check wins over the (possibly older) agent report
const managerName = computed(() => patchManager.value ?? props.agent.patch_manager);
const upgradeTarget = computed(() => majorUpgrade.value ?? props.agent.major_upgrade_available);

function append(line: string) {
  output.value = [...output.value, line];
  void nextTick(() => {
    if (outputBox.value) outputBox.value.scrollTop = outputBox.value.scrollHeight;
  });
}

async function queryUpdates() {
  querying.value = true;
  packages.value = [];
  majorUpgrade.value = null;
  patchManager.value = null;
  try {
    const res = await api.queryAgentPatches(deviceId.value, payload());
    const updateError = (res as unknown as Record<string, unknown>).error;
    if (typeof updateError === 'string' && updateError) showToast('error', t('gv.agents.query_failed'), updateError);
    packages.value = res.packages;
    majorUpgrade.value = res.major_upgrade_available;
    patchManager.value = res.patch_manager;
    showForm.value = false;
  } catch (err) {
    showToast('error', t('gv.agents.query_failed'), (err as Error).message);
  } finally {
    querying.value = false;
  }
}

function openPatchSocket(patchToken: string) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let token = localStorage.getItem('gravitylan_token') || '';
  if (token === 'undefined') token = '';
  socket = new WebSocket(`${protocol}//${window.location.host}/api/agent/patches/${deviceId.value}/run-ws?patch_token=${encodeURIComponent(patchToken)}&token=${encodeURIComponent(token)}`);
  socket.onopen = () => append('[Local] WebSocket connection established. Launching updates...\r\n');
  socket.onmessage = (event) => append(String(event.data));
  socket.onclose = (event) => {
    append(`\r\n[Local] Update process terminated (code: ${event.code}).\r\n`);
    patching.value = false;
    socket = null;
    emit('refresh');
  };
  socket.onerror = () => {
    append('\r\n[Local] Connection error.\r\n');
    patching.value = false;
  };
}

async function startPatching(mode: 'upgrade' | 'security-only') {
  const ok = await confirmAction({
    title: mode === 'security-only' ? t('agent_detail.security_only') : t('agent_detail.upgrade_all'),
    message: t('gv.agents.patch_confirm', { host: props.agent.hostname }),
    confirmLabel: t('gv.agents.patch_start'),
    danger: true,
  });
  if (!ok) return;
  patching.value = true;
  output.value = ['[Local] Requesting update token...\r\n'];
  try {
    const res = await api.prepareAgentPatch(deviceId.value, { ...payload(), mode });
    append('[Local] Token received. Connecting to WebSocket...\r\n');
    openPatchSocket(res.patch_token);
  } catch (err) {
    append(`\r\n[Local] Error: ${(err as Error).message}\r\n`);
    patching.value = false;
  }
}

onBeforeUnmount(() => socket?.close());

const tabs = computed(() => [
  { value: 'telemetry', label: t('agent_detail.tab_telemetry') },
  { value: 'patching', label: t('agent_detail.tab_patching'), badge: props.agent.patch_available > 0 ? props.agent.patch_available : undefined },
]);
</script>

<template>
  <Tabs v-model="tab" :tabs="tabs" :label="t('agent_detail.tabs_label')" list-class="px-0">
    <template #telemetry>
      <div class="space-y-4 pt-4">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h4 class="text-sm font-bold text-fg">{{ t('agent_detail.timeframe_title') }}</h4>
            <p class="text-xs text-fg-subtle">
              {{ t('agent_detail.timeframe_desc') }}<template v-if="retentionDays !== null"> · {{ t('agent_detail.retention', { days: retentionDays }) }}</template>
            </p>
          </div>
          <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('agent_detail.timeframe_title')">
            <button
              v-for="r in ranges"
              :key="r"
              type="button"
              class="h-7 rounded-sm px-2.5 font-mono text-xs transition-colors"
              :class="range === r ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="range === r"
              @click="range = r"
            >
              {{ r }}
            </button>
          </div>
        </div>

        <div v-if="loadingHistory" class="grid gap-3 lg:grid-cols-3" role="status" :aria-label="t('agent_detail.loading_history')">
          <Skeleton v-for="i in 3" :key="i" class="h-52" />
        </div>
        <p v-else-if="history.length === 0" class="gl-subcard p-6 text-center text-xs text-fg-subtle">{{ t('agent_detail.no_history') }}</p>
        <div v-else class="grid gap-3 lg:grid-cols-3">
          <section class="gl-subcard p-3">
            <h5 class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-fg"><Cpu class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent_detail.cpu_title') }}</h5>
            <TimeSeriesChart :timestamps="stamps" :series="cpuSeries" :max="100" :label="t('agent_detail.cpu_title')" />
          </section>
          <section class="gl-subcard p-3">
            <h5 class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-fg"><MemoryStick class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent_detail.ram_title') }}</h5>
            <TimeSeriesChart :timestamps="stamps" :series="ramSeries" :max="100" :label="t('agent_detail.ram_title')" />
          </section>
          <section class="gl-subcard p-3">
            <h5 class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-fg"><Thermometer class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent_detail.temp_title') }}</h5>
            <TimeSeriesChart :timestamps="stamps" :series="tempSeries" :max="100" :label="t('agent_detail.temp_title')" />
          </section>
        </div>

        <section class="gl-subcard p-3">
          <h5 class="mb-3 flex items-center gap-1.5 text-xs font-semibold text-fg"><HardDrive class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent_detail.storage_title') }}</h5>
          <p v-if="disks.length === 0" class="text-xs text-fg-subtle">{{ t('agent_detail.no_disks') }}</p>
          <ul v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <li v-for="disk in disks" :key="disk.path" class="space-y-1.5">
              <p class="flex justify-between gap-2 text-xs">
                <span class="truncate font-mono text-fg" :title="disk.path">{{ disk.path }}</span>
                <span class="font-mono font-semibold tabular" :class="disk.percent > 90 ? 'text-danger-text' : disk.percent > 75 ? 'text-warn-text' : 'text-fg-muted'">{{ disk.percent.toFixed(0) }} %</span>
              </p>
              <span class="block h-1.5 overflow-hidden rounded-full bg-sunken">
                <span class="block h-full rounded-full" :class="diskTone(disk.percent)" :style="{ width: `${Math.min(100, disk.percent)}%` }" />
              </span>
              <p class="font-mono text-[11px] text-fg-subtle">{{ t('agent_detail.disk_used', { used: disk.used_gb.toFixed(1), total: disk.total_gb.toFixed(1) }) }}</p>
            </li>
          </ul>
        </section>
      </div>
    </template>

    <template #patching>
      <div class="space-y-4 pt-4">
        <EmptyState v-if="!managerName" :icon="Shield" :title="t('agent_detail.unsupported_title')" :description="t('agent_detail.unsupported_desc')" compact />
        <template v-else>
          <p v-if="agent.reboot_required" class="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger-text">
            <RotateCcw class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ t('agent_detail.reboot_required') }}
          </p>
          <p v-if="upgradeTarget" class="flex items-start gap-2 rounded-md border border-info/30 bg-info/10 p-3 text-xs text-info-text">
            <ArrowUpCircle class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ t('agent_detail.major_upgrade', { target: upgradeTarget }) }}
          </p>

          <template v-if="!patching">
            <section v-if="showForm" class="gl-subcard space-y-3 p-3">
              <div class="flex items-center justify-between gap-2">
                <h5 class="flex items-center gap-1.5 text-xs font-semibold text-fg"><Lock class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent_detail.ssh_title') }}</h5>
                <Button v-if="hasStored" size="sm" variant="ghost" @click="showForm = false">{{ t('agent_detail.hide') }}</Button>
              </div>
              <div class="grid gap-3 md:grid-cols-[1fr_1fr_2fr]">
                <Field v-slot="{ id }" :label="t('agent_detail.username')">
                  <Input :id="id" v-model="sshUser" autocomplete="username" />
                </Field>
                <Field v-slot="{ id }" :label="t('agent_detail.auth_method')">
                  <Select :id="id" v-model="authType" :options="authOptions" />
                </Field>
                <Field v-if="authType === 'password'" v-slot="{ id }" :label="t('agent_detail.auth_password')">
                  <Input :id="id" v-model="sshPassword" type="password" :placeholder="t('agent_detail.password_placeholder')" autocomplete="current-password" />
                </Field>
                <div v-else-if="authType === 'stored_key'" class="space-y-2">
                  <Field v-slot="{ id }" :label="t('agent_detail.select_key')">
                    <Select :id="id" v-model="keyId" :options="keyOptions" />
                  </Field>
                  <Input v-if="selectedKeyNeedsPassphrase" v-model="keyPassphrase" type="password" :placeholder="t('ssh.keys.passphrase')" :aria-label="t('ssh.keys.passphrase')" autocomplete="off" />
                </div>
                <Field v-else v-slot="{ id }" :label="t('agent_detail.auth_key')">
                  <Textarea :id="id" v-model="sshKey" mono rows="3" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" />
                </Field>
              </div>
              <Field v-if="authType !== 'password'" v-slot="{ id, describedBy }" :label="t('agent.sudo_password')" :hint="t('agent.sudo_password_hint')">
                <Input :id="id" v-model="sudoPassword" type="password" autocomplete="off" :aria-describedby="describedBy" />
              </Field>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <label class="flex items-center gap-2 text-xs text-fg-muted">
                  <input v-model="saveCreds" type="checkbox" class="size-4 accent-[var(--gl-accent)]" />
                  {{ t('agent_detail.remember') }}
                </label>
                <Button size="sm" :loading="querying" @click="queryUpdates">{{ querying ? t('agent_detail.querying') : t('agent_detail.query_list') }}</Button>
              </div>
            </section>
            <div v-else class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-raised px-3 py-2 text-xs">
              <span class="text-fg-subtle">{{ t('agent_detail.ssh_configured', { user: sshUser, port: sshPort }) }}</span>
              <Button size="sm" variant="ghost" @click="showForm = true">{{ t('agent_detail.change_credentials') }}</Button>
            </div>

            <section class="gl-subcard space-y-3 p-3">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h5 class="text-xs font-semibold text-fg">{{ t('agent_detail.upgrades_title') }}</h5>
                  <p class="text-xs text-fg-subtle">{{ t('agent_detail.upgrades_count', { count: agent.patch_available, security: agent.patch_security }) }}</p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <Button v-if="packages.length === 0" size="sm" :loading="querying" @click="queryUpdates">{{ t('agent_detail.query_details') }}</Button>
                  <Button v-if="agent.patch_security > 0" size="sm" variant="danger" :disabled="querying" @click="startPatching('security-only')">{{ t('agent_detail.security_only') }}</Button>
                  <Button size="sm" variant="primary" :disabled="querying || agent.patch_available === 0" @click="startPatching('upgrade')">{{ t('agent_detail.upgrade_all') }}</Button>
                </div>
              </div>
              <div v-if="packages.length > 0" class="max-h-72 overflow-auto rounded-md border border-line">
                <table class="w-full text-left text-xs">
                  <thead class="sticky top-0 bg-raised text-fg-subtle">
                    <tr>
                      <th scope="col" class="px-3 py-2 font-medium">{{ t('agent_detail.col_package') }}</th>
                      <th scope="col" class="px-3 py-2 font-medium">{{ t('agent_detail.col_installed') }}</th>
                      <th scope="col" class="px-3 py-2 font-medium">{{ t('agent_detail.col_candidate') }}</th>
                      <th scope="col" class="hidden px-3 py-2 font-medium sm:table-cell">{{ t('agent_detail.col_repo') }}</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-line font-mono">
                    <tr v-for="(pkg, i) in packages" :key="`${pkg.package}-${i}`">
                      <td class="px-3 py-1.5 font-semibold text-fg">{{ pkg.package }}</td>
                      <td class="px-3 py-1.5 text-fg-subtle">{{ pkg.current_version }}</td>
                      <td class="px-3 py-1.5 text-accent-text">{{ pkg.new_version }}</td>
                      <td class="hidden px-3 py-1.5 text-fg-subtle sm:table-cell">{{ pkg.repo || t('common.unknown') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p v-else-if="agent.patch_available > 0 && !querying" class="text-xs text-fg-subtle">{{ t('agent_detail.details_not_loaded') }}</p>
            </section>
          </template>

          <section v-if="output.length > 0 || patching" class="gl-subcard space-y-2 p-3">
            <h5 class="flex items-center gap-1.5 text-xs font-semibold text-fg"><Terminal class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent_detail.live_output') }}</h5>
            <div ref="outputBox" class="max-h-80 overflow-auto rounded-md bg-[#07090c] p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[#cfe9e1]" role="log" aria-live="polite">
              <span v-for="(chunk, idx) in output" :key="idx">{{ chunk }}</span>
            </div>
            <div v-if="!patching" class="flex justify-end">
              <Button size="sm" @click="output = []">{{ t('agent_detail.clear_output') }}</Button>
            </div>
          </section>
        </template>
      </div>
    </template>
  </Tabs>
</template>
