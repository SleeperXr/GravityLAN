<script setup lang="ts">
import { ref, useId } from 'vue';
import { Copy, KeyRound, Lock, ShieldCheck, Sparkles, Trash2, Upload } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { SshKey, SshStatus } from '@/types';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import Input from '@/components/ui/Input.vue';
import Textarea from '@/components/ui/Textarea.vue';
import { copyText } from '@/lib/clipboard';
import { confirmAction } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { formatDateTime, t } from '@/i18n';

/** The encrypted key store: import (pasted or from a file) or generate keys, copy public keys, delete. */
const props = defineProps<{ keys: SshKey[]; status: SshStatus | null }>();
const emit = defineEmits<{ changed: [] }>();
const { showToast } = useToast();
const id = useId();

const mode = ref<'import' | 'generate'>('import');
const name = ref('');
const autoName = ref('');
const privateKey = ref('');
const passphrase = ref('');
const busy = ref(false);
const error = ref<string | null>(null);
const generated = ref<SshKey | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

const when = (value: string | null) => (value ? formatDateTime(value.endsWith('Z') || value.includes('+') ? value : `${value}Z`) : '–');

async function readFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  // Reset so picking the same file again still fires change
  input.value = '';
  if (!file) return;
  if (file.size > 16384) {
    error.value = t('ssh.keys.file_too_large');
    return;
  }
  privateKey.value = await file.text();
  // Follow the chosen file unless the user typed a name of their own
  const fileName = file.name.replace(/\.(pem|key|ppk)$/i, '');
  if (!name.value || name.value === autoName.value) {
    name.value = fileName;
    autoName.value = fileName;
  }
  error.value = null;
}

