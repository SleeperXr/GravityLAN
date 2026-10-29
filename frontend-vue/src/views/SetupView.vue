<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Info, Loader2, Network, Plus, Search, Zap } from 'lucide-vue-next';
import { api, createScanSocket } from '@/api/client';
import type { ScanProgress, SubnetInfo } from '@/types';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import { NETWORKS_STEP, SCAN_FINISHED, SCAN_STEP, SECURITY_STEP, STEP_KEYS, addCustomNetwork, scanPercent, stepState } from '@/components/setup/setupModel';
import { locale, setLocale, t } from '@/i18n';

/**
 * First-run wizard: welcome, networks to scan, first scan with live progress, admin password.
 * Finishing saves the setup, signs in with the new password and starts a first refresh.
 */
const emit = defineEmits<{ complete: [] }>();
const step = ref(0);
const heading = ref<HTMLElement | null>(null);

// Move focus to the new step's heading so keyboard and screen-reader users follow along
watch(step, async () => {
  await nextTick();
  heading.value?.focus();
});

// ── Networks ─────────────────────────────────────────────────────────────────
const subnets = ref<SubnetInfo[]>([]);
const selected = ref<string[]>([]);
const loadingNetworks = ref(true);
const networksError = ref<string | null>(null);
const dnsServer = ref('');
const extra = ref('');
const extraInvalid = ref(false);

onMounted(async () => {
  try {
    subnets.value = await api.getSubnets();
    selected.value = subnets.value.map((s) => s.subnet);
  } catch (err) {
    networksError.value = (err as Error).message;
  } finally {
    loadingNetworks.value = false;
  }
});

function toggle(subnet: string) {
  selected.value = selected.value.includes(subnet) ? selected.value.filter((s) => s !== subnet) : [...selected.value, subnet];
}

function addExtra() {
  if (!extra.value.trim()) return;
  const next = addCustomNetwork(subnets.value, selected.value, extra.value);
  if (!next) {
    extraInvalid.value = true;
    return;
  }
  subnets.value = next.subnets;
  selected.value = next.selected;
  extra.value = '';
  extraInvalid.value = false;
}

// ── First scan ───────────────────────────────────────────────────────────────
const progress = ref<ScanProgress | null>(null);
// Sent with setup completion so hosts of routed subnets (other VLANs) are adopted too
const scannedSubnets = ref<string[]>([]);
let socket: WebSocket | null = null;
onBeforeUnmount(() => socket?.close());

const scanStatus = computed(() => progress.value?.status ?? 'running');
const scanRunning = computed(() => scanStatus.value === 'running' || scanStatus.value === 'idle');
const scanEnded = computed(() => scanStatus.value === 'failed' || scanStatus.value === 'cancelled');
// A scan that failed before checking any host has no numbers worth showing
const showMeter = computed(() => scanRunning.value || scanStatus.value === 'completed' || (progress.value?.hosts_scanned ?? 0) > 0);
const percent = computed(() => scanPercent(progress.value));
const scanTitle = computed(() =>
  ({ completed: 'setup.scan_completed', failed: 'setup.scan_failed', cancelled: 'setup.scan_cancelled' } as Partial<Record<string, string>>)[scanStatus.value] ?? 'setup.scan_in_progress',
);

async function startScan() {
  if (selected.value.length === 0) return;
  step.value = SCAN_STEP;
  scannedSubnets.value = [...selected.value];
  progress.value = { status: 'running', current_subnet: '', hosts_scanned: 0, hosts_total: 0, devices_found: 0, message: '', timestamp: new Date().toISOString() };
  socket?.close();
  const ws = createScanSocket((next) => {
    progress.value = next;
    if (SCAN_FINISHED.includes(next.status)) ws.close();
  });
  socket = ws;
  try {
    await api.startScan({ subnets: scannedSubnets.value, mode: 'fast', dns_server: dnsServer.value || undefined });
  } catch (err) {
    ws.close();
    if (progress.value) progress.value = { ...progress.value, status: 'failed', message: (err as Error).message };
  }
}

async function abortScan() {
  try {
    await api.stopScan();
  } catch {
    // the scan may have ended on its own meanwhile
  }
  socket?.close();
  if (progress.value?.status === 'running') progress.value = { ...progress.value, status: 'cancelled' };
}

