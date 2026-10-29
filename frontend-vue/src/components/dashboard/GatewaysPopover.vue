<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ArrowRight, Check, Copy, GitMerge, Network, Router, Search } from 'lucide-vue-next';
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui';
import { api } from '@/api/client';
import type { GatewayEntry, MergeSuggestion } from '@/types';
import Button from '@/components/ui/Button.vue';
import Skeleton from '@/components/ui/Skeleton.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { networkColor } from '@/lib/networks';
import { copyText } from '@/lib/clipboard';
import { t } from '@/i18n';

/** Gateways of all subnets, listed in a keyboard-navigable popover in the dashboard toolbar. */
const emit = defineEmits<{ openDevice: [deviceId: number, tab?: 'interfaces'] }>();
const router = useRouter();

const open = ref(false);
const entries = ref<GatewayEntry[] | null>(null);
const suggestions = ref<MergeSuggestion[]>([]);
const error = ref<string | null>(null);
const query = ref('');
const copiedIp = ref<string | null>(null);
const listEl = ref<HTMLElement | null>(null);
const searchEl = ref<HTMLInputElement | null>(null);

async function reload() {
  try {
    const [gateways, merge] = await Promise.all([api.getGateways(), api.getMergeSuggestions().catch(() => [] as MergeSuggestion[])]);
    entries.value = gateways;
    suggestions.value = merge;
    error.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
}
void reload();

const offline = computed(() => (entries.value ?? []).filter((e) => e.gateway_ip && e.is_online === false).length);
const visible = computed(() => {
  const words = query.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return (entries.value ?? []).filter((entry) => {
    if (words.length === 0) return true;
    const hay = [entry.subnet_name, entry.cidr, entry.gateway_ip, entry.device_name, entry.vlan_id != null && `vlan ${entry.vlan_id}`]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();
    return words.every((w) => hay.includes(w));
  });
});

function onOpenChange(value: boolean) {
  open.value = value;
  if (value) {
    void reload();
    void nextTick(() => (searchEl.value ?? listEl.value?.querySelector<HTMLElement>('[data-row]'))?.focus());
  }
}

function status(entry: GatewayEntry): { state: 'online' | 'offline' | 'unknown'; text: string } {
  if (entry.is_online === true) return { state: 'online', text: t('network.online') };
  if (entry.is_online === false) return { state: 'offline', text: t('network.offline') };
  return { state: 'unknown', text: t('gateways.not_seen') };
}

function openEntry(entry: GatewayEntry) {
  open.value = false;
  if (entry.device_id != null) emit('openDevice', entry.device_id, entry.interface_id != null ? 'interfaces' : undefined);
  else router.push('/network');
}

async function copy(ip: string) {
  if (await copyText(ip)) {
    copiedIp.value = ip;
    window.setTimeout(() => (copiedIp.value = null), 1500);
  }
}

/** Arrow keys move between rows, Up from the first row returns to the filter. */
function onKeydown(event: KeyboardEvent) {
  const rows = Array.from(listEl.value?.querySelectorAll<HTMLElement>('[data-row]') ?? []);
  const index = rows.findIndex((row) => row === document.activeElement);
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    rows[Math.min(rows.length - 1, index + 1)]?.focus();
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    if (index <= 0) searchEl.value?.focus();
    else rows[index - 1]?.focus();
  } else if ((event.key === 'Home' || event.key === 'End') && index >= 0) {
    event.preventDefault();
    rows[event.key === 'Home' ? 0 : rows.length - 1]?.focus();
  } else if (event.key === 'Enter' && event.target === searchEl.value && rows.length > 0) {
    event.preventDefault();
    rows[0].focus();
  }
}
</script>

