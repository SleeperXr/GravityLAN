import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Sidebar } from '../Sidebar';
import { api, createScanSocket } from '../../api/client';
import type { Device, Subnet, DiscoveredHost } from '../../types';
import { useToast } from '../../context/ToastContext';
import { Monitor, Shield, Server, Cpu, Globe, Search, Trash2, RefreshCw, Activity, Info, Plus, Eye, EyeOff, Lock, Unlock, Save, Settings, LayoutGrid as Grid } from 'lucide-react';
import { DeviceEditor } from '../Dashboard/DeviceEditor';
import { useTranslation } from 'react-i18next';
import { useNetwork } from '../../context/NetworkContext';
import { MobileHeader } from '../MobileHeader';
import { IPTile } from './IPTile';

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
  const [subnets, setSubnets] = useState<Subnet[]>([]);
  const [subnetPrefix, setSubnetPrefix] = useState('');
  const [zoom, setZoom] = useState(1);
  const [groups, setGroups] = useState<Record<string, any[]>>({});
  const [isRefreshing, setIsRefreshing] = useState<Record<string, boolean>>({});
  const [showGroupModal, setShowGroupModal] = useState(false);
  const [showSubnetSettings, setShowSubnetSettings] = useState(false);
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
      
      if (sets && sets['network_groups']) {
        try {
          const rawGroups = typeof sets['network_groups'] === 'string' 
            ? JSON.parse(sets['network_groups']) 
            : sets['network_groups'];
          
          console.log('Loaded network groups:', rawGroups);
          console.log('Current subnet prefix:', subnetPrefix);
          
          if (Array.isArray(rawGroups)) {
            // Legacy format or single subnet: Try to find which prefix this belongs to
            setGroups({ [subnetPrefix]: rawGroups });
          } else {
            setGroups(rawGroups || {});
          }
        } catch (e) {
          console.warn('Failed to parse network_groups:', e);
          setGroups({});
        }
      }

      const subnetList = await api.getSubnetsList().catch(() => []);
      if (Array.isArray(subnetList)) {
        setSubnets(subnetList);
        if (subnetList.length > 0 && !subnetPrefix) {
          const firstSub = subnetList[0].cidr;
          const match = firstSub.match(/^(\d+\.\d+\.\d+)/);
          if (match) {
            console.log('Auto-detected prefix from subnet:', match[1]);
            setSubnetPrefix(match[1]);
          }
        }
      }

      if (!subnetPrefix && safeDevices.length > 0) {
        const firstIp = safeDevices[0]?.ip;
        const match = firstIp?.match(/(\d+\.\d+\.\d+)\./);
        if (match) {
          setSubnetPrefix(match[1]);
        }
      }
    } catch (err) {
      console.error('Failed to load data:', err);
    }
  }, [subnetPrefix]);

  // Intelligent polling based on activity
  useEffect(() => {
    loadData();
    const ws = createScanSocket((data: any) => {
      if (data.status === 'COMPLETED' || data.status === 'completed') {
        loadData();
      }
    });

    const pollInterval = isDiscovering ? 10000 : 30000;
    const interval = setInterval(loadData, pollInterval);
    
    return () => {
      clearInterval(interval);
      ws.close();
    };
  }, [loadData, isDiscovering]);

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

  const refreshDevice = useCallback(async (id: number, ip: string, type: 'info' | 'services') => {
    setIsRefreshing(prev => ({ ...prev, [`${ip}-${type}`]: true }));
    showToast('info', type === 'info' ? t('common.loading') : `${t('network.nmap_scan')}...`, `${t('common.loading')} ${ip}...`);
    
    try {
      if (type === 'info') {
        await api.refreshDeviceInfo(id);
      } else {
        await api.refreshServices(id);
      }
      await loadData();
      showToast('success', t('common.success'), t('notifications.changes_applied'));
    } catch (err: any) {
      showToast('error', t('common.error'), t('notifications.save_failed'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, [`${ip}-${type}`]: false }));
    }
  }, [loadData, t, showToast]);

  const updateDeviceField = useCallback(async (id: number, data: any) => {
    try {
      await api.updateDevice(id, data);
      showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
      await loadData();
    } catch (err: any) {
      showToast('error', t('common.error'), t('notifications.save_failed'));
    }
  }, [loadData, t, showToast]);

  const scanDiscoveredHost = useCallback(async (ip: string) => {
    setIsRefreshing(prev => ({ ...prev, [`${ip}-disc`]: true }));
    showToast('info', `${t('network.nmap_scan')}...`, `${t('common.loading')} ${ip}...`);
    
    try {
      const result = await api.scanIp(ip);
      setDiscoveredHosts((prev: DiscoveredHost[]) => prev.map((h: DiscoveredHost) => 
          h.ip === ip ? { ...h, ports: (result as any).ports || [], last_scan: new Date().toISOString() } : h
      ));
      const portsFound = (result as any).ports || [];
      showToast('success', t('notifications.scan_completed'), t('network.ports_found', { ports: portsFound.join(', ') || t('network.no_ports_found') }));
    } catch (err: any) {
      showToast('error', t('notifications.scan_failed'), t('notifications.scan_failed_text'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, [`${ip}-disc`]: false }));
    }
  }, [t, showToast, setDiscoveredHosts]);

  const addDevice = useCallback(async (ip: string) => {
    setIsRefreshing(prev => ({ ...prev, [`${ip}-add`]: true }));
    try {
      await api.addDeviceFromIp(ip);
      showToast('success', t('common.success'), t('notifications.device_added', { ip }));
      await loadData();
      setDiscoveredHosts((prev: DiscoveredHost[]) => prev.filter(h => h.ip !== ip));
    } catch (err: any) {
      showToast('error', t('common.error'), err.message || t('notifications.save_failed'));
    } finally {
      setIsRefreshing(prev => ({ ...prev, [`${ip}-add`]: false }));
    }
  }, [loadData, t, showToast, setDiscoveredHosts]);

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

  const dashboardOnlineCount = useMemo(() => devices.filter(d => d.ip?.startsWith(subnetPrefix) && d.is_online).length, [devices, subnetPrefix]);
  const discoveredOnlyCount = useMemo(() => {
    const discoveredInSubnet = discoveredHosts.filter(h => h.ip?.startsWith(subnetPrefix) && h.is_online);
    return discoveredInSubnet.filter(h => !devices.find(d => d.ip === h.ip)).length;
  }, [discoveredHosts, devices, subnetPrefix]);

  const handleAddSubnet = async () => {
    const newSub = prompt(t('network.new_subnet_prompt'));
    if (!newSub) return;
    
    let cidr = newSub;
    if (!cidr.includes('/')) {
        if (cidr.split('.').length === 3) cidr = `${cidr}.0/24`;
        else if (cidr.split('.').length === 4) cidr = `${cidr}/32`;
        else cidr = `${cidr}/24`;
    }

    try {
      await api.createSubnet({ cidr, name: `Network ${cidr}`, is_enabled: true });
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
          {/* Subnet Tabs */}
          <div style={{ display: 'flex', gap: '8px', padding: 'var(--space-md) var(--space-xl) 0', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', overflowX: 'auto', whiteSpace: 'nowrap', scrollbarWidth: 'none' }}>
            {subnets.map(sub => {
              const prefixMatch = sub.cidr.match(/(\d+\.\d+\.\d+)/);
              const prefix = prefixMatch ? prefixMatch[1] : sub.cidr;
              return (
                <button key={sub.id} style={{ padding: '8px 16px', background: subnetPrefix === prefix ? 'var(--bg-card)' : 'transparent', border: 'none', borderTopLeftRadius: '8px', borderTopRightRadius: '8px', borderBottom: subnetPrefix === prefix ? '2px solid var(--accent-primary)' : '2px solid transparent', color: subnetPrefix === prefix ? 'var(--text-primary)' : 'var(--text-secondary)', fontWeight: subnetPrefix === prefix ? 600 : 400, cursor: 'pointer', transition: 'all 0.2s' }} onClick={() => setSubnetPrefix(prefix)}>
                  {sub.name}
                </button>
              );
            })}
            <button style={{ padding: '8px 16px', background: 'transparent', border: 'none', color: 'var(--accent-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={handleAddSubnet}>
              <Plus size={14} /> {t('network.add_subnet')}
            </button>
          </div>

          <header className="subnet-header" style={{ flexWrap: isMobile ? 'wrap' : 'nowrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', width: '100%', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: '200px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', marginBottom: '4px', flexWrap: 'wrap' }}>
                  <h1 style={{ margin: 0 }}>{t('network.title')}</h1>
                  <div className="status-badge known" style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(34, 197, 94, 0.05)', color: '#4ade80', border: '1px solid rgba(34, 197, 94, 0.2)', padding: '6px 12px', borderRadius: '12px', fontSize: '0.8rem', fontWeight: 600 }}>
                    <Activity size={14} />
                    <span>{dashboardOnlineCount + discoveredOnlyCount} {t('network.online')}</span>
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
                <button className="btn btn-secondary btn-sm" onClick={() => setShowGroupModal(true)}><Grid size={16} /> {!isMobile && t('network.manage_areas')}</button>
                <button className="btn btn-secondary btn-sm" onClick={() => setShowSubnetSettings(true)}><Settings size={16} /> {!isMobile && 'Subnetz-Settings'}</button>
                <button className={`btn btn-sm ${isDiscovering ? 'btn-secondary' : 'btn-primary'}`} onClick={() => runDiscovery(subnetPrefix)} disabled={isDiscovering}>
                  {isDiscovering ? <RefreshCw size={16} className="spinning" /> : <><Search size={16} /> {!isMobile && 'Scan'}</>}
                </button>
              </div>
            </div>
          </header>

          <div className={isMobile ? "mobile-device-list" : "subnet-grid"} style={!isMobile ? { gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: `${Math.floor(12 * safeZoom)}px` } : { padding: 'var(--space-sm)' }}>
            {tiles
              .filter(tile => !isMobile || tile.status !== 'empty')
              .map(tile => (
                <IPTile 
                  key={tile.i}
                  {...tile}
                  safeZoom={isMobile ? 1 : safeZoom}
                  t={t}
                  onSelectDevice={setSelectedDevice}
                  onUpdateDeviceField={updateDeviceField}
                  onUpdateDiscoveredHost={updateDiscoveredHost}
                  onRefreshDevice={refreshDevice}
                  onScanDiscoveredHost={scanDiscoveredHost}
                  onAddDevice={addDevice}
                  isRefreshingServices={isRefreshing[`${tile.ip}-services`] || isRefreshing[`${tile.ip}-info`] || isRefreshing[`${tile.ip}-disc`]}
                  isRefreshingAdd={isRefreshing[`${tile.ip}-add`]}
                />
              ))}
          </div>

          {discoveredHosts.length > 0 && (
            <div style={{ marginTop: '30px', padding: '24px', background: 'rgba(56, 189, 248, 0.02)', borderRadius: '16px', border: '1px solid var(--border-subtle)' }}>
              <h4 style={{ margin: '0 0 16px 0', fontSize: '0.95rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
                <Search size={18} className="text-accent" /> {t('network.recent_findings')}
              </h4>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                {discoveredHosts
                  .filter(h => !devices.find(d => d.ip === h.ip))
                  .sort((a, b) => new Date(b.first_seen).getTime() - new Date(a.first_seen).getTime())
                  .slice(0, 20)
                  .map(h => (
                    <div key={h.id} style={{ padding: '6px 12px', background: h.is_online ? 'rgba(34, 197, 94, 0.08)' : 'rgba(255,255,255,0.03)', color: h.is_online ? '#4ade80' : 'var(--text-secondary)', borderRadius: '8px', fontSize: '0.8rem', border: '1px solid rgba(255,255,255,0.05)', cursor: 'pointer' }} onClick={() => setSubnetPrefix(h.ip.split('.').slice(0, 3).join('.'))}>
                      {h.ip}
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>

        {/* Modals (Subnet Settings, Group Manager, Alarm, Device Editor) */}
        {showSubnetSettings && (
          <div className="modal-overlay" onClick={() => setShowSubnetSettings(false)}>
            <div className="modal-content" style={{ maxWidth: '600px' }} onClick={e => e.stopPropagation()}>
              <div className="modal-header"><h3>Subnetz-Konfiguration</h3></div>
              <div className="modal-body">
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {subnets.map(sub => (
                    <div key={sub.id} style={{ padding: '16px', background: 'rgba(255,255,255,0.03)', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                        <strong>{sub.cidr}</strong>
                        <button className="btn btn-icon btn-sm text-danger" onClick={async () => { if (confirm(`Löschen?`)) { await api.deleteSubnet(sub.id); loadData(); } }}><Trash2 size={14} /></button>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                        <input className="input" defaultValue={sub.name} onBlur={e => api.updateSubnet(sub.id, { name: e.target.value }).then(loadData)} />
                        <input className="input" defaultValue={sub.dns_server || ''} placeholder="DNS Gateway" onBlur={e => api.updateSubnet(sub.id, { dns_server: e.target.value || null }).then(loadData)} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="modal-footer"><button className="btn btn-primary" onClick={() => setShowSubnetSettings(false)}>Fertig</button></div>
            </div>
          </div>
        )}

        {showGroupModal && (
          <div className="modal-overlay" onClick={() => setShowGroupModal(false)}>
            <div className="modal-content" style={{ maxWidth: '600px' }} onClick={e => e.stopPropagation()}>
              <div className="modal-header"><h3>{t('network.manage_areas')}</h3></div>
              <div className="modal-body">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 80px 60px 40px', gap: '12px', marginBottom: '24px', padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <input className="input" placeholder="Area Name" value={newGroup.name} onChange={e => setNewGroup({...newGroup, name: e.target.value})} />
                  <input className="input" type="number" placeholder="Start" value={newGroup.start} onChange={e => setNewGroup({...newGroup, start: parseInt(e.target.value)})} />
                  <input className="input" type="number" placeholder="End" value={newGroup.end} onChange={e => setNewGroup({...newGroup, end: parseInt(e.target.value)})} />
                  <div className="relative group">
                    <input className="w-full h-10 rounded bg-slate-800 border border-white/10 cursor-pointer" type="color" value={newGroup.color} onChange={e => setNewGroup({...newGroup, color: e.target.value})} />
                  </div>
                  <button className="btn btn-primary h-10 flex items-center justify-center" onClick={() => { saveGroups([...(groups[subnetPrefix] || []), newGroup]); setNewGroup({ name: '', start: 0, end: 0, color: '#38bdf8' }); }}>
                    <Plus size={18} />
                  </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '400px', overflowY: 'auto', paddingRight: '4px' }}>
                  {(groups[subnetPrefix] || []).map((group, idx) => (
                    <div key={idx} style={{ display: 'grid', gridTemplateColumns: '1fr 80px 80px 60px 40px', gap: '12px', alignItems: 'center', padding: '12px', background: 'rgba(255,255,255,0.03)', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.05)' }}>
                      <input className="input" value={group.name} onChange={e => {
                        const next = [...groups[subnetPrefix]];
                        next[idx].name = e.target.value;
                        saveGroups(next);
                      }} />
                      <input className="input text-center" type="number" value={group.start} onChange={e => {
                        const next = [...groups[subnetPrefix]];
                        next[idx].start = parseInt(e.target.value);
                        saveGroups(next);
                      }} />
                      <input className="input text-center" type="number" value={group.end} onChange={e => {
                        const next = [...groups[subnetPrefix]];
                        next[idx].end = parseInt(e.target.value);
                        saveGroups(next);
                      }} />
                      <input className="w-full h-8 rounded bg-transparent border-none cursor-pointer" type="color" value={group.color} onChange={e => {
                        const next = [...groups[subnetPrefix]];
                        next[idx].color = e.target.value;
                        saveGroups(next);
                      }} />
                      <button 
                        className="w-8 h-8 flex items-center justify-center rounded-lg bg-rose-500/10 text-rose-500 hover:bg-rose-500 hover:text-white transition-all border border-rose-500/20" 
                        onClick={() => saveGroups(groups[subnetPrefix].filter((_, i) => i !== idx))}
                        title="Löschen"
                      >
                        <Trash2 size={14} className="min-w-[14px]" />
                        <span className="sr-only">X</span>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {selectedDevice && (
          <DeviceEditor device={selectedDevice} onClose={() => setSelectedDevice(null)} onSave={loadData} />
        )}
      </main>
    </div>
  );
}