// ── Admin password and finish ────────────────────────────────────────────────
const password = ref('');
const confirm = ref('');
const finishing = ref(false);
const finishPercent = ref(0);
const finishStatus = ref('');
const finishError = ref<string | null>(null);
const mismatch = computed(() => password.value !== '' && confirm.value !== '' && password.value !== confirm.value);
const canFinish = computed(() => password.value !== '' && password.value === confirm.value);
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function stage(value: number, key: string) {
  finishPercent.value = value;
  finishStatus.value = t(key);
}

async function finish() {
  if (!canFinish.value) return;
  finishError.value = null;
  finishing.value = true;
  stage(10, 'setup.saving_configuration');
  try {
    await api.completeSetup({
      dns_server: dnsServer.value || undefined,
      admin_password: password.value,
      subnets: scannedSubnets.value.length > 0 ? scannedSubnets.value : undefined,
    });
  } catch (err) {
    // Stay in the wizard: without the saved password the dashboard can't be used
    finishing.value = false;
    finishError.value = (err as Error).message;
    return;
  }
  // Completing setup opens no session: sign in so the wizard ends in the overview
  try {
    await api.login(password.value);
  } catch {
    // the login screen will ask
  }
  stage(40, 'setup.stabilizing_backend');
  await wait(1000);
  stage(65, 'setup.scanning_network');
  try {
    await api.refreshAllDevices();
  } catch {
    // setup is complete either way
  }
  stage(90, 'setup.almost_done');
  await wait(500);
  stage(100, 'setup.welcome_done');
  await wait(400);
  emit('complete');
}

const skipped = computed(() => (progress.value?.status === 'completed' ? undefined : SCAN_STEP));
const stations = computed(() => STEP_KEYS.map((key, index) => ({ key, index, state: stepState(index, step.value, skipped.value) })));
const features = [
  { icon: Search, title: 'setup.auto_detection', desc: 'setup.auto_detection_desc' },
  { icon: Zap, title: 'setup.direct_access', desc: 'setup.direct_access_desc' },
];
</script>

