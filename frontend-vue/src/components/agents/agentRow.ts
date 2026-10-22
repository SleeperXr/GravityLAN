import type { AgentSummary } from '@/types';

/** One agent of /api/agent/overview; the endpoint also reports the OS, which the shared type omits. */
export interface AgentRow extends AgentSummary {
  os_pretty?: string | null;
  os_name?: string | null;
  os_version?: string | null;
}

export function osLabelOf(agent: AgentRow): string | null {
  if (agent.os_pretty) return agent.os_pretty;
  if (!agent.os_name) return null;
  return agent.os_version ? `${agent.os_name} ${agent.os_version}` : agent.os_name;
}

/** Meter tone: amber from 75 %, red from 90 %. */
export function loadTone(pct: number): 'ok' | 'warn' | 'danger' {
  if (pct >= 90) return 'danger';
  if (pct >= 75) return 'warn';
  return 'ok';
}

/** One hour of the uptime strip: fully up, partly up, down, or no data. */
export function hourState(val: number | null | undefined): 'up' | 'partial' | 'down' | 'none' {
  if (val === null || val === undefined || val < 0) return 'none';
  if (val >= 100) return 'up';
  return val > 0 ? 'partial' : 'down';
}

export function matchesAgent(agent: AgentRow, search: string): boolean {
  const q = search.trim().toLowerCase();
  return !q || agent.hostname.toLowerCase().includes(q) || agent.ip.includes(q);
}
