import { computed, reactive, ref, watch, type Ref } from 'vue';
import { api } from '@/api/client';
import type { AgentSshLogin, Device, SshProfile } from '@/types';
import { agentKeyProfiles } from '@/lib/agent';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { formatDateTime, t } from '@/i18n';

export interface AgentStatus {
  is_installed: boolean;
  is_active: boolean;
  agent_version?: string;
  latest_version?: string;
  last_seen?: string;
}

export interface AgentConfigForm {
  interval: number;
  disk_paths: string[];
  enable_temp: boolean;
  enable_patch_check?: boolean;
  enable_scanner_relay?: boolean;
}

export interface SshForm {
  ssh_user: string;
  ssh_password: string;
  ssh_key: string;
  ssh_port: number;
  /** Saved key connection of the device to log in with instead (null: user and password) */
  profile_id: number | null;
  /** Only for sudo with a saved connection; never stored */
  sudo_password: string;
}

/** The request body: the saved connection, or the typed-in credentials. */
export function sshLogin(form: SshForm): AgentSshLogin {
  if (form.profile_id !== null) {
    return form.sudo_password ? { profile_id: form.profile_id, sudo_password: form.sudo_password } : { profile_id: form.profile_id };
  }
  const { ssh_user, ssh_password, ssh_key, ssh_port } = form;
  return { ssh_user, ssh_password, ssh_key, ssh_port };
}

/**
 * Agent tab state (port of React editor/hooks.ts useAgentPanel). Lives in the editor so the
 * SSH form, the deploy log and the config draft survive switching tabs.
 */
export function useAgentPanel(device: Ref<Device>, active: Ref<boolean>) {
  const { showToast } = useToast();
  const { confirm } = useConfirm();
  const status = ref<AgentStatus | null>(null);
  const config = ref<AgentConfigForm | null>(null);
  const deploying = ref(false);
  const deployLog = ref<string[]>([]);
  const profiles = ref<SshProfile[]>([]);
  const form = reactive<SshForm>({ ssh_user: 'root', ssh_password: '', ssh_key: '', ssh_port: 22, profile_id: null, sudo_password: '' });
  let preselected = false;

  const keyProfiles = computed(() => agentKeyProfiles(profiles.value, device.value));

  async function loadStatus() {
    try {
      status.value = await api.getAgentStatus(device.value.id);
      if (status.value.is_installed) {
        try {
          config.value = await api.getAgentConfig(device.value.id);
        } catch {
          // no config yet
        }
      }
    } catch {
      // agent not available
    }
  }

  watch(
    active,
    (on) => {
      if (!on) return;
      void loadStatus();
      api
        .getSshProfiles()
        .then((list) => (profiles.value = list))
        .catch(() => (profiles.value = []));
    },
    { immediate: true },
  );

  // A saved key connection is offered first once it is known; the user can still switch to a password
  watch(keyProfiles, (list) => {
    if (preselected || list.length === 0) return;
    preselected = true;
    if (!form.ssh_password) form.profile_id = list[0].id;
  });

  const log = (line: string) => deployLog.value.push(`[${formatDateTime(new Date(), { timeStyle: 'medium' })}] ${line}`);

  async function run(kind: 'deploy' | 'uninstall') {
    if (kind === 'uninstall') {
      const ok = await confirm({ title: t('agent.uninstall'), message: t('agent.uninstall_confirm_long'), danger: true, confirmLabel: t('agent.uninstall') });
      if (!ok) return;
    }
    const keys =
      kind === 'deploy'
        ? { start: 'agent.deploying', detail: 'agent.connecting', ok: 'agent.deployed_title', failed: 'agent.deploy_failed_title' }
        : { start: 'agent.uninstalling', detail: 'agent.removing', ok: 'agent.uninstalled_title', failed: 'agent.uninstall_failed_title' };
    deploying.value = true;
    showToast('info', t(keys.start), t(keys.detail, { ip: device.value.ip }));
    try {
      const login = sshLogin(form);
      const result = kind === 'deploy' ? await api.deployAgent(device.value.id, login) : await api.uninstallAgent(device.value.id, login);
      const message = result.error_code === 'host_key_changed' ? t('agent.host_key_changed', { ip: device.value.ip }) : result.message;
      log(message);
      if (result.status === 'success') {
        showToast('success', t(keys.ok), message);
        form.ssh_password = '';
        form.ssh_key = '';
        form.sudo_password = '';
        await loadStatus();
      } else {
        showToast('error', t(keys.failed), message);
      }
    } catch (err) {
      const msg = (err as Error).message || t('agent.connection_failed');
      log(`${t('common.error').toUpperCase()}: ${msg}`);
      showToast('error', t('common.error'), msg);
    } finally {
      deploying.value = false;
    }
  }

  async function saveConfig() {
    if (!config.value) return;
    try {
      await api.updateAgentConfig(device.value.id, config.value);
      showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
    } catch (err) {
      showToast('error', t('common.error'), (err as Error).message);
    }
  }

  return {
    status,
    config,
    deploying,
    deployLog,
    form,
    keyProfiles,
    deploy: () => run('deploy'),
    uninstall: () => run('uninstall'),
    saveConfig,
  };
}

export type AgentPanel = ReturnType<typeof useAgentPanel>;
