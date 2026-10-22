<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Terminal, type IMarker } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { AlertTriangle, Check, ClipboardList, ClipboardPaste, Copy, Loader2, Minus, Plus, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck } from 'lucide-vue-next';
import { api, createSshTerminalSocket } from '@/api/client';
import type { SshSessionRequest } from '@/types';
import Button from '@/components/ui/Button.vue';
import TerminalSettings from './TerminalSettings.vue';
import { FONT_OPTIONS, fontCss, loadTerminalFont, resolveTheme, setTerminalPrefs, terminalPrefs } from './terminalPrefs';
import { hostKeyFile, lastCommandText, type AgentUpdate, type HostKeyPrompt, type TerminalStatus } from './sshModel';
import { buildInstallCommand, requestInstallCode } from '@/lib/agent';
import { copyText } from '@/lib/clipboard';
import { useToast } from '@/composables/useToast';
import { useTheme } from '@/composables/useTheme';
import { t } from '@/i18n';

/**
 * One xterm.js terminal bound to one SSH session over the /api/ssh/terminal WebSocket.
 * Ctrl+Shift+C / Ctrl+Shift+V copy and paste; plain Ctrl+C stays "interrupt".
 */
const props = withDefaults(defineProps<{ request: SshSessionRequest; active: boolean; agentUpdate?: AgentUpdate | null }>(), { agentUpdate: null });
const emit = defineEmits<{ status: [status: TerminalStatus] }>();
const { showToast } = useToast();

const SCROLLBAR_COLS = 2;
type ServerMessage =
  | { type: 'status'; stage: string }
  | ({ type: 'hostkey' } & HostKeyPrompt)
  | { type: 'error'; message: string }
  | { type: 'closed'; reason?: string };

const container = ref<HTMLElement | null>(null);
let term: Terminal | null = null;
let fit: FitAddon | null = null;
let ws: WebSocket | null = null;
let lastCommand: IMarker | null = null;
let observer: ResizeObserver | null = null;
let disposed = false;

const status = ref<TerminalStatus>('connecting');
const hostKey = ref<HostKeyPrompt | null>(null);
const message = ref<string | null>(null);
// The GravityLAN preset reads the app's colours, so it follows a light/dark switch too
const { resolved: appTheme } = useTheme();
const background = computed(() => (appTheme.value, resolveTheme(terminalPrefs).background));

const red = (text: string) => `\x1b[31m${text}\x1b[0m`;

function setStatus(next: TerminalStatus) {
  if (status.value === next) return;
  status.value = next;
  emit('status', next);
}

function fitAndSync() {
  const el = container.value;
  if (!term || !fit || !el || el.offsetWidth === 0 || el.offsetHeight === 0) return;
  const dims = fit.proposeDimensions();
  if (!dims || !Number.isFinite(dims.cols) || !Number.isFinite(dims.rows)) return;
  // xterm 6 draws its scrollbar over the text area; keep the last columns clear of it
  const cols = Math.max(2, dims.cols - SCROLLBAR_COLS);
  if (cols !== term.cols || dims.rows !== term.rows) term.resize(cols, dims.rows);
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
}

function fail(text: string) {
  message.value = text;
  setStatus('error');
  term?.writeln(`\r\n${red(text)}`);
}

function applyServerMessage(msg: ServerMessage) {
  switch (msg.type) {
    case 'status':
      if (msg.stage === 'connected') {
        hostKey.value = null;
        setStatus('connected');
        fitAndSync();
        term?.focus();
      } else {
        setStatus(msg.stage === 'authenticating' ? 'authenticating' : 'connecting');
      }
      break;
    case 'hostkey':
      hostKey.value = msg;
      setStatus('hostkey');
      break;
    case 'error':
      fail(msg.message);
      break;
    case 'closed':
      hostKey.value = null;
      message.value = msg.reason === 'idle' ? t('ssh.terminal.closed_idle') : null;
      setStatus('closed');
      break;
  }
}

