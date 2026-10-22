<script setup lang="ts">
import { ShieldCheck, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { SshKnownHost } from '@/types';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { formatDateTime, t } from '@/i18n';

/** Host keys trusted on first connect; removing one makes the next connect ask again. */
defineProps<{ hosts: SshKnownHost[] }>();
const emit = defineEmits<{ changed: [] }>();
const { showToast } = useToast();

const when = (value: string | null) => (value ? formatDateTime(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`) : '–');

async function remove(entry: SshKnownHost) {
  const host = `${entry.host}:${entry.port}`;
  const ok = await confirmAction({ title: t('ssh.known_hosts.remove'), message: t('ssh.known_hosts.delete_confirm', { host }), confirmLabel: t('ssh.known_hosts.remove'), danger: true });
  if (!ok) return;
  try {
    await api.deleteSshKnownHost(entry.id);
    emit('changed');
  } catch (err) {
    showToast('error', t('ssh.known_hosts.title'), (err as Error).message);
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-4">
    <div class="flex gap-3 rounded-lg border border-info/30 bg-info/10 p-3 text-sm text-fg">
      <ShieldCheck class="mt-0.5 size-4 shrink-0 text-info-text" aria-hidden="true" />
      <p>{{ t('ssh.known_hosts.info') }}</p>
    </div>
    <section class="gl-card p-4">
      <p v-if="hosts.length === 0" class="text-sm text-fg-subtle">{{ t('ssh.known_hosts.empty') }}</p>
      <ul v-else class="divide-y divide-line">
        <li v-for="entry in hosts" :key="entry.id" class="flex items-start gap-3 py-3">
          <span class="grid size-8 shrink-0 place-items-center rounded-md border border-line bg-raised text-accent-text" aria-hidden="true"><ShieldCheck class="size-4" /></span>
          <span class="min-w-0 flex-1 space-y-0.5">
            <span class="flex flex-wrap items-center gap-1.5 font-mono text-sm font-semibold text-fg">{{ entry.host }}:{{ entry.port }}<Badge mono>{{ entry.key_type }}</Badge></span>
            <span class="block truncate font-mono text-[11px] text-fg-subtle">{{ entry.fingerprint }}</span>
            <span class="block text-[11px] text-fg-subtle">{{ t('ssh.known_hosts.seen', { first: when(entry.first_seen), last: when(entry.last_seen) }) }}</span>
          </span>
          <Button size="icon-sm" variant="danger-ghost" :title="t('ssh.known_hosts.remove')" :aria-label="t('ssh.known_hosts.remove')" @click="remove(entry)"><Trash2 aria-hidden="true" /></Button>
        </li>
      </ul>
    </section>
  </div>
</template>
