<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { CheckCircle2, Copy, KeyRound, Plus, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { ApiTokenResponse } from '@/types';
import SettingsSection from './SettingsSection.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { copyText } from '@/lib/clipboard';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { formatDateTime, t } from '@/i18n';

/** Read-only API tokens: generate one (shown once), list and revoke. */
const { showToast } = useToast();
const { confirm } = useConfirm();
const tokens = ref<ApiTokenResponse[]>([]);
const newName = ref('');
const created = ref('');
const creating = ref(false);

async function load() {
  try {
    tokens.value = await api.getApiTokens();
  } catch {
    // keep the list
  }
}
onMounted(load);

async function create() {
  const name = newName.value.trim();
  if (!name) return;
  creating.value = true;
  created.value = '';
  try {
    const res = await api.createApiToken(name);
    created.value = res.token;
    newName.value = '';
    await load();
  } catch (err) {
    showToast('error', t('common.error'), `${t('settings.token_create_failed')} ${(err as Error).message}`);
  } finally {
    creating.value = false;
  }
}

async function copy() {
  if (await copyText(created.value)) showToast('success', t('common.success'), t('notifications.copied'));
  else showToast('error', t('common.error'), t('settings.copy_failed'));
}

async function revoke(token: ApiTokenResponse) {
  const ok = await confirm({ title: t('settings.revoke_token', { name: token.name }), message: t('settings.delete_token_confirm'), danger: true });
  if (!ok) return;
  try {
    await api.deleteApiToken(token.id);
    showToast('success', t('common.success'), t('settings.token_revoked'));
    await load();
  } catch (err) {
    showToast('error', t('common.error'), `${t('settings.token_revoke_failed')} ${(err as Error).message}`);
  }
}
</script>

<template>
  <SettingsSection id="tokens" :title="t('settings.api_tokens')" :description="t('settings.api_tokens_desc')">
    <form class="flex gap-2" @submit.prevent="create">
      <Input v-model="newName" :placeholder="t('settings.new_token_placeholder')" :aria-label="t('settings.new_token_placeholder')" :disabled="creating" />
      <Button type="submit" :loading="creating" :disabled="!newName.trim()"><Plus v-if="!creating" aria-hidden="true" />{{ t('settings.token_create') }}</Button>
    </form>

    <div v-if="created" role="status" class="space-y-2 rounded-md border border-accent/30 bg-accent/[0.07] p-3">
      <p class="flex items-center gap-2 text-sm text-fg"><CheckCircle2 class="size-4 text-accent-text" aria-hidden="true" />{{ t('settings.token_created_title') }}</p>
      <div class="flex gap-2">
        <input :value="created" readonly :aria-label="t('settings.api_tokens')" class="h-9 min-w-0 flex-1 rounded-md border border-line bg-sunken px-3 font-mono text-xs text-fg" @focus="($event.target as HTMLInputElement).select()" />
        <Button @click="copy"><Copy aria-hidden="true" />{{ t('settings.token_copy') }}</Button>
      </div>
    </div>

    <EmptyState v-if="tokens.length === 0" compact :icon="KeyRound" :title="t('settings.no_tokens')" />
    <ul v-else class="divide-y divide-line rounded-md border border-line">
      <li v-for="token in tokens" :key="token.id" class="flex items-center gap-3 px-3 py-2.5">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-fg">{{ token.name }}</p>
          <p class="mt-0.5 flex flex-wrap gap-x-2 text-xs text-fg-subtle">
            <code class="font-mono text-fg-muted">{{ token.prefix }}…</code>
            <span>{{ t('settings.token_created') }}: {{ formatDateTime(token.created_at, { dateStyle: 'medium' }) }}</span>
            <span v-if="token.last_used_at">{{ t('settings.token_used') }}: <RelativeTime :date="token.last_used_at" /></span>
          </p>
        </div>
        <Button size="icon-sm" variant="danger-ghost" :aria-label="t('settings.revoke_token', { name: token.name })" :title="t('settings.revoke_token', { name: token.name })" @click="revoke(token)"><Trash2 aria-hidden="true" /></Button>
      </li>
    </ul>
  </SettingsSection>
</template>