function closeSocket() {
  if (!ws) return;
  ws.onclose = null;
  ws.onmessage = null;
  ws.close();
  ws = null;
}

/** One SSH session per attempt (the first and every "reconnect"): ticket, socket, control messages. */
async function connect(again = false) {
  if (!term) return;
  closeSocket();
  hostKey.value = null;
  message.value = null;
  setStatus('connecting');
  if (again) term.write('\r\n');
  fitAndSync();
  let ticket: string;
  try {
    ({ ticket } = await api.prepareSshSession(props.request));
  } catch (err) {
    if (!disposed) fail((err as Error).message);
    return;
  }
  if (disposed || !term) return;
  const socket = createSshTerminalSocket(ticket, term.cols, term.rows);
  ws = socket;
  let opened = false;
  socket.onopen = () => {
    opened = true;
  };
  socket.onmessage = (event: MessageEvent) => {
    if (typeof event.data !== 'string') {
      term?.write(new Uint8Array(event.data as ArrayBuffer));
      return;
    }
    try {
      applyServerMessage(JSON.parse(event.data) as ServerMessage);
    } catch {
      // not a control message
    }
  };
  socket.onclose = () => {
    if (disposed || ws !== socket) return;
    // Refused during the handshake: the server did not accept this browser's login
    if (!opened) {
      message.value = t('ssh.terminal.login_required');
      setStatus('error');
      term?.writeln(red(t('ssh.terminal.login_required')));
      return;
    }
    if (status.value !== 'error') setStatus('closed');
    term?.writeln(`\r\n\x1b[90m${t('ssh.terminal.disconnected')}\x1b[0m`);
  };
}

function answerHostKey(accept: boolean) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: accept ? 'hostkey_accept' : 'hostkey_reject' }));
  hostKey.value = null;
  setStatus(accept ? 'authenticating' : 'closed');
}

// ── Clipboard ────────────────────────────────────────────────────────────────
type CopyState = 'idle' | 'copied' | 'empty';
const copyState = ref<CopyState>('idle');
const lastCopyState = ref<CopyState>('idle');
const pasteFallback = ref(false);
const pasteText = ref('');

function flash(target: typeof copyState, next: 'copied' | 'empty') {
  target.value = next;
  window.setTimeout(() => (target.value = 'idle'), 1500);
}

async function copySelection() {
  const text = term?.getSelection() ?? '';
  if (!text) return flash(copyState, 'empty');
  flash(copyState, (await copyText(text)) ? 'copied' : 'empty');
  term?.focus();
}

async function copyLastCommand() {
  if (!term || !lastCommand || lastCommand.isDisposed || lastCommand.line < 0) return flash(lastCopyState, 'empty');
  const text = lastCommandText(term.buffer.active, lastCommand.line);
  if (!text) return flash(lastCopyState, 'empty');
  flash(lastCopyState, (await copyText(text)) ? 'copied' : 'empty');
  term.focus();
}

async function paste() {
  try {
    // Only allowed over HTTPS (or localhost) and with permission
    if (!navigator.clipboard?.readText) throw new Error('clipboard unavailable');
    const text = await navigator.clipboard.readText();
    if (text) term?.paste(text);
    term?.focus();
  } catch {
    pasteText.value = '';
    pasteFallback.value = true;
  }
}

function submitPaste() {
  if (pasteText.value) term?.paste(pasteText.value);
  pasteFallback.value = false;
  term?.focus();
}

const copyLabel = (state: CopyState, idle: string, empty: string) => (state === 'copied' ? t('ssh.terminal.copied') : state === 'empty' ? t(empty) : t(idle));

// ── Agent update command ─────────────────────────────────────────────────────
const updating = ref(false);
const updateInert = computed(() => status.value !== 'connected' || updating.value || !props.agentUpdate?.available);

/**
 * Types the one-line installer (fresh single-use code) into the input line without Enter: the
 * user reviews and runs it. The leading space keeps it out of the shell history (HISTCONTROL).
 */
