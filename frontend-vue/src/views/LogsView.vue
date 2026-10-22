<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ArrowDown, Copy, Pause, Play, Search, Trash2 } from 'lucide-vue-next';
import PageHeader from '@/components/ui/PageHeader.vue';
import Button from '@/components/ui/Button.vue';
import { MAX_LINES, countLevels, filterLogs, parseLogLine, type LogLevel, type LogLine } from '@/components/logstream/logModel';
import { copyText } from '@/lib/clipboard';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Live backend log over /api/logs/ws (last 500 lines). Follows the newest line while scrolled to
 * the bottom; scrolling up holds the view until "jump to newest".
 */
const { showToast } = useToast();
const lines = ref<LogLine[]>([]);
const connected = ref(false);
const paused = ref(false);
const level = ref<'all' | 'warning' | 'error'>('all');
const search = ref('');
const follow = ref(true);
const box = ref<HTMLElement | null>(null);
let ws: WebSocket | null = null;
let nextId = 1;
let retry: number | undefined;

function open() {
  close();
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let token = localStorage.getItem('gravitylan_token') || '';
  if (token === 'undefined') token = '';
  const socket = new WebSocket(`${protocol}//${window.location.host}/api/logs/ws?token=${encodeURIComponent(token)}`);
  ws = socket;
  socket.onopen = () => (connected.value = true);
  socket.onclose = () => {
    if (ws !== socket) return;
    connected.value = false;
    // The backend restarted or the network blinked: try again while the stream is wanted
    if (!paused.value) retry = window.setTimeout(open, 5000);
  };
  socket.onmessage = (event) => {
    const next = [...lines.value, parseLogLine(String(event.data), nextId++)];
    lines.value = next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
  };
}

function close() {
  window.clearTimeout(retry);
  if (!ws) return;
  const socket = ws;
  ws = null;
  socket.close();
  connected.value = false;
}

watch(paused, (isPaused) => (isPaused ? close() : open()));
onMounted(open);
onBeforeUnmount(close);

const visible = computed(() => filterLogs(lines.value, level.value, search.value));
const counts = computed(() => countLevels(lines.value));

function onScroll() {
  const el = box.value;
  if (el) follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
}

function jumpToNewest() {
  follow.value = true;
  if (box.value) box.value.scrollTop = box.value.scrollHeight;
}

watch(visible, async () => {
  if (!follow.value) return;
  await nextTick();
  if (box.value) box.value.scrollTop = box.value.scrollHeight;
});

async function copyVisible() {
  const ok = await copyText(visible.value.map((l) => l.raw).join('\n'));
  showToast(ok ? 'success' : 'error', t('common.copy'), ok ? t('gv.logs.copied', { count: visible.value.length }) : t('gv.logs.copy_failed'));
}

const levelText: Record<LogLevel, string> = { debug: 'text-fg-subtle', info: 'text-info-text', warning: 'text-warn-text', error: 'text-danger-text' };
const levelRow: Record<LogLevel, string> = { debug: '', info: '', warning: 'bg-warn/[0.06]', error: 'bg-danger/[0.08]' };
const levelLabel: Record<LogLevel, string> = { debug: 'DEBUG', info: 'INFO', warning: 'WARN', error: 'ERROR' };
const shortTime = (time: string) => time.slice(11, 19);
</script>

