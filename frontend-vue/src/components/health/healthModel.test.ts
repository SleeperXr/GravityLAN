import { describe, expect, it } from 'vitest';
import type { DeviceHistoryResponse, HealthIncident } from '@/types';
import { historyEntry, incidentEntry } from './healthModel';

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
  });
});