async function insertUpdate() {
  const update = props.agentUpdate;
  if (!update?.available || updateInert.value) return;
  updating.value = true;
  try {
    const { code, expiresAt } = await requestInstallCode(update.deviceId);
    const command = ` ${buildInstallCommand(update.deviceId, code)}`;
    if (/[\r\n]/.test(command)) throw new Error('Line break in the update command');
    if (!term) return;
    term.paste(command);
    term.focus();
    showToast('success', t('ssh.terminal.agent_update_inserted'), t('ssh.terminal.agent_update_inserted_text', { time: expiresAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }));
  } catch {
    showToast('error', t('ssh.terminal.agent_update'), t('agent.install_code_failed'));
  } finally {
    updating.value = false;
  }
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
onMounted(() => {
  const el = container.value!;
  term = new Terminal({
    cursorBlink: true,
    // Start with a fallback font; the chosen one is set once it has loaded (watch below)
    fontFamily: FONT_OPTIONS.find((f) => f.id === 'system')!.css,
    fontSize: terminalPrefs.fontSize,
    lineHeight: 1.15,
    scrollback: 5000,
    theme: resolveTheme(terminalPrefs),
  });
  fit = new FitAddon();
  term.loadAddon(fit);
  term.open(el);

  term.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown' || !e.ctrlKey || !e.shiftKey) return true;
    const key = e.key.toLowerCase();
    if (key === 'c') {
      void copySelection();
      return false;
    }
    if (key === 'v') {
      void paste();
      return false;
    }
    return true;
  });

  const encoder = new TextEncoder();
  const send = (data: Uint8Array) => {
    if (ws?.readyState === WebSocket.OPEN) ws.send(data);
  };
  term.onData((data) => {
    if (/[\r\n]/.test(data) && term) {
      // Enter: remember the line of this command (the cursor is still on it)
      lastCommand?.dispose();
      lastCommand = term.registerMarker(0) ?? null;
    }
    send(encoder.encode(data));
  });
  term.onBinary((data) => send(Uint8Array.from(data, (c) => c.charCodeAt(0) & 0xff)));

  observer = new ResizeObserver(() => fitAndSync());
  observer.observe(el);
  applyPrefs();
  void connect();
});

// Font, size and colours apply live. The font family is set only after it has loaded.
let fontRun = 0;
function applyPrefs() {
  if (!term) return;
  const prefs = { ...terminalPrefs };
  const run = ++fontRun;
  term.options.fontSize = prefs.fontSize;
  term.options.theme = resolveTheme(prefs);
  fitAndSync();
  void loadTerminalFont(prefs).then(() => {
    if (run !== fontRun || !term) return;
    term.options.fontFamily = fontCss(prefs);
    fitAndSync();
  });
}
watch(() => ({ ...terminalPrefs }), applyPrefs);
watch(appTheme, applyPrefs, { flush: 'post' });

// Hidden panes have no size; refit when the tab becomes visible
watch(
  () => props.active,
  async (isActive) => {
    if (!isActive) return;
    await nextTick();
    requestAnimationFrame(() => {
      fitAndSync();
      if (status.value === 'connected') term?.focus();
    });
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  disposed = true;
  closeSocket();
  observer?.disconnect();
  term?.dispose();
  term = null;
});
</script>