<template>
  <div class="mx-auto flex h-full min-h-[30rem] max-w-[1800px] flex-col gap-4 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('sidebar.logs')" :description="t('gv.logs.subtitle')">
      <span class="flex items-center gap-2 text-xs font-medium" :class="connected ? 'text-accent-text' : paused ? 'text-fg-subtle' : 'text-danger-text'" role="status">
        <span class="size-2 rounded-full" :class="connected ? 'bg-accent shadow-[0_0_8px_var(--gl-accent)]' : paused ? 'bg-fg-subtle' : 'bg-danger'" aria-hidden="true" />
        {{ connected ? t('gv.logs.live') : paused ? t('gv.logs.paused') : t('gv.logs.reconnecting') }}
      </span>
    </PageHeader>

    <div class="flex flex-wrap items-center gap-2">
      <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('gv.logs.level')">
        <button
          v-for="opt in (['all', 'warning', 'error'] as const)"
          :key="opt"
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-xs font-semibold transition-colors"
          :class="level === opt ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="level === opt"
          @click="level = opt"
        >
          {{ t(`gv.logs.level_${opt}`) }}
          <span v-if="opt !== 'all' && counts[opt] > 0" class="rounded-sm px-1 font-mono text-[10px]" :class="opt === 'error' ? 'bg-danger/15 text-danger-text' : 'bg-warn/15 text-warn-text'">{{ counts[opt] }}</span>
        </button>
      </div>
      <label class="relative min-w-0 flex-1 sm:max-w-xs">
        <span class="sr-only">{{ t('gv.logs.search') }}</span>
        <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
        <input v-model="search" type="search" :placeholder="t('gv.logs.search')" class="h-9 w-full rounded-md border border-line bg-surface pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:outline-none" />
      </label>
      <div class="ml-auto flex gap-1">
        <Button size="icon" variant="ghost" :aria-label="paused ? t('common.resume') : t('common.pause')" :title="paused ? t('common.resume') : t('common.pause')" :aria-pressed="paused" @click="paused = !paused">
          <component :is="paused ? Play : Pause" aria-hidden="true" />
        </Button>
        <Button size="icon" variant="ghost" :aria-label="t('common.copy')" :title="t('common.copy')" :disabled="visible.length === 0" @click="copyVisible"><Copy aria-hidden="true" /></Button>
        <Button size="icon" variant="danger-ghost" :aria-label="t('common.clear')" :title="t('common.clear')" :disabled="lines.length === 0" @click="lines = []"><Trash2 aria-hidden="true" /></Button>
      </div>
    </div>

    <section class="gl-card relative flex min-h-0 flex-1 flex-col overflow-hidden" :aria-label="t('settings.live_logs_title')">
      <div ref="box" class="min-h-0 flex-1 overflow-auto bg-sunken py-2 font-mono text-[12px] leading-relaxed" role="log" aria-live="off" tabindex="0" @scroll="onScroll">
        <p v-if="lines.length === 0" class="px-4 py-3 text-fg-subtle italic">{{ paused ? t('gv.logs.paused_hint') : t('gv.logs.waiting') }}</p>
        <p v-else-if="visible.length === 0" class="px-4 py-3 text-fg-subtle italic">{{ t('gv.logs.no_match') }}</p>
        <div
          v-for="line in visible"
          :key="line.id"
          class="grid grid-cols-[auto_1fr] gap-x-3 px-4 py-px hover:bg-control-hover/60 sm:grid-cols-[4.5rem_3.5rem_minmax(0,11rem)_1fr]"
          :class="line.level ? levelRow[line.level] : ''"
        >
          <template v-if="line.time">
            <span class="text-fg-subtle tabular" :title="line.time">{{ shortTime(line.time) }}</span>
            <span class="font-semibold" :class="line.level ? levelText[line.level] : 'text-fg-subtle'">{{ line.level ? levelLabel[line.level] : '' }}</span>
            <span class="col-span-2 truncate text-fg-subtle sm:col-span-1" :title="line.correlationId ? `${line.logger} · ${line.correlationId}` : (line.logger ?? undefined)">{{ line.logger }}</span>
            <span class="col-span-2 [overflow-wrap:anywhere] whitespace-pre-wrap text-fg sm:col-span-1">{{ line.message }}</span>
          </template>
          <span v-else class="col-span-full [overflow-wrap:anywhere] whitespace-pre-wrap" :class="line.level ? levelText[line.level] : 'text-fg-muted'">{{ line.raw }}</span>
        </div>
      </div>
      <Button v-if="!follow && visible.length > 0" size="sm" variant="primary" class="absolute right-4 bottom-4 shadow-pop" @click="jumpToNewest">
        <ArrowDown aria-hidden="true" />{{ t('gv.logs.jump') }}
      </Button>
    </section>
  </div>
</template>
