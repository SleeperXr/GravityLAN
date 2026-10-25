import { useEffect, useState } from 'react';
import { AlertTriangle, Copy, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useToast } from '../../context/ToastContext';

/** Server address as the browser sees it; the Vite dev server (5173) talks to the API on 8000. */
function serverOrigin(): string {
  const { protocol, hostname, port } = window.location;
  const apiPort = port === '5173' ? ':8000' : (port ? `:${port}` : '');
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

/**
 * ``insecure``: the script downloads over plain HTTP. ``insecureAllowed``: the server allows
 * that for every install (GRAVITYLAN_ALLOW_INSECURE_INSTALL), so the command needs no opt-in.
 */
export interface InstallCode { code: string; expiresAt: Date; serverUrl: string; insecure: boolean; insecureAllowed: boolean }

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

export function buildUninstallCommand(deviceId: number): string {
  return `curl -sSL "${serverOrigin()}/api/agent/download/uninstall-sh/${deviceId}" | sudo bash`;
}

export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.error('Clipboard write failed:', err);
    }
  }
  // Plain-HTTP installs have no Clipboard API
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);
  textArea.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch (err) {
    console.error('Copy fallback failed:', err);
  }
  document.body.removeChild(textArea);
  return copied;
}

/** The one-line uninstaller for a device (needs no code: it only removes the agent). */
export function ManualUninstallCommand({ deviceId }: { deviceId: number }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const command = buildUninstallCommand(deviceId);

  const handleCopy = async () => {
    if (await copyText(command)) {
      showToast('success', t('notifications.copied'), t('notifications.copied_text'));
    } else {
      showToast('error', t('common.error'), t('settings.copy_failed'));
    }
  };

  return (
    <div className="manual-command">
      <p className="field-hint">{t('agent.manual_uninstall_desc')}</p>
      <div className="manual-command__box">
        <code className="manual-command__code is-danger">{command}</code>
        <button type="button" className="btn btn-secondary btn-sm" onClick={handleCopy}>
          <Copy size={14} aria-hidden="true" /> {t('common.copy')}
        </button>
      </div>
    </div>
  );
}

/**
 * The one-line installer for a device, with a fresh single-use enrollment code.
 * Running it on the device installs or updates the agent (no SSH access from GravityLAN needed).
 */
export function ManualInstallCommand({ deviceId }: { deviceId: number }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [installCode, setInstallCode] = useState<InstallCode | null>(null);
  const [failed, setFailed] = useState(false);
  const [request, setRequest] = useState(0);
  const [insecureOptIn, setInsecureOptIn] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setInstallCode(null);
    setFailed(false);
    setInsecureOptIn(false);
    requestInstallCode(deviceId)
      .then((result) => {
        if (!cancelled) setInstallCode(result);
      })
      .catch((err) => {
        console.error('Failed to create install code:', err);
        if (!cancelled) setFailed(true);
      });
    return () => { cancelled = true; };
  }, [deviceId, request]);

  const needsOptIn = !!installCode && needsInsecureOptIn(installCode);
  const command = installCode
    ? buildInstallCommand(deviceId, installCode.code, installCode.serverUrl, needsOptIn && insecureOptIn)
    : '';

  const handleCopy = async () => {
    if (!command) return;
    if (await copyText(command)) {
      showToast('success', t('notifications.copied'), t('notifications.copied_text'));
    } else {
      showToast('error', t('common.error'), t('settings.copy_failed'));
    }
  };

  return (
    <div className="manual-command">
      <p className="field-hint">{t('agent.manual_update_desc')}</p>
      {installCode?.insecure && (
        <div className="callout callout--warning" role="note">
          <AlertTriangle size={16} className="callout__icon" aria-hidden="true" />
          <div className="callout__body">
            <p>
              <strong>{t('agent.insecure_install_title')}:</strong> {t('agent.insecure_install_warning')}
            </p>
            {needsOptIn ? (
              <label className="agent-detail__check">
                <input type="checkbox" checked={insecureOptIn} onChange={(e) => setInsecureOptIn(e.target.checked)} />
                {t('agent.insecure_install_opt_in')}
              </label>
            ) : (
              <p>{t('agent.insecure_install_allowed')}</p>
            )}
          </div>
        </div>
      )}
      <div className="manual-command__box">
        <code className="manual-command__code">
          {installCode ? command : t(failed ? 'agent.install_code_failed' : 'common.loading')}
        </code>
        <button type="button" className="btn btn-secondary btn-sm" onClick={handleCopy} disabled={!installCode}>
          <Copy size={14} aria-hidden="true" /> {t('common.copy')}
        </button>
      </div>
      <div className="manual-command__meta">
        <span>
          {installCode && t('agent.install_code_hint', {
            time: installCode.expiresAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          })}
        </span>
        <button type="button" className="manual-command__renew" onClick={() => setRequest((n) => n + 1)}>
          <RefreshCw size={12} aria-hidden="true" /> {t('agent.install_code_retry')}
        </button>
      </div>
    </div>
  );
}
