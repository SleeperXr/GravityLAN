import type { SshKey, SshProfile } from '@/types';

export type AuthType = 'password' | 'key' | 'stored_key';

export interface SshCreds {
  ssh_user: string;
  ssh_password: string;
  sudo_password?: string;
  ssh_key: string;
  key_id: number | null;
  key_passphrase: string;
  auth_type: AuthType;
  ssh_port: number;
}

export interface SshFormState {
  sshUser: string;
  sshPassword: string;
  sudoPassword?: string;
  sshKey: string;
  keyId: number | null;
  keyPassphrase: string;
  authType: AuthType;
  sshPort: number;
}

export interface AgentPatchPayload {
  ssh_user: string;
  ssh_password?: string;
  sudo_password?: string;
  ssh_key?: string;
  key_id?: number;
  key_passphrase?: string;
  ssh_port: number;
}

export interface DefaultSshConfig {
  sshUser?: string;
  sshPort?: number;
  authType: AuthType;
  keyId: number | null;
}

/** SSH secrets are kept in memory only (never in web storage), so they are gone on reload */
export const sshCredCache = new Map<number, SshCreds>();

const PAYLOAD_BUILDERS: Record<AuthType, (form: SshFormState) => Partial<AgentPatchPayload>> = {
  password: (f) => ({
    ssh_password: f.sshPassword || undefined,
  }),
  key: (f) => ({
    // Only with a key: a sudo password kept from key mode must not replace the login password
    sudo_password: f.sudoPassword || undefined,
    ssh_key: f.sshKey || undefined,
  }),
  stored_key: (f) => ({
    sudo_password: f.sudoPassword || undefined,
    key_id: f.keyId ?? undefined,
    key_passphrase: f.keyPassphrase || undefined,
  }),
};

export function buildPatchPayload(form: SshFormState): AgentPatchPayload {
  const specific = PAYLOAD_BUILDERS[form.authType]?.(form);
  return {
    ssh_user: form.sshUser,
    ssh_port: form.sshPort,
    ...specific,
  };
}

const CACHE_BUILDERS: Record<AuthType, (form: SshFormState) => Partial<SshCreds>> = {
  password: (f) => ({
    ssh_password: f.sshPassword,
    ssh_key: '',
    key_id: null,
    key_passphrase: '',
  }),
  key: (f) => ({
    ssh_password: '',
    ssh_key: f.sshKey,
    key_id: null,
    key_passphrase: '',
  }),
  stored_key: (f) => ({
    ssh_password: '',
    ssh_key: '',
    key_id: f.keyId,
    key_passphrase: f.keyPassphrase,
  }),
};

export function buildCachedCreds(form: SshFormState): SshCreds {
  const specific = CACHE_BUILDERS[form.authType]?.(form);
  return {
    ssh_user: form.sshUser,
    sudo_password: form.sudoPassword,
    ssh_port: form.sshPort,
    auth_type: form.authType,
    ssh_password: '',
    ssh_key: '',
    key_id: null,
    key_passphrase: '',
    ...specific,
  };
}

export function resolveDefaultSshConfig(
  profiles: SshProfile[],
  deviceId: number,
  agentIp: string,
  storedKeys: SshKey[],
): DefaultSshConfig | null {
  const matched = profiles.find((p) => p.device_id === deviceId || p.host === agentIp);
  if (matched?.auth_method === 'key' && matched.key_id) {
    return {
      sshUser: matched.username || 'root',
      sshPort: matched.port || 22,
      authType: 'stored_key',
      keyId: matched.key_id,
    };
  }
  if (storedKeys.length > 0) {
    return {
      authType: 'stored_key',
      keyId: storedKeys[0].id,
    };
  }
  return null;
}