<template>
  <div class="relative flex h-full min-h-0 flex-col">
    <div class="flex shrink-0 flex-wrap items-center gap-0.5 border-b border-line bg-chrome px-2 py-1" role="toolbar" :aria-label="t('ssh.terminal.toolbar')">
      <Button size="sm" variant="ghost" :title="t('ssh.terminal.copy_hint')" :aria-label="t('ssh.terminal.copy')" @click="copySelection">
        <component :is="copyState === 'copied' ? Check : Copy" aria-hidden="true" /><span class="hidden lg:inline">{{ copyLabel(copyState, 'ssh.terminal.copy', 'ssh.terminal.nothing_selected') }}</span>
      </Button>
      <Button size="sm" variant="ghost" :title="t('ssh.terminal.copy_last_hint')" :aria-label="t('ssh.terminal.copy_last')" @click="copyLastCommand">
        <component :is="lastCopyState === 'copied' ? Check : ClipboardList" aria-hidden="true" /><span class="hidden lg:inline">{{ copyLabel(lastCopyState, 'ssh.terminal.copy_last', 'ssh.terminal.no_command_yet') }}</span>
      </Button>
      <Button size="sm" variant="ghost" :title="t('ssh.terminal.paste_hint')" :aria-label="t('ssh.terminal.paste')" @click="paste">
        <ClipboardPaste aria-hidden="true" /><span class="hidden lg:inline">{{ t('ssh.terminal.paste') }}</span>
      </Button>
      <button
        v-if="agentUpdate"
        type="button"
        class="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs transition-colors [&_svg]:size-4"
        :class="agentUpdate.available ? 'text-accent-text hover:bg-accent/10' : 'text-fg-subtle'"
        :aria-disabled="updateInert"
        :title="agentUpdate.available ? t('ssh.terminal.agent_update_hint', { from: agentUpdate.installed, to: agentUpdate.latest }) : t('ssh.terminal.agent_update_current', { version: agentUpdate.installed })"
        :aria-label="t('ssh.terminal.agent_update')"
        @click="insertUpdate"
      >
        <component :is="updating ? Loader2 : RefreshCw" :class="updating && 'animate-spin'" aria-hidden="true" />
        <span class="hidden lg:inline">{{ t('ssh.terminal.agent_update') }}</span>
        <span v-if="agentUpdate.available" class="size-1.5 rounded-full bg-accent" aria-hidden="true" />
      </button>
      <span class="mx-1 h-5 w-px bg-line" aria-hidden="true" />
      <Button size="icon-sm" variant="ghost" :aria-label="t('ssh.terminal.smaller')" :title="t('ssh.terminal.smaller')" @click="setTerminalPrefs({ fontSize: terminalPrefs.fontSize - 1 })"><Minus aria-hidden="true" /></Button>
      <span class="w-9 text-center font-mono text-[11px] text-fg-subtle tabular" aria-live="polite">{{ terminalPrefs.fontSize }}px</span>
      <Button size="icon-sm" variant="ghost" :aria-label="t('ssh.terminal.larger')" :title="t('ssh.terminal.larger')" @click="setTerminalPrefs({ fontSize: terminalPrefs.fontSize + 1 })"><Plus aria-hidden="true" /></Button>
      <TerminalSettings />
    </div>

    <!-- No padding on the element xterm measures: the fit addon reads its border-box -->
    <div class="min-h-0 flex-1 pl-2 pt-1.5" :style="{ background }">
      <div ref="container" class="h-full w-full" />
    </div>

    <div v-if="pasteFallback" class="absolute inset-0 z-10 grid place-items-center bg-black/40 p-4" role="dialog" aria-modal="false" :aria-label="t('ssh.terminal.paste')">
      <form class="w-full max-w-md space-y-3 rounded-lg border border-line bg-surface p-4 shadow-pop" @submit.prevent="submitPaste">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><ClipboardPaste class="size-4" aria-hidden="true" />{{ t('ssh.terminal.paste') }}</h3>
        <p class="text-xs text-fg-subtle">{{ t('ssh.terminal.paste_fallback') }}</p>
        <textarea v-model="pasteText" rows="5" spellcheck="false" class="w-full rounded-md border border-line bg-sunken p-2 font-mono text-xs text-fg focus:border-info focus:outline-none" :aria-label="t('ssh.terminal.paste')" autofocus />
        <div class="flex justify-end gap-2">
          <Button size="sm" @click="pasteFallback = false">{{ t('common.cancel') }}</Button>
          <Button size="sm" variant="primary" type="submit" :disabled="!pasteText"><ClipboardPaste aria-hidden="true" />{{ t('ssh.terminal.paste_send') }}</Button>
        </div>
      </form>
    </div>

    <div v-if="hostKey" class="absolute inset-0 z-10 grid place-items-center bg-black/50 p-4">
      <div v-if="hostKey.status === 'changed'" class="w-full max-w-lg space-y-3 rounded-lg border border-danger/50 bg-surface p-5 shadow-pop" role="alert">
        <h3 class="flex items-center gap-2 text-sm font-bold text-danger-text"><AlertTriangle class="size-4" aria-hidden="true" />{{ t('ssh.hostkey.changed_title') }}</h3>
        <p class="text-sm text-fg">{{ t('ssh.hostkey.changed_text', { host: `${hostKey.host}:${hostKey.port}` }) }}</p>
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt class="text-fg-subtle">{{ t('ssh.hostkey.known') }}</dt><dd class="font-mono break-all text-fg">{{ hostKey.known_fingerprint }}</dd>
          <dt class="text-fg-subtle">{{ t('ssh.hostkey.presented') }}</dt><dd class="font-mono break-all text-danger-text">{{ hostKey.fingerprint }}</dd>
        </dl>
        <p class="text-xs text-fg-subtle">{{ t('ssh.hostkey.changed_hint') }}</p>
        <div class="flex justify-end"><Button size="sm" @click="hostKey = null">{{ t('common.close') }}</Button></div>
      </div>
      <div v-else class="w-full max-w-lg space-y-3 rounded-lg border border-warn/50 bg-surface p-5 shadow-pop" role="dialog" aria-modal="false" :aria-label="t('ssh.hostkey.unknown_title')">
        <h3 class="flex items-center gap-2 text-sm font-bold text-warn-text"><ShieldAlert class="size-4" aria-hidden="true" />{{ t('ssh.hostkey.unknown_title') }}</h3>
        <p class="text-sm text-fg">{{ t('ssh.hostkey.unknown_text', { host: `${hostKey.host}:${hostKey.port}` }) }}</p>
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt class="text-fg-subtle">{{ t('ssh.hostkey.type') }}</dt><dd class="font-mono text-fg">{{ hostKey.key_type }}</dd>
          <dt class="text-fg-subtle">{{ t('ssh.hostkey.fingerprint') }}</dt><dd class="font-mono break-all text-fg">{{ hostKey.fingerprint }}</dd>
        </dl>
        <p class="text-xs text-fg-subtle">{{ t('ssh.hostkey.verify_hint', { file: hostKeyFile(hostKey.key_type) }) }}</p>
        <div class="flex justify-end gap-2">
          <Button size="sm" @click="answerHostKey(false)">{{ t('ssh.hostkey.reject') }}</Button>
          <Button size="sm" variant="primary" autofocus @click="answerHostKey(true)"><ShieldCheck aria-hidden="true" />{{ t('ssh.hostkey.accept') }}</Button>
        </div>
      </div>
    </div>

    <div
      v-else-if="status === 'connecting' || status === 'authenticating'"
      class="absolute top-12 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-line bg-surface/95 px-3 py-1.5 text-xs text-fg-muted shadow-pop"
      role="status"
    >
      <Loader2 class="size-3.5 animate-spin" aria-hidden="true" />
      {{ status === 'connecting' ? t('ssh.terminal.connecting') : t('ssh.terminal.authenticating') }}
    </div>
    <div
      v-else-if="status === 'closed' || status === 'error'"
      class="absolute inset-x-3 bottom-3 z-10 flex flex-wrap items-center gap-3 rounded-lg border bg-surface/95 px-3 py-2 text-xs shadow-pop"
      :class="status === 'error' ? 'border-danger/40 text-danger-text' : 'border-line text-fg-muted'"
      role="status"
    >
      <span class="min-w-0 flex-1">{{ message || t(status === 'error' ? 'ssh.terminal.error' : 'ssh.terminal.closed') }}</span>
      <Button size="sm" @click="connect(true)"><RotateCcw aria-hidden="true" />{{ t('ssh.terminal.reconnect') }}</Button>
    </div>
  </div>
</template>
