import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({ api: {} }));

import { patchState } from './agent';

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
