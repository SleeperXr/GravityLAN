<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { AlertCircle, CheckCircle2, ChevronDown, KeyRound, RefreshCw, Shield, Terminal } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { AgentSshLogin, Device, SshProfile } from '@/types';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import ManualInstallCommand from '@/components/agents/ManualInstallCommand.vue';
import { agentKeyProfiles, isAgentOutdated } from '@/lib/agent';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

/**
 * Agent update center: one login for all, or the saved key connection of each device,
 * then "update all" deploys one after another (no parallel SSH sessions).
 */
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ devices: Device[] }>();
const emit = defineEmits<{ complete: [] }>();

type RowStatus = 'idle' | 'running' | 'success' | 'failed';

const sshUser = ref('root');
const sshPassword = ref('');
const useSaved = ref(true);
const profiles = ref<SshProfile[]>([]);
const statuses = reactive<Record<number, { status: RowStatus; message?: string }>>({});
const manualOpen = reactive<Record<number, boolean>>({});
const running = ref(false);

const pending = computed(() =>
  props.devices.filter((d) => d.has_agent && isAgentOutdated(d.agent_info?.agent_version, d.agent_info?.latest_version)),
);

watch(open, (isOpen) => {
  if (!isOpen) return;
  api
    .getSshProfiles()
    .then((list) => (profiles.value = list))
    .catch(() => (profiles.value = []));
});

const savedLoginOf = (device: Device) => agentKeyProfiles(profiles.value, device)[0];
const loginFor = (device: Device) => (useSaved.value ? savedLoginOf(device) : undefined);
const hasSavedLogins = computed(() => pending.value.some((d) => savedLoginOf(d)));
const canUpdate = computed(() => !!sshPassword.value || pending.value.some((d) => loginFor(d)));

async function update(device: Device) {
  const saved = loginFor(device);
  if (!saved && (!sshUser.value || !sshPassword.value)) {
    statuses[device.id] = { status: 'failed', message: t('agent.credentials_missing') };
    return;
  }
  statuses[device.id] = { status: 'running' };
  try {
    const login: AgentSshLogin = saved ? { profile_id: saved.id } : { ssh_user: sshUser.value, ssh_password: sshPassword.value, ssh_port: 22 };
    const res = await api.deployAgent(device.id, login);
    statuses[device.id] = { status: res.status === 'success' ? 'success' : 'failed', message: res.message };
  } catch (err) {
    statuses[device.id] = { status: 'failed', message: (err as Error).message || t('agent.connection_error') };
  }
}

async function updateAll() {
  running.value = true;
  for (const device of pending.value) {
    if (statuses[device.id]?.status !== 'success') await update(device);
  }
  running.value = false;
  emit('complete');
}

