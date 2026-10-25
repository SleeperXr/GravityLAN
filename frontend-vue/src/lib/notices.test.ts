import { beforeEach, describe, expect, it } from 'vitest';
import type { Device, Service } from '@/types';
import { setLocale } from '@/i18n';
import { buildNotices, isStale, summarizeFleet, STALE_AFTER_MS } from './notices';

let nextId = 1;
function device(over: Partial<Device> = {}): Device {
  const id = nextId++;
  return {
    id,
    ip: `10.0.0.${id}`,
    hostname: `host-${id}`,
    display_name: null,
    is_online: true,
    alert_offline: true,
    services: [],
    has_agent: false,
    has_pending_token: false,
    old_ip: null,
    ...over,
  } as unknown as Device;
}
const svc = (name: string, is_up: boolean) => ({ name, port: 80, is_up }) as Service;

beforeEach(() => {
  nextId = 1;
  setLocale('en');
});

describe('buildNotices', () => {
  it('puts offline devices first and skips clients that may sleep', () => {
    const list = buildNotices([
      device({ old_ip: '10.0.0.99', ip_changed_at: '2026-10-25T10:00:00Z' }),
      device({ display_name: 'NAS', is_online: false }),
      device({ display_name: 'Laptop', is_online: false, alert_offline: false }),
    ]);
    expect(list.map((n) => n.kind)).toEqual(['offline', 'ip']);
    expect(list[0].title).toBe('NAS: offline');
  });

  it('reports services down, but not for a client in standby', () => {
    const list = buildNotices([
      device({ display_name: 'Web', services: [svc('http', false), svc('ssh', true)] }),
      device({ display_name: 'PC', alert_offline: false, services: [svc('rdp', false)] }),
    ]);
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ kind: 'services', tone: 'warn', detail: 'http :80' });
  });
});

describe('summarizeFleet', () => {
  it('names the first two offline devices and counts the rest', () => {
    const summary = summarizeFleet(
      buildNotices([
        device({ display_name: 'NAS', is_online: false }),
        device({ display_name: 'Pi-hole', is_online: false }),
        device({ display_name: 'Printer', is_online: false }),
        device({ display_name: 'Web', services: [svc('http', false)] }),
      ]),
    );
    expect(summary.tone).toBe('danger');
    expect(summary.headline).toBe('3 devices offline: NAS, Pi-hole +1');
    expect(summary.top?.device?.display_name).toBe('NAS');
  });

  it('lists the topics of warnings when nothing is down', () => {
    const summary = summarizeFleet(
      buildNotices([
        device({ display_name: 'Web', services: [svc('http', false)] }),
        device({ display_name: 'DB', services: [svc('pg', false)] }),
        device({ agent_info: { latest_metrics: { patch_available: 4, patch_security: 2 } } } as Partial<Device>),
      ]),
    );
    expect(summary.tone).toBe('warn');
    expect(summary.headline).toBe('3 notices: services disrupted, security updates');
    expect(summary.top?.kind).toBe('services');
  });

  it('reports a quiet fleet and still counts informational notices', () => {
    const summary = summarizeFleet(buildNotices([device(), device({ old_ip: '10.0.0.50' })]));
    expect(summary).toMatchObject({ tone: 'ok', headline: 'No disruptions', top: null, infoCount: 1 });
  });

  it('treats a new agent key as a disruption', () => {
    const summary = summarizeFleet(buildNotices([device({ display_name: 'NAS', has_pending_token: true })]));
    expect(summary.tone).toBe('danger');
    expect(summary.headline).toBe('New agent key: NAS');
  });
});

describe('isStale', () => {
  it('flags data older than the threshold and never-loaded data as not stale', () => {
    const now = 1_000_000;
    expect(isStale(null, now)).toBe(false);
    expect(isStale(now - STALE_AFTER_MS + 1, now)).toBe(false);
    expect(isStale(now - STALE_AFTER_MS - 1, now)).toBe(true);
  });
});