<template>
  <div class="relative flex min-h-dvh flex-col bg-canvas text-fg">
    <!-- Faint coordinate grid behind the panel -->
    <div class="pointer-events-none absolute inset-0 bg-[radial-gradient(var(--gl-line)_1px,transparent_1px)] [background-size:24px_24px] opacity-60" aria-hidden="true" />

    <header class="relative flex items-center justify-between gap-3 px-5 py-4 md:px-8">
      <div class="flex items-center gap-2.5">
        <span class="text-base font-bold tracking-tight text-fg">{{ t('app.title') }}</span>
        <span class="rounded-sm border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-micro font-semibold text-accent-text">{{ t('setup.first_run') }}</span>
      </div>
      <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.language')">
        <button
          v-for="lng in (['de', 'en'] as const)"
          :key="lng"
          type="button"
          class="h-7 rounded-sm px-2.5 font-mono text-xs font-semibold uppercase transition-colors"
          :class="locale === lng ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="locale === lng"
          @click="setLocale(lng)"
        >
          {{ lng }}
        </button>
      </div>
    </header>

    <main class="relative flex flex-1 items-start justify-center px-4 pt-4 pb-12 md:items-center md:pt-0">
      <div class="w-full max-w-xl">
        <!-- The four steps along the setup trajectory -->
        <ol v-if="!finishing" class="mb-6 grid grid-cols-4" :aria-label="t('setup.steps_label')">
          <li v-for="s in stations" :key="s.key" class="relative flex flex-col items-center gap-2 text-center" :aria-current="s.state === 'current' ? 'step' : undefined">
            <span
              v-if="s.index > 0"
              class="absolute top-[11px] right-1/2 h-[5px] w-full -translate-y-1/2 rounded-full"
              :class="s.state === 'todo' ? 'bg-line-strong' : 'bg-accent'"
              :style="s.state === 'skipped' ? { background: 'repeating-linear-gradient(90deg, var(--gl-accent) 0 6px, transparent 6px 12px)' } : undefined"
              aria-hidden="true"
            />
            <span
              class="relative z-10 grid size-[22px] place-items-center rounded-full border-[3px] font-mono text-micro font-bold transition-colors"
              :class="{
                'border-accent bg-accent text-accent-fg': s.state === 'done',
                'border-accent bg-canvas text-accent-text ring-4 ring-accent/20': s.state === 'current',
                'border-line-strong bg-canvas text-fg-subtle': s.state === 'todo',
                'border-accent bg-canvas text-fg-subtle': s.state === 'skipped',
              }"
              aria-hidden="true"
            >
              <Check v-if="s.state === 'done'" class="size-3" :stroke-width="3.5" />
              <template v-else-if="s.state === 'skipped'">–</template>
            </span>
            <span class="text-micro font-medium sm:text-xs" :class="s.state === 'current' ? 'text-fg' : 'text-fg-subtle'">{{ t(`setup.${s.key}`) }}</span>
          </li>
        </ol>

        <section class="gl-card p-6 md:p-8" aria-labelledby="setup-title">
          <!-- Finishing -->
          <div v-if="finishing" class="flex flex-col items-center gap-4 py-4 text-center">
            <span class="grid size-12 place-items-center rounded-full border border-accent/40 bg-accent/10 text-accent-text" aria-hidden="true">
              <Check v-if="finishPercent >= 100" class="size-6" />
              <Loader2 v-else class="size-6 animate-spin" />
            </span>
            <h1 id="setup-title" class="text-xl font-bold text-fg">{{ t('setup.welcome_title') }}</h1>
            <p class="text-sm text-fg-muted" role="status">{{ finishStatus }}</p>
            <div class="h-2 w-full overflow-hidden rounded-full bg-sunken" role="progressbar" :aria-label="t('setup.finish_progress_label')" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="finishPercent">
              <div class="h-full rounded-full bg-accent transition-[width] duration-500" :style="{ width: `${finishPercent}%` }" />
            </div>
            <p class="font-mono text-xs text-fg-subtle tabular">{{ finishPercent }}%</p>
          </div>

          <!-- 1 · Welcome -->
          <div v-else-if="step === 0" class="space-y-5">
            <h1 id="setup-title" ref="heading" tabindex="-1" class="text-2xl font-bold tracking-tight text-fg focus:outline-none">{{ t('setup.welcome_title') }}</h1>
            <p class="text-sm leading-relaxed text-fg-muted">{{ t('setup.welcome_description') }}</p>
            <ul class="space-y-3">
              <li v-for="f in features" :key="f.title" class="flex gap-3 rounded-lg border border-line bg-raised p-3">
                <span class="grid size-9 shrink-0 place-items-center rounded-md bg-accent/10 text-accent-text" aria-hidden="true"><component :is="f.icon" class="size-4" /></span>
                <div>
                  <p class="text-sm font-semibold text-fg">{{ t(f.title) }}</p>
                  <p class="text-xs leading-relaxed text-fg-muted">{{ t(f.desc) }}</p>
                </div>
              </li>
            </ul>
            <div class="flex justify-end">
              <Button variant="primary" @click="step = NETWORKS_STEP">{{ t('common.next') }}<ChevronRight aria-hidden="true" /></Button>
            </div>
          </div>

          <!-- 2 · Networks -->
          <div v-else-if="step === NETWORKS_STEP" class="space-y-5">
            <div>
              <h1 id="setup-title" ref="heading" tabindex="-1" class="text-xl font-bold text-fg focus:outline-none">{{ t('setup.select_networks_title') }}</h1>
              <p class="mt-1.5 text-sm leading-relaxed text-fg-muted">{{ t('setup.select_networks_desc') }}</p>
            </div>

            <p v-if="networksError" class="flex gap-2 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger-text" role="alert">
              <AlertTriangle class="size-4 shrink-0" aria-hidden="true" />{{ t('setup.networks_failed', { error: networksError }) }}
            </p>
            <p v-if="loadingNetworks" class="flex items-center gap-2 text-sm text-fg-muted" role="status">
              <Loader2 class="size-4 animate-spin" aria-hidden="true" />{{ t('setup.detecting_networks') }}
            </p>
            <p v-else-if="subnets.length === 0 && !networksError" class="text-sm text-fg-subtle">{{ t('setup.no_networks') }}</p>
            <div v-else class="space-y-2" role="group" aria-labelledby="setup-title">
              <label
                v-for="s in subnets"
                :key="s.subnet"
                class="flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors"
                :class="selected.includes(s.subnet) ? 'border-accent/50 bg-accent/[0.07]' : 'border-line bg-raised hover:border-line-strong'"
              >
                <input type="checkbox" class="size-4 accent-[var(--gl-accent)]" :checked="selected.includes(s.subnet)" @change="toggle(s.subnet)" />
                <Network class="size-4 text-fg-subtle" aria-hidden="true" />
                <span class="min-w-0">
                  <span class="block font-mono text-sm font-semibold text-fg">{{ s.subnet }}</span>
                  <span class="block text-xs text-fg-subtle">{{ s.interface_name ? `${s.interface_name} · ${s.ip_address}` : t('setup.custom_network') }}</span>
                </span>
              </label>
            </div>

            <form v-if="!loadingNetworks" class="space-y-1.5" novalidate @submit.prevent="addExtra">
              <label for="setup-extra-network" class="text-xs font-medium text-fg">{{ t('setup.add_network_label') }}</label>
              <div class="flex gap-2">
                <Input
                  id="setup-extra-network"
                  v-model="extra"
                  mono
                  placeholder="192.168.110.0/24"
                  :invalid="extraInvalid"
                  :aria-describedby="extraInvalid ? 'setup-extra-error' : 'setup-extra-hint'"
                  @update:model-value="extraInvalid = false"
                />
                <Button type="submit" :disabled="!extra.trim()"><Plus aria-hidden="true" />{{ t('setup.add_network') }}</Button>
              </div>
              <p v-if="extraInvalid" id="setup-extra-error" class="text-xs text-danger-text" role="alert">{{ t('setup.add_network_invalid') }}</p>
              <p v-else id="setup-extra-hint" class="text-xs text-fg-subtle">{{ t('setup.add_network_hint') }}</p>
            </form>

            <div class="space-y-1.5">
              <label for="setup-dns" class="text-xs font-medium text-fg">{{ t('setup.dns_label') }}</label>
              <Input id="setup-dns" v-model="dnsServer" mono placeholder="192.168.1.1" aria-describedby="setup-dns-hint" />
              <p id="setup-dns-hint" class="text-xs text-fg-subtle">{{ t('setup.dns_desc') }}</p>
            </div>

            <div class="flex justify-between gap-2">
              <Button @click="step = 0"><ChevronLeft aria-hidden="true" />{{ t('common.back') }}</Button>
              <Button v-if="!loadingNetworks && selected.length === 0" variant="primary" @click="step = SECURITY_STEP">{{ t('setup.skip_scan') }}<ChevronRight aria-hidden="true" /></Button>
              <Button v-else variant="primary" :disabled="loadingNetworks" @click="startScan">{{ t('dashboard.start_scan') }}<ChevronRight aria-hidden="true" /></Button>
            </div>
          </div>

          <!-- 3 · First scan -->
          <div v-else-if="step === SCAN_STEP" class="space-y-5">
            <div>
              <h1 id="setup-title" ref="heading" tabindex="-1" class="text-xl font-bold text-fg focus:outline-none">{{ t(scanTitle) }}</h1>
              <p class="mt-1.5 min-h-5 text-sm text-fg-muted" role="status">{{ progress?.message || (scanRunning ? t('setup.initializing_scan') : '') }}</p>
            </div>

            <div v-if="showMeter" class="space-y-4">
              <div class="relative h-2 overflow-hidden rounded-full bg-sunken" role="progressbar" :aria-label="t('setup.scan_progress_label')" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percent ?? undefined">
                <div v-if="percent !== null" class="h-full rounded-full bg-accent transition-[width] duration-500" :style="{ width: `${percent}%` }" />
                <div v-else-if="scanRunning" class="gl-indeterminate absolute inset-y-0 w-1/3 rounded-full bg-accent" />
              </div>
              <dl class="grid grid-cols-2 gap-3">
                <div class="rounded-lg border border-line bg-raised p-3">
                  <dt class="gl-eyebrow">{{ t('setup.hosts_checked') }}</dt>
                  <dd class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ progress?.hosts_scanned ?? 0 }} / {{ progress?.hosts_total ?? 0 }}</dd>
                </div>
                <div class="rounded-lg border border-line bg-raised p-3">
                  <dt class="gl-eyebrow">{{ t('setup.devices_label') }}</dt>
                  <dd class="mt-1 font-mono text-xl font-semibold text-accent-text tabular">{{ progress?.devices_found ?? 0 }}</dd>
                </div>
              </dl>
            </div>

            <p v-if="scanEnded" class="flex gap-2 rounded-md border border-info/30 bg-info/10 p-3 text-xs text-fg">
              <Info class="size-4 shrink-0 text-info-text" aria-hidden="true" />{{ t('setup.scan_later_hint') }}
            </p>

            <div class="flex justify-end gap-2">
              <Button v-if="scanRunning" @click="abortScan">{{ t('setup.abort_scan') }}</Button>
              <Button v-if="scanStatus === 'completed'" variant="primary" @click="step = SECURITY_STEP">{{ t('common.next') }}<ChevronRight aria-hidden="true" /></Button>
              <template v-if="scanEnded">
                <Button class="mr-auto" @click="step = NETWORKS_STEP"><ChevronLeft aria-hidden="true" />{{ t('common.back') }}</Button>
                <Button variant="primary" @click="step = SECURITY_STEP">{{ t('setup.continue_without_scan') }}<ChevronRight aria-hidden="true" /></Button>
              </template>
            </div>
          </div>

          <!-- 4 · Admin password -->
          <form v-else class="space-y-5" novalidate @submit.prevent="finish">
            <div>
              <h1 id="setup-title" ref="heading" tabindex="-1" class="text-xl font-bold text-fg focus:outline-none">{{ t('setup.security_title') }}</h1>
              <p class="mt-1.5 text-sm leading-relaxed text-fg-muted">{{ t('setup.security_desc') }}</p>
            </div>
            <div class="space-y-1.5">
              <label for="setup-password" class="text-xs font-medium text-fg">{{ t('setup.admin_password') }}</label>
              <Input id="setup-password" v-model="password" type="password" autocomplete="new-password" :placeholder="t('setup.password_placeholder')" />
            </div>
            <div class="space-y-1.5">
              <label for="setup-password-confirm" class="text-xs font-medium text-fg">{{ t('setup.confirm_password') }}</label>
              <Input
                id="setup-password-confirm"
                v-model="confirm"
                type="password"
                autocomplete="new-password"
                :placeholder="t('setup.password_confirm_placeholder')"
                :invalid="mismatch"
                :aria-describedby="mismatch ? 'setup-password-error' : undefined"
              />
              <p v-if="mismatch" id="setup-password-error" class="text-xs text-danger-text" role="alert">{{ t('setup.passwords_dont_match') }}</p>
            </div>
            <p class="flex gap-2 rounded-md border border-info/30 bg-info/10 p-3 text-xs text-fg">
              <Info class="size-4 shrink-0 text-info-text" aria-hidden="true" />{{ t('setup.password_hint') }}
            </p>
            <p v-if="finishError" class="flex gap-2 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger-text" role="alert">
              <AlertTriangle class="size-4 shrink-0" aria-hidden="true" />{{ t('setup.finish_failed', { error: finishError }) }}
            </p>
            <div class="flex justify-between gap-2">
              <Button @click="step = progress ? SCAN_STEP : NETWORKS_STEP"><ChevronLeft aria-hidden="true" />{{ t('common.back') }}</Button>
              <Button type="submit" variant="primary" :disabled="!canFinish"><Check aria-hidden="true" />{{ t('common.finish') }}</Button>
            </div>
          </form>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.gl-indeterminate {
  animation: gl-indeterminate 1.4s ease-in-out infinite;
}
@keyframes gl-indeterminate {
  from { left: -33%; }
  to { left: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .gl-indeterminate {
    animation: none;
    left: 0;
    width: 100%;
    opacity: 0.4;
  }
}
</style>
