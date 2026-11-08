import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type PropType, defineComponent, h } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import AgentDetail from './AgentDetail.vue';
import {
  type SshFormState,
  buildCachedCreds,
  buildPatchPayload,
  resolveDefaultSshConfig,
  sshCredCache,
} from './agentDetailModel';
import { api } from '@/api/client';
import type { SshKey, SshProfile } from '@/types';
import type { AgentRow } from './agentRow';

vi.mock('@/api/client', () => ({
  api: {
    getAgentMetrics: vi.fn(async () => ({ snapshots: [], available_ranges: ['6h', '24h', '7d'], retention_days: 30 })),
    getSshKeys: vi.fn(async () => []),
    getSshProfiles: vi.fn(async () => []),
    queryAgentPatches: vi.fn(async () => ({ packages: [], major_upgrade_available: null, patch_manager: 'apt' })),
    prepareAgentPatch: vi.fn(async () => ({ patch_token: 'test-token' })),
  },
}));

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

vi.mock('@/composables/useConfirm', () => ({
  confirmAction: vi.fn(async () => true),
}));

const TabsStub = defineComponent({
  props: { tabs: { type: Array as PropType<{ value: string }[]>, required: true } },
  setup: (props, { slots }) => () => h('div', props.tabs.map((tab) => h('section', { 'data-tab': tab.value }, slots[tab.value]?.()))),
});

const sampleForm = (over: Partial<SshFormState> = {}): SshFormState => ({
  sshUser: 'admin',
  sshPassword: 'secret-password',
  sudoPassword: 'sudo-secret',
  sshKey: 'ssh-rsa AAAAB3NzaC1yc2E...',
  keyId: 42,
  keyPassphrase: 'passphrase123',
  authType: 'password',
  sshPort: 2222,
  ...over,
});

describe('agentDetailModel', () => {
  describe('buildPatchPayload', () => {
    it('builds password auth payload with login password and strips key-specific fields', () => {
      const payload = buildPatchPayload(sampleForm({ authType: 'password' }));
      expect(payload).toEqual({
        ssh_user: 'admin',
        ssh_port: 2222,
        ssh_password: 'secret-password',
        sudo_password: undefined,
        ssh_key: undefined,
        key_id: undefined,
        key_passphrase: undefined,
      });
    });

    it('maps empty password string to undefined', () => {
      const payload = buildPatchPayload(sampleForm({ authType: 'password', sshPassword: '' }));
      expect(payload.ssh_password).toBeUndefined();
    });

    it('builds raw private key auth payload and excludes login password', () => {
      const payload = buildPatchPayload(sampleForm({ authType: 'key' }));
      expect(payload).toEqual({
        ssh_user: 'admin',
        ssh_port: 2222,
        ssh_password: undefined,
        sudo_password: 'sudo-secret',
        ssh_key: 'ssh-rsa AAAAB3NzaC1yc2E...',
        key_id: undefined,
        key_passphrase: undefined,
      });
    });

    it('builds stored key auth payload and handles optional passphrase', () => {
      const payload = buildPatchPayload(sampleForm({ authType: 'stored_key' }));
      expect(payload).toEqual({
        ssh_user: 'admin',
        ssh_port: 2222,
        ssh_password: undefined,
        sudo_password: 'sudo-secret',
        ssh_key: undefined,
        key_id: 42,
        key_passphrase: 'passphrase123',
      });

      const withoutPassphrase = buildPatchPayload(sampleForm({ authType: 'stored_key', keyPassphrase: '' }));
      expect(withoutPassphrase.key_passphrase).toBeUndefined();
    });
  });

  describe('buildCachedCreds', () => {
    it('preserves only password secrets when authType is password', () => {
      const cached = buildCachedCreds(sampleForm({ authType: 'password' }));
      expect(cached).toEqual({
        ssh_user: 'admin',
        sudo_password: 'sudo-secret',
        ssh_port: 2222,
        auth_type: 'password',
        ssh_password: 'secret-password',
        ssh_key: '',
        key_id: null,
        key_passphrase: '',
      });
    });

    it('preserves raw key secrets when authType is key', () => {
      const cached = buildCachedCreds(sampleForm({ authType: 'key' }));
      expect(cached).toEqual({
        ssh_user: 'admin',
        sudo_password: 'sudo-secret',
        ssh_port: 2222,
        auth_type: 'key',
        ssh_password: '',
        ssh_key: 'ssh-rsa AAAAB3NzaC1yc2E...',
        key_id: null,
        key_passphrase: '',
      });
    });

    it('preserves key id and passphrase when authType is stored_key', () => {
      const cached = buildCachedCreds(sampleForm({ authType: 'stored_key' }));
      expect(cached).toEqual({
        ssh_user: 'admin',
        sudo_password: 'sudo-secret',
        ssh_port: 2222,
        auth_type: 'stored_key',
        ssh_password: '',
        ssh_key: '',
        key_id: 42,
        key_passphrase: 'passphrase123',
      });
    });
  });

  describe('resolveDefaultSshConfig', () => {
    const keys = [{ id: 10, name: 'Default Key', key_type: 'ed25519', fingerprint: 'SHA256:abc' }] as SshKey[];

    it('matches profile by device_id when auth_method is key with key_id', () => {
      const profiles = [
        { device_id: 5, host: '192.168.1.50', auth_method: 'key', key_id: 99, username: 'ubuntu', port: 2202 },
      ] as SshProfile[];

      const config = resolveDefaultSshConfig(profiles, 5, '10.0.0.1', keys);
      expect(config).toEqual({
        sshUser: 'ubuntu',
        sshPort: 2202,
        authType: 'stored_key',
        keyId: 99,
      });
    });

    it('matches profile by host IP when device_id differs', () => {
      const profiles = [
        { device_id: 999, host: '10.0.0.5', auth_method: 'key', key_id: 88, username: 'pi', port: 22 },
      ] as SshProfile[];

      const config = resolveDefaultSshConfig(profiles, 5, '10.0.0.5', keys);
      expect(config).toEqual({
        sshUser: 'pi',
        sshPort: 22,
        authType: 'stored_key',
        keyId: 88,
      });
    });

    it('falls back to the first stored key if profile auth_method is not key', () => {
      const profiles = [
        { device_id: 5, host: '10.0.0.5', auth_method: 'password', username: 'root' },
      ] as SshProfile[];

      const config = resolveDefaultSshConfig(profiles, 5, '10.0.0.5', keys);
      expect(config).toEqual({
        authType: 'stored_key',
        keyId: 10,
      });
    });

    it('falls back to first stored key when no profile matches', () => {
      const config = resolveDefaultSshConfig([], 5, '10.0.0.5', keys);
      expect(config).toEqual({
        authType: 'stored_key',
        keyId: 10,
      });
    });

    it('returns null when no profile matches and no keys are stored', () => {
      const config = resolveDefaultSshConfig([], 5, '10.0.0.5', []);
      expect(config).toBeNull();
    });
  });
});

