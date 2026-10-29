<script setup lang="ts">
import { History, Pencil, Plus, Save, Search, SquareTerminal, Trash2, X } from 'lucide-vue-next';
import type { Device, SshHistoryEntry, SshProfile } from '@/types';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/** Where to connect: saved connections, recent ad-hoc connections, and devices with SSH. */
defineProps<{
  profiles: SshProfile[];
  hasAnyProfile: boolean;
  history: SshHistoryEntry[];
  devices: Device[];
  loaded: boolean;
  profileDeviceIds: Set<number | null>;
}>();
const search = defineModel<string>('search', { default: '' });
const showAll = defineModel<boolean>('showAll', { default: false });
const emit = defineEmits<{
  newProfile: [];
  connectProfile: [profile: SshProfile];
  editProfile: [profile: SshProfile];
  deleteProfile: [profile: SshProfile];
  reconnect: [entry: SshHistoryEntry];
  saveHistory: [entry: SshHistoryEntry];
  removeHistory: [entry: SshHistoryEntry];
  connectDevice: [device: Device | null];
}>();

const portSuffix = (port: number) => (port !== 22 ? `:${port}` : '');
const rowClass = 'flex min-w-0 flex-1 items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-control-hover focus-visible:bg-control-hover';
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <label class="relative m-3 mb-2 block">
      <span class="sr-only">{{ t('ssh.targets.search') }}</span>
      <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
      <input v-model="search" type="search" :placeholder="t('ssh.targets.search')" class="h-9 w-full rounded-md border border-line bg-sunken pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none" />
    </label>

    <div class="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 pb-4">
      <section>
        <div class="mb-1 flex items-center justify-between gap-2 px-2">
          <h2 class="gl-eyebrow">{{ t('ssh.targets.profiles') }}</h2>
          <Button size="sm" variant="ghost" class="h-7" @click="emit('newProfile')"><Plus aria-hidden="true" />{{ t('ssh.targets.new_profile') }}</Button>
        </div>
        <p v-if="profiles.length === 0" class="px-2 text-xs text-fg-subtle">{{ hasAnyProfile ? t('ssh.targets.no_match') : t('ssh.targets.no_profiles') }}</p>
        <ul v-else class="space-y-0.5">
          <li v-for="p in profiles" :key="p.id" class="group flex items-center gap-0.5">
            <button type="button" :class="rowClass" :title="t('ssh.targets.connect')" @click="emit('connectProfile', p)">
              <SquareTerminal class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ p.name }}</span>
                <span class="block truncate font-mono text-xs text-fg-subtle">{{ p.username }}@{{ p.target_host }}{{ portSuffix(p.port) }}</span>
              </span>
              <Badge class="shrink-0">{{ p.auth_method === 'key' ? p.key_name || t('ssh.auth.key') : t(`ssh.auth.${p.auth_method}`) }}</Badge>
            </button>
            <Button size="icon-sm" variant="ghost" :aria-label="t('common.edit')" :title="t('common.edit')" @click="emit('editProfile', p)"><Pencil aria-hidden="true" /></Button>
            <Button size="icon-sm" variant="danger-ghost" :aria-label="t('common.delete')" :title="t('common.delete')" @click="emit('deleteProfile', p)"><Trash2 aria-hidden="true" /></Button>
          </li>
        </ul>
      </section>

      <section v-if="history.length > 0">
        <h2 class="gl-eyebrow mb-1 px-2">{{ t('ssh.targets.recent') }}</h2>
        <ul class="space-y-0.5">
          <li v-for="h in history" :key="h.id" class="flex items-center gap-0.5">
            <button type="button" :class="rowClass" :title="t('ssh.targets.connect')" @click="emit('reconnect', h)">
              <History class="size-4 shrink-0 text-fg-subtle" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ h.label }}</span>
                <span class="block truncate font-mono text-xs text-fg-subtle">{{ h.target_host }}{{ portSuffix(h.port) }}</span>
              </span>
              <Badge class="shrink-0">{{ h.auth_method === 'key' ? h.key_name || t('ssh.auth.key') : t('ssh.auth.password') }}</Badge>
            </button>
            <Button size="icon-sm" variant="ghost" :aria-label="t('ssh.targets.save_connection')" :title="t('ssh.targets.save_connection')" @click="emit('saveHistory', h)"><Save aria-hidden="true" /></Button>
            <Button size="icon-sm" variant="danger-ghost" :aria-label="t('ssh.targets.remove_recent')" :title="t('ssh.targets.remove_recent')" @click="emit('removeHistory', h)"><X aria-hidden="true" /></Button>
          </li>
        </ul>
      </section>

      <section>
        <div class="mb-1 flex items-center justify-between gap-2 px-2">
          <h2 class="gl-eyebrow">{{ t('ssh.targets.devices') }}</h2>
          <Button size="sm" variant="ghost" class="h-7" @click="emit('connectDevice', null)"><Plus aria-hidden="true" />{{ t('ssh.targets.other_host') }}</Button>
        </div>
        <label class="mb-1 flex items-center gap-2 px-2 text-xs text-fg-muted">
          <input v-model="showAll" type="checkbox" class="size-3.5 accent-[var(--gl-accent)]" />
          {{ t('ssh.targets.show_all') }}
        </label>
        <p v-if="devices.length === 0" class="px-2 text-xs text-fg-subtle">{{ loaded ? t('ssh.targets.no_devices') : t('common.loading') }}</p>
        <ul v-else class="space-y-0.5">
          <li v-for="d in devices" :key="d.id" class="flex">
            <button type="button" :class="rowClass" :title="t('ssh.targets.connect')" @click="emit('connectDevice', d)">
              <StatusDot :state="d.is_online ? 'online' : 'offline'" size="sm" class="mx-1" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ deviceLabel(d) }}</span>
                <span class="block truncate font-mono text-xs text-fg-subtle">{{ d.ip }}</span>
              </span>
              <Badge v-if="profileDeviceIds.has(d.id)" tone="info" class="shrink-0">{{ t('ssh.targets.has_profile') }}</Badge>
            </button>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
