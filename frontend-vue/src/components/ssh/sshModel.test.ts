import { describe, expect, it } from 'vitest';
import type { Device, SshHistoryEntry, SshKey, SshProfile } from '@/types';
import { agentUpdateFor, filterDevices, historyReconnect, hostKeyFile, isLive, profileInitialFrom } from './sshModel';

const device = (over: Partial<Device>): Device => ({ id: 1, ip: '192.168.1.10', hostname: null, display_name: 'nas', is_online: true, is_hidden: false, services: [], ...over }) as Device;

const entry = (over: Partial<SshHistoryEntry> = {}): SshHistoryEntry => ({
  id: 1, label: 'root@nas', device_id: null, device_name: null, host: '10.0.0.5', target_host: '10.0.0.5',
  port: 22, username: 'root', auth_method: 'key', key_id: 7, key_name: 'lab', last_used_at: null, ...over,
});

describe('sshModel', () => {
  it('treats closed and failed sessions as no longer live', () => {
    expect(isLive({ status: 'connected' })).toBe(true);
    expect(isLive({ status: 'hostkey' })).toBe(true);
    expect(isLive({ status: 'closed' })).toBe(false);
    expect(isLive({ status: 'error' })).toBe(false);
  });

  it('reconnects a history entry directly only while its key is still stored', () => {
    const keys = [{ id: 7 }] as SshKey[];
    expect(historyReconnect(entry(), keys)).toEqual({ kind: 'open', request: { device_id: undefined, host: '10.0.0.5', port: 22, username: 'root', key_id: 7 } });
    expect(historyReconnect(entry(), []).kind).toBe('ask');
    expect(historyReconnect(entry({ auth_method: 'password', key_id: null }), keys)).toEqual({
      kind: 'ask', initial: { host: '10.0.0.5', port: 22, username: 'root', auth: 'password' },
    });
  });

  it('prefills a saved connection from an ad-hoc request', () => {
    expect(profileInitialFrom({ device_id: 3, host: 'x', username: 'pi', key_id: 2 }, 'Pi')).toEqual({
      name: 'Pi', device_id: 3, host: null, port: 22, username: 'pi', auth_method: 'key', key_id: 2,
    });
    expect(profileInitialFrom({ host: 'srv' }, 'srv').auth_method).toBe('ask');
  });

  it('lists SSH devices online first, hides hidden ones, and shows all on request', () => {
    const ssh = [{ port: 22 }] as Device['services'];
    const list = [
      device({ id: 1, display_name: 'b', is_online: false, services: ssh }),
      device({ id: 2, display_name: 'a', is_online: true, services: ssh }),
      device({ id: 3, display_name: 'c', services: [] }),
      device({ id: 4, display_name: 'd', is_hidden: true, services: ssh }),
    ];
    const label = (d: Device) => d.display_name ?? '';
    expect(filterDevices(list, '', false, label).map((d) => d.id)).toEqual([2, 1]);
    expect(filterDevices(list, '', true, label).map((d) => d.id)).toEqual([2, 3, 1]);
    expect(filterDevices(list, 'a', false, label).map((d) => d.id)).toEqual([2]);
  });

  it('offers the agent update only for a device with an agent, via its saved connection too', () => {
    const withAgent = device({ id: 5, has_agent: true, agent_info: { agent_version: '0.3.4', latest_version: '0.3.5' } as Device['agent_info'] });
    const profiles = [{ id: 9, device_id: 5 }] as SshProfile[];
    expect(agentUpdateFor({ profile_id: 9 }, [withAgent], profiles)).toEqual({ deviceId: 5, installed: '0.3.4', latest: '0.3.5', available: true });
    expect(agentUpdateFor({ host: '192.168.1.10' }, [withAgent], profiles)).toBeNull();
  });

  it('names the sshd key file for the host key type', () => {
    expect(hostKeyFile('ssh-ed25519')).toBe('/etc/ssh/ssh_host_ed25519_key.pub');
    expect(hostKeyFile('ecdsa-sha2-nistp256')).toBe('/etc/ssh/ssh_host_ecdsa_key.pub');
    expect(hostKeyFile('rsa-sha2-512')).toBe('/etc/ssh/ssh_host_rsa_key.pub');
  });
});