<template>
  <PopoverRoot :open="open" @update:open="onOpenChange">
    <PopoverTrigger as-child>
      <Button
        :aria-label="offline ? `${t('gateways.title')}: ${t('gateways.offline_count', { count: offline })}` : t('gateways.title')"
        class="relative"
      >
        <Router aria-hidden="true" />
        <span class="hidden lg:inline">{{ t('gateways.title') }}</span>
        <span v-if="entries && entries.length > 0" class="font-mono text-xs text-fg-subtle">{{ entries.length }}</span>
        <span v-if="offline > 0" class="absolute -top-0.5 -right-0.5 size-2.5 rounded-full border-2 border-canvas bg-danger" aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        align="end"
        :side-offset="8"
        class="z-50 flex max-h-[min(36rem,75dvh)] w-[min(30rem,calc(100vw-1.5rem))] flex-col rounded-lg border border-line bg-surface shadow-pop"
        @keydown="onKeydown"
      >
        <div class="border-b border-line px-4 py-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold text-fg"><Router class="size-4" aria-hidden="true" />{{ t('gateways.title') }}</h2>
          <p class="mt-0.5 text-xs text-fg-subtle">{{ t('gateways.subtitle', { count: entries?.length ?? 0 }) }}</p>
        </div>

        <label v-if="(entries?.length ?? 0) > 3" class="flex items-center gap-2 border-b border-line px-4 py-2">
          <Search class="size-4 text-fg-subtle" aria-hidden="true" />
          <input
            ref="searchEl"
            v-model="query"
            type="search"
            :placeholder="t('gateways.filter')"
            :aria-label="t('gateways.filter')"
            class="h-8 min-w-0 flex-1 bg-transparent text-sm text-fg placeholder:text-fg-subtle focus:outline-none"
          />
        </label>

        <div ref="listEl" class="min-h-0 flex-1 overflow-y-auto p-1.5">
          <p v-if="error" role="alert" class="px-3 py-6 text-center text-sm text-danger-text">{{ t('gateways.load_failed', { error }) }}</p>
          <div v-else-if="entries === null" class="space-y-1.5 p-1.5" aria-hidden="true">
            <Skeleton v-for="i in 3" :key="i" class="h-12" />
          </div>
          <p v-else-if="entries.length === 0" class="px-3 py-6 text-center text-sm text-fg-subtle">{{ t('gateways.no_subnets') }}</p>
          <p v-else-if="visible.length === 0" class="px-3 py-6 text-center text-sm text-fg-subtle">{{ t('gateways.no_match') }}</p>
          <ul v-else class="space-y-0.5">
            <li v-for="entry in visible" :key="entry.subnet_id" class="group flex items-center gap-1 rounded-md" :class="!entry.is_enabled && 'opacity-60'">
              <button
                data-row
                type="button"
                class="flex min-w-0 flex-1 items-center gap-3 rounded-md px-2.5 py-2 text-left hover:bg-raised focus-visible:bg-raised"
                :aria-label="t('gateways.row_label', {
                  where: entry.vlan_id != null ? `${entry.subnet_name}, VLAN ${entry.vlan_id}` : entry.subnet_name,
                  ip: entry.gateway_ip ?? '—',
                  status: status(entry).text,
                  target: entry.device_name || t('gateways.unknown_device'),
                })"
                @click="openEntry(entry)"
              >
                <span class="h-8 w-1 shrink-0 rounded-full" :style="{ backgroundColor: networkColor(entry.subnet_id, entry.gateway_ip) }" aria-hidden="true" />
                <span class="min-w-0 flex-1">
                  <span class="flex items-center gap-1.5">
                    <span v-if="entry.vlan_id != null" class="rounded-sm bg-raised px-1 font-mono text-micro text-fg-muted">VLAN {{ entry.vlan_id }}</span>
                    <span class="truncate text-sm font-medium text-fg">{{ entry.subnet_name }}</span>
                    <span class="hidden truncate font-mono text-xs text-fg-subtle sm:inline">{{ entry.cidr }}</span>
                  </span>
                  <span class="mt-0.5 flex items-center gap-1.5 text-xs text-fg-muted">
                    <StatusDot size="sm" :state="status(entry).state" />
                    <span class="font-mono">{{ entry.gateway_ip ?? '—' }}</span>
                    <span v-if="entry.source && entry.source !== 'configured'" class="rounded-sm border border-line px-1 text-micro text-fg-subtle">
                      {{ t(`gateways.source_${entry.source}`) }}
                    </span>
                    <ArrowRight class="size-3 text-fg-subtle" aria-hidden="true" />
                    <span class="truncate" :class="entry.device_id == null && 'text-fg-subtle italic'">{{ entry.device_name || t('gateways.unknown_device') }}</span>
                  </span>
                </span>
              </button>
              <button
                v-if="entry.gateway_ip"
                type="button"
                class="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-fg-subtle opacity-0 group-hover:opacity-100 hover:bg-raised hover:text-fg focus-visible:opacity-100 [@media(hover:none)]:opacity-100"
                :aria-label="copiedIp === entry.gateway_ip ? t('gateways.copied') : t('gateways.copy_ip', { ip: entry.gateway_ip })"
                @click="copy(entry.gateway_ip)"
              >
                <Check v-if="copiedIp === entry.gateway_ip" class="size-3.5 text-accent-text" aria-hidden="true" />
                <Copy v-else class="size-3.5" aria-hidden="true" />
              </button>
            </li>
          </ul>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2">
          <button
            v-if="suggestions.length > 0"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-warn-text hover:bg-warn/10"
            @click="open = false; emit('openDevice', suggestions[0].target_id, 'interfaces')"
          >
            <GitMerge class="size-3.5" aria-hidden="true" />{{ t('gateways.merge_hint', { count: suggestions.length }) }}
          </button>
          <button
            type="button"
            class="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-fg-muted hover:bg-raised hover:text-fg"
            @click="open = false; router.push('/network')"
          >
            <Network class="size-3.5" aria-hidden="true" />{{ t('gateways.manage_subnets') }}
          </button>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