describe('AgentDetail component', () => {
  beforeEach(() => {
    sshCredCache.clear();
    vi.clearAllMocks();
  });

  const mockAgent: AgentRow = {
    id: 1,
    device_id: 101,
    hostname: 'srv-app',
    ip: '192.168.1.15',
    agent_version: '1.2.0',
    status: 'online',
    last_seen: '2026-11-08T12:00:00Z',
    cpu_percent: 15,
    ram_percent: 45,
    disk_percent: 60,
    temperature: 42,
    patch_manager: 'apt',
    patch_available: 3,
    patch_security: 1,
    reboot_required: false,
    major_upgrade_available: null,
  };

  it('renders telemetry and requests metrics on mount', async () => {
    const wrapper = mount(AgentDetail, {
      props: { agent: mockAgent },
      global: { stubs: { Tabs: TabsStub } },
    });
    await flushPromises();

    expect(api.getAgentMetrics).toHaveBeenCalledWith(101, undefined, '24h');
    expect(wrapper.text()).toContain('24h');
  });

  it('prefills SSH credentials from cache when present', async () => {
    sshCredCache.set(101, {
      ssh_user: 'cached-user',
      ssh_password: '',
      sudo_password: '',
      ssh_key: 'cached-key',
      key_id: null,
      key_passphrase: '',
      auth_type: 'key',
      ssh_port: 2200,
    });

    const wrapper = mount(AgentDetail, {
      props: { agent: mockAgent },
      global: { stubs: { Tabs: TabsStub } },
    });
    await flushPromises();

    // With cached creds, showForm is false and configured credentials summary is shown in patching section
    const patchingSection = wrapper.find('section[data-tab="patching"]');
    expect(patchingSection.exists()).toBe(true);
    expect(patchingSection.text()).toContain('cached-user');
    expect(patchingSection.text()).toContain('2200');
  });
});
