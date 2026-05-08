import React, { useState, useEffect } from 'react';
import { api } from '../../api/client';
import type { Device } from '../../types';
import { RefreshCw, Shield, ChevronRight, CheckCircle2, AlertCircle, X, Terminal } from 'lucide-react';

interface AgentUpdateCenterProps {
  devices: Device[];
  onComplete: () => void;
  onClose: () => void;
}

interface UpdateStatus {
  deviceId: number;
  status: 'idle' | 'running' | 'success' | 'failed';
  message?: string;
}

export function AgentUpdateCenter({ devices, onComplete, onClose }: AgentUpdateCenterProps) {
  // Filter only devices that need update
  const devicesToUpdate = devices.filter(d => 
    d.has_agent && 
    d.agent_info?.agent_version && 
    d.agent_info?.latest_version && 
    d.agent_info.agent_version !== d.agent_info.latest_version
  );

  const [sshUser, setSshUser] = useState('root');
  const [sshPassword, setSshPassword] = useState('');
  const [statuses, setStatuses] = useState<Record<number, UpdateStatus>>({});
  const [isGlobalLoading, setIsGlobalLoading] = useState(false);

  // Individual overrides for credentials (optional)
  const [overrides, setOverrides] = useState<Record<number, { user?: string; pass?: string }>>({});

  const handleUpdate = async (device: Device) => {
    const user = overrides[device.id]?.user || sshUser;
    const pass = overrides[device.id]?.pass || sshPassword;

    if (!user || !pass) {
      setStatuses(prev => ({
        ...prev,
        [device.id]: { deviceId: device.id, status: 'failed', message: 'Zugangsdaten fehlen' }
      }));
      return;
    }

    setStatuses(prev => ({
      ...prev,
      [device.id]: { deviceId: device.id, status: 'running' }
    }));

    try {
      const res = await api.deployAgent(device.id, {
        ssh_user: user,
        ssh_password: pass,
        ssh_port: 22
      });

      if (res.status === 'success') {
        setStatuses(prev => ({
          ...prev,
          [device.id]: { deviceId: device.id, status: 'success', message: res.message }
        }));
      } else {
        setStatuses(prev => ({
          ...prev,
          [device.id]: { deviceId: device.id, status: 'failed', message: res.message }
        }));
      }
    } catch (err: any) {
      setStatuses(prev => ({
        ...prev,
        [device.id]: { deviceId: device.id, status: 'failed', message: err.message || 'Verbindungsfehler' }
      }));
    }
  };

  const handleUpdateAll = async () => {
    setIsGlobalLoading(true);
    // Sequential update to avoid overwhelming the server or causing SSH locks
    for (const device of devicesToUpdate) {
      if (statuses[device.id]?.status !== 'success') {
        await handleUpdate(device);
      }
    }
    setIsGlobalLoading(false);
    onComplete();
  };

  return (
    <div className="modal-overlay" style={{ zIndex: 1000 }}>
      <div className="modal-content" style={{ maxWidth: '800px', width: '95%' }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
            <RefreshCw size={20} className={isGlobalLoading ? 'spinning' : ''} />
            <h2>Agent Update Center</h2>
          </div>
          <button className="btn-close" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="modal-body">
          {/* Global Credentials */}
          <div style={{ 
            background: 'rgba(56, 189, 248, 0.05)', 
            padding: 'var(--space-md)', 
            borderRadius: 'var(--radius-md)',
            border: '1px solid rgba(56, 189, 248, 0.1)',
            marginBottom: 'var(--space-lg)'
          }}>
            <h3 style={{ fontSize: '0.9rem', marginBottom: 'var(--space-sm)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Shield size={14} /> Globale Zugangsdaten (für alle übernehmen)
            </h3>
            <div style={{ display: 'flex', gap: 'var(--space-md)' }}>
              <div style={{ flex: 1 }}>
                <label className="label">SSH Benutzer</label>
                <input 
                  type="text" 
                  className="input" 
                  value={sshUser} 
                  onChange={e => setSshUser(e.target.value)}
                  placeholder="z.B. root"
                />
              </div>
              <div style={{ flex: 1 }}>
                <label className="label">SSH Passwort</label>
                <input 
                  type="password" 
                  className="input" 
                  value={sshPassword} 
                  onChange={e => setSshPassword(e.target.value)}
                  placeholder="Passwort eingeben"
                />
              </div>
            </div>
          </div>

          {/* Device List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {devicesToUpdate.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-secondary)' }}>
                Alle Agenten sind auf dem neuesten Stand! 🎉
              </div>
            ) : (
              devicesToUpdate.map(device => {
                const status = statuses[device.id] || { status: 'idle' };
                return (
                  <div key={device.id} style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: 'var(--space-md)',
                    padding: 'var(--space-sm) var(--space-md)',
                    background: 'var(--bg-elevated)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border-color)',
                    transition: 'all 0.2s'
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600 }}>{device.display_name}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                        {device.ip} • <span style={{ color: '#f59e0b' }}>v{device.agent_info?.agent_version}</span> → <span style={{ color: 'var(--accent-success)' }}>v{device.agent_info?.latest_version}</span>
                      </div>
                    </div>

                    <div style={{ width: '150px' }}>
                      {status.status === 'idle' && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <ChevronRight size={12} /> Bereit
                        </div>
                      )}
                      {status.status === 'running' && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <RefreshCw size={12} className="spinning" /> Installiere...
                        </div>
                      )}
                      {status.status === 'success' && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--accent-success)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <CheckCircle2 size={12} /> Fertig
                        </div>
                      )}
                      {status.status === 'failed' && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--accent-danger)', display: 'flex', alignItems: 'center', gap: '4px' }} title={status.message}>
                          <AlertCircle size={12} /> Fehler
                        </div>
                      )}
                    </div>

                    <button 
                      className={`btn ${status.status === 'success' ? 'btn-secondary' : 'btn-primary'}`}
                      style={{ padding: '4px 12px', fontSize: '0.8rem' }}
                      onClick={() => handleUpdate(device)}
                      disabled={status.status === 'running' || status.status === 'success'}
                    >
                      {status.status === 'failed' ? 'Wiederholen' : 'Update'}
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>
            {devicesToUpdate.length} Updates verfügbar
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-md)' }}>
            <button className="btn btn-secondary" onClick={onClose}>Schließen</button>
            <button 
              className="btn btn-primary" 
              onClick={handleUpdateAll}
              disabled={isGlobalLoading || devicesToUpdate.length === 0 || !sshPassword}
            >
              <RefreshCw size={16} className={isGlobalLoading ? 'spinning' : ''} />
              Alle verbleibenden aktualisieren
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
