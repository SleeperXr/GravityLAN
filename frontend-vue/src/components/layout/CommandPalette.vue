<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui';
import { useEventListener } from '@vueuse/core';
import { useRouter } from 'vue-router';
import { Search } from 'lucide-vue-next';
import StatusDot from '@/components/common/StatusDot.vue';
import { NAV_ITEMS, lineInk, lineVar } from './navigation';
import { useNetworkStore } from '@/stores/network';
import { deviceLabel } from '@/lib/networks';
import { commandPaletteOpen as open, searchCommands, type CommandItem, type DeviceCommand, type PageCommand } from '@/lib/commandSearch';
import { t } from '@/i18n';

/**
 * The app-wide search: Ctrl+K (Cmd+K) from any page, or the search button in the sidebar. Finds
 * pages and devices by name, address, MAC, host name or vendor; a device opens in its editor on
 * the overview. Arrow keys move, Enter opens, Escape closes.
 */
const router = useRouter();
const store = useNetworkStore();
const query = ref('');
const active = ref(0);
const listId = 'gl-command-list';

useEventListener(window, 'keydown', (e: KeyboardEvent) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    open.value = !open.value;
  }
});

watch(open, (isOpen) => {
  if (!isOpen) return;
  query.value = '';
  active.value = 0;
  if (!store.loaded) void store.loadData();
});

const pages = computed<PageCommand[]>(() => NAV_ITEMS.map((n) => ({ kind: 'page', id: n.id, to: n.to, label: t(n.label) })));
const devices = computed<DeviceCommand[]>(() =>
  store.devices.map((d) => ({
    kind: 'device',
    id: d.id,
    label: deviceLabel(d),
    ip: d.ip,
    online: d.is_online,
    extra: [d.hostname, d.mac, d.vendor, ...(d.interfaces ?? []).map((i) => i.ip)].filter((v): v is string => !!v),
  })),
);
const results = computed(() => searchCommands(query.value, pages.value, devices.value));
watch(results, () => (active.value = 0));

const navOf = (id: string) => NAV_ITEMS.find((n) => n.id === id)!;
const optionId = (i: number) => `${listId}-${i}`;
const firstDevice = computed(() => results.value.findIndex((r) => r.kind === 'device'));

function run(item: CommandItem) {
  open.value = false;
  if (item.kind === 'page') void router.push(item.to);
  else void router.push({ path: '/', query: { device: String(item.id) } });
}

function onKey(e: KeyboardEvent) {
  const count = results.value.length;
  if (e.key === 'ArrowDown' && count) active.value = (active.value + 1) % count;
  else if (e.key === 'ArrowUp' && count) active.value = (active.value - 1 + count) % count;
  else if (e.key === 'Home' && count) active.value = 0;
  else if (e.key === 'End' && count) active.value = count - 1;
  else if (e.key === 'Enter' && results.value[active.value]) run(results.value[active.value]);
  else return;
  e.preventDefault();
  document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' });
}
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="gl-overlay fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
      <DialogContent
        class="gl-dialog fixed inset-x-3 top-[12dvh] z-50 mx-auto flex max-h-[70dvh] max-w-xl flex-col overflow-hidden rounded-xl border border-line bg-popover shadow-pop focus:outline-none"
      >
        <DialogTitle class="sr-only">{{ t('gv.search.title') }}</DialogTitle>
        <DialogDescription class="sr-only">{{ t('gv.search.hint') }}</DialogDescription>
        <label class="flex items-center gap-3 border-b border-line px-4">
          <Search class="size-4 shrink-0 text-fg-subtle" aria-hidden="true" />
          <span class="sr-only">{{ t('gv.search.title') }}</span>
          <input
            v-model="query"
            type="text"
            role="combobox"
            autocomplete="off"
            spellcheck="false"
            :placeholder="t('gv.search.placeholder')"
            :aria-expanded="results.length > 0"
            :aria-controls="listId"
            :aria-activedescendant="results.length ? optionId(active) : undefined"
            class="h-12 min-w-0 flex-1 bg-transparent text-sm text-fg placeholder:text-fg-subtle focus:outline-none max-md:text-base"
            @keydown="onKey"
          />
          <kbd class="hidden rounded border border-line px-1.5 py-0.5 font-mono text-micro text-fg-subtle sm:inline">Esc</kbd>
        </label>

        <ul v-if="results.length" :id="listId" role="listbox" :aria-label="t('gv.search.title')" class="min-h-0 flex-1 overflow-y-auto p-1.5">
          <li v-if="results[0]?.kind === 'page'" role="presentation" class="px-2.5 pt-1.5 pb-1 text-xs font-medium text-fg-subtle">{{ t('gv.search.pages') }}</li>
          <template v-for="(item, i) in results" :key="`${item.kind}-${item.id}`">
            <li v-if="i === firstDevice" role="presentation" class="px-2.5 pt-2.5 pb-1 text-xs font-medium text-fg-subtle">{{ t('gv.search.devices') }}</li>
            <li
              :id="optionId(i)"
              role="option"
              :aria-selected="i === active"
              class="flex min-h-10 cursor-pointer items-center gap-3 rounded-md px-2.5 text-sm max-md:min-h-11"
              :class="i === active ? 'bg-hover text-fg' : 'text-fg-muted'"
              @mousemove="active = i"
              @click="run(item)"
            >
              <template v-if="item.kind === 'page'">
                <span
                  class="grid size-6 shrink-0 place-items-center rounded-[7px] [&_svg]:size-3.5"
                  :style="{ background: `color-mix(in oklab, ${lineVar(navOf(item.id))} 16%, transparent)`, color: lineInk(navOf(item.id)) }"
                  aria-hidden="true"
                >
                  <component :is="navOf(item.id).icon" />
                </span>
                <span class="truncate font-medium text-fg">{{ item.label }}</span>
              </template>
              <template v-else>
                <StatusDot class="mx-[7px]" :state="item.online ? 'online' : 'offline'" :label="item.online ? t('network.online') : t('network.offline')" size="sm" />
                <span class="min-w-0 flex-1 truncate font-medium text-fg">{{ item.label }}</span>
                <span class="shrink-0 font-mono text-xs text-fg-subtle tabular">{{ item.ip }}</span>
              </template>
            </li>
          </template>
        </ul>
        <p v-else class="px-4 py-8 text-center text-sm text-fg-subtle">{{ t('gv.search.empty', { query }) }}</p>

        <footer class="hidden border-t border-line px-4 py-2 text-xs text-fg-subtle sm:block">
          {{ t('gv.search.hint') }}
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
