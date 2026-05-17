import { memo } from 'react';
import type { Device } from '../../types';
import { ServiceBadge } from './ServiceBadge';
import { DeviceMetrics } from './DeviceMetrics';
import { Move, Settings, Box, Database, RefreshCw, Check, Trash2, Server } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';

interface DeviceCardProps {
  device: Device;
  isEditMode?: boolean;
  onEdit?: (e: React.MouseEvent) => void;
  onRefresh?: () => void;
  isSelected?: boolean;
  onSelect?: (selected: boolean) => void;
}

export const DeviceCard = memo(({ device, isEditMode, onEdit, onRefresh, isSelected, onSelect }: DeviceCardProps) => {
  const { t } = useTranslation();
  const displayName = device.display_name || device.hostname || device.ip;

  return (
    <div className={`device-card ${isEditMode ? 'is-editing' : ''} ${isSelected ? 'is-selected' : ''}`} style={{ height: '100%', width: '100%', position: 'relative' }}>
      {/* Selection Tool (Top Left, shifted for mover handle) */}
      {isEditMode && onSelect && (
        <div 
          onClick={(e) => {
            e.stopPropagation();
            onSelect(!isSelected);
          }}
          title={t('dashboard.delete_selected', { count: 1 })}
          style={{ 
            position: 'absolute', top: 8, left: 42, zIndex: 30,
            width: 24, height: 24, 
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: isSelected ? 'var(--accent-danger)' : 'rgba(255,255,255,0.1)',
            borderRadius: '6px',
            border: isSelected ? 'none' : '1px solid rgba(255,255,255,0.2)',
            cursor: 'pointer',
            transition: 'all 0.2s',
            boxShadow: isSelected ? '0 0 10px var(--accent-danger)' : 'none',
            color: isSelected ? 'white' : 'var(--text-tertiary)'
          }}
        >
          {isSelected ? <Check size={16} /> : <Trash2 size={12} />}
        </div>
      )}

      {/* Edit Handle */}
      {isEditMode && (
        <div className="device-card__handle" style={{ right: 8, top: 8, left: 'auto' }}>
          <Move size={14} />
        </div>
      )}

      {/* Header Indicators (Top Right) */}
      {!isEditMode && (
        <div style={{ position: 'absolute', top: 12, right: 12, display: 'flex', alignItems: 'center', gap: '8px', zIndex: 10 }}>
          <button 
            className="device-card__refresh-btn" 
            onClick={async (e) => {
              e.stopPropagation();
              const btn = e.currentTarget;
              btn.classList.add('spinning');
              try {
                await api.refreshDeviceInfo(device.id);
                if (onRefresh) onRefresh(); 
              } catch (err) {
                console.error("Refresh failed:", err);
              } finally {
                setTimeout(() => btn.classList.remove('spinning'), 1000);
              }
            }}
            title={t('dashboard.refresh_info')}
            style={{ 
              background: 'transparent', border: 'none', color: 'var(--text-tertiary)',
              cursor: 'pointer', opacity: 0.6, display: 'flex', padding: '4px'
            }}
          >
            <RefreshCw size={12} />
          </button>
          <button 
            className="device-card__settings-btn" 
            onClick={onEdit}
            title={t('sidebar.settings')}
            style={{ 
              position: 'static',
              opacity: 0.6,
              transition: 'opacity 0.2s',
              display: 'flex',
              padding: '4px'
            }}
            onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
            onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
          >
            <Settings size={14} />
          </button>
          <div 
            className={`status-dot ${device.is_online ? 'status-dot--online' : 'status-dot--offline'}`} 
            title={device.is_online ? t('network.online') : t('network.offline')} 
            style={{ position: 'static', border: 'none' }}
          />
        </div>
      )}

      {/* Offline Overlay dimming */}
      {!device.is_online && !isEditMode && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.2)', pointerEvents: 'none', borderRadius: 'inherit',
          zIndex: 1
        }} />
      )}

      {/* Device info */}
      <div className="device-card__info" style={{ width: '100%' }}>
        <div className="device-card__name" title={displayName}>
          {displayName}
        </div>
        <div className="device-card__meta">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span className="device-card__ip">
              {device.ip}
            </span>
            
            {device.virtual_type && (
              <div className="badge-virtual" style={{
                background: device.virtual_type === 'docker' ? 'rgba(36, 150, 237, 0.1)' : 'rgba(56, 189, 248, 0.1)',
                color: device.virtual_type === 'docker' ? '#2496ed' : 'var(--accent-primary)',
                padding: '2px 6px',
                borderRadius: '4px',
                fontSize: '0.6rem',
                fontWeight: 800,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                width: 'fit-content',
                border: `1px solid ${device.virtual_type === 'docker' ? 'rgba(36, 150, 237, 0.2)' : 'rgba(56, 189, 248, 0.2)'}`,
                textTransform: 'uppercase'
              }}>
                {device.virtual_type === 'docker' ? <Database size={10} /> : <Box size={10} />}
                {device.virtual_type}
              </div>
            )}

            {/* Agent Update Badge */}
            {!isEditMode && device.agent_info?.agent_version && device.agent_info?.latest_version && device.agent_info.agent_version !== device.agent_info.latest_version && (
              <div className="badge-update" style={{
                background: 'rgba(245, 158, 11, 0.1)',
                color: '#f59e0b',
                padding: '2px 6px',
                borderRadius: '4px',
                fontSize: '0.6rem',
                fontWeight: 800,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                width: 'fit-content',
                border: '1px solid rgba(245, 158, 11, 0.2)',
                textTransform: 'uppercase',
                animation: 'pulse 2s infinite'
              }} title={t('common.update_available', { version: device.agent_info.latest_version })}>
                <RefreshCw size={10} />
                {t('dashboard.agent_updates')}
              </div>
            )}

            {/* Host Badge */}
            {device.is_host && (
              <div className="badge-host" style={{
                background: 'rgba(245, 158, 11, 0.15)',
                color: '#f59e0b',
                padding: '2px 6px',
                borderRadius: '4px',
                fontSize: '0.6rem',
                fontWeight: 900,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                width: 'fit-content',
                border: '1px solid rgba(245, 158, 11, 0.3)',
                textTransform: 'uppercase'
              }}>
                <Server size={10} />
                HOST
              </div>
            )}

            {/* Token Mismatch Badge */}
            {!isEditMode && device.has_pending_token && (
              <div 
                className="badge-security" 
                style={{
                  background: 'rgba(244, 63, 94, 0.1)',
                  color: '#f43f5e',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '0.6rem',
                  fontWeight: 900,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  width: 'fit-content',
                  border: '1px solid rgba(244, 63, 94, 0.3)',
                  textTransform: 'uppercase',
                  marginTop: '2px',
                  animation: 'pulse 1.5s infinite'
                }}
              >
                <div className="w-1.5 h-1.5 rounded-full bg-rose-500"></div>
                SECURITY ALERT
                <button 
                  className="ml-1 bg-rose-500 hover:bg-rose-600 text-white px-1.5 py-0.5 rounded text-[8px] font-black transition-colors"
                  onClick={async (e) => {
                    e.stopPropagation();
                    if (window.confirm("Diesen neuen Agent-Key dauerhaft akzeptieren?")) {
                      try {
                        await api.adoptAgent(device.id);
                        if (onRefresh) onRefresh();
                      } catch (err) {
                        console.error("Adoption failed:", err);
                      }
                    }
                  }}
                >
                  ADOPT
                </button>
              </div>
            )}

            {/* Parent Info */}
            {device.parent_id && (
              <div className="badge-parent" style={{
                background: 'rgba(255, 255, 255, 0.05)',
                color: 'var(--text-secondary)',
                padding: '2px 6px',
                borderRadius: '4px',
                fontSize: '0.6rem',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                width: 'fit-content',
                border: '1px solid var(--border-subtle)',
                marginTop: '2px'
              }}>
                <Server size={10} />
                On: {device.parent_name || 'Host System'}
              </div>
            )}
            {/* IP Change Badge */}
            {device.old_ip && (
              <div 
                className="badge-ip-change" 
                onClick={async (e) => {
                  e.stopPropagation();
                  try {
                    await api.updateDevice(device.id, { old_ip: null, ip_changed_at: null });
                    if (onRefresh) onRefresh();
                  } catch (err) {
                    console.error("Failed to clear IP change badge:", err);
                  }
                }}
                style={{
                  background: 'rgba(59, 130, 246, 0.1)',
                  color: '#3b82f6',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '0.6rem',
                  fontWeight: 800,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  width: 'fit-content',
                  border: '1px solid rgba(59, 130, 246, 0.2)',
                  cursor: 'pointer',
                  marginTop: '4px'
                }}
                title={t('dashboard.ip_changed_hint') || "IP hat sich geändert. Klicken zum Ausblenden."}
              >
                <RefreshCw size={10} />
                {device.old_ip} ➔ {device.ip}
                <div style={{ marginLeft: '4px', opacity: 0.7 }}>✕</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Agent Metrics */}
      {!isEditMode && <DeviceMetrics deviceId={device.id} compact={true} />}

      {/* Service buttons */}
      <div className="device-card__services">
        {device.services
          .sort((a, b) => a.sort_order - b.sort_order)
          .map((service) => (
            <ServiceBadge 
              key={service.id} 
              service={service} 
              ip={device.ip} 
              disabled={isEditMode} 
            />
          ))}
      </div>
    </div>
  );
}, (prev, next) => {
  return (
    prev.isEditMode === next.isEditMode &&
    prev.isSelected === next.isSelected &&
    prev.device.id === next.device.id &&
    prev.device.is_online === next.device.is_online &&
    prev.device.display_name === next.device.display_name &&
    prev.device.ip === next.device.ip &&
    prev.device.old_ip === next.device.old_ip &&
    prev.device.has_pending_token === next.device.has_pending_token &&
    JSON.stringify(prev.device.services) === JSON.stringify(next.device.services) &&
    prev.device.agent_info?.agent_version === next.device.agent_info?.agent_version
  );
});
