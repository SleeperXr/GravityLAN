import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Sidebar } from '../Sidebar';
import { api, createScanSocket } from '../../api/client';
import type { Device } from '../../types';
import { useToast } from '../../context/ToastContext';
import { Monitor, Shield, Server, Cpu, Globe, Search, Trash2, RefreshCw, Activity, Info, Plus, Eye, EyeOff, Lock, Unlock, Save, LayoutGrid as Grid } from 'lucide-react';
import { DeviceEditor } from '../Dashboard/DeviceEditor';
import { useTranslation } from 'react-i18next';
import { useNetwork } from '../../context/NetworkContext';
import { MobileHeader } from '../MobileHeader';

const DEVICE_ICON_MAP: Record<string, any> = {
  'Workstation': Monitor,
  'Server': Server,
  'Smartphone': Cpu,
  'Netzwerk': Shield,
  'Unbekannt': Globe,
};

export function SubnetView() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const { discoveredHosts, setDiscoveredHosts, isDiscovering, runDiscovery, updateDiscoveredHost } = useNetwork();
  
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const [devices, setDevices] = useState<Device[]>([]);
  const [subnets, setSubnets] = useState<string[]>(['192.168.100']);
  const [subnetPrefix, setSubnetPrefix] = useState('192.168.100');
  const [zoom, setZoom] = useState(1);
  const [groups, setGroups] = useState<Record<string, any[]>>({});
  const [isRefreshing, setIsRefreshing] = useState<Record<string, boolean>>({});
  const [showGroupModal, setShowGroupModal] = useState(false);
  const [newGroup, setNewGroup] = useState({ name: '', start: 0, end: 0, color: '#38bdf8' });
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [showAlarmModal, setShowAlarmModal] = useState(false);
  const lastScannedPrefix = useRef<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const devs = await api.getDevices().catch(() => []);
      const sets: any = await api.getSettings().catch(() => ({}));
      
      const safeDevices = Array.isArray(devs) ? devs : [];
      setDevices(safeDevices);
      
      if (sets && typeof sets['network_groups'] === 'string') {
        try {
          const g = JSON.parse(sets['network_groups']);
          if (Array.isArray(g)) {
            setGroups({ '192.168.100': g });
          } else {
            setGroups(g || {});
          }
        } catch { setGroups({}); }
      } else if (sets && sets['network_groups']) {
        // Fallback if it's already an object
        setGroups(sets['network_groups'] as any);
      }

      if (sets && typeof sets['scan_subnets'] === 'string') {
        const configuredSubnets = sets['scan_subnets'].split(',')
          .map((s: string) => s.trim())
          .filter((s: string) => s.length > 0)
          .map((s: string) => {
            const match = s.match(/(\d+\.\d+\.\d+)/);
            return match ? match[1] : null;
          })
          .filter(Boolean) as string[];
          
        if (configuredSubnets.length > 0) {
          setSubnets(prev => JSON.stringify(prev) !== JSON.stringify(configuredSubnets) ? configuredSubnets : prev);
          setSubnetPrefix(prev => configuredSubnets.includes(prev) ? prev : configuredSubnets[0]);
        }
      } else if (safeDevices.length > 0) {
        const firstIp = safeDevices[0]?.ip;
        const match = firstIp?.match(/(\d+\.\d+\.\d+)\./);
        if (match) {
          setSubnetPrefix(prev => prev || match[1]);
          setSubnets(prev => prev.length === 0 ? [match[1]] : prev);
        }
      }
    } catch (err) {
      console.error('Failed to load data:', err);
    }
  }, []);

  useEffect(() => {
    loadData();
    const ws = createScanSocket((data: any) => {
      if (data.status === 'COMPLETED' || data.status === 'completed') {
        loadData();
      }
    });
    const interval = setInterval(loadData, 30000);
    return () => {
      clearInterval(interval);
      ws.close();
    };
  }, [loadData]);

  // Trigger initial quick scan on subnet change
  useEffect(() => {
    if (!subnetPrefix || subnetPrefix === lastScannedPrefix.current) return;
    lastScannedPrefix.current = subnetPrefix;
    
    const triggerQuickScan = async () => {
      try {
        await api.quickSubnetScan(subnetPrefix);
        await loadData();
      } catch (err) {
        console.error("Auto quick scan failed:", err);
      }
    };
    
    triggerQuickScan();
  }, [subnetPrefix, loadData]);

  const saveGroups = async (updatedGroups: any[]) => {
    const newGroupsObj = { ...groups, [subnetPrefix]: updatedGroups };
    setGroups(newGroupsObj);
    try {
      await api.updateSettings({ 'network_groups': JSON.stringify(newGroupsObj) });
      showToast('success', t('notifications.saved'), t('notifications.area_saved'));
    } catch (err) { 
      showToast('error', t('common.error'), t('notifications.save_failed'));
    }
  };

  const refreshDevice = async (id: number, ip: string, type: 'info' | 'services') => {
    setIsRefreshing(prev => ({ ...prev, [`${ip}-${type}`]: true }));
    showToast('info', type === 'info' ? t('common.loading') : `${t('network.nmap_scan')}...`, `${t('common.loading')} ${ip}...`);
    
    try {
      if (type === 'info') {
        await api.refreshDeviceInfo(id);
        showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
      } else {
        await api.refreshServices(id);
        showToast('success', t('notifications.nmap_scan_finished').replace('{{ip}}', ip), t('notifications.changes_applied'));
      }
      await loadData();
    } catch (err: any) {
      showToast('error', t('common.error'), t('notifications.save_failed'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, [`${ip}-${type}`]: false }));
    }
  };

  const updateDeviceField = async (id: number, data: any) => {
    try {
      await api.updateDevice(id, data);
      showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
      await loadData();
    } catch (err: any) {
      showToast('error', t('common.error'), t('notifications.save_failed'));
    }
  };

  const scanDiscoveredHost = async (ip: string) => {
    setIsRefreshing(prev => ({ ...prev, [`${ip}-disc`]: true }));
    showToast('info', `${t('network.nmap_scan')}...`, `${t('common.loading')} ${ip}...`);
    
    try {
      const result = await api.scanIp(ip);
      setDiscoveredHosts(prev => prev.map(h => 
          h.ip === ip ? { ...h, ports: result.ports, last_scan: new Date().toISOString() } : h
      ));
      showToast('success', t('notifications.scan_completed'), t('network.ports_found', { ports: result.ports.join(', ') || t('network.no_ports_found') }));
    } catch (err: any) {
      showToast('error', t('notifications.scan_failed'), t('notifications.scan_failed_text'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, [`${ip}-disc`]: false }));
    }
  };

  const addDevice = async (ip: string) => {
    setIsRefreshing(prev => ({ ...prev, [`${ip}-add`]: true }));
    try {
      await api.addDeviceFromIp(ip);
      showToast('success', t('common.success'), t('notifications.device_added', { ip }));
      await loadData();
      setDiscoveredHosts(discoveredHosts.filter(h => h.ip !== ip));
    } catch (err: any) {
      showToast('error', t('common.error'), err.message || t('notifications.save_failed'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, [`${ip}-add`]: false }));
    }
  };

  const addAllDevices = async () => {
    const toAdd = discoveredHosts.filter(h => h.is_online && !devices.find(d => d.ip === h.ip));
    if (toAdd.length === 0) return;
    if (!confirm(t('network.discover_all_confirm', { count: toAdd.length }))) return;
    
    setIsRefreshing(prev => ({ ...prev, 'bulk-add': true }));
    let successCount = 0;
    try {
      for (const host of toAdd) {
        await api.addDeviceFromIp(host.ip);
        successCount++;
      }
      showToast('success', t('notifications.batch_completed'), t('notifications.batch_completed', { count: successCount }));
      await loadData();
      setDiscoveredHosts([]);
    } catch (err: any) {
      showToast('error', t('common.error'), t('common.error'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, 'bulk-add': false }));
    }
  };

  const safeZoom = zoom || 1;
  const columns = Math.floor(16 / safeZoom) || 1;
  const activeGroups = groups[subnetPrefix] || [];

  const tiles = useMemo(() => {
    return Array.from({ length: 256 }, (_, i) => {
      const ip = `${subnetPrefix}.${i}`;
      const device = devices.find(d => d.ip?.trim() === ip);
      const discovered = discoveredHosts.find(h => h.ip?.trim() === ip);
      const group = activeGroups.find(g => g && typeof g.start === 'number' && i >= g.start && i <= g.end);
      let status = 'empty';
      if (device) status = device.is_online ? 'online' : 'offline';
      else if (discovered) status = discovered.is_online ? 'online' : 'offline';
      else if (i === 0 || i === 255) status = 'reserved';
      
      const isReserved = device?.is_reserved || discovered?.is_reserved;
      const row = Math.floor(i / columns);
      const isFirstRows = row < 2;
      return { i, ip, device, discovered, status, group, isFirstRows, isReserved };
    });
  }, [subnetPrefix, devices, discoveredHosts, activeGroups, columns]);

  const dashboardOnlineCount = devices.filter(d => d.ip?.startsWith(subnetPrefix) && d.is_online).length;
  const discoveredInSubnet = discoveredHosts.filter(h => h.ip?.startsWith(subnetPrefix) && h.is_online);
  const discoveredOnlyCount = discoveredInSubnet.filter(h => !devices.find(d => d.ip === h.ip)).length;
  const monitoredOfflineCount = discoveredHosts.filter(h => h.is_monitored && !h.is_online && h.ip?.startsWith(subnetPrefix)).length;
  
  const totalDiscoveredOnline = discoveredHosts.filter(h => h.is_online).length;
  const otherSubnetsOnline = totalDiscoveredOnline - (dashboardOnlineCount + discoveredOnlyCount);

  const handleAddSubnet = async () => {
    const newSub = prompt(t('network.new_subnet_prompt'));
    if (!newSub) return;
    const match = newSub.match(/(\d+\.\d+\.\d+)/);
    if (!match) {
      showToast('error', t('common.error'), t('network.invalid_format'));
      return;
    }
    try {
      const sets: any = await api.getSettings();
      const current = sets['scan_subnets'] || '';
      const updated = current ? `${current}, ${newSub}` : newSub;
      await api.updateSettings({ scan_subnets: updated });
      showToast('success', t('notifications.saved'), t('network.add_subnet'));
      loadData();
    } catch (err) {
      showToast('error', t('common.error'), t('notifications.save_failed'));
    }
  };

  return (
    <div className="app-layout">
      <Sidebar active="network" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      <main className="app-main">
        <MobileHeader title="Netzwerk-Planer" onMenuClick={() => setIsSidebarOpen(true)} />
        <div className="subnet-container">
          <div style={{ 
            display: 'flex', 
            gap: '8px', 
            padding: 'var(--space-md) var(--space-xl) 0', 
            borderBottom: '1px solid var(--border-subtle)', 
            background: 'var(--bg-surface)',
            overflowX: 'auto',
            whiteSpace: 'nowrap',
            scrollbarWidth: 'none',
            msOverflowStyle: 'none'
          }}>
            {subnets.map(sub => (
              <button 
                key={sub} 
                style={{ 
                  padding: '8px 16px', background: subnetPrefix === sub ? 'var(--bg-card)' : 'transparent', border: 'none', borderTopLeftRadius: '8px', borderTopRightRadius: '8px',
                  borderBottom: subnetPrefix === sub ? '2px solid var(--accent-primary)' : '2px solid transparent',
                  color: subnetPrefix === sub ? 'var(--text-primary)' : 'var(--text-secondary)', fontWeight: subnetPrefix === sub ? 600 : 400, cursor: 'pointer', transition: 'all 0.2s'
                }}
                onClick={() => setSubnetPrefix(sub)}
              >
                {sub}.0/24
              </button>
            ))}
            <button 
              style={{ padding: '8px 16px', background: 'transparent', border: 'none', color: 'var(--accent-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
              onClick={handleAddSubnet}
            >
              <Plus size={14} /> {t('network.add_subnet')}
            </button>
          </div>
          <header className="subnet-header" style={{ flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', width: '100%', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: '200px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: '4px', flexWrap: 'wrap' }}>
                  <h1 style={{ margin: 0 }}>{t('network.title')}</h1>
                  <div style={{ display: 'flex', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
                    <div className="status-badge known" style={{ 
                      display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(34, 197, 94, 0.05)', color: '#4ade80',
                      border: '1px solid rgba(34, 197, 94, 0.2)', padding: '6px 12px', borderRadius: '12px', fontSize: '0.8rem', fontWeight: 600, boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                    }}>
                      <Activity size={14} />
                      <span>{dashboardOnlineCount + discoveredOnlyCount} {t('network.online')}</span>
                    </div>
                  </div>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                {!isMobile && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', padding: 'var(--space-sm) var(--space-md)', background: 'var(--bg-surface)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 'bold' }}>ZOOM</span>
                    <input type="range" min="0.5" max="2" step="0.1" value={zoom} onChange={e => setZoom(parseFloat(e.target.value))} />
                  </div>
                )}

                <button className="btn btn-secondary btn-sm" onClick={() => setShowGroupModal(true)}>
                  <Grid size={16} /> {!isMobile && t('network.manage_areas')}
                </button>

                <button 
                  className={`btn btn-sm ${isDiscovering ? 'btn-secondary' : 'btn-primary'}`} 
                  onClick={() => runDiscovery(subnetPrefix)} 
                  disabled={isDiscovering}
                >
                  {isDiscovering ? <><RefreshCw size={16} className="spinning" /></> : <><Search size={16} /> {!isMobile && 'Scan'}</>}
                </button>
              </div>
            </div>
          </header>

          {isMobile ? (
            <div className="mobile-device-list" style={{ padding: 'var(--space-sm)' }}>
              {tiles
                .filter(t => t.status !== 'empty')
                .map(({ i, ip, device, discovered, status }) => {
                  const Icon = device ? (DEVICE_ICON_MAP[device.device_type] || Globe) : (discovered ? Globe : Globe);
                  const isResponding = status === 'online';
                  const isDashboard = !!device;
                  
                  return (
                    <div 
                      key={i} 
                      className={`mobile-list-card ${isResponding ? 'online' : 'offline'} ${isDashboard ? 'is-dashboard' : ''}`}
                      style={{
                        background: 'var(--bg-secondary)',
                        borderRadius: 'var(--radius-lg)',
                        padding: 'var(--space-md)',
                        marginBottom: 'var(--space-sm)',
                        border: isDashboard ? '1px solid var(--primary-low)' : '1px solid var(--border-color)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 'var(--space-sm)'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
                        <div style={{ 
                          width: 40, height: 40, borderRadius: '10px', 
                          background: isResponding ? 'rgba(34, 197, 94, 0.1)' : 'rgba(255,255,255,0.05)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          color: isResponding ? '#22c55e' : 'var(--text-tertiary)',
                          flexShrink: 0
                        }}>
                          <Icon size={22} />
                        </div>
                        
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 700, fontSize: '1rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {device?.display_name || discovered?.custom_name || discovered?.hostname || `Device .${i}`}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)', fontFamily: 'monospace' }}>{ip}</span>
                            {isDashboard && <span style={{ fontSize: '0.65rem', padding: '2px 6px', background: 'var(--primary-low)', color: 'var(--primary)', borderRadius: '4px', fontWeight: 'bold' }}>Dashboard</span>}
                          </div>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                           <span className={`status-pill ${isResponding ? 'online' : 'offline'}`} style={{ fontSize: '0.65rem' }}>
                            {isResponding ? 'ONLINE' : 'OFFLINE'}
                           </span>
                           {device?.is_reserved && <Lock size={12} color="var(--primary)" />}
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: '4px' }}>
                        {isDashboard ? (
                          <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={() => setSelectedDevice(device)}>
                            <Info size={14} /> Details
                          </button>
                        ) : (
                          <button className="btn btn-primary btn-sm" style={{ flex: 1 }} onClick={() => addDevice(ip)} disabled={isRefreshing[`${ip}-add`]}>
                            {isRefreshing[`${ip}-add`] ? <RefreshCw size={14} className="spinning" /> : <Plus size={14} />} Hinzufügen
                          </button>
                        )}
                        <button className="btn btn-ghost btn-sm" style={{ flex: 1 }} onClick={() => isDashboard ? refreshDevice(device.id, ip, 'services') : scanDiscoveredHost(ip)} disabled={isRefreshing[`${ip}-services`]}>
                          <Activity size={14} className={isRefreshing[`${ip}-services`] ? 'spinning' : ''} /> Scan
                        </button>
                      </div>
                    </div>
                  );
                })}
              {tiles.filter(t => t.status !== 'empty').length === 0 && (
                <div className="empty-state" style={{ padding: '60px 20px' }}>
                  <div className="empty-state__icon">🔍</div>
                  <h3>Nichts gefunden</h3>
                  <p>Starte einen Scan, um Geräte in diesem Subnetz zu finden.</p>
                  <button className="btn btn-primary" onClick={() => runDiscovery(subnetPrefix)} disabled={isDiscovering}>
                    {isDiscovering ? <RefreshCw size={16} className="spinning" /> : 'Jetzt suchen'}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="subnet-grid" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: `${Math.floor(12 * safeZoom)}px` }}>
              {tiles.map(({ i, ip, device, discovered, status, group, isFirstRows, isReserved }) => {
                const Icon = device ? (DEVICE_ICON_MAP[device.device_type] || Globe) : (discovered ? Globe : null);
                const isDashboardDevice = !!device;
                const isResponding = status === 'online';

                return (
                  <div key={i} className={`ip-tile ${status}`} style={{ 
                      fontSize: `${0.7 * safeZoom}rem`, borderColor: group ? group.color : (isDashboardDevice ? 'var(--accent-primary)' : undefined),
                      borderWidth: group ? '2px' : (isDashboardDevice ? '1.5px' : '1px'), opacity: status === 'empty' ? 0.3 : 1,
                      boxShadow: (discovered?.is_monitored && !isResponding) ? 'inset 0 0 10px rgba(239, 68, 68, 0.4)' : undefined, position: 'relative', cursor: (device || discovered) ? 'pointer' : 'default',
                      background: (discovered && !isResponding) ? 'rgba(255, 255, 255, 0.05)' : undefined,
                      borderStyle: isReserved ? 'dashed' : 'solid'
                    }}
                    onClick={() => device && setSelectedDevice(device)}
                  >
                    {isReserved && (
                      <div style={{ position: 'absolute', bottom: 2, right: 2, color: 'var(--accent-primary)', opacity: 0.8, zIndex: 3 }}>
                        <Lock size={8 * safeZoom} />
                      </div>
                    )}
                    {discovered?.is_monitored && (
                      <div style={{ position: 'absolute', top: 2, left: 2, color: isResponding ? 'var(--accent-primary)' : 'var(--accent-danger)', zIndex: 3, animation: isResponding ? 'pulse 2s infinite' : 'pulse-fast 0.5s infinite', filter: isResponding ? 'none' : 'drop-shadow(0 0 4px var(--accent-danger))' }}>
                        <Eye size={10 * safeZoom} />
                      </div>
                    )}
                    {(isDashboardDevice || discovered) && (
                      <div style={{ position: 'absolute', top: 4, right: 4, width: 6 * safeZoom, height: 6 * safeZoom, borderRadius: '50%', background: isResponding ? '#22c55e' : '#ef4444', boxShadow: `0 0 ${4 * safeZoom}px ${isResponding ? '#22c55e' : '#ef4444'}`, zIndex: 3 }} />
                    )}
                    {device?.icon ? <div style={{ fontSize: `${1.2 * safeZoom}rem`, opacity: isResponding ? 1 : 0.5 }}>{device.icon}</div> : <span style={{ fontWeight: isResponding ? 'bold' : 'normal', opacity: (device || discovered) ? 1 : 0.4 }}>{i}</span>}
                    {group && <div style={{ position: 'absolute', top: '-8px', left: '4px', fontSize: '0.5rem', background: group.color, color: 'black', padding: '0 4px', borderRadius: '2px', fontWeight: 'bold', zIndex: 2 }}>{group.name}</div>}

                    {(device || discovered) && (
                      <div className={`ip-tooltip ${isFirstRows ? 'tooltip-bottom' : 'tooltip-top'}`} style={{ width: `${260 * safeZoom}px`, ...(isFirstRows ? { top: '130%', bottom: 'auto', transformOrigin: 'top center' } : { bottom: '130%', top: 'auto', transformOrigin: 'bottom center' }), pointerEvents: 'auto' }} onClick={e => e.stopPropagation()}>
                        <h4 style={{ color: 'var(--accent-primary)', marginBottom: '12px', display: 'flex', alignItems: 'center' }}>
                          {Icon && <Icon size={16 * safeZoom} style={{ marginRight: '8px' }} />}
                          {device?.display_name || discovered?.custom_name || discovered?.hostname || t('network.unknown_device')}
                          {device ? (
                            <button style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: device.is_reserved ? 'var(--accent-primary)' : 'var(--text-tertiary)', cursor: 'pointer' }}
                              onClick={(e) => { e.stopPropagation(); updateDeviceField(device.id, { is_reserved: !device.is_reserved }); }}
                              title={device.is_reserved ? "Reservierung aufheben" : "IP als Reserviert (Fest) markieren"}
                            >
                              {device.is_reserved ? <Lock size={16} /> : <Unlock size={16} />}
                            </button>
                          ) : discovered ? (
                            <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                              <button style={{ background: 'transparent', border: 'none', color: discovered.is_reserved ? 'var(--accent-primary)' : 'var(--text-tertiary)', cursor: 'pointer' }}
                                onClick={(e) => { e.stopPropagation(); updateDiscoveredHost(discovered.id, { is_reserved: !discovered.is_reserved }); }}
                                title={discovered.is_reserved ? "Reservierung aufheben" : "IP als Reserviert (Fest) markieren"}
                              >
                                {discovered.is_reserved ? <Lock size={16} /> : <Unlock size={16} />}
                              </button>
                              <button style={{ background: 'transparent', border: 'none', color: discovered.is_monitored ? 'var(--accent-primary)' : 'var(--text-secondary)', cursor: 'pointer' }}
                                onClick={(e) => { e.stopPropagation(); updateDiscoveredHost(discovered.id, { is_monitored: !discovered.is_monitored }); }}
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
                              <button className="btn btn-secondary" style={{ padding: '6px 8px', fontSize: '0.65rem', justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); setSelectedDevice(device); }}><Info size={12} /> {t('editor.tabs.general')}</button>
                              <button className="btn btn-secondary" style={{ padding: '6px 8px', fontSize: '0.65rem', justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); refreshDevice(device.id, ip, 'services'); }} disabled={isRefreshing[`${ip}-services`]}><Activity size={12} className={isRefreshing[`${ip}-services`] ? 'spinning' : ''} /> {t('network.nmap_scan')}</button>
                            </>
                          ) : (
                            <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              <div style={{ display: 'flex', gap: '8px' }}>
                                <input 
                                  key={`input-${discovered?.ip || i}`}
                                  id={`label-${discovered?.id || i}`} 
                                  className="input" 
                                  style={{ padding: '4px 8px', fontSize: '0.7rem', flex: 1 }} 
                                  placeholder={t('editor.custom_name_placeholder')} 
                                  defaultValue={discovered?.custom_name || ''}
                                  onKeyDown={(e) => { if (e.key === 'Enter' && discovered) { 
                                    updateDiscoveredHost(discovered.id, { custom_name: (e.target as HTMLInputElement).value });
                                  }}}
                                />
                                <button className="btn btn-secondary" style={{ padding: '4px 8px' }} onClick={() => {
                                  if (!discovered) return;
                                  const val = (document.getElementById(`label-${discovered.id}`) as HTMLInputElement).value;
                                  updateDiscoveredHost(discovered.id, { custom_name: val });
                                }}>
                                  <Save size={14} />
                                </button>
                              </div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                                <button className="btn btn-primary" style={{ padding: '6px 8px', fontSize: '0.65rem', justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); addDevice(ip); }} disabled={isRefreshing[`${ip}-add`]}>
                                  {isRefreshing[`${ip}-add`] ? <RefreshCw size={12} className="spinning" /> : <Plus size={12} />} {t('network.status_on_dashboard')}
                                </button>
                                <button className="btn btn-secondary" style={{ padding: '6px 8px', fontSize: '0.65rem', justifyContent: 'center' }} onClick={(e) => { e.stopPropagation(); scanDiscoveredHost(ip); }} disabled={isRefreshing[`${ip}-services`]}><Activity size={12} className={isRefreshing[`${ip}-services`] ? 'spinning' : ''} /> {t('network.nmap_scan')}</button>
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
              })}
            </div>
          )}

          {discoveredHosts.length > 0 && (
            <div style={{ marginTop: '30px', padding: '24px', background: 'rgba(56, 189, 248, 0.02)', borderRadius: '16px', border: '1px solid var(--border-subtle)', boxShadow: 'inset 0 0 20px rgba(0,0,0,0.2)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <Search size={18} className="text-accent" /> 
                  {t('network.recent_findings', 'Zuletzt im Netzwerk gefunden')}
                </h4>
                <div style={{ fontSize: '0.7rem', opacity: 0.5 }}>
                  {discoveredHosts.length} {t('network.total_discovered', 'Geräte insgesamt')}
                </div>
              </div>

              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                {discoveredHosts
                  .filter(h => !devices.find(d => d.ip === h.ip)) // Nur Geräte, die NICHT im Dashboard sind
                  .sort((a, b) => new Date(b.first_seen).getTime() - new Date(a.first_seen).getTime()) // Neueste zuerst
                  .slice(0, 20)
                  .map(h => {
                    const isNew = (new Date().getTime() - new Date(h.first_seen).getTime()) < 24 * 60 * 60 * 1000;
                    return (
                      <div 
                        key={h.id} 
                        style={{ 
                          padding: '6px 12px', 
                          background: h.is_online ? 'rgba(34, 197, 94, 0.08)' : 'rgba(255,255,255,0.03)', 
                          color: h.is_online ? '#4ade80' : 'var(--text-secondary)', 
                          borderRadius: '8px', 
                          fontSize: '0.8rem', 
                          border: isNew ? '1px solid rgba(56, 189, 248, 0.4)' : '1px solid rgba(255,255,255,0.05)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          cursor: 'pointer',
                          transition: 'all 0.2s',
                          boxShadow: isNew ? '0 0 10px rgba(56, 189, 248, 0.1)' : 'none'
                        }}
                        onClick={() => {
                          const prefix = h.ip.split('.').slice(0, 3).join('.');
                          setSubnetPrefix(prefix);
                          showToast('info', h.ip, `${t('network.scanning')}...`);
                        }}
                        title={`${h.hostname || h.vendor || 'Unbekannt'} | First seen: ${new Date(h.first_seen).toLocaleString()}`}
                      >
                        <div style={{ width: 6, height: 6, borderRadius: '50%', background: h.is_online ? '#22c55e' : '#ef4444' }} />
                        <span style={{ fontWeight: 600 }}>{h.ip}</span>
                        {(h.hostname || h.vendor) && (
                          <span style={{ opacity: 0.5, fontSize: '0.7rem', maxWidth: '100px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {h.hostname || h.vendor}
                          </span>
                        )}
                        {isNew && <span style={{ fontSize: '0.6rem', padding: '1px 5px', background: 'var(--accent-primary)', color: '#000', borderRadius: '4px', fontWeight: 800 }}>NEW</span>}
                        {h.ip?.startsWith(subnetPrefix) ? <span title="Im aktuellen Subnetz">📍</span> : ''}
                      </div>
                    );
                  })}
              </div>
              
              {discoveredHosts.filter(h => !devices.find(d => d.ip === h.ip)).length === 0 && (
                <div style={{ padding: '20px', textAlign: 'center', opacity: 0.5, fontSize: '0.8rem' }}>
                  Keine neuen Geräte außerhalb des Dashboards gefunden.
                </div>
              )}

              <p style={{ marginTop: '16px', fontSize: '0.7rem', opacity: 0.5, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Info size={12} />
                <span>📍 = Gerät im aktuellen Subnetz ({subnetPrefix}.0/24). Unmarkierte Geräte wurden in anderen Scans (z.B. Hintergrund/Scheduled) gefunden.</span>
              </p>
            </div>
          )}
        </div>

        {showAlarmModal && (
          <div className="modal-overlay" onClick={() => setShowAlarmModal(false)}>
            <div className="modal-content" style={{ maxWidth: '500px' }} onClick={e => e.stopPropagation()}>
              <div className="modal-header" style={{ borderBottomColor: 'rgba(239, 68, 68, 0.2)' }}>
                <h3 style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: '10px' }}><EyeOff size={20} /> {t('network.critical_devices')}</h3>
              </div>
              <div className="modal-body">
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {discoveredHosts.filter(h => h.is_monitored && !h.is_online).map(host => (
                    <div key={host.id} style={{ padding: '16px', background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontWeight: 'bold', fontSize: '1rem', color: '#f8fafc', marginBottom: '4px' }}>{host.custom_name || host.hostname || t('network.unknown_device')}</div>
                        <div style={{ fontSize: '0.8rem', opacity: 0.6, fontFamily: 'var(--font-mono)' }}>{host.ip} • {host.mac || 'N/A'}</div>
                      </div>
                      <button className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '0.75rem' }} onClick={() => { const prefix = host.ip.split('.').slice(0, 3).join('.'); setSubnetPrefix(prefix); setShowAlarmModal(false); }}>{t('network.show')}</button>
                    </div>
                  ))}
                </div>
              </div>
              <div className="modal-footer"><button className="btn btn-secondary" onClick={() => setShowAlarmModal(false)}>{t('common.close')}</button></div>
            </div>
          </div>
        )}

        {showGroupModal && (
          <div className="modal-overlay">
            <div className="modal-content" style={{ maxWidth: '600px' }}>
              <div className="modal-header"><h3>{t('network.manage_areas')}</h3></div>
              <div className="modal-body">
                <div style={{ marginBottom: '20px' }}>
                  <h4>{t('network.add_new')}</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 60px 60px 50px auto', gap: '10px' }}>
                    <input className="input" placeholder={t('network.name')} value={newGroup.name} onChange={e => setNewGroup({...newGroup, name: e.target.value})} />
                    <input className="input" type="number" value={newGroup.start} onChange={e => setNewGroup({...newGroup, start: parseInt(e.target.value)})} />
                    <input className="input" type="number" value={newGroup.end} onChange={e => setNewGroup({...newGroup, end: parseInt(e.target.value)})} />
                    <input className="input" type="color" value={newGroup.color} onChange={e => setNewGroup({...newGroup, color: e.target.value})} style={{ padding: 2, height: 38 }} />
                    <button className="btn btn-primary" onClick={() => { saveGroups([...(groups[subnetPrefix] || []), newGroup]); setShowGroupModal(false); }}>+</button>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {(groups[subnetPrefix] || []).map((g, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', borderLeft: `4px solid ${g.color}` }}>
                      <span style={{ flex: 1 }}><strong>{g.name}</strong> (.{g.start}-.{g.end})</span>
                      <button className="btn btn-icon" onClick={() => saveGroups((groups[subnetPrefix] || []).filter((_, idx) => idx !== i))}><Trash2 size={16} /></button>
                    </div>
                  ))}
                </div>
              </div>
              <div className="modal-footer"><button className="btn btn-secondary" onClick={() => setShowGroupModal(false)}>{t('common.close')}</button></div>
            </div>
          </div>
        )}

        {selectedDevice && (
          <DeviceEditor 
            device={selectedDevice} 
            onClose={() => setSelectedDevice(null)} 
            onSave={loadData}
          />
        )}
      </main>
    </div>
  );
}
