import { useState, useEffect } from 'react';
import { api } from '../../api/client';
import type { DeviceGroup } from '../../types';
import { 
  Palette, Grid, Trash2, Plus, Save, AlertTriangle, Database, Activity, Globe, Check, Download, Upload, Key
} from 'lucide-react';

import { Sidebar } from '../Sidebar';
import { useTranslation } from 'react-i18next';
import { MobileHeader } from '../MobileHeader';

export function SettingsView() {
  const { t, i18n } = useTranslation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [groups, setGroups] = useState<DeviceGroup[]>([]);
  const [newGroupName, setNewGroupName] = useState('');
  const [tokens, setTokens] = useState<any[]>([]);
  const [newTokenName, setNewTokenName] = useState('');
  const [createdToken, setCreatedToken] = useState('');
  const [isCreatingToken, setIsCreatingToken] = useState(false);

  useEffect(() => {
    loadGroups();
    loadSettings();
    loadTokens();
  }, []);

  const loadTokens = async () => {
    try {
      const data = await api.getApiTokens();
      setTokens(data);
    } catch (err) {
      console.error('Failed to load API tokens:', err);
    }
  };

  const handleCreateToken = async () => {
    if (!newTokenName.trim()) return;
    setIsCreatingToken(true);
    setCreatedToken('');
    try {
      const res = await api.createApiToken(newTokenName);
      setCreatedToken(res.token);
      setNewTokenName('');
      loadTokens();
    } catch (err) {
      console.error('Failed to create token:', err);
      alert('Failed to generate token: ' + err);
    } finally {
      setIsCreatingToken(false);
    }
  };

  const handleDeleteToken = async (id: number) => {
    if (!confirm(t('settings.delete_token_confirm'))) return;
    try {
      await api.deleteApiToken(id);
      loadTokens();
    } catch (err) {
      console.error('Failed to delete token:', err);
      alert('Failed to revoke token: ' + err);
    }
  };

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
      alert(t('settings.export_failed') + err);
    } finally {
      setIsExporting(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!confirm(t('settings.import_confirm_warning'))) {
      e.target.value = '';
      return;
    }

    setIsImporting(true);
    try {
      await api.importBackup(file);
      alert(t('settings.import_success'));
      window.location.reload();
    } catch (err) {
      console.error('Import failed:', err);
      alert(t('settings.import_failed') + err);
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
      alert(t('settings.reset_success'));
      window.location.reload();
    } catch (err) {
      console.error('Reset failed:', err);
      alert(t('settings.reset_failed') + ': ' + err);
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
              {t('settings.dns_custom_title', 'Custom DNS Server')}
            </label>
            <input
              type="text"
              className="input"
              value={dnsServer}
              onChange={(e) => setDnsServer(e.target.value)}
              placeholder="e.g. 192.168.100.1"
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.dns_custom_desc')}
            </p>
          </div>

          <div className="form-group" style={{ marginTop: 'var(--space-lg)' }}>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              {t('settings.scan_timeout')}
            </label>
            <input
              type="number"
              step="0.1"
              className="input"
              value={scanTimeout}
              onChange={(e) => setScanTimeout(e.target.value)}
              placeholder={t('settings.scan_timeout_placeholder', 'e.g. 1.5')}
            />
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.scan_timeout_desc')}
            </p>
          </div>
        </section>

        {/* System Logs */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-lg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
              <Activity size={24} className="text-accent" />
              <h2 style={{ margin: 0 }}>{t('settings.system_logging')}</h2>
            </div>
            <button className="btn btn-primary" onClick={handleSaveSettings}>
              <Save size={16} /> {t('common.save')}
            </button>
          </div>
          
          <div className="form-group">
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
              {t('settings.log_level')}
            </label>
            <select 
              className="input" 
              value={logLevel} 
              onChange={(e) => setLogLevel(e.target.value)}
              style={{ maxWidth: '300px' }}
            >
              <option value="info">{t('settings.log_level_info')}</option>
              <option value="warning">{t('settings.log_level_warning')}</option>
              <option value="debug">{t('settings.log_level_debug')}</option>
              <option value="debug_sql">{t('settings.log_level_sql')}</option>
            </select>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
              {t('settings.log_level_desc')}
            </p>
          </div>
        </section>

        {/* Live Logs Button */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
              <Activity size={24} className="text-secondary" />
              <div>
                <h2 style={{ margin: 0 }}>{t('settings.system_livelogs')}</h2>
                <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--text-tertiary)' }}>
                  {t('settings.system_livelogs_desc')}
                </p>
              </div>
            </div>
            <button 
              className="btn btn-secondary" 
              onClick={() => window.open('/logs', 'GravityLogs', 'width=1000,height=700')}
            >
              <Plus size={16} /> {t('settings.system_livelogs_open')}
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
            <h2 style={{ margin: 0 }}>{t('settings.backup_restore')}</h2>
          </div>

          <div style={{ 
            display: 'flex', gap: 'var(--space-md)', padding: 'var(--space-md)', 
            background: 'rgba(234, 179, 8, 0.1)', borderRadius: 'var(--radius-md)',
            border: '1px solid rgba(234, 179, 8, 0.2)', marginBottom: 'var(--space-lg)'
          }}>
            <AlertTriangle size={20} style={{ color: '#eab308', flexShrink: 0 }} />
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', margin: 0 }}>
              <strong style={{ color: '#eab308' }}>{t('settings.security_notice_title')}:</strong> {t('settings.security_notice_desc')}
            </p>
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-lg)' }}>
            <div className="form-group">
              <h4 style={{ marginBottom: 'var(--space-xs)' }}>{t('settings.backup_export')}</h4>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
                {t('settings.backup_export_desc')}
              </p>
              <button className="btn btn-secondary" onClick={handleExport} disabled={isExporting}>
                <Download size={16} /> {isExporting ? t('settings.backup_exporting') : t('settings.backup_download')}
              </button>
            </div>
            
            <div className="form-group">
              <h4 style={{ marginBottom: 'var(--space-xs)' }}>{t('settings.backup_import')}</h4>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
                {t('settings.backup_import_desc')}
              </p>
              <label className="btn btn-outline" style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                <Upload size={16} /> 
                {isImporting ? t('settings.backup_importing') : t('settings.backup_select_file')}
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

        {/* API Tokens */}
        <section className="card" style={{ marginBottom: 'var(--space-xl)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
            <Key size={24} className="text-accent" />
            <h2 style={{ margin: 0 }}>{t('settings.api_tokens')}</h2>
          </div>
          
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
            {t('settings.api_tokens_desc')}
          </p>

          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-lg)' }}>
            <input
              className="input"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              placeholder={t('settings.new_token_placeholder')}
              disabled={isCreatingToken}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreateToken();
              }}
            />
            <button className="btn btn-primary" onClick={handleCreateToken} disabled={isCreatingToken || !newTokenName.trim()}>
              <Plus size={16} /> {t('settings.token_create')}
            </button>
          </div>

          {createdToken && (
            <div style={{
              padding: 'var(--space-md)',
              background: 'rgba(34, 197, 94, 0.1)',
              border: '1px solid rgba(34, 197, 94, 0.3)',
              borderRadius: 'var(--radius-md)',
              marginBottom: 'var(--space-lg)'
            }}>
              <p style={{ margin: '0 0 var(--space-xs) 0', fontSize: '0.875rem', color: '#4ade80', fontWeight: 600 }}>
                {t('settings.token_created_title')}
              </p>
              <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
                <input
                  type="text"
                  readOnly
                  className="input"
                  value={createdToken}
                  style={{ fontFamily: 'monospace', flexGrow: 1 }}
                  onClick={(e) => (e.target as HTMLInputElement).select()}
                />
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    navigator.clipboard.writeText(createdToken);
                    alert(t('notifications.copied'));
                  }}
                >
                  {t('settings.token_copy')}
                </button>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {tokens.length === 0 ? (
              <p style={{ fontSize: '0.875rem', color: 'var(--text-tertiary)', margin: 0 }}>
                {t('settings.no_tokens')}
              </p>
            ) : (
              tokens.map(token => (
                <div key={token.id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: 'var(--space-sm) var(--space-md)', background: 'var(--bg-input)',
                  borderRadius: 'var(--radius-md)'
                }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    <span style={{ fontWeight: 600 }}>{token.name}</span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', fontFamily: 'monospace' }}>
                      {token.prefix} • {t('settings.token_created')}: {new Date(token.created_at).toLocaleDateString()}
                      {token.last_used_at && ` • ${t('settings.token_used')}: ${new Date(token.last_used_at).toLocaleString()}`}
                    </span>
                  </div>
                  <button className="btn-icon" onClick={() => handleDeleteToken(token.id)}>
                    <Trash2 size={16} color="var(--accent-danger)" />
                  </button>
                </div>
              ))
            )}
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
              {resetConfirm ? t('settings.reset_really') : t('settings.confirm_reset')}
            </button>
          </div>
        </section>
        </div>
      </main>
    </div>
  );
}
