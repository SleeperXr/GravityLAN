import { useState, useEffect, useCallback } from 'react';
import { api, createScanSocket } from '../../api/client';
import type { SubnetInfo, ScanProgress } from '../../types';
import { Network, Wifi, Zap, ChevronRight, Check, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

interface SetupWizardProps {
  onComplete: () => void;
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [subnets, setSubnets] = useState<SubnetInfo[]>([]);
  const [selectedSubnets, setSelectedSubnets] = useState<string[]>([]);
  const [dnsServer, setDnsServer] = useState<string>('');
  const scanMode = 'fast' as const;
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishProgress, setFinishProgress] = useState(0);
  const [finishStatus, setFinishStatus] = useState('');
  const [adminPassword, setAdminPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSubnets()
      .then((data) => {
        setSubnets(data);
        // Auto-select all subnets
        setSelectedSubnets(data.map((s) => s.subnet));
      })
      .catch((err) => setError(`Failed to detect networks: ${err.message}`));
  }, []);

  const toggleSubnet = useCallback((subnet: string) => {
    setSelectedSubnets((prev) =>
      prev.includes(subnet) ? prev.filter((s) => s !== subnet) : [...prev, subnet]
    );
  }, []);

  const startScan = useCallback(async () => {
    if (selectedSubnets.length === 0) return;

    setStep(2);
    setScanProgress({
      status: 'running',
      current_subnet: '',
      hosts_scanned: 0,
      hosts_total: 0,
      devices_found: 0,
      message: t('setup.initializing_scan'),
      timestamp: new Date().toISOString(),
    });

    // Connect WebSocket for live updates
    const ws = createScanSocket((progress) => {
      setScanProgress(progress);
      if (progress.status === 'completed' || progress.status === 'failed') {
        ws.close();
      }
    });

    try {
      await api.startScan({ subnets: selectedSubnets, mode: scanMode, dns_server: dnsServer || undefined });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
    }
  }, [selectedSubnets, scanMode, dnsServer]);

  const finishSetup = useCallback(async () => {
    if (adminPassword && adminPassword !== confirmPassword) {
      setError(t('setup.passwords_dont_match', "Passwords don't match!"));
      return;
    }

    setIsFinishing(true);
    setFinishProgress(10);
    setFinishStatus(t('setup.saving_configuration'));

    try {
      await api.completeSetup({
        dns_server: dnsServer || undefined,
        admin_password: adminPassword || undefined,
      });

      setFinishProgress(40);
      setFinishStatus(t('setup.stabilizing_backend'));
      await new Promise(resolve => setTimeout(resolve, 1500));

      setFinishProgress(65);
      setFinishStatus(t('setup.scanning_network'));
      try {
        await api.refreshAllDevices();
      } catch (e) {
        console.warn('Initial refresh trigger failed, but setup is complete:', e);
      }

      setFinishProgress(90);
      setFinishStatus(t('setup.almost_done'));
      await new Promise(resolve => setTimeout(resolve, 600));

      setFinishProgress(100);
      setFinishStatus(t('setup.welcome_done'));
      await new Promise(resolve => setTimeout(resolve, 500));

      onComplete();
      navigate('/', { replace: true });
    } catch (err) {
      console.error('Final setup step failed:', err);
      onComplete();
      navigate('/', { replace: true });
    }
  }, [onComplete, dnsServer, adminPassword, confirmPassword]);

  const steps = [
    // Step 0: Welcome
    <div key="welcome" className="setup-wizard__step">
      <div style={{ textAlign: 'center', marginBottom: 'var(--space-xl)' }}>
        <div style={{
          width: 80, height: 80, borderRadius: 'var(--radius-xl)',
          background: 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto var(--space-lg)', fontSize: '2rem',
        }}>
          🏠
        </div>
        <h1 className="setup-wizard__title">{t('setup.welcome_title')}</h1>
        <p className="setup-wizard__subtitle">
          {t('setup.welcome_description')}
        </p>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-md)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
          <Search size={24} color="var(--accent-primary)" />
          <div>
            <strong>{t('setup.auto_detection')}</strong>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
              {t('setup.auto_detection_desc')}
            </p>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-xl)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
          <Wifi size={24} color="var(--accent-secondary)" />
          <div>
            <strong>{t('setup.direct_access')}</strong>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
              {t('setup.direct_access_desc')}
            </p>
          </div>
        </div>
      </div>

      <button className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={() => setStep(1)}>
        {t('common.next')} <ChevronRight size={18} />
      </button>
    </div>,

    // Step 1: Subnet Selection
    <div key="subnets" className="setup-wizard__step">
      <h2 className="setup-wizard__title">{t('setup.select_networks_title')}</h2>
      <p className="setup-wizard__subtitle">
        {t('setup.select_networks_desc')}
      </p>

      {error && (
        <div style={{
          padding: 'var(--space-md)', background: 'rgba(252, 92, 101, 0.1)',
          border: '1px solid var(--accent-danger)', borderRadius: 'var(--radius-md)',
          color: 'var(--accent-danger)', marginBottom: 'var(--space-md)',
        }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)', marginBottom: 'var(--space-xl)' }}>
        {subnets.map((subnet) => (
          <div
            key={subnet.subnet}
            className={`checkbox-card ${selectedSubnets.includes(subnet.subnet) ? 'selected' : ''}`}
            onClick={() => toggleSubnet(subnet.subnet)}
          >
            <input
              type="checkbox"
              checked={selectedSubnets.includes(subnet.subnet)}
              onChange={() => toggleSubnet(subnet.subnet)}
              style={{ accentColor: 'var(--accent-primary)' }}
            />
            <Network size={20} color="var(--accent-primary)" />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{subnet.subnet}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                {subnet.interface_name} — {subnet.ip_address}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-xl)', border: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
          <Search size={20} color="var(--accent-primary)" />
          <div style={{ fontWeight: 600 }}>{t('setup.dns_title')}</div>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
          {t('setup.dns_desc')}
        </p>
        <input 
          type="text" 
          className="input" 
          placeholder="z.B. 192.168.100.2" 
          value={dnsServer} 
          onChange={(e) => setDnsServer(e.target.value)}
          style={{ width: '100%' }}
        />
      </div>

      <button
        className="btn btn-primary btn-lg"
        style={{ width: '100%' }}
        onClick={startScan}
        disabled={selectedSubnets.length === 0}
      >
        {t('dashboard.start_scan')} <ChevronRight size={18} />
      </button>
    </div>,

    // Step 2: Scan Progress
    <div key="scanning" className="setup-wizard__step">
      <h2 className="setup-wizard__title">
        {scanProgress?.status === 'completed' ? `✅ ${t('setup.scan_completed')}` : `🔍 ${t('setup.scan_in_progress')}`}
      </h2>
      <p className="setup-wizard__subtitle">
        {scanProgress?.message || t('common.loading')}
      </p>

      {/* Progress Bar */}
      {scanProgress && scanProgress.hosts_total > 0 && (
        <div style={{ marginBottom: 'var(--space-xl)' }}>
          <div className="progress-bar">
            <div
              className="progress-bar__fill"
              style={{
                width: `${Math.round((scanProgress.hosts_scanned / scanProgress.hosts_total) * 100)}%`,
              }}
            />
          </div>
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            marginTop: 'var(--space-sm)', fontSize: '0.8rem', color: 'var(--text-secondary)',
          }}>
            <span>{scanProgress.hosts_scanned} / {scanProgress.hosts_total} Hosts</span>
            <span>{t('setup.devices_found', { count: scanProgress.devices_found })}</span>
          </div>
        </div>
      )}

      {/* Devices Found Counter */}
      <div className="card" style={{ textAlign: 'center', marginBottom: 'var(--space-xl)' }}>
        <div style={{ fontSize: '3rem', fontWeight: 700, color: 'var(--accent-primary)' }}>
          {scanProgress?.devices_found || 0}
        </div>
        <div style={{ color: 'var(--text-secondary)' }}>{t('setup.devices_found', { count: scanProgress?.devices_found || 0 })}</div>
      </div>

      {scanProgress?.status === 'completed' && (
        <button className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={() => setStep(3)}>
          {t('common.next')} <ChevronRight size={18} />
        </button>
      )}

      {scanProgress?.status === 'running' && (
        <button className="btn btn-secondary" style={{ width: '100%' }} onClick={() => api.stopScan()}>
          {t('setup.abort_scan')}
        </button>
      )}
    </div>,

    // Step 3: Security Setup
    <div key="security" className="setup-wizard__step">
      <h2 className="setup-wizard__title">{t('setup.security_title')}</h2>
      <p className="setup-wizard__subtitle">
        {t('setup.security_desc')}
      </p>

      {error && (
        <div style={{
          padding: 'var(--space-md)', background: 'rgba(252, 92, 101, 0.1)',
          border: '1px solid var(--accent-danger)', borderRadius: 'var(--radius-md)',
          color: 'var(--accent-danger)', marginBottom: 'var(--space-md)',
        }} onClick={() => setError(null)}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBottom: 'var(--space-xl)', border: '1px solid var(--border-subtle)' }}>
        <div style={{ marginBottom: 'var(--space-md)' }}>
          <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontSize: '0.875rem', fontWeight: 600 }}>
            {t('setup.admin_password')}
          </label>
          <input 
            type="password" 
            className={`input ${adminPassword && confirmPassword && adminPassword !== confirmPassword ? 'input--error' : ''}`}
            placeholder={t('setup.password_placeholder')} 
            value={adminPassword} 
            onChange={(e) => setAdminPassword(e.target.value)}
            style={{ 
              width: '100%',
              borderColor: adminPassword && confirmPassword && adminPassword !== confirmPassword ? 'var(--accent-danger)' : undefined
            }}
          />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontSize: '0.875rem', fontWeight: 600 }}>
            {t('setup.confirm_password')}
          </label>
          <input 
            type="password" 
            className={`input ${adminPassword && confirmPassword && adminPassword !== confirmPassword ? 'input--error' : ''}`}
            placeholder={t('setup.password_confirm_placeholder')} 
            value={confirmPassword} 
            onChange={(e) => setConfirmPassword(e.target.value)}
            style={{ 
              width: '100%',
              borderColor: adminPassword && confirmPassword && adminPassword !== confirmPassword ? 'var(--accent-danger)' : undefined
            }}
          />
          {adminPassword && confirmPassword && adminPassword !== confirmPassword && (
            <p style={{ color: 'var(--accent-danger)', fontSize: '0.75rem', marginTop: 'var(--space-xs)' }}>
              ⚠️ {t('setup.passwords_dont_match')}
            </p>
          )}
        </div>
      </div>

      <div style={{ 
        padding: 'var(--space-md)', 
        background: 'rgba(245, 158, 11, 0.1)', 
        borderRadius: 'var(--radius-md)', 
        color: '#f59e0b',
        fontSize: '0.8rem',
        marginBottom: 'var(--space-xl)',
        display: 'flex',
        gap: 'var(--space-sm)'
      }}>
        <Zap size={16} style={{ flexShrink: 0 }} />
        <p>{t('setup.password_hint')}</p>
      </div>

      <button 
        className="btn btn-primary btn-lg" 
        style={{ width: '100%' }} 
        onClick={finishSetup}
        disabled={!adminPassword || adminPassword !== confirmPassword}
      >
        <Check size={18} /> {t('common.finish')}
      </button>
    </div>,
  ];

  if (isFinishing) {
    return (
      <div className="setup-wizard" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="setup-wizard__step" style={{ textAlign: 'center' }}>
          <div style={{
            width: 80, height: 80, borderRadius: 'var(--radius-xl)',
            background: 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto var(--space-lg)', fontSize: '2rem',
            animation: 'pulse 1.5s ease-in-out infinite',
          }}>
            🚀
          </div>
          <h2 className="setup-wizard__title">{t('setup.welcome_title')}</h2>
          <p className="setup-wizard__subtitle" style={{ minHeight: '1.5rem' }}>
            {finishStatus}
          </p>

          {/* Progress Bar */}
          <div style={{
            width: '100%', height: 8, background: 'var(--bg-input)',
            borderRadius: 'var(--radius-full)', overflow: 'hidden',
            margin: 'var(--space-xl) 0 var(--space-md)',
          }}>
            <div style={{
              height: '100%',
              width: `${finishProgress}%`,
              background: 'linear-gradient(90deg, var(--accent-primary), var(--accent-secondary))',
              borderRadius: 'var(--radius-full)',
              transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
              boxShadow: '0 0 12px var(--accent-primary)',
            }} />
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', fontVariantNumeric: 'tabular-nums' }}>
            {finishProgress}%
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="setup-wizard">
      {steps[step]}
    </div>
  );
}
