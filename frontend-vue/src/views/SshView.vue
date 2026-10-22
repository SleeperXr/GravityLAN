<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { KeyRound, List, Save, ShieldCheck, SquareTerminal, X } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, SshHistoryEntry, SshKey, SshKnownHost, SshProfile, SshProfileInput, SshSessionRequest, SshStatus } from '@/types';
import Button from '@/components/ui/Button.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import SshTargets from '@/components/ssh/SshTargets.vue';
import TerminalPane from '@/components/ssh/TerminalPane.vue';
import ConnectDialog from '@/components/ssh/ConnectDialog.vue';
import ProfileDialog from '@/components/ssh/ProfileDialog.vue';
import KeysPanel from '@/components/ssh/KeysPanel.vue';
import KnownHostsPanel from '@/components/ssh/KnownHostsPanel.vue';
import {
  agentUpdateFor, filterDevices, filterHistory, filterProfiles, historyReconnect, isLive, profileInitialFrom,
  type ConnectInitial, type Session, type TerminalStatus,
} from '@/components/ssh/sshModel';
import { deviceLabel } from '@/lib/networks';
import { useSshSessions } from '@/stores/sshSessions';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Browser SSH: saved connections, recent ones and devices on the left, terminal tabs on the
 * right, plus the key store and known hosts. App.vue keeps this page alive (KeepAlive), so open
 * terminals keep running while the user is elsewhere in GravityLAN.
 */
defineOptions({ name: 'SshView' });

type Section = 'terminal' | 'keys' | 'known_hosts';
const route = useRoute();
const router = useRouter();
const liveStore = useSshSessions();
const { showToast } = useToast();

// ── Data ─────────────────────────────────────────────────────────────────────
const devices = ref<Device[]>([]);
const keys = ref<SshKey[]>([]);
const profiles = ref<SshProfile[]>([]);
const knownHosts = ref<SshKnownHost[]>([]);
const history = ref<SshHistoryEntry[]>([]);
const status = ref<SshStatus | null>(null);
const loaded = ref(false);

const loadKeys = async () => (keys.value = await api.getSshKeys());
const loadProfiles = async () => (profiles.value = await api.getSshProfiles());
const loadKnownHosts = async () => (knownHosts.value = await api.getSshKnownHosts());
const loadHistory = async () => (history.value = await api.getSshHistory());
const fail = (err: unknown) => showToast('error', t('ssh.title'), (err as Error).message);
// Deleting a key also changes the connections that used it
const onKeysChanged = () => Promise.all([loadKeys(), loadProfiles()]).catch(fail);

onMounted(async () => {
  try {
    await Promise.all([
      api.getDevices().then((d) => (devices.value = d)),
      loadKeys(),
      loadProfiles(),
      loadKnownHosts(),
      loadHistory(),
      api.getSshStatus().then((s) => (status.value = s)),
    ]);
  } catch (err) {
    fail(err);
  } finally {
    loaded.value = true;
  }
});

// ── Visibility (KeepAlive) ───────────────────────────────────────────────────
const visible = ref(true);
onActivated(() => {
  visible.value = true;
  // The device list may have changed while the page was hidden
  if (loaded.value) api.getDevices().then((d) => (devices.value = d)).catch(() => {});
});
onDeactivated(() => (visible.value = false));

// ── Sessions ─────────────────────────────────────────────────────────────────
const section = ref<Section>('terminal');
const sessions = ref<Session[]>([]);
const activeId = ref<number | null>(null);
const pickerOpen = ref(true);
let nextId = 1;

function openSession(request: SshSessionRequest, label: string) {
  const id = nextId++;
  sessions.value = [...sessions.value, { id, label, request, status: 'connecting' }];
  activeId.value = id;
  pickerOpen.value = false;
  section.value = 'terminal';
  connect.value = null;
}

function closeSession(id: number) {
  const rest = sessions.value.filter((s) => s.id !== id);
  sessions.value = rest;
  if (activeId.value === id) activeId.value = rest.length ? rest[rest.length - 1].id : null;
  if (!rest.length) pickerOpen.value = true;
}

function selectSession(id: number) {
  activeId.value = id;
  pickerOpen.value = false;
}

