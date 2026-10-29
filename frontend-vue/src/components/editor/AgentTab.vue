<script setup lang="ts">
import { computed, ref } from 'vue';
import { ChevronDown, HardDrive, KeyRound, Radio, RefreshCw, Save, Settings, Terminal, Thermometer, Trash2, Upload, X } from 'lucide-vue-next';
import type { AgentPanel } from '@/composables/useAgentPanel';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import Switch from '@/components/ui/Switch.vue';
import Badge from '@/components/ui/Badge.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import DeviceMetrics from '@/components/dashboard/DeviceMetrics.vue';
import ManualInstallCommand from '@/components/agents/ManualInstallCommand.vue';
import { isAgentOutdated, profileTarget } from '@/lib/agent';
import { t } from '@/i18n';

/** Agent tab: status and live metrics, SSH install/update/uninstall, manual commands, config. */
const props = defineProps<{ deviceId: number; panel: AgentPanel }>();
const showManual = ref(false);
const newDiskPath = ref('');

const status = computed(() => props.panel.status.value);
const config = computed(() => props.panel.config.value);
const form = props.panel.form;
const useSaved = computed(() => form.profile_id !== null);
const noCredentials = computed(() => !useSaved.value && !form.ssh_password && !form.ssh_key);
const profileOptions = computed(() =>
  props.panel.keyProfiles.value.map((p) => ({ value: p.id, label: `${p.name} – ${profileTarget(p)}${p.key_name ? ` (${p.key_name})` : ''}` })),
);

function addDiskPath() {
  const path = newDiskPath.value.trim();
  if (!config.value || !path || config.value.disk_paths.includes(path)) return;
  config.value.disk_paths = [...config.value.disk_paths, path];
  newDiskPath.value = '';
}
</script>

