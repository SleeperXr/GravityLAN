import type { AgentSummary } from '@/types';

/**
 * What the admin is told about a host waiting for confirmation (an agent token pinned to another
 * host, app.services.agent_telemetry._verify_or_pin_host_uid): where it reports from, compared with
 * the address of the device the token belongs to. The full host identity never reaches the browser,
 * only its fingerprint, which the confirmation has to send back.
 */
export type PendingHostRelation = 'same_address' | 'other_address' | 'unknown';

export function pendingHostRelation(agent: Pick<AgentSummary, 'ip' | 'pending_host_ip'>): PendingHostRelation {
  if (!agent.pending_host_ip) return 'unknown';
  return agent.pending_host_ip === agent.ip ? 'same_address' : 'other_address';
}
