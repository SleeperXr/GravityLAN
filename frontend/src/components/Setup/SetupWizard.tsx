import { useState, useEffect, useCallback, useRef, type FormEvent, type ReactNode } from 'react';
import { api, createScanSocket } from '../../api/client';
import type { SubnetInfo, ScanProgress } from '../../types';
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Info, Loader2, Network, Search, Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { LanguageToggle } from '../LanguageToggle';

interface SetupWizardProps {
  onComplete: () => void;
}

const STEP_KEYS = ['step_welcome', 'step_networks', 'step_scan', 'step_security'] as const;
const SCAN_STEP = 2;
const SECURITY_STEP = 3;

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err));
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Page frame: text logo and language switch above a centered panel. */
function SetupShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="setup-shell">
      <header className="setup-shell__header">
        <div className="sidebar-brand setup-shell__brand">
          <span className="sidebar-brand__name">{t('app.title')}</span>
          <span className="setup-shell__tag">{t('setup.first_run')}</span>
        </div>
        <LanguageToggle />
      </header>
      <main className="setup-panel">{children}</main>
    </div>
  );
}

/** `skipped`: a passed step that did not complete (scan skipped or failed), shown without a check. */
function Stepper({ current, skipped }: { current: number; skipped?: number }) {
  const { t } = useTranslation();
  return (
    <ol className="setup-stepper" aria-label={t('setup.steps_label')}>
      {STEP_KEYS.map((key, index) => {
        const state = index === skipped && index < current ? 'skipped'
          : index < current ? 'done'
          : index === current ? 'current'
          : 'todo';
        return (
          <li key={key} className={`setup-stepper__item is-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="setup-stepper__dot" aria-hidden="true">
              {state === 'done' ? <Check size={12} strokeWidth={3} /> : state === 'skipped' ? '–' : index + 1}
            </span>
            <span className="setup-stepper__label">{t(`setup.${key}`)}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [subnets, setSubnets] = useState<SubnetInfo[]>([]);
  const [subnetsLoading, setSubnetsLoading] = useState(true);
  const [subnetError, setSubnetError] = useState<string | null>(null);
  const [selectedSubnets, setSelectedSubnets] = useState<string[]>([]);
  const [dnsServer, setDnsServer] = useState('');
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishProgress, setFinishProgress] = useState(0);
  const [finishStatus, setFinishStatus] = useState('');
  const [adminPassword, setAdminPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [finishError, setFinishError] = useState<string | null>(null);

  const scanSocketRef = useRef<WebSocket | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const isFirstStep = useRef(true);

  useEffect(() => {
    api.getSubnets()
      .then((data) => {
        setSubnets(data);
        // Auto-select all detected subnets
        setSelectedSubnets(data.map((s) => s.subnet));
      })
      .catch((err) => setSubnetError(errorText(err)))
      .finally(() => setSubnetsLoading(false));
  }, []);

  // Close the progress socket if the wizard unmounts mid-scan
  useEffect(() => () => scanSocketRef.current?.close(), []);

  // Move focus to the new step's heading so keyboard and screen-reader users follow along
  useEffect(() => {
    if (isFirstStep.current) {
      isFirstStep.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  const toggleSubnet = useCallback((subnet: string) => {
    setSelectedSubnets((prev) =>
      prev.includes(subnet) ? prev.filter((s) => s !== subnet) : [...prev, subnet]
    );
  }, []);

  const startScan = useCallback(async () => {
    if (selectedSubnets.length === 0) return;

    setStep(SCAN_STEP);
    setScanProgress({
      status: 'running',
      current_subnet: '',
      hosts_scanned: 0,
      hosts_total: 0,
      devices_found: 0,
      message: '',
      timestamp: new Date().toISOString(),
    });

    // Live progress over WebSocket
    scanSocketRef.current?.close();
    const ws = createScanSocket((progress) => {
      setScanProgress(progress);
      if (progress.status === 'completed' || progress.status === 'failed' || progress.status === 'cancelled') {
        ws.close();
      }
    });
    scanSocketRef.current = ws;

    try {
      await api.startScan({ subnets: selectedSubnets, mode: 'fast', dns_server: dnsServer || undefined });
    } catch (err) {
      ws.close();
      setScanProgress((prev) => prev && { ...prev, status: 'failed', message: errorText(err) });
    }
  }, [selectedSubnets, dnsServer]);

  const abortScan = async () => {
    try {
      await api.stopScan();
    } catch (err) {
      console.warn('Stopping the scan failed:', err);
    }
    scanSocketRef.current?.close();
    setScanProgress((prev) => (prev && prev.status === 'running' ? { ...prev, status: 'cancelled' } : prev));
  };

  const passwordsMismatch = adminPassword !== '' && confirmPassword !== '' && adminPassword !== confirmPassword;
  const canFinish = adminPassword !== '' && adminPassword === confirmPassword;

  const finishSetup = async (e: FormEvent) => {
    e.preventDefault();
    if (!canFinish) return;

    setFinishError(null);
    setIsFinishing(true);
    setFinishProgress(10);
    setFinishStatus(t('setup.saving_configuration'));

    try {
      await api.completeSetup({
        dns_server: dnsServer || undefined,
        admin_password: adminPassword,
      });
    } catch (err) {
      console.error('Final setup step failed:', err);
      // Stay in the wizard: without the saved password the dashboard can't be used
      setIsFinishing(false);
      setFinishError(errorText(err));
      return;
    }

    // Completing setup opens no session: sign in with the new password so the wizard ends in
    // the dashboard (not the login screen) and the initial refresh below is authorised
    try {
      await api.login(adminPassword);
    } catch (err) {
      console.warn('Automatic sign-in after setup failed, the login screen will ask:', err);
    }

    setFinishProgress(40);
    setFinishStatus(t('setup.stabilizing_backend'));
    await wait(1500);

    setFinishProgress(65);
    setFinishStatus(t('setup.scanning_network'));
    try {
      await api.refreshAllDevices();
    } catch (err) {
      console.warn('Initial refresh trigger failed, but setup is complete:', err);
    }

    setFinishProgress(90);
    setFinishStatus(t('setup.almost_done'));
    await wait(600);

    setFinishProgress(100);
    setFinishStatus(t('setup.welcome_done'));
    await wait(500);

    onComplete();
    navigate('/', { replace: true });
  };

  const heading = (text: string) => (
    <h1 className="setup-step__title" id="setup-step-title" ref={headingRef} tabIndex={-1}>{text}</h1>
  );

  const renderWelcome = () => (
    <div className="setup-step">
      {heading(t('setup.welcome_title'))}
      <p className="setup-step__lead">{t('setup.welcome_description')}</p>

      <ul className="setup-features">
        <li>
          <span className="setup-features__icon" aria-hidden="true"><Search size={18} /></span>
          <div>
            <strong>{t('setup.auto_detection')}</strong>
            <p>{t('setup.auto_detection_desc')}</p>
          </div>
        </li>
        <li>
          <span className="setup-features__icon" aria-hidden="true"><Zap size={18} /></span>
          <div>
            <strong>{t('setup.direct_access')}</strong>
            <p>{t('setup.direct_access_desc')}</p>
          </div>
        </li>
      </ul>

      <div className="setup-actions">
        <button type="button" className="btn btn-primary" onClick={() => setStep(1)}>
          {t('common.next')} <ChevronRight size={18} aria-hidden="true" />
        </button>
      </div>
    </div>
  );

  const renderNetworks = () => (
    <div className="setup-step">
      {heading(t('setup.select_networks_title'))}
      <p className="setup-step__lead">{t('setup.select_networks_desc')}</p>

      {subnetError && (
        <div className="callout callout--danger" role="alert">
          <AlertTriangle size={16} className="callout__icon" aria-hidden="true" />
          <p className="callout__body">{t('setup.networks_failed', { error: subnetError })}</p>
        </div>
      )}

      {subnetsLoading ? (
        <p className="setup-loading" role="status">
          <Loader2 size={16} className="animate-spin" aria-hidden="true" /> {t('setup.detecting_networks')}
        </p>
      ) : subnets.length === 0 ? (
        !subnetError && <p className="settings-empty">{t('setup.no_networks')}</p>
      ) : (
        <div className="setup-choices" role="group" aria-labelledby="setup-step-title">
          {subnets.map((subnet) => {
            const checked = selectedSubnets.includes(subnet.subnet);
            return (
              <label key={subnet.subnet} className={`setup-choice${checked ? ' is-selected' : ''}`}>
                <input type="checkbox" checked={checked} onChange={() => toggleSubnet(subnet.subnet)} />
                <Network size={18} className="setup-choice__icon" aria-hidden="true" />
                <span className="setup-choice__text">
                  <span className="setup-choice__title">{subnet.subnet}</span>
                  <span className="setup-choice__meta">{subnet.interface_name} · {subnet.ip_address}</span>
                </span>
              </label>
            );
          })}
        </div>
      )}

      <div className="settings-field">
        <label className="form-label" htmlFor="setup-dns">{t('setup.dns_label')}</label>
        <input
          id="setup-dns"
          className="input input--mono"
          placeholder="192.168.1.1"
          value={dnsServer}
          onChange={(e) => setDnsServer(e.target.value)}
          aria-describedby="setup-dns-hint"
        />
        <p className="field-hint" id="setup-dns-hint">{t('setup.dns_desc')}</p>
      </div>

      <div className="setup-actions">
        <button type="button" className="btn btn-secondary" onClick={() => setStep(0)}>
          <ChevronLeft size={18} aria-hidden="true" /> {t('common.back')}
        </button>
        {!subnetsLoading && selectedSubnets.length === 0 ? (
          <button type="button" className="btn btn-primary" onClick={() => setStep(SECURITY_STEP)}>
            {t('setup.skip_scan')} <ChevronRight size={18} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={startScan} disabled={subnetsLoading}>
            {t('dashboard.start_scan')} <ChevronRight size={18} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );

  const renderScan = () => {
    const status = scanProgress?.status ?? 'running';
    const isRunning = status === 'running' || status === 'idle';
    const scanned = scanProgress?.hosts_scanned ?? 0;
    const total = scanProgress?.hosts_total ?? 0;
    const percent = total > 0 ? Math.round((scanned / total) * 100) : null;
    // A scan that failed before checking any host has no numbers worth showing
    const showProgress = isRunning || status === 'completed' || scanned > 0;
    const title =
      status === 'completed' ? t('setup.scan_completed')
      : status === 'failed' ? t('setup.scan_failed')
      : status === 'cancelled' ? t('setup.scan_cancelled')
      : t('setup.scan_in_progress');

    return (
      <div className="setup-step">
        {heading(title)}
        <p className="setup-step__lead" role="status">
          {scanProgress?.message || (isRunning ? t('setup.initializing_scan') : '')}
        </p>

        {showProgress && <div className="setup-scan">
          <div
            className={`progress-bar${percent === null && isRunning ? ' is-indeterminate' : ''}`}
            role="progressbar"
            aria-label={t('setup.scan_progress_label')}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent ?? undefined}
          >
            <div className="progress-bar__fill" style={percent !== null ? { width: `${percent}%` } : undefined} />
          </div>
          <dl className="setup-scan__stats">
            <div>
              <dt>{t('setup.hosts_checked')}</dt>
              <dd>{scanned} / {total}</dd>
            </div>
            <div>
              <dt>{t('setup.devices_label')}</dt>
              <dd className="is-accent">{scanProgress?.devices_found ?? 0}</dd>
            </div>
          </dl>
        </div>}

        {(status === 'failed' || status === 'cancelled') && (
          <div className="callout callout--info">
            <Info size={16} className="callout__icon" aria-hidden="true" />
            <p className="callout__body">{t('setup.scan_later_hint')}</p>
          </div>
        )}

        <div className="setup-actions">
          {isRunning ? (
            <button type="button" className="btn btn-secondary" onClick={abortScan}>
              {t('setup.abort_scan')}
            </button>
          ) : status === 'completed' ? (
            <button type="button" className="btn btn-primary" onClick={() => setStep(SECURITY_STEP)}>
              {t('common.next')} <ChevronRight size={18} aria-hidden="true" />
            </button>
          ) : (
            <>
              <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>
                <ChevronLeft size={18} aria-hidden="true" /> {t('common.back')}
              </button>
              <button type="button" className="btn btn-primary" onClick={() => setStep(SECURITY_STEP)}>
                {t('setup.continue_without_scan')} <ChevronRight size={18} aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </div>
    );
  };

  const renderSecurity = () => (
    <form className="setup-step" onSubmit={finishSetup} noValidate>
      {heading(t('setup.security_title'))}
      <p className="setup-step__lead">{t('setup.security_desc')}</p>

      <div className="settings-field">
        <label className="form-label" htmlFor="setup-password">{t('setup.admin_password')}</label>
        <input
          id="setup-password"
          type="password"
          className="input"
          autoComplete="new-password"
          placeholder={t('setup.password_placeholder')}
          value={adminPassword}
          onChange={(e) => setAdminPassword(e.target.value)}
        />
      </div>
      <div className="settings-field">
        <label className="form-label" htmlFor="setup-password-confirm">{t('setup.confirm_password')}</label>
        <input
          id="setup-password-confirm"
          type="password"
          className={`input${passwordsMismatch ? ' input--error' : ''}`}
          autoComplete="new-password"
          placeholder={t('setup.password_confirm_placeholder')}
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          aria-invalid={passwordsMismatch}
          aria-describedby={passwordsMismatch ? 'setup-password-error' : undefined}
        />
        {passwordsMismatch && (
          <p className="field-error" id="setup-password-error" role="alert">{t('setup.passwords_dont_match')}</p>
        )}
      </div>

      <div className="callout callout--info">
        <Info size={16} className="callout__icon" aria-hidden="true" />
        <p className="callout__body">{t('setup.password_hint')}</p>
      </div>

      {finishError && (
        <div className="callout callout--danger" role="alert">
          <AlertTriangle size={16} className="callout__icon" aria-hidden="true" />
          <p className="callout__body">{t('setup.finish_failed', { error: finishError })}</p>
        </div>
      )}

      <div className="setup-actions">
        <button type="button" className="btn btn-secondary" onClick={() => setStep(scanProgress ? SCAN_STEP : 1)}>
          <ChevronLeft size={18} aria-hidden="true" /> {t('common.back')}
        </button>
        <button type="submit" className="btn btn-primary" disabled={!canFinish}>
          <Check size={18} aria-hidden="true" /> {t('common.finish')}
        </button>
      </div>
    </form>
  );

  if (isFinishing) {
    return (
      <SetupShell>
        <div className="setup-step setup-step--center">
          <span className="setup-finish__icon" aria-hidden="true">
            {finishProgress >= 100 ? <Check size={22} /> : <Loader2 size={22} className="animate-spin" />}
          </span>
          <h1 className="setup-step__title">{t('setup.welcome_title')}</h1>
          <p className="setup-step__lead" role="status">{finishStatus}</p>
          <div
            className="progress-bar"
            role="progressbar"
            aria-label={t('setup.finish_progress_label')}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={finishProgress}
          >
            <div className="progress-bar__fill" style={{ width: `${finishProgress}%` }} />
          </div>
          <p className="setup-finish__percent">{finishProgress}%</p>
        </div>
      </SetupShell>
    );
  }

  const renderers = [renderWelcome, renderNetworks, renderScan, renderSecurity];

  return (
    <SetupShell>
      <Stepper current={step} skipped={scanProgress?.status === 'completed' ? undefined : SCAN_STEP} />
      {renderers[step]()}
    </SetupShell>
  );
}
