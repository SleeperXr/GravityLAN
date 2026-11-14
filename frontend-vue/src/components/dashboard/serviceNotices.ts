import type { Device } from '@/types';
import { isAgentOutdated, patchState } from '@/lib/agent';
import { isClientStandby } from '@/lib/standby';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

export interface Notice {
  key: string;
  rank: number;
  device?: Device;
  tone: 'danger' | 'warn' | 'info';
  title: string;
  detail: string;
  since?: string | null;
  action?: 'device' | 'updates' | 'patches';
}

function offlineNotice(d: Device, name: string): Notice | null {
  if (d.is_online || d.alert_offline === false) return null;
  return { key: `off-${d.id}`, rank: 0, device: d, tone: 'danger', title: t('gv.notices.dropped', { name }), detail: d.ip, since: d.status_changed_at, action: 'device' };
}

function newKeyNotice(d: Device, name: string): Notice | null {
  if (!d.has_pending_token) return null;
  return { key: `key-${d.id}`, rank: 1, device: d, tone: 'danger', title: t('gv.notices.new_key', { name }), detail: t('dashboard.security_alert'), action: 'device' };
}

/** The host answers, but its agent stopped reporting: metrics, updates and the 24/7 check go stale */
function agentSilentNotice(d: Device, name: string): Notice | null {
  // An offline device has its own notice; a new key is the reason the agent is refused
  if (!d.has_agent || d.has_pending_token || !d.is_online || d.agent_info?.reporting !== false) return null;
  const last = d.agent_info.last_report ?? null;
  return {
    key: `agent-${d.id}`,
    rank: 1,
    device: d,
    tone: 'warn',
    title: t('gv.notices.agent_silent', { name }),
    detail: last ? t('gv.notices.agent_silent_detail') : t('gv.notices.agent_never'),
    since: last,
    action: 'device',
  };
}

function servicesDownNotice(d: Device, name: string): Notice | null {
  // A client with every port closed is asleep (standby), not disrupted
  const down = d.is_online && !isClientStandby(d) ? d.services.filter((s) => !s.is_up) : [];
  if (!down.length) return null;
  const title = down.length === d.services.length ? t('gv.notices.services_none', { name }) : t('gv.notices.services_down', { name, count: down.length });
  return { key: `svc-${d.id}`, rank: 2, device: d, tone: 'warn', title, detail: down.map((s) => `${s.name} :${s.port}`).join(', '), action: 'device' };
}

/** Security updates the agent reports, or a pending reboot: the Agents page installs them */
function patchesNotice(d: Device, name: string): Notice | null {
  const patches = patchState(d);
  if (!patches || (patches.security <= 0 && !patches.reboot)) return null;
  const parts = [t('gv.notices.updates_total', { count: patches.available }), patches.reboot ? t('gv.notices.reboot') : ''].filter(Boolean);
  const title = patches.security > 0 ? t('gv.notices.security_updates', { name, count: patches.security }) : t('gv.notices.reboot_only', { name });
  return { key: `sec-${d.id}`, rank: 2, device: d, tone: patches.security > 0 ? 'warn' : 'info', title, detail: parts.join(' · '), action: 'patches' };
}

function ipChangedNotice(d: Device, name: string): Notice | null {
  if (!d.old_ip) return null;
  return { key: `ip-${d.id}`, rank: 3, device: d, tone: 'info', title: t('gv.notices.ip_changed', { name }), detail: `${d.old_ip} → ${d.ip}`, since: d.ip_changed_at, action: 'device' };
}

const DEVICE_NOTICES = [offlineNotice, newKeyNotice, agentSilentNotice, servicesDownNotice, patchesNotice, ipChangedNotice];

function agentUpdatesNotice(devices: Device[]): Notice | null {
  const outdated = devices.filter((d) => d.has_agent && isAgentOutdated(d.agent_info?.agent_version, d.agent_info?.latest_version));
  if (!outdated.length) return null;
  const target = outdated[0].agent_info?.latest_version;
  return { key: 'updates', rank: 4, tone: 'info', title: t('gv.notices.updates', { count: outdated.length }), detail: target ? `→ v${target}` : '', action: 'updates' };
}

/** Everything that needs the operator, most urgent first. */
export function buildNotices(devices: Device[]): Notice[] {
  const list = devices.flatMap((d) => {
    const name = deviceLabel(d);
    return DEVICE_NOTICES.map((notice) => notice(d, name)).filter((n): n is Notice => n !== null);
  });
  const updates = agentUpdatesNotice(devices);
  if (updates) list.push(updates);
  return list.sort((a, b) => a.rank - b.rank);
}
