import type { Device } from '@/types';
import { isAgentOutdated, patchState } from '@/lib/agent';
import { isClientStandby } from '@/lib/standby';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';

export type NoticeKind = 'offline' | 'key' | 'services' | 'patches' | 'ip' | 'agent_updates';
export type NoticeTone = 'danger' | 'warn' | 'info';

export interface Notice {
  key: string;
  kind: NoticeKind;
  rank: number;
  device?: Device;
  tone: NoticeTone;
  title: string;
  detail: string;
  since?: string | null;
  action?: 'device' | 'updates' | 'patches';
}

/** Older data than this (three missed 30 s polls) means the overview has stopped updating. */
export const STALE_AFTER_MS = 90_000;
/** Names spelled out in the status line before the rest is counted as "+n". */
const NAMED_DEVICES = 2;

/**
 * Everything that needs the operator, most urgent first: offline devices watched 24/7, new agent
 * keys, services down (not for clients in standby), security updates and pending reboots reported
 * by agents, IP changes, agent updates.
 */
export function buildNotices(devices: Device[]): Notice[] {
  const list: Notice[] = [];
  for (const d of devices) {
    const name = deviceLabel(d);
    if (!d.is_online && d.alert_offline !== false) {
      list.push({ key: `off-${d.id}`, kind: 'offline', rank: 0, device: d, tone: 'danger', title: t('gv.notices.dropped', { name }), detail: d.ip, since: d.status_changed_at, action: 'device' });
    }
    if (d.has_pending_token) {
      list.push({ key: `key-${d.id}`, kind: 'key', rank: 1, device: d, tone: 'danger', title: t('gv.notices.new_key', { name }), detail: t('dashboard.security_alert'), action: 'device' });
    }
    // A client with every port closed is asleep (standby), not disrupted
    const down = d.is_online && !isClientStandby(d) ? d.services.filter((s) => !s.is_up) : [];
    if (down.length) {
      const title = down.length === d.services.length ? t('gv.notices.services_none', { name }) : t('gv.notices.services_down', { name, count: down.length });
      list.push({ key: `svc-${d.id}`, kind: 'services', rank: 2, device: d, tone: 'warn', title, detail: down.map((s) => `${s.name} :${s.port}`).join(', '), action: 'device' });
    }
    // Security updates the agent reports, or a pending reboot: the Agents page installs them
    const patches = patchState(d);
    if (patches && (patches.security > 0 || patches.reboot)) {
      const parts = [t('gv.notices.updates_total', { count: patches.available }), patches.reboot ? t('gv.notices.reboot') : ''].filter(Boolean);
      const title = patches.security > 0 ? t('gv.notices.security_updates', { name, count: patches.security }) : t('gv.notices.reboot_only', { name });
      list.push({ key: `sec-${d.id}`, kind: 'patches', rank: 2, device: d, tone: patches.security > 0 ? 'warn' : 'info', title, detail: parts.join(' · '), action: 'patches' });
    }
    if (d.old_ip) {
      list.push({ key: `ip-${d.id}`, kind: 'ip', rank: 3, device: d, tone: 'info', title: t('gv.notices.ip_changed', { name }), detail: `${d.old_ip} → ${d.ip}`, since: d.ip_changed_at, action: 'device' });
    }
  }
  const outdated = devices.filter((d) => d.has_agent && isAgentOutdated(d.agent_info?.agent_version, d.agent_info?.latest_version));
  if (outdated.length) {
    const target = outdated[0].agent_info?.latest_version;
    list.push({ key: 'updates', kind: 'agent_updates', rank: 4, tone: 'info', title: t('gv.notices.updates', { count: outdated.length }), detail: target ? `→ v${target}` : '', action: 'updates' });
  }
  return list.sort((a, b) => a.rank - b.rank);
}

export interface FleetSummary {
  tone: 'danger' | 'warn' | 'ok';
  headline: string;
  /** The most urgent notice to jump to; null when nothing is disrupted or needs attention. */
  top: Notice | null;
  /** Notices that need no action now (IP changes, reboots, agent updates). */
  infoCount: number;
}

function namesOf(notices: Notice[]): string {
  const names = notices.map((n) => (n.device ? deviceLabel(n.device) : n.title));
  const shown = names.slice(0, NAMED_DEVICES).join(', ');
  return names.length > NAMED_DEVICES ? `${shown} ${t('gv.fleet.more', { count: names.length - NAMED_DEVICES })}` : shown;
}

/** The answer to "is everything all right?" in one sentence, in facts rather than the orbit metaphor. */
export function summarizeFleet(notices: Notice[]): FleetSummary {
  const infoCount = notices.filter((n) => n.tone === 'info').length;
  const offline = notices.filter((n) => n.kind === 'offline');
  if (offline.length) {
    return { tone: 'danger', headline: t('gv.fleet.offline', { count: offline.length, names: namesOf(offline) }), top: offline[0], infoCount };
  }
  const danger = notices.filter((n) => n.tone === 'danger');
  if (danger.length) {
    return { tone: 'danger', headline: t('gv.fleet.new_key', { names: namesOf(danger) }), top: danger[0], infoCount };
  }
  const warn = notices.filter((n) => n.tone === 'warn');
  if (warn.length) {
    const topics = (['services', 'patches'] as const)
      .filter((kind) => warn.some((n) => n.kind === kind))
      .map((kind) => t(`gv.fleet.topic_${kind}`))
      .join(', ');
    return { tone: 'warn', headline: t('gv.fleet.attention', { count: warn.length, topics }), top: warn[0], infoCount };
  }
  return { tone: 'ok', headline: t('gv.fleet.quiet'), top: null, infoCount };
}

/** True when data was loaded once but not refreshed within STALE_AFTER_MS. */
export function isStale(loadedAt: number | null, now: number): boolean {
  return loadedAt !== null && now - loadedAt > STALE_AFTER_MS;
}