function setSessionStatus(id: number, next: TerminalStatus) {
  const session = sessions.value.find((s) => s.id === id);
  if (session) session.status = next;
  // The server records ad-hoc connections when they are prepared; show them right away
  if (next === 'connected') loadHistory().catch(() => {});
}

const liveCount = computed(() => sessions.value.filter(isLive).length);
watch(liveCount, (n) => liveStore.setLiveCount(n), { immediate: true });
const warnUnload = (e: BeforeUnloadEvent) => {
  if (!liveCount.value) return;
  e.preventDefault();
  e.returnValue = '';
};
window.addEventListener('beforeunload', warnUnload);
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnUnload);
  liveStore.setLiveCount(0);
});

// ── Dialogs ──────────────────────────────────────────────────────────────────
interface ConnectState { device: Device | null; initial?: ConnectInitial; askProfile?: SshProfile | null }
const connect = ref<ConnectState | null>(null);
const editing = ref<{ profile: SshProfile | null; initial?: Partial<SshProfileInput> } | null>(null);

function connectProfile(profile: SshProfile) {
  if (profile.auth_method === 'ask') connect.value = { device: null, askProfile: profile };
  else openSession({ profile_id: profile.id }, profile.name);
}

async function deleteProfile(profile: SshProfile) {
  const ok = await confirmAction({ title: t('common.delete'), message: t('ssh.profiles.delete_confirm', { name: profile.name }), confirmLabel: t('common.delete'), danger: true });
  if (!ok) return;
  try {
    await api.deleteSshProfile(profile.id);
    await loadProfiles();
  } catch (err) {
    fail(err);
  }
}

async function removeHistory(entry: SshHistoryEntry) {
  try {
    await api.deleteSshHistory(entry.id);
    history.value = history.value.filter((h) => h.id !== entry.id);
  } catch (err) {
    fail(err);
  }
}

function reconnect(entry: SshHistoryEntry) {
  const how = historyReconnect(entry, keys.value);
  if (how.kind === 'open') openSession(how.request, entry.label);
  else connect.value = { device: entry.device_id ? (devices.value.find((d) => d.id === entry.device_id) ?? null) : null, initial: how.initial };
}

function openLinked(device: Device) {
  const profile = profiles.value.find((p) => p.device_id === device.id);
  if (profile) connectProfile(profile);
  else connect.value = { device };
}

// Deep link from a device card: /ssh?device=<id>
watch(
  [() => route.query.device, loaded],
  ([param, isLoaded]) => {
    if (!param || !isLoaded) return;
    const device = devices.value.find((d) => d.id === Number(param));
    void router.replace({ query: {} });
    if (device) openLinked(device);
  },
  { immediate: true },
);

// ── Filters ──────────────────────────────────────────────────────────────────
const search = ref('');
const showAllDevices = ref(false);
const query = computed(() => search.value.trim().toLowerCase());
const filteredProfiles = computed(() => filterProfiles(profiles.value, query.value));
const filteredHistory = computed(() => filterHistory(history.value, query.value));
const filteredDevices = computed(() => filterDevices(devices.value, query.value, showAllDevices.value, deviceLabel));
const profileDeviceIds = computed(() => new Set(profiles.value.map((p) => p.device_id)));

// ── Tab context menu ─────────────────────────────────────────────────────────
const menu = ref<{ id: number; x: number; y: number } | null>(null);
const menuSession = computed(() => (menu.value ? sessions.value.find((s) => s.id === menu.value!.id) : undefined));
const closeMenu = () => (menu.value = null);
// Keep the menu inside the window near the right/bottom edge
const menuStyle = computed(() =>
  menu.value
    ? { left: `${Math.max(8, Math.min(menu.value.x, window.innerWidth - 268))}px`, top: `${Math.max(8, Math.min(menu.value.y, window.innerHeight - 120))}px` }
    : {},
);
watch(menu, (open) => {
  const method = open ? 'addEventListener' : 'removeEventListener';
  window[method]('mousedown', closeMenu);
  window[method]('resize', closeMenu);
});
function onMenuKey(e: KeyboardEvent) {
  if (e.key === 'Escape') closeMenu();
}

