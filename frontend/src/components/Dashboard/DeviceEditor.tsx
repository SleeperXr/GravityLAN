import { useState, useEffect } from 'react';
import type { Device, DeviceGroup } from '../../types';
import { api } from '../../api/client';
import { X, Save, Trash2, Tag, Layout, Folder, Settings, RefreshCw, Cpu, Globe, Lock, Terminal, Monitor, Activity, ExternalLink, Upload, HardDrive, Thermometer, ChevronDown, ChevronRight, Wifi, Radio, Server, Database } from 'lucide-react';
import { useToast } from '../../context/ToastContext';
import { useTranslation } from 'react-i18next';
import { DeviceMetrics } from './DeviceMetrics';

const PROTOCOL_ICON_MAP: Record<string, any> = {
  'ssh': Terminal,
  'http': Globe,
  'https': Lock,
  'rdp': Monitor,
  'tcp': Activity,
};

interface DeviceEditorProps {
  device: Device;
  devices?: Device[]; // Made optional for backward compatibility if needed
  onClose: () => void;
  onSave: () => void;
}

export function DeviceEditor({ device, devices = [], onClose, onSave }: DeviceEditorProps) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [groups, setGroups] = useState<DeviceGroup[]>([]);
  const [currentDevice, setCurrentDevice] = useState<Device>(device);
  const [formData, setFormData] = useState({
    display_name: currentDevice.display_name || '',
    notes: currentDevice.notes || '',
    group_id: currentDevice.group_id,
    vendor: currentDevice.vendor || '',
    w: currentDevice.w || 2,
    h: currentDevice.h || 3,
    virtual_type: currentDevice.virtual_type || null,
    parent_id: currentDevice.parent_id || null,
    rack_id: currentDevice.rack_id || null,
    rack_unit: currentDevice.rack_unit || null,
    rack_height: currentDevice.rack_height || 1,
    is_wlan: currentDevice.is_wlan || false,
    is_ap: currentDevice.is_ap || false,
    is_host: currentDevice.is_host || false,
  });
  const [isSaving, setIsSaving] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState<'settings' | 'services' | 'history' | 'agent'>('settings');
  const [history, setHistory] = useState<any[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isScanningServices, setIsScanningServices] = useState(false);

  // Agent state
  const [agentStatus, setAgentStatus] = useState<{ is_installed: boolean; is_active: boolean; agent_version?: string; latest_version?: string; last_seen?: string } | null>(null);
  const [isDeploying, setIsDeploying] = useState(false);
  const [sshForm, setSshForm] = useState({ ssh_user: 'root', ssh_password: '', ssh_key: '', ssh_port: 22 });
  const [agentConfig, setAgentConfig] = useState<{ interval: number; disk_paths: string[]; enable_temp: boolean } | null>(null);
  const [newDiskPath, setNewDiskPath] = useState('');
  const [deployLog, setDeployLog] = useState<string[]>([]);
  const [showManual, setShowManual] = useState(false);

  useEffect(() => {
    const loadGroups = async () => {
      try {
        const data = await api.getGroups();
        setGroups(data);
      } catch (err) {
        console.error('Failed to load groups:', err);
      }
    };
    loadGroups();
  }, []);

  const [racks, setRacks] = useState<any[]>([]);
  useEffect(() => {
    const loadRacks = async () => {
      try {
        const data = await api.getRacks();
        setRacks(Array.isArray(data) ? data : []);
      } catch (err) {
        console.error('Failed to load racks:', err);
        setRacks([]);
      }
    };
    loadRacks();
  }, []);

  useEffect(() => {
    if (activeTab === 'history') {
      loadHistory();
    }
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === 'agent') {
      loadAgentStatus();
    }
  }, [activeTab]);

  const loadAgentStatus = async () => {
    try {
      const status = await api.getAgentStatus(currentDevice.id);
      setAgentStatus(status);
      if (status.is_installed) {
        try {
          const config = await api.getAgentConfig(currentDevice.id);
          setAgentConfig(config);
        } catch { /* no config yet */ }
      }
    } catch { /* agent not available */ }
  };

  const handleDeploy = async () => {
    setIsDeploying(true);
    showToast('info', t('agent.deploying'), t('agent.connecting', { ip: currentDevice.ip }));
    try {
      const result = await api.deployAgent(currentDevice.id, sshForm);
      setDeployLog(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${result.message}`]);
      if (result.status === 'success') {
        showToast('success', t('agent.deployed_title'), result.message);
        setSshForm(prev => ({ ...prev, ssh_password: '', ssh_key: '' }));
        await loadAgentStatus();
      } else {
        showToast('error', t('agent.deploy_failed_title'), result.message);
      }
    } catch (err: any) {
      const msg = err.message || t('agent.connection_failed');
      setDeployLog(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${t('common.error').toUpperCase()}: ${msg}`]);
      showToast('error', t('common.error'), msg);
    } finally {
      setIsDeploying(false);
    }
  };

  const handleUninstall = async () => {
    if (!window.confirm(t('agent.uninstall_confirm_long'))) {
      return;
    }
    
    setIsDeploying(true);
    showToast('info', t('agent.uninstalling'), t('agent.removing', { ip: currentDevice.ip }));
    try {
      const result = await api.uninstallAgent(currentDevice.id, sshForm);
      setDeployLog(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${result.message}`]);
      if (result.status === 'success') {
        showToast('success', t('agent.uninstalled_title'), result.message);
        setSshForm(prev => ({ ...prev, ssh_password: '', ssh_key: '' }));
        await loadAgentStatus();
      } else {
        showToast('error', t('agent.uninstall_failed_title'), result.message);
      }
    } catch (err: any) {
      const msg = err.message || t('agent.connection_failed');
      setDeployLog(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${t('common.error').toUpperCase()}: ${msg}`]);
      showToast('error', t('common.error'), msg);
    } finally {
      setIsDeploying(false);
    }
  };

  const loadHistory = async () => {
    setIsLoadingHistory(true);
    try {
      const data = await api.getDeviceHistory(currentDevice.id);
      setHistory(data);
    } catch (err) {
      console.error('Failed to load history:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleRefreshInfo = async () => {
    setIsRefreshing(true);
    showToast('info', t('dashboard.refreshing'), t('notifications.refreshing_details', { ip: currentDevice.ip }));
    try {
      const updated = await api.refreshDeviceInfo(currentDevice.id);
      setCurrentDevice(updated);
      setFormData(prev => ({ 
        ...prev, 
        vendor: updated.vendor || '',
        display_name: (prev.display_name === currentDevice.ip && updated.hostname) 
          ? updated.hostname.split('.')[0] 
          : prev.display_name
      }));
      showToast('success', t('notifications.info_updated'), t('notifications.info_updated_text', { ip: currentDevice.ip }));
      onSave(); // Update dashboard
    } catch (err: any) {
      console.error('Failed to refresh device info:', err);
      showToast('error', t('common.error'), t('notifications.refresh_failed', { error: err.message || t('common.unknown') }));
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleScanServices = async () => {
    setIsScanningServices(true);
    showToast('info', t('network.nmap_scan'), t('notifications.nmap_scan_started', { ip: currentDevice.ip }));
    try {
      const updated = await api.refreshServices(currentDevice.id);
      setCurrentDevice(updated);
      showToast('success', t('network.nmap_scan'), t('notifications.nmap_scan_finished', { ip: currentDevice.ip }));
      onSave();
    } catch (err: any) {
      console.error('Failed to scan services:', err);
      showToast('error', t('common.error'), err.message || t('common.unknown'));
    } finally {
      setIsScanningServices(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    let updateData: any = { ...formData };
    const isGroupChanged = formData.group_id !== currentDevice.group_id;
    
    if (isGroupChanged) {
      // Find the exact bottom of the target group to avoid endless scrolling
      const targetGroupDevices = devices.filter(d => d.group_id === formData.group_id && d.id !== currentDevice.id);
      let maxY = 0;
      targetGroupDevices.forEach(d => {
        const bottom = (d.y || 0) + (d.h || 1);
        if (bottom > maxY) maxY = bottom;
      });
      
      updateData.x = 0;
      updateData.y = maxY;
    }

    try {
      await api.updateDevice(currentDevice.id, updateData);
      onSave();
      onClose();
    } catch (err) {
      console.error('Failed to save device:', err);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content animate-in" style={{ 
        maxWidth: activeTab === 'agent' ? '1150px' : '800px', 
        maxHeight: '90vh',
        display: 'flex',
        flexDirection: 'column',
        transition: 'all 0.3s ease' 
      }}>
        <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-md)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
            <div className="logo__icon" style={{ width: 32, height: 32 }}>
              <Settings size={16} color="white" />
            </div>
            <h3>{t('editor.title_edit')}</h3>
          </div>
          <button className="btn-close" onClick={onClose}><X size={18} /></button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border-subtle)', padding: '0 var(--space-lg)' }}>
          <button 
            className={`tab-item ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
            style={{ 
              padding: 'var(--space-md)', 
              background: 'none', 
              border: 'none', 
              color: activeTab === 'settings' ? 'var(--accent-primary)' : 'var(--text-tertiary)',
              borderBottom: activeTab === 'settings' ? '2px solid var(--accent-primary)' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.875rem'
            }}
          >
            {t('editor.tabs.general')}
          </button>
          <button 
            className={`tab-item ${activeTab === 'services' ? 'active' : ''}`}
            onClick={() => setActiveTab('services')}
            style={{ 
              padding: 'var(--space-md)', 
              background: 'none', 
              border: 'none', 
              color: activeTab === 'services' ? 'var(--accent-primary)' : 'var(--text-tertiary)',
              borderBottom: activeTab === 'services' ? '2px solid var(--accent-primary)' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.875rem'
            }}
          >
            {t('editor.tabs.services')}
          </button>
          <button 
            className={`tab-item ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => setActiveTab('history')}
            style={{ 
              padding: 'var(--space-md)', 
              background: 'none', 
              border: 'none', 
              color: activeTab === 'history' ? 'var(--accent-primary)' : 'var(--text-tertiary)',
              borderBottom: activeTab === 'history' ? '2px solid var(--accent-primary)' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.875rem'
            }}
          >
            {t('editor.tabs.history')}
          </button>
          <button 
            className={`tab-item ${activeTab === 'agent' ? 'active' : ''}`}
            onClick={() => setActiveTab('agent')}
            style={{ 
              padding: 'var(--space-md)', 
              background: 'none', 
              border: 'none', 
              color: activeTab === 'agent' ? 'var(--accent-primary)' : 'var(--text-tertiary)',
              borderBottom: activeTab === 'agent' ? '2px solid var(--accent-primary)' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.875rem'
            }}
          >
            {t('editor.tabs.agent')}
          </button>
        </div>

        <div className="modal-body" style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-lg)', minHeight: 400 }}>
          {activeTab === 'settings' ? (
            <form onSubmit={handleSubmit}>
              {/* Basic Information */}
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: '1fr 1fr', 
                gap: '24px', 
                background: 'rgba(255,255,255,0.02)', 
                padding: '20px', 
                borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.05)',
                marginBottom: '24px'
              }}>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label><Tag size={14} /> {t('editor.display_name')}</label>
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <input
                      className="input"
                      style={{ flex: 1 }}
                      value={formData.display_name}
                      onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                      placeholder={currentDevice.hostname || currentDevice.ip}
                    />
                    <button 
                      type="button"
                      className="btn btn-secondary" 
                      onClick={handleRefreshInfo}
                      disabled={isRefreshing}
                      style={{ height: 42, padding: '0 16px', display: 'flex', alignItems: 'center', gap: '8px' }}
                    >
                      <RefreshCw size={16} className={isRefreshing ? 'spinning' : ''} />
                      {isRefreshing ? t('common.loading') : t('editor.refresh_info')}
                    </button>
                  </div>
                </div>

                <div className="form-group">
                  <label><Folder size={14} /> {t('editor.group')}</label>
                  <select
                    className="input"
                    value={formData.group_id || ''}
                    onChange={(e) => setFormData({ ...formData, group_id: e.target.value ? parseInt(e.target.value) : null })}
                  >
                    <option value="">{t('dashboard.unassigned_devices')}</option>
                    {Array.isArray(groups) && groups.map(group => (
                      <option key={group.id} value={group.id}>{group.name}</option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label><Cpu size={14} /> {t('editor.vendor')}</label>
                  <input
                    className="input"
                    value={formData.vendor}
                    onChange={(e) => setFormData({ ...formData, vendor: e.target.value })}
                    placeholder={t('common.unknown')}
                  />
                </div>

                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label><Monitor size={14} /> {t('editor.parent_device', 'Physischer Host')}</label>
                  <select
                    className="input"
                    value={formData.parent_id || ''}
                    onChange={(e) => setFormData({ ...formData, parent_id: e.target.value ? parseInt(e.target.value) : null })}
                  >
                    <option value="">{t('editor.no_parent', 'Kein Host (Physisch)')}</option>
                    {(devices || []).filter(d => d.id !== currentDevice.id && d.is_host).map(dev => (
                      <option key={dev.id} value={dev.id}>{dev.display_name || dev.hostname || dev.ip}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Infrastructure & Placement */}
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: '1fr 1fr', 
                gap: '24px', 
                background: 'rgba(255,255,255,0.02)', 
                padding: '20px', 
                borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.05)',
                marginBottom: '24px'
              }}>
                <div className="form-group">
                  <label><Layout size={14} /> {t('editor.rack_position', 'Rack & Position')}</label>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <select
                      className="input"
                      style={{ flex: 2 }}
                      value={formData.rack_id || ''}
                      onChange={(e) => setFormData({ ...formData, rack_id: e.target.value ? parseInt(e.target.value) : null })}
                    >
                      <option value="">Kein Rack</option>
                      {Array.isArray(racks) && racks.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                    <input
                      type="number"
                      className="input"
                      style={{ flex: 1 }}
                      placeholder="Unit"
                      value={formData.rack_unit || ''}
                      onChange={(e) => setFormData({ ...formData, rack_unit: e.target.value ? parseInt(e.target.value) : null })}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label><HardDrive size={14} /> {t('editor.rack_height', 'Höhe (HE)')}</label>
                  <input
                    type="number"
                    className="input"
                    min={1}
                    max={10}
                    value={formData.rack_height}
                    onChange={(e) => setFormData({ ...formData, rack_height: parseInt(e.target.value) || 1 })}
                  />
                </div>

                <div className="form-group">
                  <label><Layout size={14} /> {t('editor.grid_size')}</label>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input
                      type="number"
                      className="input"
                      style={{ flex: 1 }}
                      value={formData.w}
                      min={1}
                      max={12}
                      onChange={(e) => setFormData({ ...formData, w: parseInt(e.target.value) })}
                    />
                    <span style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>x</span>
                    <input
                      type="number"
                      className="input"
                      style={{ flex: 1 }}
                      value={formData.h}
                      min={1}
                      max={10}
                      onChange={(e) => setFormData({ ...formData, h: parseInt(e.target.value) })}
                    />
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginLeft: 4 }}>Units</span>
                  </div>
                </div>

                <div className="form-group">
                  <label>{t('editor.badge', 'Special Marker (Badge)')}</label>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    {[
                      { id: null, label: t('editor.none'), color: 'var(--bg-input)' },
                      { id: 'vm', label: 'VM', color: 'rgba(217, 70, 239, 0.2)' },
                      { id: 'docker', label: 'Docker', color: 'rgba(147, 51, 234, 0.2)' }
                    ].map(type => (
                      <button
                        key={String(type.id)}
                        type="button"
                        onClick={() => setFormData({ ...formData, virtual_type: type.id as any })}
                        style={{
                          flex: 1,
                          padding: '8px 4px',
                          background: formData.virtual_type === type.id ? type.color : 'rgba(255,255,255,0.03)',
                          border: `1px solid ${formData.virtual_type === type.id ? 'var(--accent-primary)' : 'rgba(255,255,255,0.1)'}`,
                          borderRadius: '8px',
                          color: formData.virtual_type === type.id ? 'var(--text-primary)' : 'var(--text-tertiary)',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                          transition: 'all 0.2s'
                        }}
                      >
                        {type.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Advanced Connectivity & Role */}
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: '1fr 1fr 1fr', 
                gap: '16px', 
                marginBottom: '24px' 
              }}>
                <div 
                  onClick={() => setFormData({ ...formData, is_wlan: !formData.is_wlan })}
                  style={{
                    padding: '12px',
                    background: formData.is_wlan ? 'rgba(56, 189, 248, 0.1)' : 'rgba(255,255,255,0.02)',
                    border: `1px solid ${formData.is_wlan ? '#38bdf8' : 'rgba(255,255,255,0.05)'}`,
                    borderRadius: '12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    transition: 'all 0.2s'
                  }}
                >
                  <div style={{ 
                    width: 32, 
                    height: 32, 
                    borderRadius: '8px', 
                    background: formData.is_wlan ? '#38bdf8' : 'rgba(255,255,255,0.05)', 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center' 
                  }}>
                    <Wifi size={16} color={formData.is_wlan ? 'white' : '#64748b'} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 700, color: formData.is_wlan ? '#f8fafc' : '#94a3b8' }}>WLAN Client</span>
                    <span style={{ fontSize: '0.6rem', color: '#64748b' }}>Signalbalken</span>
                  </div>
                </div>

                <div 
                  onClick={() => setFormData({ ...formData, is_ap: !formData.is_ap })}
                  style={{
                    padding: '12px',
                    background: formData.is_ap ? 'rgba(34, 211, 238, 0.1)' : 'rgba(255,255,255,0.02)',
                    border: `1px solid ${formData.is_ap ? '#22d3ee' : 'rgba(255,255,255,0.05)'}`,
                    borderRadius: '12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    transition: 'all 0.2s'
                  }}
                >
                  <div style={{ 
                    width: 32, 
                    height: 32, 
                    borderRadius: '8px', 
                    background: formData.is_ap ? '#22d3ee' : 'rgba(255,255,255,0.05)', 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center' 
                  }}>
                    <Radio size={16} color={formData.is_ap ? 'white' : '#64748b'} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 700, color: formData.is_ap ? '#f8fafc' : '#94a3b8' }}>Access Point</span>
                    <span style={{ fontSize: '0.6rem', color: '#64748b' }}>WLAN Quelle</span>
                  </div>
                </div>

                <div 
                  onClick={() => setFormData({ ...formData, is_host: !formData.is_host })}
                  style={{
                    padding: '12px',
                    background: formData.is_host ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255,255,255,0.02)',
                    border: `1px solid ${formData.is_host ? '#10b981' : 'rgba(255,255,255,0.05)'}`,
                    borderRadius: '12px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    transition: 'all 0.2s'
                  }}
                >
                  <div style={{ 
                    width: 32, 
                    height: 32, 
                    borderRadius: '8px', 
                    background: formData.is_host ? '#10b981' : 'rgba(255,255,255,0.05)', 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center' 
                  }}>
                    <Server size={16} color={formData.is_host ? 'white' : '#64748b'} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 700, color: formData.is_host ? '#f8fafc' : '#94a3b8' }}>Physischer Host</span>
                    <span style={{ fontSize: '0.6rem', color: '#64748b' }}>Beinhaltet VMs/Docker</span>
                  </div>
                </div>
              </div>

              {/* Host Assignment */}
              {!formData.is_host && (
                <div className="form-group" style={{ marginBottom: '24px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', fontWeight: 700, color: '#94a3b8', marginBottom: '8px', textTransform: 'uppercase' }}>
                    <Database size={14} /> {t('editor.parent_host', 'Physisches Host-System')}
                  </label>
                  <select
                    className="input"
                    value={formData.parent_id || ''}
                    onChange={(e) => setFormData({ ...formData, parent_id: e.target.value ? parseInt(e.target.value) : null })}
                    style={{
                      width: '100%',
                      background: 'rgba(15, 23, 42, 0.6)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '8px',
                      padding: '10px',
                      color: '#f1f5f9'
                    }}
                  >
                    <option value="">Kein Host (Eigenständiges System)</option>
                    {devices.filter(d => d.is_host && d.id !== currentDevice.id).map(d => (
                      <option key={d.id} value={d.id}>{d.display_name || d.hostname || d.ip}</option>
                    ))}
                  </select>
                </div>
              )}


              <div className="form-group">
                <label>{t('editor.notes')}</label>
                <textarea
                  className="input"
                  style={{ minHeight: 80, resize: 'vertical' }}
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Gerätenotizen hier eingeben..."
                />
              </div>

              <div style={{ 
                padding: '16px', 
                background: 'rgba(15, 23, 42, 0.4)', 
                borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.05)',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '16px'
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', fontWeight: 700 }}>System Info</div>
                  <div style={{ fontSize: '0.85rem', display: 'grid', gridTemplateColumns: '80px 1fr', gap: '4px' }}>
                    <span style={{ color: 'var(--text-tertiary)' }}>IP:</span> <span>{currentDevice.ip}</span>
                    <span style={{ color: 'var(--text-tertiary)' }}>MAC:</span> <span style={{ fontFamily: 'monospace' }}>{currentDevice.mac || 'N/A'}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                   <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', fontWeight: 700 }}>Network Info</div>
                   <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                     {currentDevice.hostname || 'Kein DNS Name'}
                     {currentDevice.hostname && currentDevice.hostname.includes('.') && (
                       <div style={{ fontSize: '0.7rem', color: 'var(--accent-primary)', marginTop: 2 }}>
                         FQDN: {currentDevice.hostname}
                       </div>
                     )}
                   </div>
                </div>
              </div>
            </form>
          ) : activeTab === 'services' ? (
            <div className="services-tab" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h4 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{t('editor.active_services')}</h4>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button 
                    className="btn btn-secondary" 
                    style={{ fontSize: '0.75rem', padding: '4px 10px', color: 'var(--accent-primary)', borderColor: 'rgba(56, 189, 248, 0.3)' }}
                    onClick={handleScanServices}
                    disabled={isScanningServices}
                  >
                    <Activity size={14} className={isScanningServices ? 'spinning' : ''} />
                    {isScanningServices ? t('dashboard.scanning') : t('network.nmap_scan')}
                  </button>
                  <button 
                    className="btn btn-secondary" 
                    style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                    onClick={async () => {
                      const name = prompt('Service Name?', 'Web Interface');
                      const port = parseInt(prompt('Port?', '80') || '0');
                      if (name && port > 0) {
                        await api.addService(currentDevice.id, { name, port, protocol: 'http' });
                        const updated = await api.getDevice(currentDevice.id);
                        setCurrentDevice(updated);
                        onSave();
                      }
                    }}
                  >
                    + {t('editor.add_service')}
                  </button>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '300px', overflowY: 'auto', paddingRight: '4px' }}>
                {currentDevice.services.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-tertiary)', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
                    {t('editor.no_services')}
                  </div>
                ) : (
                  currentDevice.services.sort((a, b) => a.port - b.port).map(svc => {
                    const ServiceIcon = PROTOCOL_ICON_MAP[svc.protocol.toLowerCase()] || ExternalLink;

                    return (
                      <div key={svc.id} style={{ 
                        padding: '12px', 
                        background: 'var(--bg-input)', 
                        borderRadius: 'var(--radius-md)', 
                        display: 'flex', 
                        alignItems: 'center', 
                        gap: 'var(--space-md)',
                        border: '1px solid var(--border-subtle)',
                        transition: 'border-color 0.2s'
                      }}>
                        <div style={{ 
                          width: 40, height: 40, 
                          background: svc.is_up ? 'rgba(74, 222, 128, 0.1)' : 'rgba(248, 113, 113, 0.1)', 
                          borderRadius: '8px',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          color: svc.is_up ? 'var(--accent-secondary)' : 'var(--text-tertiary)',
                        }}>
                          <ServiceIcon size={18} />
                        </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <input 
                            style={{ background: 'none', border: 'none', color: 'var(--text-primary)', fontWeight: 600, width: '100%' }}
                            value={svc.name}
                            onChange={async (e) => {
                              const newName = e.target.value;
                              setCurrentDevice(prev => ({
                                ...prev,
                                services: prev.services.map(s => s.id === svc.id ? { ...s, name: newName, is_auto_detected: false } : s)
                              }));
                            }}
                            onBlur={async (e) => {
                              await api.updateService(svc.id, { name: e.target.value });
                              onSave();
                            }}
                          />
                          {!svc.is_auto_detected && (
                            <span style={{ fontSize: '0.6rem', background: 'var(--accent-primary)', color: 'black', padding: '1px 4px', borderRadius: '3px', fontWeight: 'bold', whiteSpace: 'nowrap' }}>MANUELL</span>
                          )}
                        </div>
                        <div style={{ display: 'flex', gap: 12, fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                          <span style={{ display: 'flex', gap: 4 }}>
                            PROT: 
                            <select 
                              style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', fontSize: '0.75rem', padding: 0, cursor: 'pointer' }}
                              value={svc.protocol}
                              onChange={async (e) => {
                                const newProto = e.target.value;
                                try {
                                  await api.updateService(svc.id, { protocol: newProto });
                                  const updated = await api.getDevice(currentDevice.id);
                                  setCurrentDevice(updated);
                                  onSave();
                                  showToast('success', 'Protokoll aktualisiert', `${svc.name} ist nun als ${newProto.toUpperCase()} konfiguriert.`);
                                } catch (err: any) {
                                  showToast('error', 'Fehler', `Konnte Protokoll nicht speichern: ${err.message || 'Unbekannter Fehler'}`);
                                }
                              }}
                            >
                              <option value="http">HTTP</option>
                              <option value="https">HTTPS</option>
                              <option value="ssh">SSH</option>
                              <option value="tcp">TCP</option>
                              <option value="udp">UDP</option>
                            </select>
                          </span>
                          <span style={{ display: 'flex', gap: 4 }}>
                            PORT: 
                            <input 
                              type="number"
                              style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', fontSize: '0.75rem', padding: 0, width: '50px' }}
                              value={svc.port}
                              onChange={async (e) => {
                                const newPort = parseInt(e.target.value);
                                if (!isNaN(newPort)) {
                                  setCurrentDevice(prev => ({
                                    ...prev,
                                    services: prev.services.map(s => s.id === svc.id ? { ...s, port: newPort, is_auto_detected: false } : s)
                                  }));
                                }
                              }}
                              onBlur={async (e) => {
                                const newPort = parseInt(e.target.value);
                                if (!isNaN(newPort)) {
                                  await api.updateService(svc.id, { port: newPort });
                                  onSave();
                                }
                              }}
                            />
                          </span>
                        </div>
                      </div>
                      <button 
                        className="btn-icon" 
                        style={{ color: 'var(--text-tertiary)' }}
                        onClick={async () => {
                          if (confirm('Dienst entfernen?')) {
                            await api.deleteService(svc.id);
                            const updated = await api.getDevice(currentDevice.id);
                            setCurrentDevice(updated);
                            onSave();
                          }
                        }}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  );
                  })
                )}
              </div>
              
              <div style={{ marginTop: 'auto', padding: '12px', background: 'rgba(56, 189, 248, 0.05)', borderRadius: '8px', fontSize: '0.8rem', border: '1px dashed rgba(56, 189, 248, 0.3)' }}>
                <p style={{ margin: 0, color: '#38bdf8' }}>
                  <strong>{t('common.warning')}:</strong> {t('editor.service_note')}
                </p>
              </div>
            </div>
          ) : activeTab === 'history' ? (
            <div className="history-timeline" style={{ maxHeight: '400px', overflowY: 'auto', paddingRight: '8px' }}>
              {isLoadingHistory ? (
                <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-tertiary)' }}>
                  <RefreshCw size={24} className="spinning" style={{ marginBottom: 10 }} />
                  <p>{t('common.loading')}</p>
                </div>
              ) : history.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-tertiary)' }}>
                  <p>{t('notifications.no_events')}</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                  {Array.isArray(history) && history.map((item) => (
                    <div key={item.id} style={{ 
                      padding: 'var(--space-md)', 
                      background: 'var(--bg-input)', 
                      borderRadius: 'var(--radius-md)',
                      borderLeft: `4px solid ${
                        (item.status === 'online' || item.status === 'up') 
                          ? 'var(--accent-success)' 
                          : 'var(--accent-danger)'
                      }`,
                      animation: 'slideUp 0.3s ease-out'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ 
                            fontWeight: 700, 
                            textTransform: 'uppercase', 
                            fontSize: '0.7rem', 
                            color: (item.status === 'online' || item.status === 'up') 
                              ? 'var(--accent-success)' 
                              : 'var(--accent-danger)',
                            background: (item.status === 'online' || item.status === 'up')
                              ? 'rgba(79, 209, 197, 0.1)'
                              : 'rgba(255, 107, 107, 0.1)',
                            padding: '2px 6px',
                            borderRadius: 4
                          }}>
                            {item.status}
                          </span>
                          {item.service_id && (
                            <span style={{ fontSize: '0.7rem', background: 'var(--bg-elevated)', padding: '2px 6px', borderRadius: 4, color: 'var(--text-secondary)' }}>
                              SERVICE
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                          {item.timestamp ? new Date(item.timestamp).toLocaleString() : t('common.loading')}
                        </span>
                      </div>
                      <p style={{ fontSize: '0.875rem', margin: 0, fontWeight: item.service_id ? 500 : 400, color: 'var(--text-primary)' }}>
                        {item.message}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : activeTab === 'agent' ? (
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', 
              gap: 'var(--space-lg)',
              alignItems: 'start'
            }}>
              {/* Spalte 1: Status & Metriken */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                <div style={{ 
                  padding: '16px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)',
                  border: `1px solid ${agentStatus?.is_active ? 'rgba(16, 185, 129, 0.3)' : 'var(--border-subtle)'}` 
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ 
                        width: 10, height: 10, borderRadius: '50%',
                        background: agentStatus?.is_active ? '#10b981' : (agentStatus?.is_installed ? '#f59e0b' : '#64748b'),
                        boxShadow: agentStatus?.is_active ? '0 0 8px #10b981' : 'none'
                      }} />
                      <span style={{ fontWeight: 700 }}>
                        {agentStatus?.is_active ? t('agent.status_active') : (agentStatus?.is_installed ? `${t('agent.status_active')} (${t('common.offline')})` : t('agent.status_inactive'))}
                      </span>
                    </div>
                    {agentStatus?.agent_version && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {agentStatus.latest_version && agentStatus.agent_version !== agentStatus.latest_version && (
                          <span style={{ 
                            fontSize: '0.65rem', background: 'rgba(245, 158, 11, 0.2)', color: '#f59e0b', 
                            padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(245, 158, 11, 0.3)',
                            fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4
                          }}>
                            <RefreshCw size={10} /> {t('common.next')} Update
                          </span>
                        )}
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>v{agentStatus.agent_version}</span>
                      </div>
                    )}
                  </div>
                  {agentStatus?.last_seen && (
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', margin: '8px 0 0' }}>
                      {t('agent.last_report')}: {new Date(agentStatus.last_seen).toLocaleString()}
                    </p>
                  )}
                </div>

                {/* Live Metrics (only if active) */}
                {agentStatus?.is_active && (
                  <DeviceMetrics 
                    deviceId={currentDevice.id} 
                    compact={false} 
                    onUpdate={(m) => {
                      if (agentStatus) {
                        setAgentStatus({ ...agentStatus, last_seen: m.timestamp });
                      }
                    }}
                  />
                )}
              </div>

              {/* Spalte 2: Management & Config */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                {/* SSH Management Form (Compact) */}
                <div style={{ padding: '12px', background: 'rgba(56, 189, 248, 0.03)', border: '1px dashed rgba(56, 189, 248, 0.2)', borderRadius: 'var(--radius-md)' }}>
                  <h4 style={{ margin: '0 0 8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Terminal size={14} /> {t('agent.ssh_management')}
                  </h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: 8 }}>
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label style={{ fontSize: '0.65rem' }}>{t('agent.ssh_user')}</label>
                      <input className="input" style={{ padding: '4px 8px', height: 32 }} value={sshForm.ssh_user} onChange={e => setSshForm(prev => ({ ...prev, ssh_user: e.target.value }))} />
                    </div>
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label style={{ fontSize: '0.65rem' }}>{t('agent.ssh_port')}</label>
                      <input className="input" type="number" style={{ padding: '4px 8px', height: 32 }} value={sshForm.ssh_port} onChange={e => setSshForm(prev => ({ ...prev, ssh_port: parseInt(e.target.value) || 22 }))} />
                    </div>
                  </div>
                  <div className="form-group" style={{ marginBottom: 8 }}>
                    <label style={{ fontSize: '0.65rem' }}>{t('agent.ssh_password')}</label>
                    <input className="input" type="password" style={{ padding: '4px 8px', height: 32 }} value={sshForm.ssh_password} onChange={e => setSshForm(prev => ({ ...prev, ssh_password: e.target.value }))} placeholder={t('agent.password_placeholder')} />
                  </div>
                  
                  <div style={{ display: 'flex', gap: 8 }}>
                    {!agentStatus?.is_installed ? (
                      <button className="btn btn-primary" onClick={handleDeploy} disabled={isDeploying || (!sshForm.ssh_password && !sshForm.ssh_key)} style={{ flex: 1, padding: '4px 12px', fontSize: '0.75rem' }}>
                        <Upload size={14} /> {isDeploying ? t('common.loading') : t('agent.install_via_ssh')}
                      </button>
                    ) : (
                      <>
                        <button className="btn btn-primary" onClick={handleDeploy} disabled={isDeploying || (!sshForm.ssh_password && !sshForm.ssh_key)} 
                          style={{ 
                            flex: 1, padding: '4px 12px', fontSize: '0.75rem',
                            background: agentStatus?.agent_version !== agentStatus?.latest_version ? 'linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%)' : undefined,
                          }}
                        >
                          <RefreshCw size={14} className={isDeploying ? 'spinning' : ''} /> {isDeploying ? t('common.loading') : t('agent.update_agent')}
                        </button>
                        <button className="btn btn-secondary" onClick={handleUninstall} disabled={isDeploying || (!sshForm.ssh_password && !sshForm.ssh_key)} style={{ flex: 1, borderColor: '#ef4444', color: '#ef4444', padding: '4px 12px', fontSize: '0.75rem' }}>
                          <Trash2 size={14} /> {t('agent.uninstall')}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {/* Manual Installation Toggle */}
                <div style={{ marginTop: 'var(--space-sm)' }}>
                  <button 
                    onClick={() => setShowManual(!showManual)}
                    style={{ 
                      background: 'none', border: 'none', color: 'var(--text-tertiary)', 
                      fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: 6,
                      cursor: 'pointer', padding: '4px 0'
                    }}
                  >
                    {showManual ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    {t('agent.manual_install_options', 'Manuelle Installation/Deinstallation anzeigen')}
                  </button>

                  {showManual && (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-md)', marginTop: 8, animation: 'fadeIn 0.2s ease-out' }}>
                      {/* Manual Installation (Zero-SSH) */}
                      <div style={{ padding: '12px', background: 'rgba(16, 185, 129, 0.05)', border: '1px dashed rgba(16, 185, 129, 0.3)', borderRadius: 'var(--radius-md)' }}>
                        <h4 style={{ margin: '0 0 8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                          <ExternalLink size={14} /> {t('agent.manual_install')}
                        </h4>
                        <div style={{ 
                          padding: '8px', 
                          background: 'var(--bg-dashboard)', 
                          borderRadius: '4px', 
                          fontSize: '0.65rem', 
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--accent-primary)',
                          border: '1px solid var(--border-subtle)',
                          position: 'relative',
                          wordBreak: 'break-all',
                          cursor: 'pointer'
                        }}
                        onClick={() => {
                          const host = window.location.hostname;
                          const port = window.location.port === '5173' ? ':8000' : (window.location.port ? `:${window.location.port}` : '');
                          const protocol = window.location.protocol;
                          const cmd = `curl -sSL ${protocol}//${host}${port}/api/agent/download/install-sh/${currentDevice.id} | bash`;
                          
                          if (navigator.clipboard && window.isSecureContext) {
                            navigator.clipboard.writeText(cmd);
                            showToast('success', t('notifications.copied'), t('notifications.copied_text'));
                          } else {
                            const textArea = document.createElement("textarea");
                            textArea.value = cmd;
                            document.body.appendChild(textArea);
                            textArea.select();
                            try {
                              document.execCommand('copy');
                              showToast('success', t('notifications.copied'), t('notifications.copied_text'));
                            } catch (err) {
                              console.error('Copy fallback failed', err);
                            }
                            document.body.removeChild(textArea);
                          }
                        }}>
                          <code>install-sh/{currentDevice.id} | bash</code>
                        </div>
                      </div>

                      {/* Manual Uninstall (Zero-SSH) */}
                      <div style={{ padding: '12px', background: 'rgba(239, 68, 68, 0.05)', border: '1px dashed rgba(239, 68, 68, 0.3)', borderRadius: 'var(--radius-md)' }}>
                        <h4 style={{ margin: '0 0 8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Trash2 size={14} /> {t('agent.manual_uninstall')}
                        </h4>
                        <div style={{ 
                          padding: '8px', 
                          background: 'var(--bg-dashboard)', 
                          borderRadius: '4px', 
                          fontSize: '0.65rem', 
                          fontFamily: 'var(--font-mono)',
                          color: '#ef4444',
                          border: '1px solid var(--border-subtle)',
                          position: 'relative',
                          wordBreak: 'break-all',
                          cursor: 'pointer'
                        }}
                        onClick={() => {
                          const host = window.location.hostname;
                          const port = window.location.port === '5173' ? ':8000' : (window.location.port ? `:${window.location.port}` : '');
                          const protocol = window.location.protocol;
                          const cmd = `curl -sSL ${protocol}//${host}${port}/api/agent/download/uninstall-sh/${currentDevice.id} | bash`;
                          
                          if (navigator.clipboard && window.isSecureContext) {
                            navigator.clipboard.writeText(cmd);
                            showToast('success', t('notifications.copied'), t('notifications.copied_text'));
                          } else {
                            const textArea = document.createElement("textarea");
                            textArea.value = cmd;
                            document.body.appendChild(textArea);
                            textArea.select();
                            try {
                              document.execCommand('copy');
                              showToast('success', t('notifications.copied'), t('notifications.copied_text'));
                            } catch (err) {
                              console.error('Copy fallback failed', err);
                            }
                            document.body.removeChild(textArea);
                          }
                        }}>
                          <code>uninstall-sh/{currentDevice.id} | bash</code>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Agent Config (only if installed) */}
                {agentStatus?.is_installed && agentConfig && (
                  <div style={{ padding: '16px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)' }}>
                    <h4 style={{ margin: '0 0 12px', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Settings size={16} /> {t('agent.configuration')}
                    </h4>
                    <div className="form-group">
                      <label style={{ fontSize: '0.7rem' }}>{t('agent.report_interval')}</label>
                      <input className="input" type="number" value={agentConfig.interval} onChange={e => setAgentConfig(prev => prev ? { ...prev, interval: parseInt(e.target.value) || 30 } : prev)} />
                    </div>
                    <div className="form-group" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label style={{ fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Thermometer size={12} /> {t('agent.temp_monitoring')}
                      </label>
                      <button
                        className={`btn ${agentConfig.enable_temp ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ padding: '4px 12px', fontSize: '0.75rem' }}
                        onClick={() => setAgentConfig(prev => prev ? { ...prev, enable_temp: !prev.enable_temp } : prev)}
                      >
                        {agentConfig.enable_temp ? t('common.activated') : t('common.deactivated')}
                      </button>
                    </div>
                    <div className="form-group">
                      <label style={{ fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <HardDrive size={12} /> {t('agent.disk_paths')}
                      </label>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                        {(agentConfig.disk_paths || []).map((p, i) => (
                          <span key={i} style={{ 
                            background: 'var(--bg-elevated)', padding: '3px 8px', borderRadius: 4,
                            fontSize: '0.75rem', fontFamily: 'var(--font-mono)', display: 'flex', alignItems: 'center', gap: 4
                          }}>
                            {p}
                            <button style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', padding: 0, fontSize: '0.8rem' }}
                              onClick={() => setAgentConfig(prev => prev ? { ...prev, disk_paths: (prev.disk_paths || []).filter((_, idx) => idx !== i) } : prev)}
                            >×</button>
                          </span>
                        ))}
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <input className="input" style={{ flex: 1 }} placeholder="/mnt/data" value={newDiskPath} onChange={e => setNewDiskPath(e.target.value)} />
                        <button className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                          onClick={() => {
                            if (newDiskPath && !(agentConfig.disk_paths || []).includes(newDiskPath)) {
                              setAgentConfig(prev => prev ? { ...prev, disk_paths: [...(prev.disk_paths || []), newDiskPath] } : prev);
                              setNewDiskPath('');
                            }
                          }}
                        >+</button>
                      </div>
                    </div>
                    <button className="btn btn-primary" style={{ width: '100%', marginTop: 8 }}
                      onClick={async () => {
                        try {
                          await api.updateAgentConfig(currentDevice.id, agentConfig);
                          showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
                        } catch (err: any) {
                          showToast('error', t('common.error'), err.message);
                        }
                      }}
                    >
                      <Save size={16} /> {t('agent.save_config')}
                    </button>
                  </div>
                )}

                {/* Deployment Logs */}
                {deployLog.length > 0 && (
                  <div style={{ marginTop: 'var(--space-md)' }}>
                    <h4 style={{ margin: '0 0 8px', fontSize: '0.8rem', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Terminal size={14} /> {t('agent.deployment_logs')}
                    </h4>
                    <div style={{ 
                      background: '#000', padding: '12px', borderRadius: '4px', 
                      fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: '#10b981',
                      maxHeight: '150px', overflowY: 'auto', border: '1px solid var(--border-subtle)'
                    }}>
                      {deployLog.map((log, i) => (
                        <div key={i} style={{ marginBottom: 4 }}>{log}</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        <div className="modal-footer" style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          <button className="btn btn-secondary" onClick={onClose}>{t('common.cancel')}</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={isSaving}>
            <Save size={16} /> {isSaving ? t('common.saving') : t('common.save')}
          </button>
          
          <button className="btn" style={{ 
            marginLeft: 'auto',
            background: 'rgba(239, 68, 68, 0.1)',
            color: '#ef4444',
            border: '1px solid rgba(239, 68, 68, 0.2)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 16px',
            borderRadius: 'var(--radius-md)',
            fontWeight: 600,
            cursor: 'pointer'
          }} onClick={() => {
            if (confirm(t('settings.delete_group_confirm'))) {
              api.deleteDevice(currentDevice.id).then(() => { onSave(); onClose(); });
            }
          }}>
            <Trash2 size={16} /> {t('common.delete')}
          </button>
        </div>
      </div>
    </div>
  );
}
