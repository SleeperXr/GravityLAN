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

/** A server URL that may go into a root shell command: scheme, host, port and a plain path only. */
const SAFE_SERVER_URL = /^https?:\/\/[A-Za-z0-9.\-[\]:]+(\/[A-Za-z0-9._~\-/]*)?$/;

/**
 * The one-line installer. It fetches the script from the address the script itself downloads
 * from, so an HTTPS server URL protects this first download too, and curl may not follow a
 * redirect down to HTTP (#44). Over plain HTTP the script refuses to run unless ALLOW_INSECURE=1
 * is set: ``optInInsecure`` adds it, only after the user agreed. `env` passes it through sudo
 * whatever the sudoers env policy says.
 */
export function buildInstallCommand(deviceId: number, code: string, serverUrl = serverOrigin(), optInInsecure = false): string {
  const base = serverUrl.replace(/\/+$/, '');
  const curl = base.toLowerCase().startsWith('https://') ? "curl --proto '=https' -sSL" : 'curl -sSL';
  const shell = optInInsecure ? 'sudo env ALLOW_INSECURE=1 bash' : 'sudo bash';
  return `${curl} "${base}/api/agent/download/install-sh/${deviceId}?code=${code}" | ${shell}`;
}

export function buildUninstallCommand(deviceId: number): string {
  return `curl -sSL "${serverOrigin()}/api/agent/download/uninstall-sh/${deviceId}" | sudo bash`;
}

export interface InstallCode {
  code: string;
  expiresAt: Date;
  /** Address the install script downloads from; the command fetches the script from it too */
  serverUrl: string;
  /** The script downloads over plain HTTP */
  insecure: boolean;
  /** The server allows that for every install (GRAVITYLAN_ALLOW_INSECURE_INSTALL): no opt-in needed */
  insecureAllowed: boolean;
}

/** Over plain HTTP the installer stops unless the user opts in (or the server allows it). */
export function needsInsecureOptIn(installCode: InstallCode): boolean {
  return installCode.insecure && !installCode.insecureAllowed;
}

/** A fresh single-use enrollment code for the install command of one device. */
export async function requestInstallCode(deviceId: number): Promise<InstallCode> {
  const { code, expires_in, server_url, insecure, insecure_allowed } = await api.createAgentEnrollment(deviceId);
  // Code and server URL end up in a root shell command: accept only what they can legitimately contain.
  if (!/^[A-Za-z0-9_-]+$/.test(code)) throw new Error('Unexpected install code format');
  const serverUrl = server_url || serverOrigin();
  if (!SAFE_SERVER_URL.test(serverUrl)) throw new Error('Unexpected server URL format');
  return {
    code,
    expiresAt: new Date(Date.now() + expires_in * 1000),
    serverUrl,
    insecure: !!insecure,
    insecureAllowed: !!insecure_allowed,
  };
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
