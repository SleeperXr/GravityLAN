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
  const [scanMode, setScanMode] = useState<'gentle' | 'fast'>('fast');
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
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
      message: 'Initializing scan...',
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
    try {
      await api.completeSetup({ dns_server: dnsServer || undefined });
      
      // Give the backend a moment to stabilize after the setup transaction
      await new Promise(resolve => setTimeout(resolve, 1500));

      console.log('Setup complete, triggering initial full refresh of all devices...');
      try {
        await api.refreshAllDevices();
      } catch (e) {
        console.warn('Initial refresh trigger failed, but setup is complete:', e);
      }
      
      onComplete();
      navigate('/', { replace: true });
    } catch (err) {
      console.error('Final setup step failed:', err);
      onComplete(); // Still complete so user can enter dashboard
      navigate('/', { replace: true });
    }
  }, [onComplete, dnsServer]);

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
        <h1 className="setup-wizard__title">Willkommen bei HomeLan</h1>
        <p className="setup-wizard__subtitle">
          Deine Zentrale für das Heimnetzwerk. Lass uns dein Netzwerk erkunden.
        </p>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-md)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
          <Search size={24} color="var(--accent-primary)" />
          <div>
            <strong>Automatische Erkennung</strong>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
              Server, Firewalls, NAS und Web-Interfaces werden automatisch erkannt.
            </p>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-xl)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
          <Wifi size={24} color="var(--accent-secondary)" />
          <div>
            <strong>Direkter Zugriff</strong>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
              Ein Klick auf RDP, SSH, Web-UI oder SMB — direkt aus dem Dashboard.
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
      <h2 className="setup-wizard__title">Netzwerke auswählen</h2>
      <p className="setup-wizard__subtitle">
        Wähle die Subnetze, die gescannt werden sollen.
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
          <div style={{ fontWeight: 600 }}>Namensauflösung (DNS)</div>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
          Optional: Gib einen DNS-Server für bessere interne Namensauflösung an (z.B. Pi-hole oder lokaler DNS).
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
        Scan starten <ChevronRight size={18} />
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
        <button className="btn btn-primary btn-lg" style={{ width: '100%' }} onClick={finishSetup}>
          <Check size={18} /> {t('sidebar.dashboard')}
        </button>
      )}

      {scanProgress?.status === 'running' && (
        <button className="btn btn-secondary" style={{ width: '100%' }} onClick={() => api.stopScan()}>
          {t('setup.abort_scan')}
        </button>
      )}
    </div>,
  ];

  return (
    <div className="setup-wizard">
      {steps[step]}
    </div>
  );
}
