/** Pure SSH page logic, ported from the React UI (Ssh/view/sshModel.ts and the terminal helpers). */
import type { IBuffer } from '@xterm/xterm';
import type { Device, SshHistoryEntry, SshKey, SshProfile, SshProfileInput, SshSessionRequest } from '@/types';
import { isAgentOutdated } from '@/lib/agent';

export type TerminalStatus = 'connecting' | 'hostkey' | 'authenticating' | 'connected' | 'closed' | 'error';

export interface Session {
  id: number;
  label: string;
  request: SshSessionRequest;
  status: TerminalStatus;
}

/** The agent of the device a terminal is connected to, and whether an update for it is available. */
export interface AgentUpdate {
  deviceId: number;
  installed: string;
  latest: string;
  available: boolean;
}

/** Values to start the connect dialog with, e.g. from a recent connection. */
export interface ConnectInitial {
  host?: string;
  port?: number;
  username?: string;
  auth?: 'key' | 'password';
  keyId?: number | null;
}

export interface HostKeyPrompt {
  status: 'unknown' | 'changed';
  host: string;
  port: number;
  key_type: string;
  fingerprint: string;
  known_fingerprint?: string;
}

export function hasSsh(device: Device): boolean {
  return device.services?.some((s) => s.protocol?.toLowerCase() === 'ssh' || s.port === 22) ?? false;
}

export function isLive(session: Pick<Session, 'status'>): boolean {
  return session.status !== 'closed' && session.status !== 'error';
}

/**
 * The agent of the device a session is connected to (chosen directly or through its saved
 * connection), null when the device has no agent. Plain host connections are not matched to
 * devices by address: the update command enrols the agent for one device id.
 */
export function agentUpdateFor(request: SshSessionRequest, devices: Device[], profiles: SshProfile[]): AgentUpdate | null {
  const deviceId = request.device_id ?? profiles.find((p) => p.id === request.profile_id)?.device_id;
  const device = deviceId == null ? undefined : devices.find((d) => d.id === deviceId);
  const installed = device?.agent_info?.agent_version;
  const latest = device?.agent_info?.latest_version;
  if (!device?.has_agent || !installed || !latest) return null;
  return { deviceId: device.id, installed, latest, available: isAgentOutdated(installed, latest) };
}

/** Prefill for "save as connection" from an ad-hoc request (tab) or a history entry. */
export function profileInitialFrom(
  source: { device_id?: number | null; host?: string | null; port?: number; username?: string; key_id?: number | null },
  name: string,
): Partial<SshProfileInput> {
  return {
    name,
    device_id: source.device_id ?? null,
    host: source.device_id ? null : (source.host ?? null),
    port: source.port ?? 22,
    username: source.username ?? 'root',
    auth_method: source.key_id ? 'key' : 'ask',
    key_id: source.key_id ?? null,
  };
}

/** Reconnect a history entry straight away when its key is still stored, else through the dialog. */
export function historyReconnect(
  entry: SshHistoryEntry,
  keys: SshKey[],
): { kind: 'open'; request: SshSessionRequest } | { kind: 'ask'; initial: ConnectInitial } {
  const keyStillStored = entry.auth_method === 'key' && entry.key_id !== null && keys.some((k) => k.id === entry.key_id);
  if (keyStillStored) {
    return {
      kind: 'open',
      request: {
        device_id: entry.device_id ?? undefined,
        host: entry.device_id ? undefined : (entry.host ?? undefined),
        port: entry.port,
        username: entry.username,
        key_id: entry.key_id!,
      },
    };
  }
  return { kind: 'ask', initial: { host: entry.host ?? '', port: entry.port, username: entry.username, auth: 'password' } };
}

const contains = (query: string, values: (string | null | undefined)[]) => !query || values.some((v) => v?.toLowerCase().includes(query));

export function filterProfiles(profiles: SshProfile[], query: string): SshProfile[] {
  return profiles.filter((p) => contains(query, [p.name, p.username, p.target_host, p.device_name]));
}

export function filterHistory(history: SshHistoryEntry[], query: string): SshHistoryEntry[] {
  return history.filter((h) => contains(query, [h.label, h.target_host, h.device_name]));
}

/** Visible devices with an SSH service (or all), matching the search, online first then by name. */
export function filterDevices(devices: Device[], query: string, showAll: boolean, label: (d: Device) => string): Device[] {
  return devices
    .filter((d) => !d.is_hidden && (showAll || hasSsh(d)))
    .filter((d) => contains(query, [label(d), d.ip, d.hostname]))
    .sort((a, b) => Number(b.is_online) - Number(a.is_online) || label(a).localeCompare(label(b)));
}

/** The sshd public key file matching a host key type, for the "verify on the server" hint. */
export function hostKeyFile(keyType: string): string {
  const kind = keyType.includes('ed25519') ? 'ed25519' : keyType.startsWith('ecdsa') ? 'ecdsa' : keyType.includes('rsa') ? 'rsa' : '*';
  return `/etc/ssh/ssh_host_${kind}_key.pub`;
}

/**
 * The command entered on `markerLine` plus everything it printed, without the new prompt the
 * cursor sits on once it finished. Wrapped rows are joined.
 */
export function lastCommandText(buffer: IBuffer, markerLine: number): string {
  const lineStart = (row: number, floor: number) => {
    let start = row;
    while (start > floor && buffer.getLine(start)?.isWrapped) start--;
    return start;
  };
  const first = lineStart(markerLine, 0);
  const cursorLine = buffer.baseY + buffer.cursorY;
  const promptStart = lineStart(cursorLine, first);
  const end = promptStart > first ? promptStart - 1 : cursorLine;
  let text = '';
  for (let i = first; i <= end; i++) {
    const line = buffer.getLine(i);
    if (!line) continue;
    const nextWraps = buffer.getLine(i + 1)?.isWrapped ?? false;
    text += (i > first && !line.isWrapped ? '\n' : '') + line.translateToString(!nextWraps);
  }
  return text.replace(/\s+$/, '');
}
