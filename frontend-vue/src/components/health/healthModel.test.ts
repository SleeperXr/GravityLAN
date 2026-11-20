import { describe, expect, it } from 'vitest';
import type { DeviceHistoryResponse, HealthIncident } from '@/types';
import { compareUptime, historyEntry, incidentEntry, pct, sharedIncidentTime, statusWord } from './healthModel';
import { relativeTimeText } from '@/lib/relativeTime';

const incident = (over: Partial<HealthIncident>): HealthIncident => ({
  id: 1,
  device_id: 2,
  device_name: 'nas',
  device_ip: '192.168.1.2',
  status: 'offline',
  severity: 'critical',
  message: null,
  timestamp: '2026-10-23T10:00:00Z',
  ...over,
});

describe('incidentEntry', () => {
  it('fills problems by severity and hollows recoveries', () => {
    expect(incidentEntry(incident({}))).toMatchObject({ key: 1, tone: 'danger', hollow: false });
    expect(incidentEntry(incident({ status: 'flapping', severity: 'critical' })).tone).toBe('warn');
    expect(incidentEntry(incident({ status: 'service_down', severity: 'warn' })).tone).toBe('warn');
    expect(incidentEntry(incident({ status: 'info', severity: 'info' })).tone).toBe('info');
    expect(incidentEntry(incident({ status: 'service_up', severity: 'info' }))).toMatchObject({ tone: 'accent', hollow: true });
  });
});

describe('historyEntry', () => {
  it('marks up as a hollow green dot and anything else as a red one', () => {
    const rec = (status: string): DeviceHistoryResponse => ({ id: 7, device_id: 2, service_id: null, status, message: null, timestamp: '' });
    expect(historyEntry(rec('online'))).toMatchObject({ key: 7, tone: 'accent', hollow: true });
    expect(historyEntry(rec('UP')).hollow).toBe(true);
    expect(historyEntry(rec('offline'))).toMatchObject({ tone: 'danger', hollow: false });
    expect(historyEntry(rec('mac_conflict'))).toMatchObject({ tone: 'warn', hollow: false });
    expect(historyEntry(rec('mac_changed'))).toMatchObject({ tone: 'info', hollow: true });
  });

  it('translates mac_conflict and mac_changed and keeps unknown status words as sent', () => {
    expect(statusWord('mac_conflict')).not.toBe('mac_conflict');
    expect(statusWord('mac_changed')).not.toBe('mac_changed');
    expect(statusWord('future_status')).toBe('future_status');
  });
});

describe('sharedIncidentTime', () => {
  const now = Date.parse('2026-10-29T12:00:00Z');
  const at = (iso: string) => ({ timestamp: iso });
  const fourDays = relativeTimeText(new Date('2026-10-25T12:00:00Z'), now);

  it('names the time every incident shares once', () => {
    const list = [at('2026-10-25T10:00:00Z'), at('2026-10-25T12:00:00Z'), at('2026-10-25T14:00:00Z')];
    expect(sharedIncidentTime(list, now)).toEqual({ text: fourDays, all: true });
  });

  it('names the most common time when some differ', () => {
    const list = [at('2026-10-25T10:00:00Z'), at('2026-10-29T11:00:00Z'), at('2026-10-25T12:00:00Z')];
    expect(sharedIncidentTime(list, now)).toEqual({ text: fourDays, all: false });
  });

  it('names nothing when no two incidents share a time', () => {
    expect(sharedIncidentTime([at('2026-10-25T12:00:00Z'), at('2026-10-29T11:00:00Z')], now)).toBeNull();
    expect(sharedIncidentTime([at('2026-10-25T12:00:00Z')], now)).toBeNull();
    expect(sharedIncidentTime([], now)).toBeNull();
  });
});

describe('pct and compareUptime (Finding F null-safe uptime handling)', () => {
  it('formats null and undefined as – while preserving true 0 % and 100 %', () => {
    expect(pct(null)).toBe('–');
    expect(pct(undefined)).toBe('–');
    expect(pct(0, 1)).toBe('0.0%');
    expect(pct(0, 0)).toBe('0%');
    expect(pct(99.45, 1)).toBe('99.5%');
    expect(pct(100, 1)).toBe('100.0%');
  });

  it('sorts measured uptimes (including 0 %) before unmeasured null values in both directions', () => {
    const items = [
      { name: 'unmeasured-b', uptime: null as number | null },
      { name: 'healthy', uptime: 100.0 as number | null },
      { name: 'down', uptime: 0.0 as number | null },
      { name: 'degraded', uptime: 75.5 as number | null },
      { name: 'unmeasured-a', uptime: null as number | null },
    ];

    const asc = [...items].sort((a, b) => {
      const cmp = compareUptime(a.uptime, b.uptime, 1);
      return cmp !== 0 ? cmp : a.name.localeCompare(b.name);
    });
    expect(asc.map((i) => i.name)).toEqual(['down', 'degraded', 'healthy', 'unmeasured-a', 'unmeasured-b']);

    const desc = [...items].sort((a, b) => {
      const cmp = compareUptime(a.uptime, b.uptime, -1);
      return cmp !== 0 ? cmp : a.name.localeCompare(b.name);
    });
    expect(desc.map((i) => i.name)).toEqual(['healthy', 'degraded', 'down', 'unmeasured-a', 'unmeasured-b']);
  });
});
