import React, { memo } from 'react';
import { Monitor, Globe, Server, Cpu, Shield, Lock, Eye, EyeOff, Info, Activity, Plus, Save } from 'lucide-react';
import type { Device, DiscoveredHost } from '../../types';

const DEVICE_ICON_MAP: Record<string, any> = {
  'Workstation': Monitor,
  'Server': Server,
  'Smartphone': Cpu,
  'Netzwerk': Shield,
  'Unbekannt': Globe,
};

interface IPTileProps {
  i: number;
  ip: string;
  device?: Device;
  discovered?: DiscoveredHost;
  status: string;
  group?: any;
  isFirstRows: boolean;
  isReserved?: boolean;
  safeZoom: number;
  t: any;
  onSelectDevice: (device: Device) => void;
  onUpdateDeviceField: (id: number, data: any) => void;
  onUpdateDiscoveredHost: (id: number, data: any) => void;
  onRefreshDevice: (id: number, ip: string, type: 'info' | 'services') => void;
  onScanDiscoveredHost: (ip: string) => void;
  onAddDevice: (ip: string) => void;
  isRefreshingServices: boolean;
  isRefreshingAdd: boolean;
}

export const IPTile = memo(({
  i, ip, device, discovered, status, group, isFirstRows, isReserved, safeZoom, t,
  onSelectDevice, onUpdateDeviceField, onUpdateDiscoveredHost, onRefreshDevice,
  onScanDiscoveredHost, onAddDevice, isRefreshingServices, isRefreshingAdd
}: IPTileProps) => {
  const Icon = device ? (DEVICE_ICON_MAP[device.device_type] || Globe) : (discovered ? Globe : null);
  const isDashboardDevice = !!device;
  const isResponding = status === 'online';

  return (
    <div 
      className={`ip-tile ${status}`} 
      tabIndex={0}
      role="button"
      aria-label={`${t('network.device')} ${ip}, ${status === 'online' ? t('network.online') : t('network.offline')}`}
      style={{ 
        fontSize: `${0.7 * safeZoom}rem`, 
        borderColor: group ? group.color : (isDashboardDevice ? 'var(--accent-primary)' : undefined),
        borderWidth: group ? '2px' : (isDashboardDevice ? '1.5px' : '1px'), 
        opacity: status === 'empty' ? 0.3 : 1,
        boxShadow: (discovered?.is_monitored && !isResponding) ? 'inset 0 0 10px rgba(239, 68, 68, 0.4)' : undefined, 
        position: 'relative', 
        cursor: (device || discovered) ? 'pointer' : 'default',
        background: (discovered && !isResponding) ? 'rgba(255, 255, 255, 0.05)' : undefined,
        borderStyle: isReserved ? 'dashed' : 'solid',
        outline: 'none'
      }}
      onClick={() => device && onSelectDevice(device)}
      onKeyDown={(e) => { if (e.key === 'Enter' && device) onSelectDevice(device); }}
    >
      {isReserved && (
        <div style={{ position: 'absolute', bottom: 2, right: 2, color: 'var(--accent-primary)', opacity: 0.8, zIndex: 3 }}>
          <Lock size={8 * safeZoom} />
        </div>
      )}
      {discovered?.is_monitored && (
        <div style={{ 
          position: 'absolute', top: 2, left: 2, 
          color: isResponding ? 'var(--accent-primary)' : 'var(--accent-danger)', 
          zIndex: 3, 
          animation: isResponding ? 'pulse 2s infinite' : 'pulse-fast 0.5s infinite', 
          filter: isResponding ? 'none' : 'drop-shadow(0 0 4px var(--accent-danger))' 
        }}>
          <Eye size={10 * safeZoom} />
        </div>
      )}
      {(isDashboardDevice || discovered) && (
        <div style={{ 
          position: 'absolute', top: 4, right: 4, 
          width: 6 * safeZoom, height: 6 * safeZoom, 
          borderRadius: '50%', background: isResponding ? '#22c55e' : '#ef4444', 
          boxShadow: `0 0 ${4 * safeZoom}px ${isResponding ? '#22c55e' : '#ef4444'}`, 
          zIndex: 3 
        }} />
      )}
      {device?.icon ? (
        <div style={{ fontSize: `${1.2 * safeZoom}rem`, opacity: isResponding ? 1 : 0.5 }}>{device.icon}</div>
      ) : (
        <span style={{ fontWeight: isResponding ? 'bold' : 'normal', opacity: (device || discovered) ? 1 : 0.4 }}>{i}</span>
      )}
      {group && (
        <div style={{ 
          position: 'absolute', top: '-8px', left: '4px', fontSize: '0.5rem', 
          background: group.color, color: 'black', padding: '0 4px', 
          borderRadius: '2px', fontWeight: 'bold', zIndex: 2 
        }}>
          {group.name}
        </div>
      )}

      {(device || discovered) && (
        <div 
          className={`ip-tooltip ${isFirstRows ? 'tooltip-bottom' : 'tooltip-top'}`} 
          style={{ 
            width: `${260 * safeZoom}px`, 
            ...(isFirstRows ? { top: '130%', bottom: 'auto', transformOrigin: 'top center' } : { bottom: '130%', top: 'auto', transformOrigin: 'bottom center' }), 
            pointerEvents: 'auto' 
          }} 
          onClick={e => e.stopPropagation()}
        >
          <h4 style={{ color: 'var(--accent-primary)', marginBottom: '12px', display: 'flex', alignItems: 'center' }}>
            {Icon && <Icon size={16 * safeZoom} style={{ marginRight: '8px' }} />}
            {device?.display_name || discovered?.custom_name || discovered?.hostname || t('network.unknown_device')}
            {device ? (
              <button 
                style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: device.is_reserved ? 'var(--accent-primary)' : 'var(--text-tertiary)', cursor: 'pointer' }}
                onClick={(e) => { e.stopPropagation(); onUpdateDeviceField(device.id, { is_reserved: !device.is_reserved }); }}
                title={device.is_reserved ? "Reservierung aufheben" : "IP als Reserviert (Fest) markieren"}
              >
                {device.is_reserved ? <Lock size={16} /> : <Lock size={16} style={{ opacity: 0.3 }} />}
              </button>
            ) : discovered ? (
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                <button 
                  style={{ background: 'transparent', border: 'none', color: discovered.is_reserved ? 'var(--accent-primary)' : 'var(--text-tertiary)', cursor: 'pointer' }}
                  onClick={(e) => { e.stopPropagation(); onUpdateDiscoveredHost(discovered.id, { is_reserved: !discovered.is_reserved }); }}
                  title={discovered.is_reserved ? "Reservierung aufheben" : "IP als Reserviert (Fest) markieren"}
                >
                  {discovered.is_reserved ? <Lock size={16} /> : <Lock size={16} style={{ opacity: 0.3 }} />}
                </button>
                <button 
                  style={{ background: 'transparent', border: 'none', color: discovered.is_monitored ? 'var(--accent-primary)' : 'var(--text-secondary)', cursor: 'pointer' }}
                  onClick={(e) => { e.stopPropagation(); onUpdateDiscoveredHost(discovered.id, { is_monitored: !discovered.is_monitored }); }}
                  title={discovered.is_monitored ? t('network.stop_monitoring') : t('network.start_monitoring')}
                >
                  {discovered.is_monitored ? <Eye size={16} /> : <EyeOff size={16} />}
                </button>
              </div>
            ) : null}
          </h4>
          <div className="meta" style={{ fontSize: `${0.75 * safeZoom}rem` }}>
            <span className="label">IP:</span> <span className="value">{ip}</span>
            <span className="label">MAC:</span> <span className="value">{device?.mac || discovered?.mac || 'N/A'}</span>
            <span className="label">Status:</span> <span className="value" style={{ color: isResponding ? '#22c55e' : '#ef4444' }}>{isResponding ? t('network.online') : t('network.offline')}</span>
            {isDashboardDevice && <><span className="label">Dashboard:</span> <span className="value" style={{ color: 'var(--accent-primary)' }}>{t('network.yes')}</span></>}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '16px' }}>
            {isDashboardDevice ? (
              <>
                <button className="btn btn-secondary btn-sm" style={{ justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); onSelectDevice(device); }}><Info size={12} /> {t('editor.tabs.general')}</button>
                <button className="btn btn-secondary btn-sm" style={{ justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); onRefreshDevice(device.id, ip, 'services'); }} disabled={isRefreshingServices}><Activity size={12} className={isRefreshingServices ? 'spinning' : ''} /> {t('network.nmap_scan')}</button>
              </>
            ) : (
              <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input 
                    className="input" 
                    style={{ padding: '4px 8px', fontSize: '0.7rem', flex: 1 }} 
                    placeholder={t('editor.custom_name_placeholder')} 
                    defaultValue={discovered?.custom_name || ''}
                    onKeyDown={(e) => { if (e.key === 'Enter' && discovered) { 
                      onUpdateDiscoveredHost(discovered.id, { custom_name: (e.target as HTMLInputElement).value });
                    }}}
                  />
                  <button className="btn btn-secondary btn-sm" onClick={(e) => {
                    e.stopPropagation();
                    if (!discovered) return;
                    const input = (e.currentTarget.previousElementSibling as HTMLInputElement);
                    onUpdateDiscoveredHost(discovered.id, { custom_name: input.value });
                  }}>
                    <Save size={14} />
                  </button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <button className="btn btn-primary btn-sm" style={{ justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); onAddDevice(ip); }} disabled={isRefreshingAdd}>
                    {isRefreshingAdd ? <Activity size={12} className="spinning" /> : <Plus size={12} />} {t('network.status_on_dashboard')}
                  </button>
                  <button className="btn btn-secondary btn-sm" style={{ justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); onScanDiscoveredHost(ip); }} disabled={isRefreshingServices}><Activity size={12} className={isRefreshingServices ? 'spinning' : ''} /> {t('network.nmap_scan')}</button>
                </div>
              </div>
            )}
          </div>
          {(device?.services || discovered?.ports) && (
            <div style={{ marginTop: '12px', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.65rem', marginBottom: '8px', opacity: 0.6, fontWeight: 'bold', textTransform: 'uppercase' }}>Services / {t('network.nmap_scan')}:</div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {device?.services?.filter((s: any) => s.is_up).map((s: any) => (<span key={s.id} className="service-badge" style={{ fontSize: '0.55rem', padding: '2px 6px', background: 'rgba(56, 189, 248, 0.1)', color: 'white' }}>{s.name?.replace('Service ', '') || 'Svc'}</span>))}
                {discovered?.ports?.map((p: number) => (<span key={p} className="service-badge" style={{ fontSize: '0.55rem', padding: '2px 6px', background: 'rgba(34, 197, 94, 0.1)', color: '#4ade80' }}>{p}</span>))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}, (prev, next) => {
  // Custom equality check for maximum performance
  return (
    prev.status === next.status &&
    prev.isReserved === next.isReserved &&
    prev.safeZoom === next.safeZoom &&
    prev.device?.id === next.device?.id &&
    prev.device?.is_online === next.device?.is_online &&
    prev.device?.is_reserved === next.device?.is_reserved &&
    prev.discovered?.id === next.discovered?.id &&
    prev.discovered?.is_online === next.discovered?.is_online &&
    prev.discovered?.is_monitored === next.discovered?.is_monitored &&
    prev.isRefreshingServices === next.isRefreshingServices &&
    prev.isRefreshingAdd === next.isRefreshingAdd &&
    prev.group?.name === next.group?.name
  );
});
