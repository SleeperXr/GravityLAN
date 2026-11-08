import { describe, expect, it } from 'vitest';
import type { Device, Service } from '@/types';
import { buildNotices } from './serviceNotices';

const svc = (is_up: boolean, name = 'web', port = 80) => ({ is_up, name, port }) as Service;
const dev = (extra: Partial<Device> = {}): Device =>
  ({ id: 1, ip: '192.0.2.1', display_name: 'nas', is_online: true, alert_offline: true, services: [], ...extra }) as Device;
const metrics = (latest_metrics: Record<string, unknown>) => ({ agent_info: { latest_metrics } }) as unknown as Partial<Device>;
const keys = (...devices: Device[]) => buildNotices(devices).map((n) => n.key);

describe('buildNotices', () => {
  it('is empty for a healthy device', () => {
    expect(keys(dev())).toEqual([]);
  });

  it('reports watched devices that are offline, not clients that may sleep', () => {
    expect(keys(dev({ is_online: false }))).toEqual(['off-1']);
    expect(keys(dev({ is_online: false, alert_offline: false }))).toEqual([]);
  });

  it('reports a new agent key as urgent', () => {
    expect(buildNotices([dev({ has_pending_token: true })])[0]).toMatchObject({ key: 'key-1', rank: 1, tone: 'danger', action: 'device' });
  });

  it('names the services that are down', () => {
    const [notice] = buildNotices([dev({ services: [svc(true), svc(false, 'ssh', 22)] })]);
    expect(notice).toMatchObject({ key: 'svc-1', tone: 'warn', detail: 'ssh :22' });
  });

  it('stays quiet about services on a client in standby or an offline device', () => {
    expect(keys(dev({ alert_offline: false, services: [svc(false)] }))).toEqual([]);
    expect(keys(dev({ is_online: false, services: [svc(false)] }))).toEqual(['off-1']);
  });

  it('sends security updates and pending reboots to the patches page', () => {
    expect(buildNotices([dev(metrics({ patch_available: 3, patch_security: 2 }))])[0]).toMatchObject({ key: 'sec-1', tone: 'warn', action: 'patches' });
    expect(buildNotices([dev(metrics({ patch_available: 3, reboot_required: true }))])[0]).toMatchObject({ key: 'sec-1', tone: 'info', action: 'patches' });
  });

  it('ignores plain updates that are neither security fixes nor a reboot', () => {
    expect(keys(dev(metrics({ patch_available: 3 })))).toEqual([]);
  });

  it('shows an IP change with both addresses', () => {
    expect(buildNotices([dev({ old_ip: '192.0.2.9' })])[0]).toMatchObject({ key: 'ip-1', rank: 3, detail: '192.0.2.9 → 192.0.2.1' });
  });

  it('bundles outdated agents into one notice without a device', () => {
    const outdated = { has_agent: true, agent_info: { agent_version: '0.3.1', latest_version: '0.3.2' } } as unknown as Partial<Device>;
    const notices = buildNotices([dev({ id: 1, ...outdated }), dev({ id: 2, ...outdated })]);
    expect(notices).toHaveLength(1);
    expect(notices[0]).toMatchObject({ key: 'updates', detail: '→ v0.3.2', action: 'updates' });
    expect(notices[0].device).toBeUndefined();
  });

  it('sorts by urgency and keeps device order within a rank', () => {
    const a = dev({ id: 1, old_ip: '192.0.2.9' });
    const b = dev({ id: 2, is_online: false });
    const c = dev({ id: 3, is_online: false });
    expect(keys(a, b, c)).toEqual(['off-2', 'off-3', 'ip-1']);
  });
});
