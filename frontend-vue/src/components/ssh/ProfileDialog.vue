<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import { api } from '@/api/client';
import type { Device, SshAuthMethod, SshKey, SshProfile, SshProfileInput } from '@/types';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/** Create or edit a saved connection (target device or host, user, port, login method). */
const props = defineProps<{ profile: SshProfile | null; initial?: Partial<SshProfileInput>; devices: Device[]; keys: SshKey[] }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const id = useId();
const formId = `${id}-form`;

const start = props.profile ?? props.initial;
const name = ref(start?.name ?? '');
const targetMode = ref<'device' | 'host'>(start && !start.device_id && start.host ? 'host' : 'device');
const deviceId = ref<number | null>(start?.device_id ?? null);
const host = ref(start?.host ?? '');
const port = ref(start?.port ?? 22);
const username = ref(start?.username ?? 'root');
const authMethod = ref<SshAuthMethod>(start?.auth_method ?? (props.keys.length > 0 ? 'key' : 'ask'));
const keyId = ref<number | null>(start?.key_id ?? (props.keys.length === 1 ? props.keys[0].id : null));
const password = ref('');
const busy = ref(false);
const error = ref<string | null>(null);
const hasStoredPassword = computed(() => !!props.profile?.has_password);

const deviceOptions = computed(() => [
  { value: null, label: t('ssh.dialog.choose_device') },
  ...[...props.devices].sort((a, b) => deviceLabel(a).localeCompare(deviceLabel(b))).map((d) => ({ value: d.id as number | null, label: `${deviceLabel(d)} (${d.ip})` })),
]);
const keyOptions = computed(() => [{ value: null, label: t('ssh.dialog.choose_key') }, ...props.keys.map((k) => ({ value: k.id as number | null, label: `${k.name} (${k.key_type})` }))]);

async function submit() {
  error.value = null;
  const selected = props.devices.find((d) => d.id === deviceId.value);
  const payload: SshProfileInput = {
    name: name.value.trim() || (targetMode.value === 'device' && selected ? deviceLabel(selected) : host.value.trim()),
    device_id: targetMode.value === 'device' ? deviceId.value : null,
    host: targetMode.value === 'host' ? host.value.trim() : null,
    port: port.value,
    username: username.value.trim(),
    auth_method: authMethod.value,
    key_id: authMethod.value === 'key' ? keyId.value : null,
  };
  if (authMethod.value === 'password' && password.value) payload.password = password.value;
  busy.value = true;
  try {
    if (props.profile) await api.updateSshProfile(props.profile.id, payload);
    else await api.createSshProfile(payload);
    emit('saved');
  } catch (err) {
    error.value = (err as Error).message;
    busy.value = false;
  }
}
</script>

<template>
  <Dialog :open="true" :title="profile ? t('ssh.dialog.edit_profile') : t('ssh.dialog.new_profile')" size="lg" @update:open="(v) => !v && emit('close')">
    <form :id="formId" class="space-y-4" @submit.prevent="submit">
      <div class="space-y-1.5">
        <label :for="`${id}-name`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.profile_name') }}</label>
        <Input :id="`${id}-name`" v-model="name" :placeholder="t('ssh.dialog.profile_name_hint')" autofocus />
      </div>

      <div class="space-y-1.5">
        <span class="text-xs font-medium text-fg">{{ t('ssh.dialog.target') }}</span>
        <div class="flex w-fit rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('ssh.dialog.target')">
          <button
            v-for="opt in (['device', 'host'] as const)"
            :key="opt"
            type="button"
            class="h-7 rounded-sm px-3 text-xs transition-colors"
            :class="targetMode === opt ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="targetMode === opt"
            @click="targetMode = opt"
          >
            {{ t(`ssh.dialog.target_${opt}`) }}
          </button>
        </div>
      </div>

      <div v-if="targetMode === 'host'" class="space-y-1.5">
        <label :for="`${id}-host`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.host') }}</label>
        <Input :id="`${id}-host`" v-model="host" placeholder="server.lan" required />
      </div>
      <div v-else class="space-y-1.5">
        <label :for="`${id}-device`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.device') }}</label>
        <Select :id="`${id}-device`" v-model="deviceId" :options="deviceOptions" required />
      </div>

      <div class="grid grid-cols-[1fr_7rem] gap-3">
        <div class="space-y-1.5">
          <label :for="`${id}-user`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.username') }}</label>
          <Input :id="`${id}-user`" v-model="username" autocomplete="off" required />
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
            v-for="opt in (['key', 'password', 'ask'] as const)"
            :key="opt"
            type="button"
            class="h-7 rounded-sm px-3 text-xs transition-colors"
            :class="authMethod === opt ? 'bg-raised text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="authMethod === opt"
            @click="authMethod = opt"
          >
            {{ t(`ssh.auth.${opt}`) }}
          </button>
        </div>
      </div>

      <div v-if="authMethod === 'key'" class="space-y-1.5">
        <label :for="`${id}-key`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.key') }}</label>
        <p v-if="keys.length === 0" class="text-xs text-fg-subtle">{{ t('ssh.dialog.no_keys') }}</p>
        <Select v-else :id="`${id}-key`" v-model="keyId" :options="keyOptions" required />
      </div>
      <div v-else-if="authMethod === 'password'" class="space-y-1.5">
        <label :for="`${id}-pw`" class="text-xs font-medium text-fg">{{ t('ssh.dialog.password') }}</label>
        <Input :id="`${id}-pw`" v-model="password" type="password" autocomplete="off" :placeholder="hasStoredPassword ? t('ssh.dialog.password_unchanged') : ''" :required="!hasStoredPassword" />
        <p class="text-xs text-fg-subtle">{{ t('ssh.dialog.password_stored_hint') }}</p>
      </div>
      <p v-else class="text-xs text-fg-subtle">{{ t('ssh.dialog.ask_hint') }}</p>

      <p v-if="error" class="text-xs text-danger-text" role="alert">{{ error }}</p>
    </form>

    <template #footer>
      <Button @click="emit('close')">{{ t('common.cancel') }}</Button>
      <Button variant="primary" type="submit" :form="formId" :loading="busy">{{ t('common.save') }}</Button>
    </template>
  </Dialog>
</template>
