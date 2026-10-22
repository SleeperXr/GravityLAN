import type { BadgeTone } from '@/components/ui/Badge.vue';
import type { DeviceHealthItem, ServiceHealthItem } from '@/types';
import { t } from '@/i18n';

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