const statusIcon = { running: RefreshCw, success: CheckCircle2, failed: AlertCircle } as const;
const statusTone: Record<RowStatus, string> = {
  idle: 'text-fg-subtle',
  running: 'text-info-text',
  success: 'text-accent-text',
  failed: 'text-danger-text',
};
function statusText(status: RowStatus) {
  return { idle: t('common.ready'), running: t('agent.installing'), success: t('common.done'), failed: t('common.error') }[status];
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('agent.update_center_title')" size="lg">
    <section class="space-y-3" aria-labelledby="uc-creds">
      <h3 id="uc-creds" class="flex items-center gap-2 text-sm font-semibold text-fg"><Shield class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('agent.global_credentials') }}</h3>
      <label v-if="hasSavedLogins" class="flex items-start gap-2.5 rounded-md border border-line bg-raised p-3">
        <input v-model="useSaved" type="checkbox" class="mt-0.5 size-4 accent-[var(--gl-accent)]" />
        <span>
          <span class="block text-sm text-fg">{{ t('agent.use_saved_connections') }}</span>
          <span class="mt-0.5 block text-xs text-fg-subtle">{{ t('agent.use_saved_connections_hint') }}</span>
        </span>
      </label>
      <div class="grid gap-3 sm:grid-cols-2">
        <Field v-slot="{ id }" :label="t('agent.ssh_user')">
          <Input :id="id" v-model="sshUser" autocomplete="username" :placeholder="t('agent.ssh_user_placeholder')" />
        </Field>
        <Field v-slot="{ id }" :label="t('agent.ssh_password')">
          <Input :id="id" v-model="sshPassword" type="password" autocomplete="current-password" :placeholder="t('agent.password_placeholder')" />
        </Field>
      </div>
    </section>

    <p v-if="pending.length === 0" class="mt-6 rounded-md border border-line bg-raised px-4 py-6 text-center text-sm text-fg-muted">{{ t('agent.all_up_to_date') }}</p>
    <ul v-else class="mt-5 divide-y divide-line rounded-md border border-line">
      <li v-for="device in pending" :key="device.id" class="p-3">
        <div class="flex flex-wrap items-center gap-3">
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-fg">{{ deviceLabel(device) }}</p>
            <p class="font-mono text-xs text-fg-subtle">
              {{ device.ip }} · <span class="text-fg-muted">v{{ device.agent_info?.agent_version }}</span> →
              <span class="text-accent-text">v{{ device.agent_info?.latest_version }}</span>
            </p>
            <p v-if="loginFor(device)" class="mt-0.5 flex items-center gap-1 text-[11px] text-fg-subtle">
              <KeyRound class="size-3" aria-hidden="true" />{{ t('agent.via_saved_connection', { name: loginFor(device)!.name }) }}
            </p>
          </div>
          <span role="status" class="inline-flex items-center gap-1 text-xs font-medium" :class="statusTone[statuses[device.id]?.status ?? 'idle']">
            <component
              :is="statusIcon[(statuses[device.id]?.status ?? 'idle') as keyof typeof statusIcon]"
              v-if="(statuses[device.id]?.status ?? 'idle') !== 'idle'"
              class="size-3.5"
              :class="statuses[device.id]?.status === 'running' && 'animate-spin'"
              aria-hidden="true"
            />
            {{ statusText(statuses[device.id]?.status ?? 'idle') }}
          </span>
          <div class="flex gap-2">
            <Button size="sm" :aria-expanded="!!manualOpen[device.id]" @click="manualOpen[device.id] = !manualOpen[device.id]">
              <Terminal aria-hidden="true" />{{ t('agent.manual_update') }}
              <ChevronDown class="transition-transform" :class="manualOpen[device.id] && 'rotate-180'" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              :variant="statuses[device.id]?.status === 'success' ? 'secondary' : 'primary'"
              :disabled="statuses[device.id]?.status === 'running' || statuses[device.id]?.status === 'success'"
              @click="update(device)"
            >
              {{ statuses[device.id]?.status === 'failed' ? t('common.retry') : t('common.update') }}
            </Button>
          </div>
        </div>
        <p v-if="statuses[device.id]?.status === 'failed' && statuses[device.id]?.message" class="mt-2 rounded-sm bg-danger/10 px-2 py-1 font-mono text-[11px] break-words text-danger-text">
          {{ statuses[device.id]?.message }}
        </p>
        <div v-if="manualOpen[device.id]" class="mt-3"><ManualInstallCommand :device-id="device.id" /></div>
      </li>
    </ul>

    <template #footer>
      <span class="mr-auto self-center text-xs text-fg-subtle">{{ pending.length }} {{ t('agent.updates_available') }}</span>
      <Button variant="ghost" @click="open = false">{{ t('common.close') }}</Button>
      <Button variant="primary" :loading="running" :disabled="pending.length === 0 || !canUpdate" @click="updateAll">
        <RefreshCw v-if="!running" aria-hidden="true" />{{ t('agent.update_remaining') }}
      </Button>
    </template>
  </Dialog>
</template>
