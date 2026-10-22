import { describe, expect, it } from 'vitest';
import { hourState, loadTone, matchesAgent, osLabelOf, type AgentRow } from './agentRow';

const agent = (over: Partial<AgentRow> = {}): AgentRow => ({
  device_id: 1,
  hostname: 'proxmox.lan',
  ip: '192.168.100.10',
  is_online: true,
  agent_version: '0.3.5',
  last_seen: null,
  cpu_usage: 0,
  ram_usage: 0,
  temp: null,
  uptime_pct: 100,
  uptime_history: [],
  metrics_count: 0,
  patch_available: 0,
  patch_security: 0,
  patch_manager: null,
  reboot_required: false,
  major_upgrade_available: null,
  ...over,
});

describe('agentRow', () => {
  it('prefers the pretty OS name and falls back to name + version', () => {
    expect(osLabelOf(agent({ os_pretty: 'Debian 12', os_name: 'debian' }))).toBe('Debian 12');
    expect(osLabelOf(agent({ os_name: 'Ubuntu', os_version: '24.04' }))).toBe('Ubuntu 24.04');
    expect(osLabelOf(agent({ os_name: 'Alpine' }))).toBe('Alpine');
    expect(osLabelOf(agent())).toBeNull();
  });

  it('turns load amber at 75 % and red at 90 %', () => {
    expect(loadTone(74.9)).toBe('ok');
    expect(loadTone(75)).toBe('warn');
    expect(loadTone(90)).toBe('danger');
  });

  it('classifies uptime hours, treating missing or negative values as no data', () => {
    expect(hourState(100)).toBe('up');
    expect(hourState(40)).toBe('partial');
    expect(hourState(0)).toBe('down');
    expect(hourState(-1)).toBe('none');
    expect(hourState(null)).toBe('none');
  });

  it('matches by hostname (case-insensitive) or IP, and everything for an empty search', () => {
    expect(matchesAgent(agent(), 'PROX')).toBe(true);
    expect(matchesAgent(agent(), '100.10')).toBe(true);
    expect(matchesAgent(agent(), '  ')).toBe(true);
    expect(matchesAgent(agent(), 'unraid')).toBe(false);
  });
});