<template>
  <div class="grid gap-5 lg:grid-cols-2">
    <div class="space-y-4">
      <div class="rounded-md border p-4" :class="status?.is_active ? 'border-accent/30 bg-accent/[0.05]' : 'border-line bg-raised'">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="flex items-center gap-2.5 text-sm font-semibold text-fg">
            <StatusDot :state="status?.is_active ? 'online' : status?.is_installed ? 'warn' : 'unknown'" :pulse="status?.is_active" />
            {{ status?.is_active ? t('agent.status_active') : status?.is_installed ? `${t('agent.status_active')} (${t('common.offline')})` : t('agent.status_inactive') }}
          </span>
          <span v-if="status?.agent_version" class="flex items-center gap-2">
            <Badge v-if="isAgentOutdated(status.agent_version, status.latest_version)" tone="warn">
              <RefreshCw aria-hidden="true" />{{ t('common.update_available', { version: status.latest_version }) }}
            </Badge>
            <span class="font-mono text-xs text-fg-subtle">v{{ status.agent_version }}</span>
          </span>
        </div>
        <p v-if="status?.last_seen" class="mt-2 text-xs text-fg-subtle">{{ t('agent.last_report') }}: <RelativeTime :date="status.last_seen" /></p>
      </div>
      <DeviceMetrics v-if="status?.is_active" :device-id="deviceId" :compact="false" />
    </div>

    <div class="space-y-4">
      <section class="space-y-3 rounded-md border border-line p-4" aria-labelledby="agent-ssh-title">
        <h3 id="agent-ssh-title" class="flex items-center gap-2 text-sm font-semibold text-fg"><Terminal class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('agent.ssh_management') }}</h3>
        <div v-if="panel.keyProfiles.value.length > 0" class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('agent.login_method')">
          <button
            type="button"
            class="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[5px] text-xs font-medium"
            :class="useSaved ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="useSaved"
            @click="form.profile_id = form.profile_id ?? panel.keyProfiles.value[0].id"
          >
            <KeyRound class="size-3.5" aria-hidden="true" />{{ t('agent.login_saved') }}
          </button>
          <button
            type="button"
            class="h-8 flex-1 rounded-[5px] text-xs font-medium"
            :class="!useSaved ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
            :aria-pressed="!useSaved"
            @click="form.profile_id = null; form.sudo_password = ''"
          >
            {{ t('agent.login_password') }}
          </button>
        </div>

        <template v-if="useSaved">
          <Field v-slot="{ id, describedBy }" :label="t('agent.saved_connection')" :hint="t('agent.saved_connection_hint')">
            <Select :id="id" v-model="form.profile_id" :options="profileOptions" :aria-describedby="describedBy" />
          </Field>
          <Field v-slot="{ id, describedBy }" :label="t('agent.sudo_password')" :hint="t('agent.sudo_password_hint')">
            <Input :id="id" v-model="form.sudo_password" type="password" autocomplete="off" :aria-describedby="describedBy" />
          </Field>
        </template>
        <div v-else class="grid gap-3 sm:grid-cols-[1fr_6rem]">
          <Field v-slot="{ id }" :label="t('agent.ssh_user')">
            <Input :id="id" v-model="form.ssh_user" autocomplete="username" />
          </Field>
          <Field v-slot="{ id }" :label="t('agent.ssh_port')">
            <Input :id="id" :model-value="form.ssh_port" type="number" mono @update:model-value="(v) => (form.ssh_port = parseInt(String(v), 10) || 22)" />
          </Field>
          <div class="sm:col-span-2">
            <Field v-slot="{ id }" :label="t('agent.ssh_password')">
              <Input :id="id" v-model="form.ssh_password" type="password" autocomplete="current-password" :placeholder="t('agent.password_placeholder')" />
            </Field>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <Button v-if="!status?.is_installed" variant="primary" size="sm" :loading="panel.deploying.value" :disabled="noCredentials" @click="panel.deploy">
            <Upload v-if="!panel.deploying.value" aria-hidden="true" />{{ t('agent.install_via_ssh') }}
          </Button>
          <template v-else>
            <Button variant="primary" size="sm" :loading="panel.deploying.value" :disabled="noCredentials" @click="panel.deploy">
              <RefreshCw v-if="!panel.deploying.value" aria-hidden="true" />{{ t('agent.update_agent') }}
            </Button>
            <Button variant="danger-ghost" size="sm" :disabled="panel.deploying.value || noCredentials" @click="panel.uninstall">
              <Trash2 aria-hidden="true" />{{ t('agent.uninstall') }}
            </Button>
          </template>
        </div>
      </section>

      <div>
        <button type="button" class="flex items-center gap-1.5 py-1 text-xs font-medium text-fg-muted hover:text-fg" :aria-expanded="showManual" @click="showManual = !showManual">
          <ChevronDown class="size-3.5 transition-transform" :class="!showManual && '-rotate-90'" aria-hidden="true" />{{ t('agent.manual_install_options') }}
        </button>
        <div v-if="showManual" class="mt-2 space-y-3">
          <section class="space-y-2 rounded-md border border-line p-4">
            <h4 class="text-sm font-semibold text-fg">{{ t('agent.manual_install') }}</h4>
            <ManualInstallCommand :device-id="deviceId" />
          </section>
          <section class="space-y-2 rounded-md border border-danger/25 p-4">
            <h4 class="text-sm font-semibold text-fg">{{ t('agent.manual_uninstall') }}</h4>
            <ManualInstallCommand :device-id="deviceId" mode="uninstall" />
          </section>
        </div>
      </div>

      <section v-if="status?.is_installed && config" class="space-y-4 rounded-md border border-line p-4" aria-labelledby="agent-config-title">
        <h3 id="agent-config-title" class="flex items-center gap-2 text-sm font-semibold text-fg"><Settings class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('agent.configuration') }}</h3>
        <Field v-slot="{ id }" :label="t('agent.report_interval')">
          <Input :id="id" :model-value="config.interval" type="number" min="5" mono @update:model-value="(v) => (config!.interval = parseInt(String(v), 10) || 30)" />
        </Field>
        <label class="flex items-center justify-between gap-3">
          <span class="flex items-center gap-2 text-sm text-fg"><Thermometer class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('agent.temp_monitoring') }}</span>
          <Switch v-model="config.enable_temp" :aria-label="t('agent.temp_monitoring')" />
        </label>
        <label class="flex items-start justify-between gap-3">
          <span>
            <span class="flex items-center gap-2 text-sm text-fg"><Radio class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('agent.scanner_relay') }}</span>
            <span class="mt-0.5 block text-xs text-fg-subtle">{{ t('agent.scanner_relay_hint') }}</span>
          </span>
          <Switch :model-value="!!config.enable_scanner_relay" :aria-label="t('agent.scanner_relay')" @update:model-value="(v) => (config!.enable_scanner_relay = v)" />
        </label>
        <div class="space-y-2">
          <p class="flex items-center gap-2 text-xs font-medium text-fg"><HardDrive class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('agent.disk_paths') }}</p>
          <div v-if="config.disk_paths.length" class="flex flex-wrap gap-1.5">
            <span v-for="(path, i) in config.disk_paths" :key="path" class="inline-flex items-center gap-1 rounded-sm border border-line bg-raised py-0.5 pr-0.5 pl-2 font-mono text-xs text-fg">
              {{ path }}
              <button type="button" class="inline-flex size-5 items-center justify-center rounded-sm text-fg-subtle hover:bg-danger/10 hover:text-danger-text" :aria-label="`${t('common.delete')}: ${path}`" @click="config.disk_paths = config.disk_paths.filter((_, idx) => idx !== i)">
                <X class="size-3" aria-hidden="true" />
              </button>
            </span>
          </div>
          <form class="flex gap-2" @submit.prevent="addDiskPath">
            <Input v-model="newDiskPath" mono placeholder="/mnt/data" :aria-label="t('agent.disk_paths')" />
            <Button type="submit" size="icon" :aria-label="t('interfaces.add')">+</Button>
          </form>
        </div>
        <Button variant="primary" class="w-full" @click="panel.saveConfig"><Save aria-hidden="true" />{{ t('agent.save_config') }}</Button>
      </section>

      <section v-if="panel.deployLog.value.length > 0" class="space-y-2">
        <h4 class="flex items-center gap-1.5 text-xs font-medium text-fg-muted"><Terminal class="size-3.5" aria-hidden="true" />{{ t('agent.deployment_logs') }}</h4>
        <pre class="max-h-40 overflow-y-auto rounded-md border border-line bg-[#06080a] p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-[#4ade80]" role="log">{{ panel.deployLog.value.join('\n') }}</pre>
      </section>
    </div>
  </div>
</template>
