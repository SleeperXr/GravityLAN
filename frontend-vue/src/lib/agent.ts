/** Agent helpers ported from the React UI (Agents/ManualInstallCommand.tsx, Agents/savedLogins.ts). */
import { api } from '@/api/client';
import type { Device, SshProfile } from '@/types';

export { isAgentOutdated } from '@shared/utils/version';

/** Pending package updates of a host from its agent's latest report, or null without an agent report. */
export function patchState(device: Pick<Device, 'agent_info'>): { available: number; security: number; reboot: boolean } | null {
  const m = device.agent_info?.latest_metrics;
  if (!m) return null;
  return { available: m.patch_available ?? 0, security: m.patch_security ?? 0, reboot: !!m.reboot_required };
}

/** Server address as the browser sees it; the Vite dev servers (5173/5174) talk to the API on 8000. */
export function serverOrigin(): string {
  const { protocol, hostname, port } = window.location;
  const apiPort = port === '5173' || port === '5174' ? ':8000' : port ? `:${port}` : '';
  return `${protocol}//${hostname}${apiPort}`;
}

/**
 * The one-line installer. Over plain HTTP the script refuses to run unless ALLOW_INSECURE=1
 * is set (#44); `env` passes it through sudo whatever the sudoers env policy says.
 */
export function buildInstallCommand(deviceId: number, code: string, insecure = false): string {
  const shell = insecure ? 'sudo env ALLOW_INSECURE=1 bash' : 'sudo bash';
  return `curl -sSL "${serverOrigin()}/api/agent/download/install-sh/${deviceId}?code=${code}" | ${shell}`;
}

export function buildUninstallCommand(deviceId: number): string {
  return `curl -sSL "${serverOrigin()}/api/agent/download/uninstall-sh/${deviceId}" | sudo bash`;
}

export interface InstallCode {
  code: string;
  expiresAt: Date;
  /** The script downloads over plain HTTP, so the command needs ALLOW_INSECURE=1 */
  insecure: boolean;
}

/** A fresh single-use enrollment code for the install command of one device. */
export async function requestInstallCode(deviceId: number): Promise<InstallCode> {
  const { code, expires_in, insecure } = await api.createAgentEnrollment(deviceId);
  // The code ends up in a root shell command: accept only the backend's token_urlsafe alphabet.
  if (!/^[A-Za-z0-9_-]+$/.test(code)) throw new Error('Unexpected install code format');
  return { code, expiresAt: new Date(Date.now() + expires_in * 1000), insecure: !!insecure };
}

/**
 * Saved SSH connections that may log in for agent deploy and updates: key logins of
 * this device (linked to it, or to its address). The backend checks the same (ADR-002).
 */
export function agentKeyProfiles(profiles: SshProfile[], device: Pick<Device, 'id' | 'ip'>): SshProfile[] {
  return profiles.filter(
    (p) => p.auth_method === 'key' && p.key_id !== null && (p.device_id !== null ? p.device_id === device.id : p.host === device.ip),
  );
}

/** "user@host" (with a port other than 22) of a saved connection. */
export function profileTarget(profile: SshProfile): string {
  const port = profile.port !== 22 ? `:${profile.port}` : '';
  return `${profile.username}@${profile.target_host ?? profile.host ?? ''}${port}`;
}
