<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import { Plug, Server } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Device, SshAuthMethod, SshKey, SshProfile, SshProfileInput, SshSessionRequest } from '@/types';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import { deviceLabel } from '@/lib/networks';
import type { ConnectInitial } from './sshModel';
import { t } from '@/i18n';

/**
 * Connect once to a device, any host, or a saved 'ask' connection (password prompt only),
 * optionally saving the connection.
 */
const props = defineProps<{ device: Device | null; keys: SshKey[]; initial?: ConnectInitial; askProfile?: SshProfile | null }>();
const emit = defineEmits<{ close: []; connect: [request: SshSessionRequest, label: string]; profileSaved: [] }>();
const id = useId();
const formId = `${id}-form`;

const host = ref(props.initial?.host ?? '');
const port = ref(props.initial?.port ?? 22);
const username = ref(props.initial?.username ?? 'root');
const auth = ref<'key' | 'password'>(props.initial?.auth ?? (props.keys.length > 0 ? 'key' : 'password'));
const keyId = ref<number | null>(props.initial?.keyId ?? (props.keys.length === 1 ? props.keys[0].id : null));
const password = ref('');
const save = ref(false);
const storePassword = ref(false);
const name = ref(props.device ? deviceLabel(props.device) : '');
const busy = ref(false);
const error = ref<string | null>(null);

const targetLabel = computed(() => (props.device ? deviceLabel(props.device) : host.value.trim()));
const keyOptions = computed(() => [{ value: null, label: t('ssh.dialog.choose_key') }, ...props.keys.map((k) => ({ value: k.id as number | null, label: `${k.name} (${k.key_type})` }))]);
const title = computed(() => {
  if (props.askProfile) return t('ssh.dialog.password_for', { name: props.askProfile.name });
  return props.device ? t('ssh.dialog.connect_to', { name: deviceLabel(props.device) }) : t('ssh.dialog.connect_title');
});

async function submit() {
  error.value = null;
  if (props.askProfile) {
    emit('connect', { profile_id: props.askProfile.id, password: password.value }, props.askProfile.name);
    return;
  }
  if (auth.value === 'key' && !keyId.value) {
    error.value = t('ssh.dialog.choose_key');
    return;
  }
  const credentials = auth.value === 'key' ? { key_id: keyId.value! } : { password: password.value };
  if (!save.value) {
    emit(
      'connect',
      { device_id: props.device?.id, host: props.device ? undefined : host.value.trim(), port: port.value, username: username.value.trim(), ...credentials },
      `${username.value.trim()}@${targetLabel.value}`,
    );
    return;
  }
  const authMethod: SshAuthMethod = auth.value === 'key' ? 'key' : storePassword.value ? 'password' : 'ask';
  const input: SshProfileInput = {
    name: name.value.trim() || targetLabel.value,
    device_id: props.device?.id ?? null,
    host: props.device ? null : host.value.trim(),
    port: port.value,
    username: username.value.trim(),
    auth_method: authMethod,
    key_id: auth.value === 'key' ? keyId.value : null,
    password: authMethod === 'password' ? password.value : undefined,
  };
  busy.value = true;
  try {
    const profile = await api.createSshProfile(input);
    emit('profileSaved');
    emit('connect', { profile_id: profile.id, password: authMethod === 'ask' ? password.value : undefined }, profile.name);
  } catch (err) {
    error.value = (err as Error).message;
    busy.value = false;
  }
}
</script>

<template>
  <Dialog :open="true" :title="title" size="md" @update:open="(v) => !v && emit('close')">
    <form :id="formId" class="space-y-4" @submit.prevent="submit">
      <p v-if="askProfile" class="flex items-center gap-2 font-mono text-xs text-fg-muted">
        <Server class="size-3.5" aria-hidden="true" />{{ askProfile.username }}@{{ askProfile.target_host }}:{{ askProfile.port }}
      </p>
      <template v-else>
        <p v-if="device" class="flex items-center gap-2 font-mono text-xs text-fg-muted"><Server class="size-3.5" aria-hidden="true" />{{ device.ip }}</p>
        <div v-else class="space-y-1.5">
          <label :for="`${id}-host`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.host') }}</label>
          <Input :id="`${id}-host`" v-model="host" placeholder="192.168.1.10" required autofocus />
        </div>

        <div class="grid grid-cols-[1fr_7rem] gap-3">
          <div class="space-y-1.5">
            <label :for="`${id}-user`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.username') }}</label>
            <Input :id="`${id}-user`" v-model="username" autocomplete="off" required :autofocus="!!device" />
          </div>
          <div class="space-y-1.5">
            <label :for="`${id}-port`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.port') }}</label>
            <Input :id="`${id}-port`" :model-value="port" type="number" min="1" max="65535" required mono @update:model-value="(v) => (port = Number(v) || 22)" />
          </div>
        </div>

        <div class="space-y-1.5">
          <span class="text-xs font-medium text-fg">{{ t('ssh.dialog.auth') }}</span>
          <div class="flex w-fit rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('ssh.dialog.auth')">
            <button
              v-for="opt in (['key', 'password'] as const)"
              :key="opt"
              type="button"
              class="h-7 rounded-sm px-3 text-xs transition-colors"
              :class="auth === opt ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="auth === opt"
              @click="auth = opt"
            >
              {{ t(`ssh.auth.${opt}`) }}
            </button>
          </div>
        </div>

        <div v-if="auth === 'key'" class="space-y-1.5">
          <label :for="`${id}-key`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.key') }}</label>
          <p v-if="keys.length === 0" class="text-xs text-fg-subtle">{{ t('ssh.dialog.no_keys') }}</p>
          <Select v-else :id="`${id}-key`" v-model="keyId" :options="keyOptions" required />
        </div>
      </template>

      <div v-if="askProfile || auth === 'password'" class="space-y-1.5">
        <label :for="`${id}-pw`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.password') }}</label>
        <Input :id="`${id}-pw`" v-model="password" type="password" autocomplete="off" required :autofocus="!!askProfile" />
      </div>

      <template v-if="!askProfile">
        <label class="flex items-center gap-2 text-sm text-fg">
          <input v-model="save" type="checkbox" class="size-4 accent-[var(--gl-accent)]" />
          {{ t('ssh.dialog.save_profile') }}
        </label>
        <div v-if="save" class="space-y-3 border-l-2 border-line pl-3">
          <div class="space-y-1.5">
            <label :for="`${id}-name`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.profile_name') }}</label>
            <Input :id="`${id}-name`" v-model="name" :placeholder="targetLabel" />
          </div>
          <label v-if="auth === 'password'" class="flex items-center gap-2 text-sm text-fg">
            <input v-model="storePassword" type="checkbox" class="size-4 accent-[var(--gl-accent)]" />
            {{ t('ssh.dialog.store_password') }}
          </label>
        </div>
      </template>

      <p v-if="error" class="text-xs text-danger-text" role="alert">{{ error }}</p>
    </form>

    <template #footer>
      <Button @click="emit('close')">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" :form="formId" :loading="busy"><Plug v-if="!busy" aria-hidden="true" />{{ t('ssh.dialog.connect') }}</Button>
    </template>
  </Dialog>
</template>
