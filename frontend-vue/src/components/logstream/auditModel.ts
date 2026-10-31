import { t } from '@/i18n';
import type { BadgeTone } from '@/components/ui/Badge.vue';

/** Filter classes of the audit log; each is a list of action prefixes for GET /api/audit?action=. */
export const AUDIT_CATEGORIES = {
  all: [],
  remote: ['agent', 'ssh.terminal'],
  credentials: ['ssh.key', 'ssh.connection', 'ssh.known_host', 'auth.token', 'auth.password', 'webhook'],
  instance: ['backup', 'database'],
  logins: ['auth.login'],
} as const satisfies Record<string, readonly string[]>;

export type AuditCategory = keyof typeof AUDIT_CATEGORIES;
export type AuditResult = 'ok' | 'failed' | 'denied';

export interface AuditEvent {
  id: number;
  created_at: string;
  actor: string;
  source_ip: string;
  action: string;
  result: AuditResult;
  device_id: number | null;
  target: string;
  detail: string;
}

export interface AuditPage {
  items: AuditEvent[];
  has_more: boolean;
  retention_days: number;
}

/** "agent.deploy" → "Agent installiert"; an action this UI does not know yet shows as it is. */
export function actionLabel(action: string): string {
  const key = `gv.audit.action.${action.replaceAll('.', '_')}`;
  const label = t(key);
  return label === key ? action : label;
}

/** "session" → "Browser-Sitzung", "api_token:ha" → "API-Token „ha“". */
export function actorLabel(actor: string): string {
  if (actor.startsWith('api_token:')) return t('gv.audit.actor.api_token', { name: actor.slice('api_token:'.length) });
  const key = `gv.audit.actor.${actor}`;
  const label = t(key);
  return label === key ? actor : label;
}

export const RESULT_TONE: Record<AuditResult, BadgeTone> = { ok: 'accent', failed: 'danger', denied: 'warn' };