async function submit() {
  error.value = null;
  busy.value = true;
  try {
    if (mode.value === 'generate') {
      generated.value = await api.generateSshKey(name.value.trim());
    } else {
      await api.createSshKey({ name: name.value.trim(), private_key: privateKey.value, passphrase: passphrase.value || undefined });
      showToast('success', t('ssh.keys.title'), t('ssh.keys.imported', { name: name.value.trim() }));
      generated.value = null;
    }
    name.value = '';
    autoName.value = '';
    privateKey.value = '';
    passphrase.value = '';
    emit('changed');
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function copyPublicKey(key: SshKey) {
  const ok = await copyText(key.public_key);
  showToast(ok ? 'success' : 'error', t('ssh.keys.public_key'), ok ? t('ssh.keys.copied') : t('ssh.keys.copy_failed'));
}

async function remove(key: SshKey) {
  const ok = await confirmAction({ title: t('common.delete'), message: t('ssh.keys.delete_confirm', { name: key.name }), confirmLabel: t('common.delete'), danger: true });
  if (!ok) return;
  try {
    await api.deleteSshKey(key.id);
    if (generated.value?.id === key.id) generated.value = null;
    emit('changed');
  } catch (err) {
    showToast('error', t('ssh.keys.title'), (err as Error).message);
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-4">
    <div class="flex gap-3 rounded-lg border border-info/30 bg-info/10 p-3 text-sm text-fg">
      <Lock class="mt-0.5 size-4 shrink-0 text-info-text" aria-hidden="true" />
      <div class="space-y-1">
        <p>{{ t('ssh.keys.storage_info') }}</p>
        <p class="text-xs text-fg-subtle">{{ props.status?.vault_key_source === 'env' ? t('ssh.keys.vault_env') : t('ssh.keys.vault_file') }}</p>
      </div>
    </div>

    <section class="gl-card space-y-4 p-4" :aria-labelledby="`${id}-add`">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 :id="`${id}-add`" class="text-sm font-bold text-fg">{{ t('ssh.keys.add') }}</h2>
        <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('ssh.keys.add')">
          <button
            v-for="opt in [{ v: 'import', icon: Upload, label: t('ssh.keys.import') }, { v: 'generate', icon: Sparkles, label: t('ssh.keys.generate') }] as const"
            :key="opt.v"
            type="button"
            class="inline-flex h-7 items-center gap-1.5 rounded-sm px-3 text-xs transition-colors"
            :class="mode === opt.v ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="mode === opt.v"
            @click="mode = opt.v"
          >
            <component :is="opt.icon" class="size-3.5" aria-hidden="true" />{{ opt.label }}
          </button>
        </div>
      </div>

      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1.5">
          <label :for="`${id}-name`" class="text-xs font-medium text-fg">{{ t('ssh.keys.name') }}</label>
          <Input :id="`${id}-name`" v-model="name" :placeholder="t('ssh.keys.name_hint')" maxlength="100" required />
        </div>

        <template v-if="mode === 'import'">
          <div class="space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <label :for="`${id}-pem`" class="text-xs font-medium text-fg">{{ t('ssh.keys.private_key') }}</label>
              <Button size="sm" @click="fileInput?.click()"><Upload aria-hidden="true" />{{ t('ssh.keys.choose_file') }}</Button>
              <input ref="fileInput" type="file" class="sr-only" tabindex="-1" aria-hidden="true" @change="readFile" />
            </div>
            <Textarea
              :id="`${id}-pem`"
              v-model="privateKey"
              mono
              rows="6"
              spellcheck="false"
              autocomplete="off"
              required
              :placeholder="'-----BEGIN OPENSSH PRIVATE KEY-----\n…\n-----END OPENSSH PRIVATE KEY-----'"
              @input="error = null"
            />
            <p class="text-xs text-fg-subtle">{{ t('ssh.keys.format_hint') }}</p>
          </div>
          <div class="space-y-1.5">
            <label :for="`${id}-pass`" class="text-xs font-medium text-fg">{{ t('ssh.keys.passphrase') }}</label>
            <Input :id="`${id}-pass`" v-model="passphrase" type="password" autocomplete="off" />
            <p class="text-xs text-fg-subtle">{{ t('ssh.keys.passphrase_hint') }}</p>
          </div>
        </template>
        <p v-else class="text-xs text-fg-subtle">{{ t('ssh.keys.generate_hint') }}</p>

        <p v-if="error" class="text-xs text-danger-text" role="alert">{{ error }}</p>
        <div class="flex justify-end">
          <Button type="submit" variant="primary" :loading="busy">
            <component :is="mode === 'import' ? Upload : Sparkles" v-if="!busy" aria-hidden="true" />
            {{ mode === 'import' ? t('ssh.keys.save') : t('ssh.keys.generate_button') }}
          </Button>
        </div>
      </form>

      <div v-if="generated" class="space-y-2 rounded-lg border border-accent/40 bg-accent/[0.07] p-3 text-sm">
        <p class="flex items-center gap-2 font-semibold text-fg"><ShieldCheck class="size-4 text-accent-text" aria-hidden="true" />{{ t('ssh.keys.generated_title', { name: generated.name }) }}</p>
        <p class="text-xs text-fg-muted">{{ t('ssh.keys.generated_hint') }}</p>
        <code class="block rounded-md bg-sunken p-2 font-mono text-xs break-all text-fg">{{ generated.public_key }}</code>
        <Button size="sm" @click="copyPublicKey(generated)"><Copy aria-hidden="true" />{{ t('ssh.keys.copy_public') }}</Button>
      </div>
    </section>

    <section class="gl-card p-4" :aria-labelledby="`${id}-list`">
      <h2 :id="`${id}-list`" class="mb-3 text-sm font-bold text-fg">{{ t('ssh.keys.stored', { count: keys.length }) }}</h2>
      <p v-if="keys.length === 0" class="text-sm text-fg-subtle">{{ t('ssh.keys.empty') }}</p>
      <ul v-else class="divide-y divide-line">
        <li v-for="key in keys" :key="key.id" class="flex items-start gap-3 py-3">
          <span class="grid size-8 shrink-0 place-items-center rounded-md border border-line bg-raised text-fg-subtle" aria-hidden="true"><KeyRound class="size-4" /></span>
          <span class="min-w-0 flex-1 space-y-0.5">
            <span class="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-fg">
              {{ key.name }}<Badge mono>{{ key.key_type }}</Badge><Badge v-if="key.has_passphrase">{{ t('ssh.keys.with_passphrase') }}</Badge>
            </span>
            <span class="block truncate font-mono text-xs text-fg-subtle">{{ key.fingerprint }}</span>
            <span class="block text-xs text-fg-subtle">{{ t('ssh.keys.last_used', { date: when(key.last_used_at) }) }}</span>
          </span>
          <Button size="icon-sm" variant="ghost" :title="t('ssh.keys.copy_public')" :aria-label="t('ssh.keys.copy_public')" @click="copyPublicKey(key)"><Copy aria-hidden="true" /></Button>
          <Button size="icon-sm" variant="danger-ghost" :title="t('common.delete')" :aria-label="t('common.delete')" @click="remove(key)"><Trash2 aria-hidden="true" /></Button>
        </li>
      </ul>
    </section>
  </div>
</template>
