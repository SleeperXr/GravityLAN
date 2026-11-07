import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({ api: {} }));

import { patchState, updateCenterLogin } from './agent';

describe('updateCenterLogin', () => {
  it('sends the typed password as sudo password with a saved key connection', () => {
    expect(updateCenterLogin({ id: 4 }, 'root', 'pw')).toEqual({ profile_id: 4, sudo_password: 'pw' });
    expect(updateCenterLogin({ id: 4 }, 'root', '')).toEqual({ profile_id: 4 });
  });

  it('logs in with the typed user and password without one', () => {
    expect(updateCenterLogin(undefined, 'sleeper', 'pw')).toEqual({ ssh_user: 'sleeper', ssh_password: 'pw', ssh_port: 22 });
  });
});

describe('patchState', () => {
  it('reads pending, security and reboot from the latest agent report', () => {
    const device = { agent_info: { agent_version: '0.3.9', latest_version: '0.3.9', latest_metrics: { patch_available: 7, patch_security: 2, reboot_required: true } } };
    expect(patchState(device)).toEqual({ available: 7, security: 2, reboot: true });
  });

  it('is null without an agent or before its first report, and zero for missing counts', () => {
    expect(patchState({ agent_info: undefined })).toBeNull();
    expect(patchState({ agent_info: { agent_version: '0.3.9', latest_version: '0.3.9', latest_metrics: null } })).toBeNull();
    expect(patchState({ agent_info: { agent_version: '0.3.9', latest_version: '0.3.9', latest_metrics: {} } })).toEqual({ available: 0, security: 0, reboot: false });
  });
});