function saveTab() {
  const session = menuSession.value;
  closeMenu();
  if (!session) return;
  const r = session.request;
  const device = r.device_id ? devices.value.find((d) => d.id === r.device_id) : undefined;
  editing.value = { profile: null, initial: profileInitialFrom(r, device ? deviceLabel(device) : (r.host ?? session.label)) };
}

const sections = computed(() => [
  { id: 'terminal' as const, label: t('ssh.tabs.terminal'), icon: SquareTerminal, count: sessions.value.length || undefined },
  { id: 'keys' as const, label: t('ssh.tabs.keys'), icon: KeyRound, count: keys.value.length || undefined },
  { id: 'known_hosts' as const, label: t('ssh.tabs.known_hosts'), icon: ShieldCheck, count: undefined },
]);

function pickSection(id: Section) {
  section.value = id;
  if (id === 'known_hosts') loadKnownHosts().catch(fail);
}

const statusDot: Record<TerminalStatus, string> = {
  connecting: 'bg-warn animate-pulse',
  hostkey: 'bg-warn',
  authenticating: 'bg-warn animate-pulse',
  connected: 'bg-accent',
  closed: 'bg-fg-subtle',
  error: 'bg-danger',
};
</script>

<template>
  <div class="flex h-full min-h-[32rem] flex-col">
    <header class="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-6">
      <div class="min-w-0">
        <h1 class="sr-only text-xl font-bold text-fg md:not-sr-only">{{ t('ssh.title') }}</h1>
        <p class="text-sm text-fg-muted">{{ t('ssh.subtitle') }}</p>
      </div>
      <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('ssh.title')">
        <button
          v-for="s in sections"
          :key="s.id"
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-xs font-semibold transition-colors"
          :class="section === s.id ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="section === s.id"
          @click="pickSection(s.id)"
        >
          <component :is="s.icon" class="size-3.5" aria-hidden="true" />{{ s.label }}
          <span v-if="s.count" class="rounded-sm bg-raised px-1 font-mono text-[10px] text-fg-subtle">{{ s.count }}</span>
        </button>
      </div>
    </header>

    <!-- The terminal workspace stays mounted so open sessions survive switching sections -->
    <div v-show="section === 'terminal'" class="flex min-h-0 flex-1">
      <aside
        class="w-full shrink-0 flex-col border-r border-line bg-chrome md:flex md:w-80"
        :class="pickerOpen || sessions.length === 0 ? 'flex' : 'hidden'"
        :aria-label="t('ssh.targets.label')"
      >
        <button
          v-if="sessions.length > 0"
          type="button"
          class="flex w-full items-center gap-2 border-b border-line px-4 py-2.5 text-left text-sm font-medium text-accent-text md:hidden"
          @click="pickerOpen = false"
        >
          <SquareTerminal class="size-4" aria-hidden="true" />{{ t('gv.ssh.back_to_sessions', { count: sessions.length }) }}
        </button>
        <SshTargets
          v-model:search="search"
          v-model:show-all="showAllDevices"
          :profiles="filteredProfiles"
          :has-any-profile="profiles.length > 0"
          :history="filteredHistory"
          :devices="filteredDevices"
          :loaded="loaded"
          :profile-device-ids="profileDeviceIds"
          @new-profile="editing = { profile: null }"
          @connect-profile="connectProfile"
          @edit-profile="(p) => (editing = { profile: p })"
          @delete-profile="deleteProfile"
          @reconnect="reconnect"
          @save-history="(h) => (editing = { profile: null, initial: profileInitialFrom(h, h.device_name || h.target_host || h.label) })"
          @remove-history="removeHistory"
          @connect-device="(d) => (connect = { device: d })"
        />
      </aside>

      <section
        class="min-w-0 flex-1 flex-col"
        :class="pickerOpen && sessions.length > 0 ? 'hidden md:flex' : sessions.length === 0 ? 'hidden md:flex' : 'flex'"
        :aria-label="t('ssh.sessions.label')"
      >
        <template v-if="sessions.length > 0">
          <div class="flex shrink-0 items-stretch gap-px overflow-x-auto border-b border-line bg-chrome [scrollbar-width:none]" role="tablist" :aria-label="t('ssh.sessions.label')">
            <button type="button" class="grid w-10 shrink-0 place-items-center text-fg-subtle hover:text-fg md:hidden" :aria-label="t('ssh.targets.label')" :aria-expanded="pickerOpen" @click="pickerOpen = !pickerOpen">
              <List class="size-4" aria-hidden="true" />
            </button>
            <div
              v-for="s in sessions"
              :key="s.id"
              class="group relative flex max-w-60 shrink-0 items-center border-r border-line"
              :class="s.id === activeId ? 'bg-surface after:absolute after:inset-x-0 after:top-0 after:h-0.5 after:bg-accent' : 'hover:bg-control-hover'"
              @contextmenu.prevent="menu = { id: s.id, x: $event.clientX, y: $event.clientY }"
            >
              <button type="button" role="tab" :aria-selected="s.id === activeId" class="flex min-w-0 items-center gap-2 py-2 pr-1 pl-3 text-xs" @click="selectSession(s.id)">
                <span class="size-2 shrink-0 rounded-full" :class="statusDot[s.status]" aria-hidden="true" />
                <span class="truncate font-mono" :class="s.id === activeId ? 'text-fg' : 'text-fg-muted'">{{ s.label }}</span>
              </button>
              <button type="button" class="mr-1 grid size-6 shrink-0 place-items-center rounded text-fg-subtle hover:bg-control-hover hover:text-fg" :aria-label="t('ssh.sessions.close', { name: s.label })" @click="closeSession(s.id)">
                <X class="size-3.5" aria-hidden="true" />
              </button>
            </div>
          </div>
          <div class="relative min-h-0 flex-1">
            <div v-for="s in sessions" v-show="s.id === activeId" :key="s.id" class="absolute inset-0">
              <TerminalPane
                :request="s.request"
                :active="visible && section === 'terminal' && s.id === activeId"
                :agent-update="agentUpdateFor(s.request, devices, profiles)"
                @status="(next) => setSessionStatus(s.id, next)"
              />
            </div>
          </div>
        </template>
        <div v-else class="grid flex-1 place-items-center p-6">
          <EmptyState :icon="SquareTerminal" :title="t('ssh.sessions.empty_title')" :description="t('ssh.sessions.empty_text')">
            <Button v-if="loaded && keys.length === 0" size="sm" @click="pickSection('keys')"><KeyRound aria-hidden="true" />{{ t('ssh.sessions.add_key') }}</Button>
          </EmptyState>
        </div>
      </section>
    </div>

    <div v-if="section === 'keys'" class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-6">
      <KeysPanel :keys="keys" :status="status" @changed="onKeysChanged" />
    </div>
    <div v-else-if="section === 'known_hosts'" class="min-h-0 flex-1 overflow-y-auto px-4 py-5 md:px-6">
      <KnownHostsPanel :hosts="knownHosts" @changed="loadKnownHosts().catch(fail)" />
    </div>

    <div
      v-if="menu && menuSession"
      class="fixed z-50 w-64 rounded-lg border border-line bg-surface p-1 shadow-pop"
      role="menu"
      :style="menuStyle"
      @mousedown.stop
      @keydown="onMenuKey"
    >
      <button v-if="menuSession.request.profile_id === undefined" type="button" role="menuitem" class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-fg hover:bg-control-hover" autofocus @click="saveTab">
        <Save class="size-4" aria-hidden="true" />{{ t('ssh.targets.save_connection') }}
      </button>
      <p v-else class="px-2.5 py-2 text-xs text-fg-subtle">{{ t('ssh.sessions.already_saved') }}</p>
      <button type="button" role="menuitem" class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-fg hover:bg-control-hover" @click="closeMenu(); closeSession(menuSession.id)">
        <X class="size-4" aria-hidden="true" />{{ t('ssh.sessions.close', { name: menuSession.label }) }}
      </button>
    </div>

    <ConnectDialog
      v-if="connect"
      :device="connect.device"
      :initial="connect.initial"
      :ask-profile="connect.askProfile"
      :keys="keys"
      @close="connect = null"
      @connect="openSession"
      @profile-saved="loadProfiles().catch(fail)"
    />
    <ProfileDialog
      v-if="editing"
      :profile="editing.profile"
      :initial="editing.initial"
      :devices="devices"
      :keys="keys"
      @close="editing = null"
      @saved="editing = null; loadProfiles().catch(fail)"
    />
  </div>
</template>
