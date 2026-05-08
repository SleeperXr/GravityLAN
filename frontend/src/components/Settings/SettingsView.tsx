import { useState, useEffect } from 'react';
import { api } from '../../api/client';
import type { DeviceGroup } from '../../types';
import { 
  Palette, Grid, Trash2, Plus, Save, AlertTriangle, Database, Activity, Globe, Check, Download, Upload
} from 'lucide-react';

import { Sidebar } from '../Sidebar';
import { useTranslation } from 'react-i18next';
import { MobileHeader } from '../MobileHeader';

export function SettingsView() {
  const { t, i18n } = useTranslation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [groups, setGroups] = useState<DeviceGroup[]>([]);
  const [newGroupName, setNewGroupName] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    loadGroups();
    loadSettings();
  }, []);

  const [scanInterval, setScanInterval] = useState('0');
  const [quickScanInterval, setQuickScanInterval] = useState('300');
  const [scanSubnets, setScanSubnets] = useState('');
  const [retentionDays, setRetentionDays] = useState('7');
  const [dnsServer, setDnsServer] = useState('');
  const [serverUrlOverride, setServerUrlOverride] = useState('');
  const [logLevel, setLogLevel] = useState('info');
  const [scanTimeout, setScanTimeout] = useState('1.5');

  const loadSettings = async () => {
    try {
      const settings = await api.getSettings();
      if (settings.scan_interval) setScanInterval(settings.scan_interval);
      if (settings.quick_scan_interval) setQuickScanInterval(settings.quick_scan_interval);
      if (settings.scan_subnets) setScanSubnets(settings.scan_subnets);
      if (settings.history_retention_days) setRetentionDays(settings.history_retention_days);
      if (settings['dns.server']) setDnsServer(settings['dns.server']);
      if (settings['server_url_override']) setServerUrlOverride(settings['server_url_override']);
      if (settings['system.log_level']) setLogLevel(settings['system.log_level']);
      if (settings['scan_timeout']) setScanTimeout(settings['scan_timeout']);
    } catch (err) {
      console.error('Failed to load settings:', err);
    }
  };

  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const handleSaveSettings = async () => {
    setSaveStatus('saving');
    try {
      await api.updateSettings({
        scan_interval: scanInterval,
        quick_scan_interval: quickScanInterval,
        scan_subnets: scanSubnets,
        history_retention_days: retentionDays,
        'dns.server': dnsServer,
        'server_url_override': serverUrlOverride,
        'system.log_level': logLevel,
        'scan_timeout': scanTimeout
      });
      setSaveStatus('saved');
      await loadSettings();
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch (err) {
      console.error('Save failed:', err);
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 5000);
    }
  };

  const loadGroups = async () => {
    const data = await api.getGroups();
    setGroups(data);
  };

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    await api.createGroup({ name: newGroupName, icon: 'folder' });
    setNewGroupName('');
    loadGroups();
  };

  const handleDeleteGroup = async (id: number) => {
    if (!confirm(t('settings.delete_group_confirm'))) return;
    await api.deleteGroup(id);
    loadGroups();
  };

  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const data = await api.exportBackup();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `gravitylan_backup_${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Export fehlgeschlagen: ' + err);
    } finally {
      setIsExporting(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!confirm('Bist du sicher? Alle bestehenden Daten werden überschrieben!')) {
      e.target.value = '';
      return;
    }

    setIsImporting(true);
    try {
      await api.importBackup(file);
      alert('Backup erfolgreich importiert! Die Seite wird neu geladen.');
      window.location.reload();
    } catch (err) {
      console.error('Import failed:', err);
      alert('Import fehlgeschlagen: ' + err);
    } finally {
      setIsImporting(false);
      e.target.value = '';
    }
  };

  const [resetConfirm, setResetConfirm] = useState(false);
  const handleResetDB = async () => {
    console.log('Reset DB triggered. Current confirm state:', resetConfirm);
    
    if (!resetConfirm) {
      setResetConfirm(true);
      setTimeout(() => setResetConfirm(false), 5000); // Reset after 5s
      return;
    }

    try {
      console.log('Sending reset request to backend...');
      await api.resetDatabase();
      alert('Datenbank erfolgreich zurückgesetzt');
      window.location.reload();
    } catch (err) {
      console.error('Reset failed:', err);
      alert('Reset fehlgeschlagen: ' + err);
    }
  };

  return (
    <div className="app-layout">
      <Sidebar active="settings" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      <main className="app-main">
        <MobileHeader title={t('settings.title')} onMenuClick={() => setIsSidebarOpen(true)} />
        <div style={{ maxWidth: 800, margin: '0 auto', width: '100%' }}>
          <h1 style={{ marginBottom: 'var(--space-xl)' }}>{t('settings.title')}</h1>

        {/* Group Management */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
            <Grid size={24} className="text-accent" />
            <h2 style={{ margin: 0 }}>{t('settings.manage_groups')}</h2>
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-lg)' }}>
            <input
              className="input"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              placeholder={t('settings.new_group_name')}
            />
            <button className="btn btn-primary" onClick={handleCreateGroup}>
              <Plus size={16} /> {t('settings.create')}
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {groups.map(group => (
              <div key={group.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: 'var(--space-sm) var(--space-md)', background: 'var(--bg-input)',
                borderRadius: 'var(--radius-md)'
              }}>
                <span>{group.name}</span>
                {!group.is_default && (
                  <button className="btn-icon" onClick={() => handleDeleteGroup(group.id)}>
                    <Trash2 size={16} color="var(--accent-danger)" />
                  </button>
                )}
                {group.is_default && <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>{t('settings.standard')}</span>}
              </div>
            ))}
          </div>
        </section>

        {/* Scan Settings */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-lg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
              <Activity size={24} className="text-accent" />
              <h2 style={{ margin: 0 }}>{t('settings.auto_scan')}</h2>
            </div>
            <button 
              className={`btn ${saveStatus === 'saved' ? 'btn-success' : 'btn-primary'}`} 
              onClick={handleSaveSettings} 
              disabled={saveStatus === 'saving'}
            >
              {saveStatus === 'saving' ? <Activity size={16} className="animate-spin" /> : 
               saveStatus === 'saved' ? <Check size={16} /> : 
               <Save size={16} />}
              {saveStatus === 'saving' ? ` ${t('common.saving')}` : 
               saveStatus === 'saved' ? ` ${t('settings.save_success')}` : 
               saveStatus === 'error' ? ` ${t('settings.save_error')}` : ` ${t('common.save')}`}
            </button>
          </div>

          <div className="form-group" style={{ marginBottom: 'var(--space-lg)' }}>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              {t('settings.scan_interval')}
            </label>
            <input
              type="number"
              className="input"
              value={scanInterval}
              onChange={(e) => setScanInterval(e.target.value)}
              placeholder="e.g. 15 (0 to disable)"
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.scan_interval_hint')}
            </p>
          </div>
          
          <div className="form-group" style={{ marginBottom: 'var(--space-lg)' }}>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              {t('settings.quick_scan')}
            </label>
            <input
              type="number"
              className="input"
              value={quickScanInterval}
              onChange={(e) => setQuickScanInterval(e.target.value)}
              placeholder="e.g. 300 (0 to disable)"
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.quick_scan_hint')}
            </p>
          </div>

          <div className="form-group">
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              {t('settings.subnets')}
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <Globe size={18} color="var(--text-tertiary)" />
              <input
                className="input"
                value={scanSubnets}
                onChange={(e) => setScanSubnets(e.target.value)}
                placeholder="e.g. 192.168.1.0/24, 10.0.0.0/24"
              />
            </div>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.subnets_hint')}
            </p>
          </div>

          <div className="form-group" style={{ marginTop: 'var(--space-lg)' }}>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              {t('settings.retention')}
            </label>
            <input
              type="number"
              className="input"
              value={retentionDays}
              onChange={(e) => setRetentionDays(e.target.value)}
              placeholder="e.g. 7 (0 for unlimited)"
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.retention_hint')}
            </p>
          </div>

          <div className="form-group" style={{ marginTop: 'var(--space-lg)' }}>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              Custom DNS Server
            </label>
            <input
              type="text"
              className="input"
              value={dnsServer}
              onChange={(e) => setDnsServer(e.target.value)}
              placeholder="e.g. 192.168.100.1"
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              If set, the scanner will use this server to resolve hostnames instead of the system default.
            </p>
          </div>

          <div className="form-group" style={{ marginTop: 'var(--space-lg)' }}>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              Scanner Timeout (Sekunden)
            </label>
            <input
              type="number"
              step="0.1"
              className="input"
              value={scanTimeout}
              onChange={(e) => setScanTimeout(e.target.value)}
              placeholder="z.B. 1.5"
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              Erhöhe diesen Wert (z.B. auf 2.0), falls Geräte im Deep-Sleep nicht erkannt werden.
            </p>
          </div>
        </section>

        {/* System Logs */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-lg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
              <Activity size={24} className="text-accent" />
              <h2 style={{ margin: 0 }}>System-Logging</h2>
            </div>
            <button className="btn btn-primary" onClick={handleSaveSettings}>
              <Save size={16} /> {t('common.save')}
            </button>
          </div>
          
          <div className="form-group">
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              Log-Level
            </label>
            <select 
              className="input" 
              value={logLevel} 
              onChange={(e) => setLogLevel(e.target.value)}
              style={{ maxWidth: '300px' }}
            >
              <option value="info">INFO (Standard)</option>
              <option value="warning">WARNING (Nur Fehler/Warnungen)</option>
              <option value="debug">DEBUG (Ausführlich)</option>
              <option value="debug_sql">DEBUG + SQL (Vollständige Datenbank-Logs)</option>
            </select>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              Hinweis: SQL-Logs verlangsamen das System und machen die Logs sehr unübersichtlich.
            </p>
          </div>
        </section>

        {/* Live Logs Button */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
              <Activity size={24} className="text-secondary" />
              <div>
                <h2 style={{ margin: 0 }}>System Live-Logs</h2>
                <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--text-tertiary)' }}>
                  Echtzeit-Ansicht der Backend-Vorgänge (Fehlersuche & Monitoring)
                </p>
              </div>
            </div>
            <button 
              className="btn btn-secondary" 
              onClick={() => window.open('/logs', 'GravityLogs', 'width=1000,height=700')}
            >
              <Plus size={16} /> Logs öffnen
            </button>
          </div>
        </section>

        {/* Appearance (Language) */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
            <Palette size={24} className="text-accent" />
            <h2 style={{ margin: 0 }}>{t('settings.language')}</h2>
          </div>
          
          <div className="form-group">
            <select 
              className="input" 
              value={i18n.resolvedLanguage || 'en'} 
              onChange={(e) => i18n.changeLanguage(e.target.value)}
              style={{ maxWidth: '300px' }}
            >
              <option value="de">{t('settings.language_de')}</option>
              <option value="en">{t('settings.language_en')}</option>
            </select>
          </div>
        </section>

        {/* Backup & Restore */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
            <Database size={24} className="text-accent" />
            <h2 style={{ margin: 0 }}>Backup & Restore</h2>
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-lg)' }}>
            <div className="form-group">
              <h4 style={{ marginBottom: 'var(--space-xs)' }}>Export</h4>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
                Sichere alle Geräte, Gruppen und Einstellungen in einer JSON-Datei.
              </p>
              <button className="btn btn-secondary" onClick={handleExport} disabled={isExporting}>
                <Download size={16} /> {isExporting ? 'Exportiere...' : 'Backup herunterladen'}
              </button>
            </div>
            
            <div className="form-group">
              <h4 style={{ marginBottom: 'var(--space-xs)' }}>Import</h4>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
                Stelle Daten aus einer Backup-Datei wieder her. Bestehende Daten werden überschrieben!
              </p>
              <label className="btn btn-outline" style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                <Upload size={16} /> 
                {isImporting ? 'Importiere...' : 'Datei auswählen & Importieren'}
                <input 
                  type="file" 
                  accept=".json" 
                  style={{ display: 'none' }} 
                  onChange={handleImport}
                  disabled={isImporting}
                />
              </label>
            </div>
          </div>
        </section>

        {/* Danger Zone */}
        <section className="card" style={{ borderColor: 'var(--accent-danger)', background: 'rgba(239, 68, 68, 0.02)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)', color: 'var(--accent-danger)' }}>
            <AlertTriangle size={24} />
            <h2 style={{ margin: 0 }}>{t('settings.danger_zone')}</h2>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h4 style={{ marginBottom: 4 }}>{t('settings.reset_db')}</h4>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                {t('settings.reset_warning')}
              </p>
            </div>
            <button 
              className={`btn ${resetConfirm ? 'btn-danger animate-pulse' : 'btn-danger'}`} 
              onClick={handleResetDB}
              style={resetConfirm ? { background: '#ef4444', color: 'white' } : {}}
            >
              <Database size={16} /> 
              {resetConfirm ? 'JETZT WIRKLICH LÖSCHEN?' : t('settings.confirm_reset')}
            </button>
          </div>
        </section>
        </div>
      </main>
    </div>
  );
}
