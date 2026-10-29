import type { BadgeTone } from '@/components/ui/Badge.vue';
import type { DeviceHealthItem, DeviceHistoryResponse, HealthIncident, ServiceHealthItem } from '@/types';
import type { TimelineEntry } from '@/components/common/timeline';
import { t } from '@/i18n';
import { parseDate, relativeTimeText } from '@/lib/relativeTime';

export type HealthStatus = DeviceHealthItem['health_status'];

/** Label and tone of a health status; flapping/degraded warn, critical/offline alarm. */
export function statusMeta(status: HealthStatus): { label: string; tone: BadgeTone; dot: 'online' | 'warn' | 'offline' | 'unknown' } {
  switch (status) {
    case 'healthy':
      return { label: t('health_page.filter_healthy'), tone: 'accent', dot: 'online' };
    case 'flapping':
      return { label: t('health_page.filter_flapping'), tone: 'warn', dot: 'warn' };
    case 'degraded':
      return { label: t('health_page.filter_degraded'), tone: 'warn', dot: 'warn' };
    case 'critical':
      return { label: t('health_page.filter_critical'), tone: 'danger', dot: 'offline' };
    case 'standby':
      return { label: t('health_page.filter_standby'), tone: 'neutral', dot: 'unknown' };
    default:
      return { label: t('common.offline'), tone: 'neutral', dot: 'offline' };
  }
}

/** Score colour: >= 90 good, >= 70 watch, below that bad; standby devices stay neutral. */
export function scoreTone(score: number, status?: HealthStatus): BadgeTone {
  if (status === 'standby') return 'neutral';
  if (score >= 90) return 'accent';
  if (score >= 70) return 'warn';
  return 'danger';
}

export const scoreText = (score: number) => (score >= 90 ? 'text-accent-text' : score >= 70 ? 'text-warn-text' : 'text-danger-text');

export const sslWarnings = (services: ServiceHealthItem[]) =>
  services.filter((s) => !s.ignore_ssl && s.ssl_expiry_days !== null && s.ssl_expiry_days <= 14).length;

export const hasAgentWarning = (device: DeviceHealthItem) => Boolean(device.agent && (device.agent.patch_security > 0 || device.agent.reboot_required));

/** A status word from history/incident records in the UI language (unknown words stay as sent). */
export function statusWord(status: string): string {
  const key = status.toLowerCase();
  if (key === 'online' || key === 'up') return t('network.online');
  if (key === 'offline' || key === 'down') return t('network.offline');
  if (key === 'flapping' || key === 'service_up' || key === 'service_down') return t(`gv.status.${key}`);
  return status;
}

export const ms = (value: number | null | undefined, digits = 1) => (value === null || value === undefined ? '–' : `${value.toFixed(digits)} ms`);

/** Hours covered by a health period, for the status monitor's time axis. */
export const periodHours = (period: '24h' | '7d' | '30d') => ({ '24h': 24, '7d': 168, '30d': 720 })[period];

const isRecovery = (status: string) => ['online', 'up', 'service_up'].includes(status.toLowerCase());

/** Timeline dot of an incident: tone by severity, hollow when something came back. */
export function incidentEntry(incident: HealthIncident): TimelineEntry<HealthIncident> {
  const tone = isRecovery(incident.status) ? 'accent' : incident.status === 'flapping' || incident.severity === 'warn' ? 'warn' : incident.severity === 'critical' ? 'danger' : 'info';
  return { key: incident.id, tone, hollow: isRecovery(incident.status), data: incident };
}

/**
 * The relative time most incidents share ("vor 4 Tagen"), so a list says it once instead of on
 * every row; rows with a different time keep their own. Null when no time is shared by two or more.
 */
export function sharedIncidentTime(incidents: Pick<HealthIncident, 'timestamp'>[], now: number = Date.now()): { text: string; all: boolean } | null {
  const counts = new Map<string, number>();
  for (const incident of incidents) {
    const date = parseDate(incident.timestamp);
    if (!date) continue;
    const text = relativeTimeText(date, now);
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  let best: { text: string; count: number } | null = null;
  for (const [text, count] of counts) if (!best || count > best.count) best = { text, count };
  if (!best || best.count < 2) return null;
  return { text: best.text, all: best.count === incidents.length };
}

/** Timeline dot of a status history record: up is a hollow green dot, anything else a red one. */
export function historyEntry(item: DeviceHistoryResponse): TimelineEntry<DeviceHistoryResponse> {
  const up = isRecovery(item.status);
  return { key: item.id, tone: up ? 'accent' : 'danger', hollow: up, data: item };
}
